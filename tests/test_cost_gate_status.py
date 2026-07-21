#!/usr/bin/env python3
"""test_cost_gate_status.py — focused tests for tools/cost_gate_status.py.

Covers the `_resolved_state` helper extracted in slice #317 (closes
inspect dup-10) and the argparse mutual-exclusivity guard added at the
same time. Black-box tests subprocess the CLI; the helper itself is
exercised via direct import so we can assert on its return shape.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
LIB = REPO_ROOT / "lib"
TOOLS = REPO_ROOT / "tools"


def _run_cli(*args: str, cwd: Path | None = None,
             env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(TOOLS / "cost_gate_status.py"), *args],
        capture_output=True, text=True, timeout=15,
        cwd=str(cwd) if cwd else None, env=env,
    )


# ============================================================================
# 1. _resolved_state helper
# ============================================================================

class TestResolvedState(unittest.TestCase):
    """Exercises _resolved_state(args) -> (Path, dict) in isolation.

    Both halves of the contract are asserted: args handling (which
    state_path gets resolved) AND state loading (real file vs
    ephemeral fallback). The warning-attach behavior is verified
    end-to-end via the CLI black-box test in #3 below.
    """

    def setUp(self):
        sys.path.insert(0, str(TOOLS))
        import importlib
        if "cost_gate_status" in sys.modules:
            self.cgs = importlib.reload(sys.modules["cost_gate_status"])
        else:
            import cost_gate_status  # type: ignore
            self.cgs = cost_gate_status

    def test_resolved_state_returns_path_and_state(self):
        with tempfile.TemporaryDirectory() as td:
            args = argparse.Namespace(state=str(Path(td) / "missing.json"))
            state_path, state = self.cgs._resolved_state(args)
            # args handling: state_path echoes the --state arg verbatim.
            self.assertEqual(state_path, Path(td) / "missing.json")
            # state loading: ephemeral fallback populated by
            # _load_or_ephemeral_state (no real file at state_path).
            self.assertIsInstance(state, dict)
            self.assertEqual(state.get("scope_id"), "ephemeral")
            self.assertEqual(state.get("status"), "ok")

    def test_resolved_state_loads_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            sys.path.insert(0, str(LIB))
            from cost_gate import new_session_state, save_state  # type: ignore
            state_path = Path(td) / "state.json"
            save_state(state_path, new_session_state(
                session_id="real-sess", cwd=td, branch="feat/x",
                repository="r", model="claude-sonnet-5",
            ))
            args = argparse.Namespace(state=str(state_path))
            resolved_path, state = self.cgs._resolved_state(args)
            self.assertEqual(resolved_path, state_path)
            # Real file was loaded — not the ephemeral fallback.
            self.assertEqual(state["scope_id"], "real-sess")
            self.assertEqual(state["sessions"][0]["model"], "claude-sonnet-5")

    def test_resolved_state_no_args_uses_default_path(self):
        with tempfile.TemporaryDirectory() as td:
            args = argparse.Namespace(state=None)
            env_backup = os.environ.pop("DEV_KIT_COST_GATE_STATE", None)
            cwd_backup = os.getcwd()
            try:
                os.chdir(td)
                state_path, state = self.cgs._resolved_state(args)
            finally:
                os.chdir(cwd_backup)
                if env_backup is not None:
                    os.environ["DEV_KIT_COST_GATE_STATE"] = env_backup
            # args handling: default path follows cg.default_state_path(cwd).
            # macOS resolves /tmp -> /private/tmp; resolve() both sides.
            self.assertEqual(
                state_path.resolve(),
                (Path(td) / ".dev-kit" / ".cost-gate" / "state.json").resolve(),
            )
            # state loading: nothing on disk -> ephemeral fallback.
            self.assertEqual(state["scope_id"], "ephemeral")


# ============================================================================
# 2. argparse mutual exclusivity
# ============================================================================

class TestMutuallyExclusiveModes(unittest.TestCase):
    """--json / --html / --footer / --aggregate-pr reject combinations.

    The 'Modes (mutually exclusive)' docstring has been a contract since
    the cost-gate hook was removed; before this slice the contract was
    enforced only by main()'s if/elif precedence (so e.g. `--json --html`
    silently dropped --html). argparse now refuses the combination.
    """

    def test_json_and_html_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            r = _run_cli("--json", "--html", str(Path(td) / "x.html"),
                         cwd=Path(td))
            self.assertNotEqual(r.returncode, 0,
                                f"--json --html accepted: stdout={r.stdout!r}")
            self.assertIn("--json", r.stderr)
            self.assertIn("--html", r.stderr)

    def test_json_and_footer_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            r = _run_cli("--json", "--footer", cwd=Path(td))
            self.assertNotEqual(r.returncode, 0,
                                f"--json --footer accepted: stdout={r.stdout!r}")
            self.assertIn("--json", r.stderr)
            self.assertIn("--footer", r.stderr)

    def test_html_and_aggregate_pr_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            r = _run_cli(
                "--html", str(Path(td) / "x.html"),
                "--aggregate-pr", "--bodies-file", str(Path(td) / "b.txt"),
                cwd=Path(td),
            )
            self.assertNotEqual(r.returncode, 0,
                                f"--html --aggregate-pr accepted: stdout={r.stdout!r}")
            self.assertIn("--html", r.stderr)
            self.assertIn("--aggregate-pr", r.stderr)


# ============================================================================
# 3. CLI black-box: default-warning still emitted by _cli_text only
# ============================================================================

class TestTextDefaultWarning(unittest.TestCase):
    """_cli_text must keep emitting the 'no state file' warning line.

    The warning is gated on `state["scope_id"] == "ephemeral"` after
    _resolved_state returns — this guards the post-extraction refactor
    so the warning doesn't disappear (or leak into JSON/HTML output).
    """

    def test_text_shows_default_warning_when_ephemeral(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"
            r = _run_cli("--state", str(state_path))
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            self.assertIn("warnings:", r.stdout)
            self.assertIn("no state file", r.stdout)

    def test_json_does_not_leak_default_warning(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"
            r = _run_cli("--state", str(state_path), "--json")
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            doc = json.loads(r.stdout)
            # _cli_json must not have run through the "ephemeral warning"
            # path. Empty list is the safe default from new_session_state.
            self.assertEqual(doc.get("warnings"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
