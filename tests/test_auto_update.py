#!/usr/bin/env python3
"""test_auto_update.py — regression tests for hooks/auto-update.sh.

The auto-update hook is a SessionStart hook that:
  - silently no-ops if no marketplace clone exists
  - silently no-ops if origin/main is up to date
  - pulls + reinstalls the plugin if origin/main is ahead
  - fails soft (warns to stderr, never breaks the session)

We test the script as a black box by feeding it JSON via stdin and
asserting on exit code + stdout/stderr. We synthesize a real "remote"
git repo + a local "marketplace" clone via `git clone` to exercise
the actual `git fetch` + `git rev-parse` logic.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK = REPO_ROOT / "hooks" / "auto-update.sh"


def _run_hook(marketplace_dir: str) -> subprocess.CompletedProcess:
    """Invoke auto-update.sh with the given marketplace dir override."""
    env = {**os.environ, "DEV_KIT_MARKETPLACE_DIR": marketplace_dir}
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"hook_event_name": "SessionStart"}),
        capture_output=True, text=True, timeout=60, env=env,
    )


def _init_remote_with_commits(tmp: Path, n: int) -> Path:
    """Create a bare-ish 'remote' repo at tmp/remote with `n` commits on main.
    Returns the remote path."""
    remote = tmp / "remote"
    remote.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)],
                   check=True, capture_output=True)
    # Use a separate workdir to push commits
    seed = tmp / "seed"
    seed.mkdir()
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
    ):
        subprocess.run(cmd + [str(seed)], check=True, capture_output=True)
    (seed / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(seed), "add", "README.md"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "commit", "-q", "-m", "init"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "remote", "add", "origin", str(remote)],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "main"],
                   check=True, capture_output=True)
    for i in range(1, n):
        (seed / f"f{i}.txt").write_text(f"v{i}\n")
        subprocess.run(["git", "-C", str(seed), "add", f"f{i}.txt"],
                       check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(seed), "commit", "-q", "-m", f"c{i}"],
            check=True, capture_output=True,
        )
        subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "main"],
                       check=True, capture_output=True)
    return remote


def _clone_to(path: Path, remote: Path) -> None:
    """Clone `remote` into `path` (must not exist)."""
    subprocess.run(["git", "clone", "-q", str(remote), str(path)],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "T"],
                   check=True, capture_output=True)


class TestAutoUpdateHook(unittest.TestCase):
    """SessionStart hook: auto-pull + reinstall when origin/main is ahead."""

    @classmethod
    def setUpClass(cls):
        if not HOOK.exists():
            raise unittest.SkipTest(f"auto-update.sh not found: {HOOK}")

    def test_noop_when_marketplace_dir_missing(self):
        """Path 1: silent no-op if no marketplace clone exists."""
        with tempfile.TemporaryDirectory() as td:
            r = _run_hook(f"{td}/does-not-exist")
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout, "")
            self.assertEqual(r.stderr, "")

    def test_noop_when_marketplace_dir_exists_but_not_a_git_repo(self):
        """No .git/ subdir → not a git clone → silent no-op."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "dev-kit").mkdir()
            r = _run_hook(f"{td}/dev-kit")
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout, "")
            self.assertEqual(r.stderr, "")

    def test_noop_when_up_to_date(self):
        """Path 2: silent no-op when origin/main == local HEAD."""
        with tempfile.TemporaryDirectory() as td:
            remote = _init_remote_with_commits(Path(td), n=2)
            mp = Path(td) / "marketplace"
            _clone_to(mp, remote)
            # Clone is at HEAD == origin/main → no-op expected.
            r = _run_hook(str(mp))
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            self.assertEqual(r.stdout, "")
            self.assertEqual(r.stderr, "")

    def test_pulls_when_remote_ahead(self):
        """Path 3: behind → fast-forward pull. Stub `claude` so the
        install step no-ops (we only test the pull here)."""
        with tempfile.TemporaryDirectory() as td:
            remote = _init_remote_with_commits(Path(td), n=2)
            mp = Path(td) / "marketplace"
            _clone_to(mp, remote)
            # Add a new commit on the remote (not in the local clone yet).
            seed = Path(td) / "seed2"
            subprocess.run(["git", "clone", "-q", str(remote), str(seed)],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(seed), "config", "user.email", "t@t"],
                           check=True, capture_output=True)
            (seed / "extra.txt").write_text("x\n")
            subprocess.run(["git", "-C", str(seed), "add", "extra.txt"],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(seed), "commit", "-q", "-m", "extra"],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "main"],
                           check=True, capture_output=True)
            # Local clone is now behind origin/main.
            before = subprocess.run(
                ["git", "-C", str(mp), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            remote_head = subprocess.run(
                ["git", "-C", str(remote), "rev-parse", "main"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertNotEqual(before, remote_head, "test setup: local must be behind")
            # Stub `claude` on PATH so the install step becomes a no-op
            # (we only want to verify the pull here).
            stub_dir = Path(td) / "stub-bin"
            stub_dir.mkdir()
            (stub_dir / "claude").write_text("#!/usr/bin/env bash\nexit 0\n")
            (stub_dir / "claude").chmod(0o755)
            env = {**os.environ, "DEV_KIT_MARKETPLACE_DIR": str(mp),
                   "PATH": f"{stub_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
            r = subprocess.run(
                ["bash", str(HOOK)],
                input=json.dumps({"hook_event_name": "SessionStart"}),
                capture_output=True, text=True, timeout=60, env=env,
            )
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            # Local HEAD should now equal remote HEAD.
            after = subprocess.run(
                ["git", "-C", str(mp), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertEqual(after, remote_head, "hook should have fast-forwarded")

    def test_noop_when_claude_binary_missing(self):
        """No `claude` on PATH → pull still happens, install skipped."""
        with tempfile.TemporaryDirectory() as td:
            remote = _init_remote_with_commits(Path(td), n=2)
            mp = Path(td) / "marketplace"
            _clone_to(mp, remote)
            # Advance the remote.
            seed = Path(td) / "seed2"
            subprocess.run(["git", "clone", "-q", str(remote), str(seed)],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(seed), "config", "user.email", "t@t"],
                           check=True, capture_output=True)
            (seed / "f3.txt").write_text("z\n")
            subprocess.run(["git", "-C", str(seed), "add", "f3.txt"],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(seed), "commit", "-q", "-m", "z"],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "main"],
                           check=True, capture_output=True)
            # Strip `claude` from PATH but keep the standard utility dirs
            # (bash, git, etc.) so the hook itself can run.
            import shutil
            claude_real = shutil.which("claude")
            util_dirs = set()
            for util in ("bash", "sh", "git", "cat", "echo", "printf", "command", "timeout", "realpath"):
                p = shutil.which(util)
                if p:
                    util_dirs.add(os.path.dirname(p))
            if claude_real:
                util_dirs.discard(os.path.dirname(claude_real))
            minimal_path = os.pathsep.join(sorted(util_dirs)) or "/usr/bin:/bin"
            env = {**os.environ,
                   "DEV_KIT_MARKETPLACE_DIR": str(mp),
                   "PATH": minimal_path}
            r = subprocess.run(
                ["bash", str(HOOK)],
                input=json.dumps({"hook_event_name": "SessionStart"}),
                capture_output=True, text=True, timeout=60, env=env,
            )
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")

    @property
    def _git_real(self) -> str:
        import shutil
        return shutil.which("git") or "/usr/bin/git"


class TestAutoUpdateWiring(unittest.TestCase):
    """hooks.json must register auto-update.sh on SessionStart."""

    def setUp(self):
        path = REPO_ROOT / "hooks" / "hooks.json"
        if not path.exists():
            self.skipTest(f"hooks.json not found at {path}")
        self._cfg = json.loads(path.read_text(encoding="utf-8"))

    def test_auto_update_wired_in_sessionstart(self):
        cmds = []
        for entry in self._cfg["hooks"].get("SessionStart", []):
            for h in entry.get("hooks", []):
                cmds.append(h.get("command", ""))
        self.assertTrue(
            any("auto-update.sh" in c for c in cmds),
            f"auto-update.sh not wired into SessionStart. Got: {cmds}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)