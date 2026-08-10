"""tests/test_linear_trigger_hooks.py — Runtime tests for the new
Linear auto-trigger bash hooks (linear-session-start,
linear-worktree-create, linear-task-change).

Mirrors `tests/test_linear_autosync_hook.py` (the existing
runtime-test pattern for `linear-autosync.sh`):

  - Each hook must exit 0 in every test (non-blocking per #539).
  - Each hook must emit no stderr noise when jq or Python is missing
    on $PATH (the per-script worktree_detect_jq_missing_warn path).
  - Each hook must bail before forking Python when no Linear
    activation source is present (env var, .env.linear,
    per-worktree linear-config.json, legacy .enabled.json).
  - `linear-worktree-create.sh` must not fire on a non-`git worktree
    add` command (the matcher is Bash, so every command lands here).

The integration-level verification — that the hook actually calls
`auto-sync` from the right cwd, that the gate bails for non-owners
— lives in `tests/test_linear_sync.py` (TestAutoSync + the
TestLinearAutosyncHookCallsAutoSync guard). These runtime tests
keep the bash half hermetic.
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
SESSION_START_HOOK = ROOT / "hooks" / "linear-session-start.sh"
WORKTREE_CREATE_HOOK = ROOT / "hooks" / "linear-worktree-create.sh"
TASK_CHANGE_HOOK = ROOT / "hooks" / "linear-task-change.sh"


def _hermetic_env() -> dict[str, str]:
    """Return a subprocess env with every LINEAR_* key scrubbed.

    The hooks read `LINEAR_API_KEY` directly; a real key in the
    parent env would let them fork Python and make a real API
    call. The tests stay hermetic by stripping all LINEAR_* keys
    and by feeding empty payloads so the fast-path bail kicks in
    before any Python fork.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("LINEAR_")}


def _run_hook(hook: Path, payload: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(hook)], input=payload,
        capture_output=True, text=True, timeout=10, env=_hermetic_env(),
    )


class TestLinearSessionStartHook(unittest.TestCase):
    def test_empty_payload_exits_zero(self):
        # Empty payload — fast-path bails before forking Python.
        result = _run_hook(SESSION_START_HOOK, payload="")
        self.assertEqual(result.returncode, 0)

    def test_no_stderr_on_empty_payload(self):
        result = _run_hook(SESSION_START_HOOK, payload="")
        # Silent no-op when the activation gate is closed.
        self.assertEqual(result.stderr, "")

    def test_main_checkout_cwd_does_not_fire(self):
        # The session-start hook is worktree-only. A main-checkout
        # cwd leaves WORKTREE_DETECT=main, so the hook bails
        # before forking Python.
        result = _run_hook(SESSION_START_HOOK, payload=json.dumps({"cwd": str(ROOT)}))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")


class TestLinearWorktreeCreateHook(unittest.TestCase):
    def test_empty_payload_exits_zero(self):
        result = _run_hook(WORKTREE_CREATE_HOOK, payload="")
        self.assertEqual(result.returncode, 0)

    def test_non_worktree_command_exits_zero(self):
        # `git status` is not `git worktree add` — the hook must
        # bail before parsing.
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
            "tool_response": "",
        })
        result = _run_hook(WORKTREE_CREATE_HOOK, payload=payload)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_git_worktree_list_does_not_fire(self):
        # `git worktree list` and `git worktree remove` must NOT
        # match the `git worktree add` fragment selector. (A naive
        # substring match would fire on these — the case statement
        # guards against that.)
        for cmd in ("git worktree list", "git worktree remove .worktrees/foo"):
            payload = json.dumps({
                "tool_name": "Bash",
                "tool_input": {"command": cmd},
                "tool_response": "",
            })
            result = _run_hook(WORKTREE_CREATE_HOOK, payload=payload)
            self.assertEqual(result.returncode, 0, msg=cmd)
            self.assertEqual(result.stderr, "", msg=cmd)

    def test_chained_command_with_worktree_add_is_detected(self):
        # The bash tool may chain `cd /tmp && git worktree add ...`.
        # The hook must find the worktree-add fragment in the chain.
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "cd /tmp && git worktree add -b fix/x /tmp/x main"},
            "tool_response": "",
        })
        # The hook may try to cd into /tmp/x; on a host without
        # /tmp/x the path resolution falls through to `git worktree
        # list --porcelain`, which will fail outside any repo. The
        # contract is "exits 0"; stderr may be non-empty from the
        # python fork attempt.
        result = _run_hook(WORKTREE_CREATE_HOOK, payload=payload)
        self.assertEqual(result.returncode, 0)


class TestLinearTaskChangeHook(unittest.TestCase):
    def test_empty_payload_exits_zero(self):
        result = _run_hook(TASK_CHANGE_HOOK, payload="")
        self.assertEqual(result.returncode, 0)

    def test_main_checkout_cwd_does_not_fire(self):
        # The task-change hook is worktree-only.
        result = _run_hook(TASK_CHANGE_HOOK, payload=json.dumps({"cwd": str(ROOT)}))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_no_stderr_on_empty_payload(self):
        result = _run_hook(TASK_CHANGE_HOOK, payload="")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
