#!/usr/bin/env python3
"""test_lcs_route.py -- NL->URI router break-even table regression (Gap 1, issue #455).

Pins the router's classification behavior against the break-even table
in the LCS UX proposal (issue #455). The router is a deterministic
classifier -- no LLM -- so the test table IS the contract.

Each row of the proposal's break-even table has a corresponding test
method that asserts the verdict and resolved URI. Unknown questions
fall through to verdict=shell with an explicit reason (the router never
invents LCS routing for an unmapped question).

CLI surface (--list-rules, empty-question exit code) is exercised via
subprocess to match the existing dev-kit-lcs-cli test pattern.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BIN = REPO_ROOT / "bin" / "dev-kit-lcs-route.py"

# Import the router module in-process for fast classification tests.
# The filename contains a hyphen (Python module-name constraint), so use
# importlib to load it directly from the file path.
_spec = importlib.util.spec_from_file_location("dev_kit_lcs_route", BIN)
router = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(router)  # type: ignore[union-attr]


def _run_cli(*args: str, timeout: float = 5.0,
             cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    return subprocess.run(
        [sys.executable, str(BIN), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        check=False,
    )


def _run_cli_with_timeout(*args: str, timeout: float,
                          cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Wrapper used when the subprocess is expected to take longer than the default 5s
    (e.g. --invoke which calls out to dev-kit-lcs.py for lcs://worktrees)."""
    return _run_cli(*args, timeout=timeout, cwd=cwd)


# ──────────────────────────────────────────────────────────────────
# Break-even table (mirror of proposal Gap 1)
# ──────────────────────────────────────────────────────────────────


class TestBreakEvenTable(unittest.TestCase):
    """Each method maps 1:1 to a row of the proposal's break-even table."""

    def test_branch_am_i_on_classifies_as_shell(self):
        result = router.classify("what branch am I on?")
        self.assertEqual(result["verdict"], "shell")
        self.assertEqual(result["question"], "what branch am I on?")
        self.assertEqual(
            result["shell_cmd"], "git branch --show-current",
        )
        self.assertNotIn("uri", result)

    def test_worktrees_stale_routes_to_lcs_worktrees(self):
        result = router.classify("what worktrees are stale?")
        self.assertEqual(result["verdict"], "lcs")
        self.assertEqual(result["uri"], "lcs://worktrees")

    def test_slot_version_on_branch_routes_to_branches_slot(self):
        result = router.classify("what's the slot version on branch main?")
        self.assertEqual(result["verdict"], "lcs")
        self.assertEqual(result["uri"], "lcs://branches/main/slot")

    def test_pr_n_ci_routes_to_pr_n(self):
        result = router.classify("what's PR #42's CI + slot?")
        self.assertEqual(result["verdict"], "lcs")
        self.assertEqual(result["uri"], "lcs://pr/42")

    def test_spend_last_24h_routes_to_spend_24h(self):
        result = router.classify("token spend per worktree last 24h?")
        self.assertEqual(result["verdict"], "lcs")
        self.assertEqual(result["uri"], "lcs://spend/24h")

    def test_session_routes_to_sessions_with_id(self):
        result = router.classify("what session is doing X?")
        self.assertEqual(result["verdict"], "lcs")
        self.assertEqual(result["uri"], "lcs://sessions/X")


# ──────────────────────────────────────────────────────────────────
# Fall-through + shell-rule coverage
# ──────────────────────────────────────────────────────────────────


class TestFallThroughAndShellRules(unittest.TestCase):
    """Unknown questions route to shell with an explicit reason."""

    def test_unknown_question_falls_through_to_shell(self):
        result = router.classify("how is the weather in Tokyo?")
        self.assertEqual(result["verdict"], "shell")
        self.assertEqual(
            result["reason"],
            "no matching rule, fall through to direct tool",
        )
        self.assertNotIn("uri", result)

    def test_head_sha_routes_to_shell(self):
        result = router.classify("what's HEAD's SHA?")
        self.assertEqual(result["verdict"], "shell")
        self.assertEqual(result["shell_cmd"], "git rev-parse HEAD")

    def test_working_tree_dirty_routes_to_shell(self):
        result = router.classify("is the working tree dirty?")
        self.assertEqual(result["verdict"], "shell")
        self.assertEqual(result["shell_cmd"], "git status --porcelain")

    def test_pwd_routes_to_shell(self):
        result = router.classify("what directory am I in?")
        self.assertEqual(result["verdict"], "shell")
        self.assertEqual(result["shell_cmd"], "pwd")

    def test_spend_without_window_routes_to_spend_collection(self):
        # "spend" with no "last Xh" window still matches, but the URI
        # template strips the placeholder -> lcs://spend (the list
        # variant) rather than a malformed lcs://spend/{window}.
        result = router.classify("what's the spend?")
        self.assertEqual(result["verdict"], "lcs")
        self.assertEqual(result["uri"], "lcs://spend")


# ──────────────────────────────────────────────────────────────────
# CLI surface (subprocess-driven, end-to-end)
# ──────────────────────────────────────────────────────────────────


class TestCliSurface(unittest.TestCase):
    """Exercise the binary via subprocess so argv/exit-code/JSON framing are pinned."""

    def test_classification_emits_valid_json_on_stdout(self):
        cp = _run_cli("what branch am I on?")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["verdict"], "shell")
        self.assertEqual(payload["question"], "what branch am I on?")

    def test_lcs_verdict_emits_uri_on_stdout(self):
        cp = _run_cli("what worktrees are stale?")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["verdict"], "lcs")
        self.assertEqual(payload["uri"], "lcs://worktrees")

    def test_empty_question_exits_2_with_stderr_message(self):
        cp = _run_cli("")
        self.assertEqual(cp.returncode, 2)
        self.assertIn("empty", cp.stderr.lower())

    def test_whitespace_only_question_exits_2(self):
        cp = _run_cli("   ")
        self.assertEqual(cp.returncode, 2)
        self.assertIn("empty", cp.stderr.lower())

    def test_list_rules_emits_json_array_with_required_fields(self):
        cp = _run_cli("--list-rules")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        rules = json.loads(cp.stdout)
        self.assertIsInstance(rules, list)
        self.assertGreater(len(rules), 0)
        # Each entry must have rule_id, verdict, reason.
        for entry in rules:
            self.assertIn("rule_id", entry)
            self.assertIn("verdict", entry)
            self.assertIn(entry["verdict"], ("shell", "lcs"))
            self.assertIn("reason", entry)
            # Internal compiled patterns must NOT leak into JSON output.
            self.assertNotIn("_pattern", entry)
            # lcs rules must have uri or uri_template (the operator can
            # see the placeholder shape via --list-rules).
            if entry["verdict"] == "lcs":
                self.assertTrue(
                    "uri" in entry or "uri_template" in entry,
                    f"lcs rule {entry['rule_id']!r} missing uri/uri_template",
                )

    def test_invoke_flag_passes_lcs_call_to_subprocess(self):
        # With --invoke, an lcs verdict shells out to dev-kit-lcs.py.
        # The exit code depends on whether the URI is registered, but
        # the call must NOT hang and must NOT be an argparse error (1).
        # Run from REPO_ROOT so dev-kit-lcs.py finds its lib/ on sys.path.
        cp = _run_cli_with_timeout(
            "--invoke", "what worktrees are stale?",
            timeout=30.0, cwd=REPO_ROOT,
        )
        self.assertIn(cp.returncode, (0, 2, 3),
                      f"unexpected exit {cp.returncode}: {cp.stderr}")


if __name__ == "__main__":
    unittest.main()
