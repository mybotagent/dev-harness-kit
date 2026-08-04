"""Tests for lib/babysit_pr_reliability.py — including check_verdict_freshness."""

import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

import babysit_pr_reliability as bpr


def _ts(iso: str) -> int:
    return int(datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


class TestCheckVerdictFreshness(unittest.TestCase):
    def _mock_run(self, payload):
        fake = MagicMock()
        fake.returncode = 0
        fake.stdout = json.dumps(payload)
        return fake

    def test_returns_ghost_on_transport_error(self):
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", side_effect=Exception("boom")):
                result = bpr.check_verdict_freshness(
                    pr_number=566, run_id=1, run_started_epoch=0, now_epoch=0
                )
        self.assertEqual(result["status"], bpr.GHOST)

    def test_returns_ghost_when_no_claude_comments(self):
        payload = [
            {"user": {"login": "github-actions"},
             "body": "x", "updated_at": "2026-08-01T00:00:00Z", "id": "c1"},
        ]
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", return_value=self._mock_run(payload)):
                result = bpr.check_verdict_freshness(
                    pr_number=566, run_id=1, run_started_epoch=0, now_epoch=0
                )
        self.assertEqual(result["status"], bpr.GHOST)

    def test_returns_fresh_when_latest_comment_after_run(self):
        latest = "2026-08-04T00:18:20Z"
        latest_epoch = _ts(latest)
        run_started = latest_epoch - 100  # comment 100s after run started
        now_epoch = latest_epoch + 100
        payload = [
            {"user": {"login": "claude[bot]"},
             "body": "**Verdict:** Approve\nstuff",
             "updated_at": latest, "id": "c1"},
        ]
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", return_value=self._mock_run(payload)):
                result = bpr.check_verdict_freshness(
                    pr_number=566, run_id=1,
                    run_started_epoch=run_started, now_epoch=now_epoch,
                )
        self.assertEqual(result["status"], bpr.FRESH)
        self.assertEqual(result["comment_id"], "c1")
        self.assertEqual(result["comment_age_seconds"], 100)

    def test_returns_stale_when_latest_comment_before_run(self):
        # Run started AFTER the most recent claude[bot] comment -> STALE
        latest = "2026-08-04T00:08:20Z"
        latest_epoch = _ts(latest)
        run_started = latest_epoch + 500
        now_epoch = run_started + 200
        payload = [
            {"user": {"login": "claude[bot]"},
             "body": "**Verdict:** Approve",
             "updated_at": latest, "id": "c1"},
        ]
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", return_value=self._mock_run(payload)):
                result = bpr.check_verdict_freshness(
                    pr_number=566, run_id=1,
                    run_started_epoch=run_started, now_epoch=now_epoch,
                )
        self.assertEqual(result["status"], bpr.STALE)
        self.assertEqual(result["comment_id"], "c1")
        self.assertEqual(result["comment_age_seconds"], 700)


class TestIsStaleLock(unittest.TestCase):
    def test_no_lock_returns_false(self):
        self.assertFalse(bpr.is_stale_lock("/tmp/does-not-exist-babysit.lock"))

    def test_fresh_lock_returns_false(self):
        # Use the current process PID so the pid-alive check passes
        with tempfile.NamedTemporaryFile(mode="w", suffix=".lock", delete=False) as f:
            f.write(f"pid={os.getpid()}\n")
            path = f.name
        self.assertFalse(bpr.is_stale_lock(path))


if __name__ == "__main__":
    unittest.main()
