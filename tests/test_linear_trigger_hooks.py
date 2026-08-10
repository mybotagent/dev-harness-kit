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

For the bash half to be load-bearing, the worktree-create tests
place a stub `python3` shim first on `$PATH` and assert the hook
actually invokes it (catching the failure mode where the parser
returns no `WT_PATH` and the hook bails silently — a returncode
of 0 alone cannot distinguish that from a real fork).

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
import sys
import tempfile
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


def _run_hook(hook: Path, payload: str = "",
              env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(hook)], input=payload,
        capture_output=True, text=True, timeout=10,
        env=env if env is not None else _hermetic_env(),
    )


def _python_stub_env(stub_dir: Path, marker: Path) -> dict[str, str]:
    """Build a hermetic env with a `python3` stub first on PATH.

    The stub records the hook's argv + cwd to `marker`, then
    execs the real Python interpreter (whose path is hard-coded
    into the stub at creation time) with the same argv. Tests
    that place this stub first on PATH can assert "the hook
    forked Python" by reading `marker` after the hook returns.
    The existing `python3` (if any) is shadowed; the stub is
    intentionally trivial so it cannot accidentally make a real
    API call.

    Why hard-code the path instead of resolving it inside the
    stub: `command -v python3` resolves the stub itself
    (the stub is named `python3` and is first on PATH), which
    causes infinite recursion on the fallback branch. Passing
    the real interpreter path as a literal in the stub is the
    simplest correct fix; the path is baked in at stub creation
    time, when `sys.executable` is the test runner's Python.
    """
    # Build the inner Python recorder as a separate file so we
    # can avoid f-string brace-escaping for the JSON dict literal.
    recorder_src = (
        "import json, os, sys\n"
        "with open(os.environ['_LINEAR_STUB_MARKER'], 'w', encoding='utf-8') as fh:\n"
        "    json.dump({'argv': sys.argv[1:], 'cwd': os.getcwd()}, fh)\n"
    )
    recorder_path = stub_dir / "_recorder.py"
    recorder_path.write_text(recorder_src, encoding="utf-8")

    real_python = sys.executable  # bake the real interpreter in
    stub = stub_dir / "python3"
    # Quote each path so a Python install under "/usr/bin/..." or
    # "/opt/homebrew/..." survives the shell. f-string the
    # paths in; the recorder source uses no {} so no brace
    # escaping is needed.
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "# Test stub for hooks/linear-*.sh PATH-isolation tests.\n"
        f"\"{real_python}\" \"{recorder_path}\" \"$@\"\n"
        f"exec \"{real_python}\" \"$@\"\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    env = _hermetic_env()
    env["PATH"] = f"{stub_dir}{os.pathsep}{env.get('PATH', '')}"
    # The recorder path is hard-coded into the stub, so the
    # env var is now informational only — keep it for diagnostics
    # in case a future test wants to assert on it.
    env["_LINEAR_STUB_MARKER"] = str(marker)
    return env


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
            "tool_response": "On branch main",
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
                "tool_response": "ok",
            })
            result = _run_hook(WORKTREE_CREATE_HOOK, payload=payload)
            self.assertEqual(result.returncode, 0, msg=cmd)
            self.assertEqual(result.stderr, "", msg=cmd)

    def test_failed_worktree_add_response_does_not_invoke_python(self):
        # A failed `git worktree add` leaves `fatal:` in the tool
        # response. The hook MUST NOT auto-sync to an arbitrary
        # pre-existing worktree — the reviewer flagged this as a
        # wrong-target write. With a python3 stub on PATH, "the
        # hook did not invoke python" is observable by checking
        # the marker file is empty.
        with tempfile.TemporaryDirectory() as tmp:
            stub_dir = Path(tmp) / "stub"
            marker = Path(tmp) / "marker.json"
            stub_dir.mkdir()
            env = _python_stub_env(stub_dir, marker)
            env["LINEAR_API_KEY"] = "test-key"  # force past the env fast-path
            # The parser will find `add -b fix/x .worktrees/fix/x`
            # but the response says git failed; the hook must bail
            # before forking.
            payload = json.dumps({
                "tool_name": "Bash",
                "tool_input": {"command": "git worktree add -b fix/x .worktrees/fix/x main"},
                "tool_response": "fatal: a branch named 'fix/x' already exists",
            })
            result = _run_hook(WORKTREE_CREATE_HOOK, payload=payload, env=env)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(
                marker.exists(),
                f"hook must NOT fork python on a failed worktree-add "
                f"response; marker was created at {marker}",
            )

    def test_chained_command_with_worktree_add_is_detected(self):
        # The bash tool may chain `cd /tmp && git worktree add ...`.
        # The hook must find the worktree-add fragment in the chain.
        # With a python stub on PATH, a successful response
        # (no `fatal:`) and a parseable path WILL trigger the
        # auto-sync — the marker file is the observable signal.
        with tempfile.TemporaryDirectory() as tmp:
            wt_path = Path(tmp) / "wt-fix-x"
            wt_path.mkdir()
            # Minimal `tools/linear_sync.py` shim so the hook does
            # not bail on the missing-toolkit guard.
            (wt_path / "tools").mkdir()
            (wt_path / "tools" / "linear_sync.py").write_text(
                "# test shim\n", encoding="utf-8",
            )
            stub_dir = Path(tmp) / "stub"
            marker = Path(tmp) / "marker.json"
            stub_dir.mkdir()
            env = _python_stub_env(stub_dir, marker)
            payload = json.dumps({
                "tool_name": "Bash",
                "tool_input": {
                    "command": f"cd {wt_path.parent} && git worktree add -b fix/x {wt_path} main",
                },
                "tool_response": "Preparing worktree (new branch 'fix/x')\nHEAD is now at abc1234",
            })
            result = _run_hook(WORKTREE_CREATE_HOOK, payload=payload, env=env)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(
                marker.exists(),
                f"hook should fork python on a successful chained "
                f"worktree-add; marker missing at {marker}",
            )
            record = json.loads(marker.read_text(encoding="utf-8"))
            # macOS resolves /tmp to /private/tmp under the hood; the
            # hook's `pwd -P` agrees with that, so we resolve the
            # expected path the same way before comparing.
            self.assertEqual(record["cwd"], str(wt_path.resolve()),
                             "auto-sync must run with cwd = new worktree path")
            # The hook should pass `auto-sync` as the subcommand.
            joined = " ".join(record["argv"])
            self.assertIn("auto-sync", joined,
                          f"expected 'auto-sync' subcommand, got argv={record['argv']}")


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
