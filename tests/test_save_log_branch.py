#!/usr/bin/env python3
"""
test_save_log_branch.py — Coverage for the per-branch write side of
tools/save_log.py.

Spawns ``python3 tools/save_log.py --tool claude-code`` against synthetic
fixtures and asserts the JSONL lands in ``logs/claude-code/<branch>/<sid>.jsonl``
under the correct branch bucket. Covers:

- Attached HEAD on a feature branch → ``logs/claude-code/feature-foo/<sid>.jsonl``
- Detached HEAD (commit SHA) → ``logs/claude-code/detached-<sha>/<sid>.jsonl``
- Non-git cwd → ``logs/claude-code/no-git/<sid>.jsonl``
- Branch name with slashes → sanitized to single segment
- ``git`` binary missing (empty PATH) → exit 0 + ``no-git`` fallback
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

PROJECT_ROOT = Path(__file__).parent.parent
TOOL_PY = PROJECT_ROOT / "tools" / "save_log.py"
# Allow `from save_log import ...` in the unit-test case.
sys.path.insert(0, str(TOOL_PY.parent))


def _run_save_log(cwd: Path, *, session_id: str = "sid",
                  transcript: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke save_log.py with a minimal payload, returning the CompletedProcess."""
    payload = json.dumps({
        "session_id": session_id,
        "transcript_path": str(transcript),
        "cwd": str(cwd),
    })
    return subprocess.run(
        [sys.executable, str(TOOL_PY), "--tool", "claude-code"],
        input=payload, capture_output=True, text=True,
        env=env, timeout=15, check=False,
    )


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in ``cwd``; ``check=True`` raises on non-zero."""
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        check=check, timeout=10,
    )


class TestSaveLogBranch(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="save-log-branch-"))
        self.transcript = self.tmpdir / "transcript.jsonl"
        # Minimal valid JSONL — save_log will keep only conversation lines
        # but its fallback path handles empty/garbage input by copying verbatim.
        self.transcript.write_text("{}\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ---- attached HEAD ----------------------------------------------------

    def test_attached_head_creates_branch_subdir(self):
        repo = self.tmpdir / "r"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "checkout", "-q", "-b", "feature/foo")
        rc = _run_save_log(repo, transcript=self.transcript)
        self.assertEqual(rc.returncode, 0, msg=rc.stderr)
        self.assertTrue(
            (repo / "logs" / "claude-code" / "feature-foo" / "sid.jsonl").exists(),
            f"feature-foo subdir missing under {repo / 'logs' / 'claude-code'}",
        )

    # ---- detached HEAD ----------------------------------------------------

    def test_detached_head_creates_detached_short_sha_subdir(self):
        repo = self.tmpdir / "r"
        repo.mkdir()
        _git(repo, "init", "-q")
        # Need at least one commit so HEAD resolves to a real SHA.
        (repo / "f").write_text("x")
        _git(repo, "add", ".")
        _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-q", "-m", "init")
        sha = _git(repo, "rev-parse", "HEAD").stdout.strip()[:7]
        # ``git checkout <sha>`` detaches HEAD (the revision form is what
        # triggers detach; ``git checkout HEAD`` without a rev just stays
        # on the current branch).
        _git(repo, "checkout", "-q", sha)
        rc = _run_save_log(repo, transcript=self.transcript)
        self.assertEqual(rc.returncode, 0, msg=rc.stderr)
        d = repo / "logs" / "claude-code"
        matched = [p for p in d.iterdir() if p.name.startswith(f"detached-{sha}")]
        self.assertTrue(
            matched,
            f"no detached-{sha}* subdir under {d}; got {[p.name for p in d.iterdir()]}",
        )

    # ---- non-git cwd ------------------------------------------------------

    def test_non_git_cwd_uses_no_git_subdir(self):
        nonrepo = self.tmpdir / "n"
        nonrepo.mkdir()
        rc = _run_save_log(nonrepo, transcript=self.transcript)
        self.assertEqual(rc.returncode, 0, msg=rc.stderr)
        self.assertTrue(
            (nonrepo / "logs" / "claude-code" / "no-git" / "sid.jsonl").exists(),
        )

    # ---- branch name sanitization -----------------------------------------

    def test_branch_with_slashes_sanitized_to_dash(self):
        repo = self.tmpdir / "r"
        repo.mkdir()
        _git(repo, "init", "-q")
        # Modern git (≥2.30) allows slashes in branch names — pick one with
        # a single slash so it round-trips through ``symbolic-ref`` cleanly.
        _git(repo, "checkout", "-q", "-b", "feature/foo")
        rc = _run_save_log(repo, transcript=self.transcript)
        self.assertEqual(rc.returncode, 0, msg=rc.stderr)
        d = repo / "logs" / "claude-code"
        matched = [p for p in d.iterdir() if p.name == "feature-foo"]
        self.assertTrue(
            matched,
            f"feature-foo subdir missing under {d}; got {[p.name for p in d.iterdir()]}",
        )

    # ---- git binary missing -----------------------------------------------

    def test_git_missing_falls_back_to_no_git_subdir(self):
        repo = self.tmpdir / "r"
        repo.mkdir()
        # Set up a git repo so cwd is otherwise valid; PATH removal ensures
        # detect_branch() cannot find git.
        _git(repo, "init", "-q")
        _git(repo, "checkout", "-q", "-b", "feature/whatever")
        empty_bin = self.tmpdir / "empty-bin"
        empty_bin.mkdir()
        env = {
            "PATH": str(empty_bin),
            "HOME": str(self.tmpdir),
            "TMPDIR": str(self.tmpdir),
        }
        rc = _run_save_log(repo, transcript=self.transcript, env=env)
        self.assertEqual(rc.returncode, 0, msg=rc.stderr)
        self.assertTrue(
            (repo / "logs" / "claude-code" / "no-git" / "sid.jsonl").exists(),
            "expected no-git fallback when git is not on PATH",
        )

    # ---- worktree session capture lands in MAIN checkout logs ------------

    def test_worktree_session_writes_to_main_repo_logs(self):
        # Regression: a session started inside a worktree must capture to
        # the main checkout's logs/, not the worktree's own logs/. Otherwise
        # the analyzer has to walk 90+ worktree dirs to find any session.
        main = self.tmpdir / "main"
        main.mkdir()
        _git(main, "init", "-q")
        (main / "f").write_text("x")
        _git(main, "add", ".")
        _git(main, "-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-q", "-m", "init")
        wt = main / "wt"
        _git(main, "worktree", "add", "-q", "-b", "fix-x", str(wt))
        rc = _run_save_log(wt, transcript=self.transcript)
        self.assertEqual(rc.returncode, 0, msg=rc.stderr)
        # The worktree itself should NOT have grown a logs/ dir.
        self.assertFalse(
            (wt / "logs").exists(),
            f"worktree captured to its own logs/ instead of main: {wt / 'logs'}",
        )
        # Main checkout got the capture.
        self.assertTrue(
            (main / "logs" / "claude-code" / "fix-x" / "sid.jsonl").exists(),
            f"main repo logs/ missing the captured transcript",
        )

    def test_find_main_repo_root_walks_to_shared_git(self):
        from save_log import find_main_repo_root
        main = self.tmpdir / "r2"
        main.mkdir()
        _git(main, "init", "-q")
        self.assertEqual(
            os.path.realpath(find_main_repo_root(str(main)) or ""),
            os.path.realpath(str(main)),
        )
        wt = main / "wt2"
        _git(main, "worktree", "add", "-q", "-b", "feat-y", str(wt))
        self.assertEqual(
            os.path.realpath(find_main_repo_root(str(wt)) or ""),
            os.path.realpath(str(main)),
        )

    def test_find_main_repo_root_returns_none_for_non_git(self):
        from save_log import find_main_repo_root
        nonrepo = self.tmpdir / "n2"
        nonrepo.mkdir()
        self.assertIsNone(find_main_repo_root(str(nonrepo)))

    # ---- detect_branch unit-level (no subprocess) -------------------------

    def test_detect_branch_unit_sanitize(self):
        """Direct unit coverage for the sanitizer edge cases."""
        from save_log import _sanitize_branch, detect_branch
        self.assertEqual(_sanitize_branch("main"), "main")
        self.assertEqual(_sanitize_branch("feature/foo"), "feature-foo")
        self.assertEqual(_sanitize_branch(""), "detached")
        self.assertEqual(_sanitize_branch("."), "detached")
        self.assertEqual(_sanitize_branch(".."), "detached")
        self.assertEqual(_sanitize_branch("/"), "detached")
        # Long names get truncated to 120 chars.
        long = "a" * 200
        self.assertEqual(len(_sanitize_branch(long)), 120)
        # A branch name that sanitizes to nothing becomes "detached".
        self.assertEqual(_sanitize_branch("///"), "detached")
        # non-git path → "no-git"
        bogus = self.tmpdir / "no_such_repo_xyz"
        self.assertEqual(detect_branch(str(bogus)), "no-git")


if __name__ == "__main__":
    unittest.main()
