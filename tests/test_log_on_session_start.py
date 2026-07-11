#!/usr/bin/env python3
"""test_log_on_session_start.py — regression tests for hooks/log-on-session-start.sh.

Verifies that the new SessionStart hook:
  - Fires log-on idempotently inside a real worktree session with
    tools/save_log.py present (auto-install), emitting an additionalContext.
  - Stays silent in a main checkout (loghooks there are owned by user
    setup layer, not per-session automation).
  - Stays silent outside any git repo.
  - Empty payload: no crash, exit 0.
  - Worktree without tools/save_log.py: silent no-op (refuse-and-skip).
  - hooks.json wires log-on-session-start.sh into SessionStart with
    timeout >= 5 (log-on runs jq + python discovery).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOKS = REPO_ROOT / "hooks"


def _run_hook(
    script: str,
    payload: dict,
    cwd: Path | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    # Without this the hook's ${CLAUDE_PLUGIN_ROOT} resolves via its
    # fallback path (dirname $0/..); on a worktree that lands on the
    # worktree root, which is fine, but setting it explicitly keeps
    # the test independent of invocation-path quirks.
    full_env.setdefault("CLAUDE_PLUGIN_ROOT", str(REPO_ROOT))
    return subprocess.run(
        ["bash", str(HOOKS / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(cwd) if cwd else None,
        env=full_env,
    )


def _session_payload(cwd: str = "") -> dict:
    p = {"hook_event_name": "SessionStart", "session_id": "test"}
    if cwd:
        p["cwd"] = cwd
    return p


def _touch_save_log(target: Path) -> Path:
    """Touch the canonical tools/save_log.py that log-on.sh gates on.

    log-on.sh refuses with rc=5 unless the file is executable (-x), so
    we chmod +x too. /dev-kit:log setup produces a real executable, so
    this mirrors the production layout.
    """
    p = target / "tools" / "save_log.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    p.chmod(0o755)
    return p


def _make_loghooks_template_dir() -> tuple:
    """Build a hermetic LOGHOOKS_DIR for log-on.sh consumption.

    log-on.sh's lib.sh:resolve_loghooks_dir() looks first at $LOGHOOKS_DIR
    and falls back to $HOME/dev/loghooks. CI runners don't carry the
    user's loghooks source repo, so the test must inject a tempdir that
    mirrors the canonical template shape (so A08 command-shape validation
    in lib.sh passes as well).

    Returns (TemporaryDirectory, path). Caller is responsible for `.cleanup()`
    on the TemporaryDirectory — wrap in try/finally.
    """
    td = tempfile.TemporaryDirectory()
    root = Path(td.name)
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".codex").mkdir(parents=True, exist_ok=True)
    cmd_claude = (
        "for i in python3 python py; do "
        "if \"$i\" -c \"\" </dev/null >/dev/null 2>&1; then "
        "exec \"$i\" \"${CLAUDE_PROJECT_DIR}/tools/save_log.py\" --tool claude-code; "
        "fi; done"
    )
    cmd_codex = cmd_claude.replace("--tool claude-code", "--tool codex")
    (root / ".claude" / "settings.json").write_text(
        json.dumps({
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": cmd_claude}]}],
                "SessionEnd": [{"hooks": [{"type": "command", "command": cmd_claude}]}],
            },
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / ".codex" / "hooks.json").write_text(
        json.dumps({
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": cmd_codex}]}],
            },
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return td, root


def _init_main_with_worktree() -> tuple:
    """Build a throwaway main repo + linked worktree.

    Mirrors the fixture shape from tests/test_worktree_guard.py so we
    exercise the same --git-dir/--git-common-dir discriminator that
    worktree-detect.sh reads.
    """
    main_tmp = tempfile.TemporaryDirectory()
    main_root = Path(main_tmp.name)
    subprocess.run(["git", "init", "-q", "-b", "main", str(main_root)],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(main_root), "config", "user.email", "test@example.com"],
                   check=True)
    subprocess.run(["git", "-C", str(main_root), "config", "user.name", "Test"],
                   check=True)
    (main_root / "README.md").write_text("x")
    subprocess.run(["git", "-C", str(main_root), "add", "README.md"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(main_root), "commit", "-q", "-m", "init"],
                   check=True, capture_output=True)

    wt_parent = tempfile.TemporaryDirectory()
    wt_path = Path(wt_parent.name) / "wt"
    subprocess.run(
        ["git", "-C", str(main_root), "worktree", "add", "-b", "fix/test", str(wt_path)],
        check=True, capture_output=True,
    )
    return main_tmp, wt_parent, wt_path


class TestLogOnSessionStartWorktree(unittest.TestCase):
    """Inside a worktree with tools/save_log.py: hook must fire log-on."""

    def setUp(self):
        if not (HOOKS / "log-on-session-start.sh").exists():
            self.skipTest("log-on-session-start.sh not found")
        if not shutil.which("jq"):
            self.skipTest("jq not installed; hook fails open")

    def test_fires_log_on_in_worktree(self):
        _, wt_parent, wt_path = _init_main_with_worktree()
        template_td, template_dir = _make_loghooks_template_dir()
        try:
            _touch_save_log(wt_path)
            r = _run_hook(
                "log-on-session-start.sh",
                _session_payload(cwd=str(wt_path)),
                cwd=wt_path,
                env={"LOGHOOKS_DIR": str(template_dir)},
            )
            self.assertEqual(
                r.returncode, 0,
                f"got rc={r.returncode}, stderr={r.stderr}, stdout={r.stdout!r}",
            )
            doc = json.loads(r.stdout)
            self.assertIn("hookSpecificOutput", doc)
            ctx = doc["hookSpecificOutput"].get("additionalContext", "")
            self.assertIn("loghooks:", ctx,
                          f"additionalContext missing loghooks marker: {ctx!r}")
        finally:
            template_td.cleanup()
            wt_parent.cleanup()


class TestLogOnSessionStartMain(unittest.TestCase):
    """Main checkout: hook stays silent (different layer owns main)."""

    def setUp(self):
        if not (HOOKS / "log-on-session-start.sh").exists():
            self.skipTest("log-on-session-start.sh not found")
        if not shutil.which("jq"):
            self.skipTest("jq not installed; hook fails open")

    def test_silent_in_main_checkout(self):
        main_tmp, _, _ = _init_main_with_worktree()
        try:
            r = _run_hook(
                "log-on-session-start.sh",
                _session_payload(cwd=main_tmp.name),
                cwd=Path(main_tmp.name),
            )
            self.assertEqual(
                r.returncode, 0,
                f"got rc={r.returncode}, stderr={r.stderr}",
            )
            self.assertNotIn("loghooks:", r.stdout,
                             f"unexpected log-on fire in main: stdout={r.stdout!r}")
        finally:
            main_tmp.cleanup()


class TestLogOnSessionStartMissingSaveLog(unittest.TestCase):
    """Worktree without tools/save_log.py: silent refuse-and-skip."""

    def setUp(self):
        if not (HOOKS / "log-on-session-start.sh").exists():
            self.skipTest("log-on-session-start.sh not found")
        if not shutil.which("jq"):
            self.skipTest("jq not installed; hook fails open")

    def test_silent_when_save_log_missing(self):
        _, wt_parent, wt_path = _init_main_with_worktree()
        try:
            # Intentionally do NOT touch tools/save_log.py. log-on.sh
            # would refuse this; the hook should silently no-op before
            # ever invoking it.
            self.assertFalse((wt_path / "tools" / "save_log.py").exists())
            r = _run_hook(
                "log-on-session-start.sh",
                _session_payload(cwd=str(wt_path)),
                cwd=wt_path,
            )
            self.assertEqual(
                r.returncode, 0,
                f"got rc={r.returncode}, stderr={r.stderr}",
            )
            self.assertNotIn("loghooks:", r.stdout)
        finally:
            wt_parent.cleanup()


class TestLogOnSessionStartOutsideGit(unittest.TestCase):
    """Outside any git repo: hook stays silent."""

    def setUp(self):
        if not (HOOKS / "log-on-session-start.sh").exists():
            self.skipTest("log-on-session-start.sh not found")
        if not shutil.which("jq"):
            self.skipTest("jq not installed; hook fails open")

    def test_silent_outside_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run_hook(
                "log-on-session-start.sh",
                _session_payload(cwd=tmp),
                cwd=Path(tmp),
            )
            self.assertEqual(r.returncode, 0)
            self.assertNotIn("loghooks:", r.stdout)


class TestLogOnSessionStartEmptyPayload(unittest.TestCase):
    """No cwd in payload: hook must not crash; exit 0."""

    def setUp(self):
        if not (HOOKS / "log-on-session-start.sh").exists():
            self.skipTest("log-on-session-start.sh not found")
        if not shutil.which("jq"):
            self.skipTest("jq not installed; hook fails open")

    def test_empty_payload(self):
        r = _run_hook("log-on-session-start.sh", _session_payload())
        self.assertEqual(r.returncode, 0)


class TestLogOnSessionStartWiring(unittest.TestCase):
    """hooks.json must register log-on-session-start.sh under SessionStart."""

    def setUp(self):
        path = HOOKS / "hooks.json"
        if not path.exists():
            self.skipTest(f"hooks.json not found at {path}")
        self._cfg = json.loads(path.read_text(encoding="utf-8"))

    def _hooks_under(self, event: str) -> list:
        flat = []
        for entry in self._cfg["hooks"].get(event, []):
            for h in entry.get("hooks", []):
                flat.append(h)
        return flat

    def test_log_on_session_start_wired_into_sessionstart(self):
        hooks = self._hooks_under("SessionStart")
        match = [h for h in hooks if "log-on-session-start.sh" in h.get("command", "")]
        self.assertTrue(
            match,
            f"log-on-session-start.sh not wired into SessionStart. Got: {hooks}",
        )
        # log-on runs jq + python discovery; budget must be >= 5s.
        for h in match:
            self.assertGreaterEqual(
                h.get("timeout", 0), 5,
                f"timeout too low for log-on: {h}",
            )

    def test_session_start_check_still_wired(self):
        """Regression: existing nudge hook must remain alongside the new one."""
        hooks = self._hooks_under("SessionStart")
        self.assertTrue(
            any("session-start-check.sh" in h.get("command", "") for h in hooks),
            f"session-start-check.sh missing from SessionStart: {hooks}",
        )
        self.assertTrue(
            any("log-on-session-start.sh" in h.get("command", "") for h in hooks),
            f"log-on-session-start.sh missing from SessionStart: {hooks}",
        )


if __name__ == "__main__":
    unittest.main()
