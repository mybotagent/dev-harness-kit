#!/usr/bin/env python3
"""test_log_capture_coverage.py — End-to-end coverage of the worktree
session-capture pipeline.

Goal: prove that a session started inside a sibling worktree shows up in
the analyzer dashboard without any manual reconciliation. Pipeline under
test:

  1. ``tools/save_log.py`` (capture hook) writes to the **main** checkout's
     ``logs/`` regardless of which worktree the session ran in.
  2. ``tools/token_efficiency_analyzer.py`` discovers JSONL files under
     ``<main>/.claude/worktrees/*/logs/`` and recurses into nested
     ``.claude/worktrees/`` layers.
  3. ``worktree_from_path`` resolves each session's worktree bucket from
     the JSONL file path, so the Cost by Worktree panel populates.

Test layout (one tmpdir per test):

    <tmp>/main/
        .git/                                  real git repo
        .claude/worktrees/wt-x/                git worktree, branch=fix-x
            (session captured here)
        logs/claude-code/fix-x/<sid>.jsonl     capture destination
            (must end up HERE, not in wt-x/)

The test runs the real save_log.py subprocess against the worktree path
and the real analyzer against the main checkout, with the real git
binaries. No mocks. If any layer breaks, the test fails with a clear
message about which pipeline stage regressed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SAVE_LOG_PY = PROJECT_ROOT / "tools" / "save_log.py"
ANALYZER_PY = PROJECT_ROOT / "tools" / "token_efficiency_analyzer.py"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        check=check, timeout=10,
    )


def _make_minimal_transcript(path: Path) -> None:
    """Write a JSONL file with one user + one assistant line carrying text.
    save_log.slim_transcript keeps these; the result is a real JSONL that
    aggregate_session can parse.
    """
    lines = [
        json.dumps({"type": "user", "isMeta": False,
                    "message": {"role": "user", "content": "hello from wt"}}),
        json.dumps({"type": "assistant", "message": {
            "role": "assistant", "model": "claude-sonnet-5",
            "content": [{"type": "text", "text": "hi from main"}],
            "usage": {"input_tokens": 100, "output_tokens": 20,
                      "cache_read_input_tokens": 50,
                      "cache_creation": {"ephemeral_5m_input_tokens": 0,
                                         "ephemeral_1h_input_tokens": 0}},
        }}),
    ]
    path.write_text("\n".join(lines) + "\n")


class TestWorktreeCapturePipeline(unittest.TestCase):
    """End-to-end: capture in a worktree → analyzer sees it under the right bucket."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="capture-cov-"))
        self.main = self.tmp / "main"
        self.main.mkdir()
        _git(self.main, "init", "-q")
        (self.main / "f").write_text("init\n")
        _git(self.main, "add", ".")
        _git(self.main, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-q", "-m", "init")
        # Create a sibling worktree under .claude/worktrees/ — matches
        # the layout the analyzer discovers.
        wt_dir = self.main / ".claude" / "worktrees" / "wt-fix-x"
        _git(self.main, "worktree", "add", "-q", "-b", "fix-x", str(wt_dir))
        self.wt = wt_dir
        # Synthetic transcript inside the worktree.
        self.transcript = self.wt / "transcript.jsonl"
        _make_minimal_transcript(self.transcript)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_save_log(self, cwd: Path, sid: str) -> subprocess.CompletedProcess:
        payload = json.dumps({
            "session_id": sid,
            "transcript_path": str(self.transcript),
            "cwd": str(cwd),
        })
        return subprocess.run(
            [sys.executable, str(SAVE_LOG_PY), "--tool", "claude-code"],
            input=payload, capture_output=True, text=True, timeout=15,
        )

    def _run_analyzer(self) -> subprocess.CompletedProcess:
        out_html = self.tmp / "dashboard.html"
        return subprocess.run(
            [sys.executable, str(ANALYZER_PY), "--repo", "wt-fix-x",
             "--days", "30", "--logs-dir", str(self.main / "logs"),
             "--include-worktree-logs",
             "--out", str(out_html)],
            capture_output=True, text=True, timeout=30,
            cwd=str(self.main),
        )

    def test_worktree_capture_lands_in_main_logs(self):
        rc = self._run_save_log(self.wt, "sess-fix-x")
        self.assertEqual(rc.returncode, 0,
                         f"save_log failed in worktree:\n{rc.stderr}")
        # Pipeline assertion 1: capture lands in MAIN, not worktree.
        captured = self.main / "logs" / "claude-code" / "fix-x" / "sess-fix-x.jsonl"
        self.assertTrue(captured.exists(),
                        f"capture missing from MAIN logs at {captured}")
        self.assertFalse((self.wt / "logs").exists(),
                         f"worktree grew its own logs/ dir: {self.wt / 'logs'}")

    def test_worktree_session_shows_in_cost_by_worktree_panel(self):
        rc = self._run_save_log(self.wt, "sess-fix-x")
        self.assertEqual(rc.returncode, 0, f"save_log failed: {rc.stderr}")

        out_html = self.tmp / "dashboard.html"
        ana = subprocess.run(
            [sys.executable, str(ANALYZER_PY), "--repo", "wt-fix-x",
             "--days", "30", "--logs-dir", str(self.main / "logs"),
             "--include-worktree-logs",
             "--out", str(out_html)],
            capture_output=True, text=True, timeout=30,
            cwd=str(self.main),
        )
        self.assertEqual(ana.returncode, 0,
                         f"analyzer failed:\nstdout={ana.stdout}\nstderr={ana.stderr}")
        # Pipeline assertion 2: HTML contains the worktree bucket row.
        html = out_html.read_text()
        self.assertIn("wt-fix-x", html,
                      "Cost by Worktree panel missing the worktree bucket")
        self.assertIn("(main)", html,
                      "Cost by Worktree panel missing the main bucket")

    def test_nested_worktree_capture_lands_in_main_logs(self):
        # Worktree-of-a-worktree: wt-fix-x adds wt-fix-y underneath itself.
        nested_wt = self.wt / ".claude" / "worktrees" / "wt-fix-y"
        _git(self.wt, "worktree", "add", "-q", "-b", "fix-y", str(nested_wt))
        # Use the same synthetic transcript; what matters is the cwd.
        rc = self._run_save_log(nested_wt, "sess-fix-y")
        self.assertEqual(rc.returncode, 0,
                         f"save_log failed in nested worktree:\n{rc.stderr}")
        # Same canonical destination regardless of nesting depth.
        captured = self.main / "logs" / "claude-code" / "fix-y" / "sess-fix-y.jsonl"
        self.assertTrue(captured.exists(),
                        f"nested capture missing from MAIN logs at {captured}")
        # And the analyzer's recursive walker must surface it.
        out_html = self.tmp / "nested-dashboard.html"
        ana = subprocess.run(
            [sys.executable, str(ANALYZER_PY), "--repo", "wt-fix-y",
             "--days", "30", "--logs-dir", str(self.main / "logs"),
             "--include-worktree-logs",
             "--out", str(out_html)],
            capture_output=True, text=True, timeout=30,
            cwd=str(self.main),
        )
        self.assertEqual(ana.returncode, 0, f"analyzer failed: {ana.stderr}")
        self.assertIn("wt-fix-y", out_html.read_text(),
                      "nested-worktree bucket missing from dashboard")


if __name__ == "__main__":
    unittest.main()