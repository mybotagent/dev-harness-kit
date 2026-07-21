#!/usr/bin/env python3
"""test_git_worktree.py — Regression tests for lib/git_worktree.py (issue #310).

The cut_worktree() helper is the canonical `git worktree add` entry point used
by both lib/acp_dispatch.py (safe mode) and lib/execute.py (per-step mode).
These tests pin every intentional behavior so a refactor cannot silently
change the contract.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "lib"))

from git_worktree import (  # noqa: E402
    CutWorktreeResult,
    cut_worktree,
    git_common_dir,
    list_worktree_dirs,
)


def _init_throwaway_repo(*, with_origin: bool = True) -> "tempfile.TemporaryDirectory":
    """Throwaway repo on `main` with a single commit.

    Mirrors the helper in tests/test_acp_dispatch.py — copied here to keep
    the worktree test self-contained.
    """
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@e.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "T"], check=True)
    (root / "README.md").write_text("x")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)
    if with_origin:
        origin_dir = root.parent / f"{root.name}-origin"
        if origin_dir.exists():
            shutil.rmtree(origin_dir)
        subprocess.run(["git", "clone", "-q", "--bare", str(root), str(origin_dir)], check=True)
        subprocess.run(["git", "-C", str(root), "remote", "add", "origin", str(origin_dir)], check=True)
        subprocess.run(["git", "-C", str(root), "fetch", "-q", "origin"], check=True)
        subprocess.run(["git", "-C", str(root), "branch", "--set-upstream-to=origin/main", "main"], check=True)
    return tmp


class CutWorktreeSafeMode(unittest.TestCase):
    """acp_dispatch.py contract: safe mode. -b (fail if branch exists)."""

    def setUp(self):
        self.tmp = _init_throwaway_repo()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cut_worktree_happy_path(self):
        wt = self.root / ".worktrees" / "x"
        result = cut_worktree(
            repo_root=self.root,
            branch="feat/x",
            worktree_path=wt,
        )
        self.assertIsInstance(result, CutWorktreeResult)
        self.assertEqual(result.branch, "feat/x")
        self.assertEqual(result.worktree_path, wt)
        self.assertTrue(wt.is_dir())
        # The branch was created fresh (not pre-existing).
        self.assertFalse(result.was_pre_existing)

    def test_safe_mode_fails_when_branch_exists(self):
        # Pre-create the branch on origin/main so it pre-exists.
        subprocess.run(
            ["git", "-C", str(self.root), "branch", "feat/x"],
            check=True,
        )
        wt = self.root / ".worktrees" / "x"
        if wt.exists():
            shutil.rmtree(wt)
        with self.assertRaises(subprocess.CalledProcessError) as cm:
            cut_worktree(
                repo_root=self.root,
                branch="feat/x",
                worktree_path=wt,
            )
        # The pre-existing branch must survive.
        still = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "--verify",
             "refs/heads/feat/x"],
            capture_output=True,
        )
        self.assertEqual(
            still.returncode, 0,
            f"pre-existing branch must survive a failed safe cut; msg={cm.exception}",
        )

    def test_safe_mode_fails_when_worktree_dir_exists(self):
        wt = self.root / ".worktrees" / "x"
        wt.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            cut_worktree(
                repo_root=self.root,
                branch="feat/x",
                worktree_path=wt,
            )

    def test_safe_mode_returns_result_for_repeat_cut_of_existing_dir(self):
        # Regression for the "AC1: cut already-cut worktree → 1 result" contract.
        # After a successful cut, the dir exists. A second cut must raise
        # FileExistsError (safe) — not silently re-cut and lose the session's
        # in-progress state.
        wt = self.root / ".worktrees" / "x"
        cut_worktree(repo_root=self.root, branch="feat/x", worktree_path=wt)
        with self.assertRaises(FileExistsError):
            cut_worktree(repo_root=self.root, branch="feat/x", worktree_path=wt)


class CutWorktreeResetMode(unittest.TestCase):
    """execute.py contract: per-step reset mode. -B (reset branch to base)."""

    def setUp(self):
        self.tmp = _init_throwaway_repo()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reset_branch_resets_existing_branch_to_base(self):
        # Pre-create a branch pointing somewhere different from origin/main.
        subprocess.run(
            ["git", "-C", str(self.root), "branch", "feat/x"], check=True,
        )
        wt = self.root / ".worktrees" / "x"
        if wt.exists():
            shutil.rmtree(wt)
        result = cut_worktree(
            repo_root=self.root,
            branch="feat/x",
            worktree_path=wt,
            reset_branch=True,
        )
        self.assertTrue(result.was_pre_existing)
        self.assertTrue(wt.is_dir())
        # Branch ref should now point at origin/main (not the old SHA).
        head_sha = subprocess.run(
            ["git", "-C", str(wt), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        main_sha = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "origin/main"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(head_sha, main_sha,
                         "reset_branch=True must point the new worktree at base")

    def test_reset_mode_still_fails_when_worktree_dir_exists(self):
        # -B only resets the branch; the dir must be absent for the cut to
        # proceed. This preserves the execute.py invariant that no stale
        # worktree dir can hijack a fresh per-step run.
        wt = self.root / ".worktrees" / "x"
        wt.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            cut_worktree(
                repo_root=self.root,
                branch="feat/x",
                worktree_path=wt,
                reset_branch=True,
            )


class CutWorktreeCustomBase(unittest.TestCase):
    """Both callers default to ``origin/main``; the helper accepts any base ref."""

    def setUp(self):
        self.tmp = _init_throwaway_repo()
        self.root = Path(self.tmp.name)
        # Make an extra commit so origin/main advances one SHA.
        (self.root / "second.txt").write_text("2")
        subprocess.run(["git", "-C", str(self.root), "add", "second.txt"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "-m", "second"], check=True)
        subprocess.run(["git", "-C", str(self.root), "push", "-q", "origin", "main"], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_base_ref(self):
        wt = self.root / ".worktrees" / "x"
        # Cut from the original main SHA (HEAD~1) instead of origin/main.
        old_sha = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD~1"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        cut_worktree(
            repo_root=self.root,
            branch="feat/x",
            worktree_path=wt,
            base=old_sha,
        )
        head_in_wt = subprocess.run(
            ["git", "-C", str(wt), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(head_in_wt, old_sha,
                         "explicit base ref must drive the new worktree's HEAD")


class GitCommonDir(unittest.TestCase):
    def test_resolves_main_checkout(self):
        tmp = _init_throwaway_repo()
        try:
            root = Path(tmp.name)
            common = git_common_dir(root)
            self.assertIsNotNone(common)
            # git-common-dir for a normal checkout ends with `.git`.
            # Compare basenames (the temp dir may resolve through
            # /private/var/folders/... vs the caller's Path(tmp.name)
            # which on macOS is the canonical /private/var path —
            # strict equality breaks across the symlink layer).
            self.assertEqual(Path(common).name, ".git")
            # And it must be a real path on disk (dir for main, file
            # gitfile for linked worktrees).
            self.assertTrue(Path(common).exists())
        finally:
            tmp.cleanup()

    def test_returns_none_outside_repo(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(git_common_dir(Path(td)))


class ListWorktreeDirs(unittest.TestCase):
    """Canonical worktree enumeration used by the dashboard side."""

    def setUp(self):
        self.tmp = _init_throwaway_repo()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_only_worktree_dirs_under_canonical_root(self):
        # Cut two worktrees.
        for slug in ("a", "b"):
            cut_worktree(
                repo_root=self.root,
                branch=f"feat/{slug}",
                worktree_path=self.root / ".worktrees" / slug,
            )
        dirs = list_worktree_dirs(self.root)
        names = sorted(p.name for p in dirs)
        self.assertEqual(names, ["a", "b"])

    def test_returns_empty_when_no_worktrees(self):
        self.assertEqual(list_worktree_dirs(self.root), [])


if __name__ == "__main__":
    unittest.main()
