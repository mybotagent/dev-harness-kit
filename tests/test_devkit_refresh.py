#!/usr/bin/env python3
"""test_devkit_refresh.py — regression tests for bin/devkit-refresh.sh.

The four behaviors that matter:
  1. Pipefail safety: --dry-run with a large diff does NOT abort the
     script under `set -euo pipefail` (regression for the 🟠 major
     from PR #26 review).
  2. Argument validation: --marketplace/--cache with no arg dies
     with a helpful error, not an unbound-variable message.
  3. Cache-dir no-mutation: --dry-run must not create $CACHE_DIR.
  4. End-to-end: actual refresh syncs files + preserves +x bit.

We deliberately do NOT test "no changes" (rsync uses mtime+size, not
just content; making that test stable requires either touching files
to backdate mtimes or mocking rsync — neither is worth the brittleness).
"""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "bin" / "devkit-refresh.sh"


def _run(script_args: list, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        ["bash", str(SCRIPT), *script_args],
        capture_output=True, text=True, timeout=60, env=env,
    )


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          check=True, capture_output=True)


def _init_marketplace_with_remote(tmp: Path, files: dict) -> Path:
    """Bare remote + local marketplace clone. `git pull origin main` works."""
    remote = tmp / "remote"
    remote.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)],
                   check=True, capture_output=True)
    mp = tmp / "mp"
    mp.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(mp)],
                   check=True, capture_output=True)
    for cfg in (
        ["config", "user.email", "t@t"],
        ["config", "user.name", "T"],
        ["config", "commit.gpgsign", "false"],
    ):
        _git(mp, *cfg)
    (mp / ".claude-plugin").mkdir()
    (mp / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "dev-kit", "version": "0.1.0"}\n'
    )
    for rel, content in files.items():
        p = mp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(mp, "add", "-A")
    _git(mp, "commit", "-q", "-m", "init")
    _git(mp, "remote", "add", "origin", str(remote))
    _git(mp, "push", "-q", "origin", "main")
    return mp


def _cache_root(tmp: Path) -> Path:
    """The CACHE_ROOT the script expects (parent of the version dir)."""
    return tmp / "cache" / "dev-kit" / "dev-kit"


class TestDevkitRefresh(unittest.TestCase):
    """bin/devkit-refresh.sh — manual refresh script."""

    @classmethod
    def setUpClass(cls):
        if not SCRIPT.exists():
            raise unittest.SkipTest(f"devkit-refresh.sh not found: {SCRIPT}")

    # 1. Pipefail safety — the 🟠 major regression from PR #26 review.
    def test_dry_run_pipefail_safety_major_regression(self):
        with tempfile.TemporaryDirectory() as td:
            mp = _init_marketplace_with_remote(Path(td), {
                f"hooks/f{i:03d}.sh": f"#!/bin/sh\necho {i}\n" for i in range(50)
            })
            cache_root = _cache_root(Path(td))
            cache_dir = cache_root / "0.1.0"
            cache_dir.mkdir(parents=True)
            (cache_dir / "hooks").mkdir()
            (cache_dir / "hooks" / "extra.sh").write_text("stale\n")
            r = _run(["--dry-run", "--marketplace", str(mp), "--cache", str(cache_root)])
            # Critical: must NOT have aborted. rc=0 with truncation notice.
            self.assertEqual(
                r.returncode, 0,
                f"🟠 major regression: --dry-run aborted (rc={r.returncode}). "
                f"stderr={r.stderr}\nstdout={r.stdout[-500:]}"
            )
            self.assertIn("truncated", r.stdout)
            self.assertIn("total diff lines", r.stdout)

    # 2. Argument validation — the 🟡 minor from PR #26 review.
    def test_missing_marketplace_arg_dies_with_helpful_message(self):
        r = _run(["--marketplace"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--marketplace requires a path argument", r.stderr)

    def test_missing_cache_arg_dies_with_helpful_message(self):
        r = _run(["--cache"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--cache requires a path argument", r.stderr)

    def test_bad_marketplace_path_dies_with_helpful_message(self):
        r = _run(["--marketplace", "/no/such/path"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("marketplace clone not found", r.stderr)

    # 3. Cache-dir no-mutation — the 🟡 minor from PR #26 review.
    def test_dry_run_does_not_create_cache_dir(self):
        with tempfile.TemporaryDirectory() as td:
            mp = _init_marketplace_with_remote(Path(td), {"hooks/x.sh": "x\n"})
            cache_root = _cache_root(Path(td))
            # CACHE_ROOT must pre-exist (the script dies with a helpful
            # error if it doesn't — that's a separate behavior). The
            # version subdir is what must NOT be created.
            cache_root.mkdir(parents=True)
            self.assertFalse((cache_root / "0.1.0").exists())
            r = _run(["--dry-run", "--marketplace", str(mp), "--cache", str(cache_root)])
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            self.assertFalse(
                (cache_root / "0.1.0").exists(),
                "--dry-run must NOT create $CACHE_DIR/<version>",
            )

    # 4. End-to-end.
    def test_actual_refresh_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            mp = _init_marketplace_with_remote(Path(td), {
                "hooks/auto-update.sh": "#!/bin/sh\necho ok\n",
                "hooks/lib/worktree-detect.sh": "#!/bin/sh\n",
            })
            cache_root = _cache_root(Path(td))
            cache_root.mkdir(parents=True)
            r = _run(["--marketplace", str(mp), "--cache", str(cache_root)])
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            cache_hooks = cache_root / "0.1.0" / "hooks"
            self.assertTrue((cache_hooks / "auto-update.sh").exists())
            self.assertTrue((cache_hooks / "lib" / "worktree-detect.sh").exists())
            self.assertTrue(
                (cache_hooks / "auto-update.sh").stat().st_mode & stat.S_IXUSR,
                "auto-update.sh should be executable after refresh",
            )

    # 🟢 nit from PR #26 review.
    def test_help_lists_cache_flag(self):
        r = _run(["--help"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("--cache", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
