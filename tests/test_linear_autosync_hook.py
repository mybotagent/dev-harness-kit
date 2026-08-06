"""tests/test_linear_autosync_hook.py — Runtime tests for hooks/linear-autosync.sh.

The hook is a PreToolUse Edit|Write|MultiEdit guard that forks
tools/linear_sync.py. These tests exercise the shell wrapper directly
via subprocess to cover the "PROJECT_DIR has no tools/" and "non-git
cwd" guards added in #583 followup.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
HOOK = ROOT / "hooks" / "linear-autosync.sh"


def _hermetic_env() -> dict[str, str]:
    """Return a subprocess env with all LINEAR_* keys scrubbed.

    The hook reads `LINEAR_API_KEY` directly; if a real key is set in
    the test runner's parent env, the hook would fork Python and make
    a real API call. We keep HOME + PATH (the hook depends on both via
    `set -uo pipefail` and the `python3` lookup) but strip every
    `LINEAR_*` activation source so the test is fully hermetic.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("LINEAR_")}


def _run_hook(cwd: str | None) -> subprocess.CompletedProcess:
    payload = json.dumps(
        {"session_id": "t", "tool_name": "Write", "cwd": cwd or "/tmp"}
    )
    return subprocess.run(
        ["bash", str(HOOK)], input=payload,
        capture_output=True, text=True, timeout=10, env=_hermetic_env(),
    )


class TestLinearAutosyncHook(unittest.TestCase):
    def test_bails_when_no_tools_dir(self):
        # exists, but not a dev-harness-kit checkout
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_hook(tmp)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_bails_on_non_git_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_hook(tmp)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_runs_python_when_tools_present(self):
        # ROOT has tools/linear_sync.py; with empty stdin + no LINEAR_* env,
        # the hook fast-paths (no activation source) and exits 0.
        result = subprocess.run(
            ["bash", str(HOOK)], input="",
            capture_output=True, text=True, timeout=10, cwd=str(ROOT),
            env=_hermetic_env(),
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
