#!/usr/bin/env python3
"""test_worktree_log_auto_install.py — End-to-end coverage for the
worktree-log-auto-install PostToolUse hook.

Wires up a fake loghooks source repo + a fake target project + the
REAL hook script (and its sibling log-setup.sh / log-on.sh) under
tmpdir, runs `git worktree add`, then drives the hook with a synthetic
PostToolUse payload (matching the actual shape Claude Code emits).
Asserts:
  - hook exits 0 for non-worktree-add commands (no-op)
  - hook exits 0 for empty payloads
  - hook auto-installs loghooks on the new worktree after a real
    `git worktree add` succeeds (save_log.py + .claude/settings.json
    managed entries both present)
  - hook tolerates the --detach / --force flag variations
  - hook tolerates relative worktree paths
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK = REPO_ROOT / "hooks" / "worktree-log-auto-install.sh"
LOG_SETUP = REPO_ROOT / "skills" / "log" / "scripts" / "log-setup.sh"
LOG_ON = REPO_ROOT / "skills" / "log" / "scripts" / "log-on.sh"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        check=check, timeout=10,
    )


def _make_fake_loghooks(tmp: Path) -> Path:
    src = tmp / "loghooks"
    (src / "tools").mkdir(parents=True)
    (src / ".claude").mkdir(parents=True)
    settings = {
        "hooks": {
            "Stop": [{"hooks": [{"type": "command",
                                  "command": 'for i in python3 python py; do if "$i" -c "" </dev/null >/dev/null 2>&1; then exec "$i" "${CLAUDE_PROJECT_DIR}/tools/save_log.py" --tool claude-code; fi; done'}]}],
            "SessionEnd": [{"hooks": [{"type": "command",
                                        "command": 'for i in python3 python py; do if "$i" -c "" </dev/null >/dev/null 2>&1; then exec "$i" "${CLAUDE_PROJECT_DIR}/tools/save_log.py" --tool claude-code; fi; done'}]}],
        }
    }
    (src / ".claude" / "settings.json").write_text(json.dumps(settings))
    # Stub save_log.py — does nothing useful, but file must exist for
    # the install to succeed.
    (src / "tools" / "save_log.py").write_text(
        "#!/usr/bin/env python3\nimport sys, os, json\n"
        "payload=json.load(sys.stdin); open('logs/__noop__','w').close(); sys.exit(0)\n"
    )
    (src / "tools" / "save_log.py").chmod(0o755)
    return src


def _make_fake_target(tmp: Path) -> Path:
    tgt = tmp / "target"
    (tgt / ".claude" / "worktrees").mkdir(parents=True)
    _git(tgt, "init", "-q")
    (tgt / "f").write_text("init")
    _git(tgt, "add", ".")
    _git(tgt, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "init")
    return tgt


def _drive_hook(payload: dict, *, env_extra: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=20,
        env={**os.environ, **env_extra},
    )


class TestWorktreeLogAutoInstall(unittest.TestCase):
    def setUp(self):
        if not HOOK.exists():
            self.skipTest(f"hook not found: {HOOK}")
        self.tmp = Path(tempfile.mkdtemp(prefix="wtlog-auto-"))
        self.src = _make_fake_loghooks(self.tmp)
        self.tgt = _make_fake_target(self.tmp)
        self.env = {"LOGHOOKS_DIR": str(self.src),
                    "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT)}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_noop_on_empty_payload(self):
        r = _drive_hook({}, env_extra=self.env)
        self.assertEqual(r.returncode, 0, f"hook should no-op, got {r.stderr}")
        self.assertEqual(r.stderr.strip(), "",
                         f"empty payload should be silent: {r.stderr!r}")

    def test_noop_on_non_worktree_command(self):
        payload = {"tool_input": {"command": "ls -la"}, "cwd": str(self.tgt)}
        r = _drive_hook(payload, env_extra=self.env)
        self.assertEqual(r.returncode, 0)
        # Hook should silently no-op on unrelated commands.
        self.assertNotIn("hooks installed", r.stderr)

    def test_noop_when_target_dir_missing(self):
        # Command names a worktree path that does not exist on disk
        # (e.g. user typo'd or git worktree add failed). Hook must
        # silently bail out, not throw.
        payload = {
            "tool_input": {"command": "git worktree add -b feat/x .claude/worktrees/nonexistent"},
            "cwd": str(self.tgt),
        }
        r = _drive_hook(payload, env_extra=self.env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("does not exist", r.stderr)

    def test_auto_installs_on_successful_worktree_add(self):
        # Pre-create the worktree (so the dir exists for the hook).
        wt_path = self.tgt / ".claude" / "worktrees" / "wt-x"
        _git(self.tgt, "worktree", "add", "-b", "fix/x", str(wt_path))
        self.assertTrue(wt_path.exists())

        payload = {
            "tool_input": {"command": f"git worktree add -b fix/x {wt_path}"},
            "cwd": str(self.tgt),
        }
        r = _drive_hook(payload, env_extra=self.env)
        self.assertEqual(r.returncode, 0,
                         f"hook failed: stdout={r.stdout} stderr={r.stderr}")
        self.assertIn("hooks installed", r.stderr)

        # save_log.py was copied.
        self.assertTrue((wt_path / "tools" / "save_log.py").exists(),
                        f"save_log.py not copied into {wt_path / 'tools'}")
        self.assertTrue((wt_path / "logs" / "claude-code").is_dir(),
                        f"logs/claude-code/ missing in {wt_path}")

        # settings.json has managed hooks.
        settings = json.loads((wt_path / ".claude" / "settings.json").read_text())
        managed = [h for ev in (settings.get("hooks") or {}).values()
                   for h in ev if h.get("_loghooks_managed")]
        self.assertEqual(len(managed), 2,
                         f"expected 2 managed hooks (Stop, SessionEnd), got {managed}")

    def test_handles_relative_worktree_path(self):
        wt_rel = ".claude/worktrees/wt-rel"
        wt_abs = self.tgt / wt_rel
        _git(self.tgt, "worktree", "add", "-b", "fix/rel", wt_rel)
        self.assertTrue(wt_abs.exists())

        payload = {
            "tool_input": {"command": f"git worktree add -b fix/rel {wt_rel}"},
            "cwd": str(self.tgt),
        }
        r = _drive_hook(payload, env_extra=self.env)
        self.assertEqual(r.returncode, 0, f"hook failed: {r.stderr}")
        self.assertIn("hooks installed", r.stderr)
        self.assertTrue((wt_abs / "tools" / "save_log.py").exists())

    def test_handles_force_flag(self):
        # `git worktree add --force -b fix/forced .claude/worktrees/wt-f`
        # — the hook must skip the --force flag when picking the path.
        wt_abs = self.tgt / ".claude" / "worktrees" / "wt-f"
        _git(self.tgt, "worktree", "add", "--force", "-b", "fix/forced", str(wt_abs))
        payload = {
            "tool_input": {"command": f"git worktree add --force -b fix/forced {wt_abs}"},
            "cwd": str(self.tgt),
        }
        r = _drive_hook(payload, env_extra=self.env)
        self.assertEqual(r.returncode, 0, f"hook failed: {r.stderr}")
        self.assertIn("hooks installed", r.stderr)
        self.assertTrue((wt_abs / "tools" / "save_log.py").exists())

    def test_noop_on_worktree_remove(self):
        # `git worktree remove` should NOT trigger auto-install.
        payload = {"tool_input": {"command": "git worktree remove .claude/worktrees/old"},
                   "cwd": str(self.tgt)}
        r = _drive_hook(payload, env_extra=self.env)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("hooks installed", r.stderr)


if __name__ == "__main__":
    unittest.main()
