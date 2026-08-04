"""Tests for lib/babysit_pr_reliability.py — including check_verdict_freshness.

Covers the SHO-179 findings:
  - FRESH-WINDOW-BYPASS: 600s window enforced independently of ordering
  - CROSS-GATE-FALSE-FRESH: gate/run matching via expected_run_id
  - RETURN-SURFACE: no raw comments returned
"""

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


def _comment(updated_at: str, body: str = "**Verdict:** Approve", comment_id: str = "c1",
            run_id: int | None = None) -> dict:
    if run_id is not None:
        body = f"<!-- dev-kit-verdict-audit --> run={run_id} job=maintenance status=success verdict=Approve source=issue-comment-extraction\n\n{body}"
    return {
        "user": {"login": "claude[bot]"},
        "body": body,
        "updated_at": updated_at,
        "id": comment_id,
    }


class TestCheckVerdictFreshness(unittest.TestCase):
    def _mock_run(self, payload):
        fake = MagicMock()
        fake.returncode = 0
        fake.stdout = json.dumps(payload)
        return fake

    def test_ghost_on_transport_error(self):
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", side_effect=OSError("boom")):
                result = bpr.check_verdict_freshness(
                    pr_number=566, run_started_epoch=0, now_epoch=0
                )
        self.assertEqual(result["status"], bpr.GHOST)
        self.assertIn("reason", result)
        self.assertNotIn("comments", result)

    def test_ghost_when_no_claude_comments(self):
        payload = [_comment("2026-08-01T00:00:00Z").update(
            {"user": {"login": "github-actions"}})]
        # Reset to a non-claude comment
        payload = [{"user": {"login": "github-actions"},
                    "body": "x", "updated_at": "2026-08-01T00:00:00Z", "id": "c1"}]
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", return_value=self._mock_run(payload)):
                result = bpr.check_verdict_freshness(
                    pr_number=566, run_started_epoch=0, now_epoch=0
                )
        self.assertEqual(result["status"], bpr.GHOST)

    def test_fresh_when_latest_comment_after_run_and_within_window(self):
        latest_iso = "2026-08-04T00:18:20Z"
        latest_epoch = _ts(latest_iso)
        run_started = latest_epoch - 100
        now_epoch = latest_epoch + 50  # 50s after comment, within 600s window
        payload = [_comment(latest_iso, comment_id="c1", run_id=1)]
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", return_value=self._mock_run(payload)):
                result = bpr.check_verdict_freshness(
                    pr_number=566, expected_run_id=1,
                    run_started_epoch=run_started, now_epoch=now_epoch,
                )
        self.assertEqual(result["status"], bpr.FRESH)

    def test_stale_when_latest_comment_before_run_within_window(self):
        latest_iso = "2026-08-04T00:18:20Z"
        latest_epoch = _ts(latest_iso)
        run_started = latest_epoch + 10   # 10s after the comment (within window)
        now_epoch = run_started + 100     # 100s after run
        payload = [_comment(latest_iso, comment_id="c1", run_id=1)]
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", return_value=self._mock_run(payload)):
                result = bpr.check_verdict_freshness(
                    pr_number=566, expected_run_id=1,
                    run_started_epoch=run_started, now_epoch=now_epoch,
                )
        self.assertEqual(result["status"], bpr.STALE)

    def test_ghost_when_latest_comment_before_run_past_window(self):
        latest_iso = "2026-08-04T00:08:20Z"
        latest_epoch = _ts(latest_iso)
        run_started = latest_epoch + 50
        now_epoch = run_started + 1000  # > 600s window
        payload = [_comment(latest_iso, comment_id="c1", run_id=1)]
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", return_value=self._mock_run(payload)):
                result = bpr.check_verdict_freshness(
                    pr_number=566, expected_run_id=1,
                    run_started_epoch=run_started, now_epoch=now_epoch,
                )
        self.assertEqual(result["status"], bpr.GHOST)

    def test_ghost_when_latest_comment_newer_than_run_but_past_window(self):
        # FRESH-WINDOW-BYPASS fix: even if comment is newer than run,
        # if it's past the 600s window, must be GHOST.
        latest_iso = "2026-08-04T00:00:00Z"
        latest_epoch = _ts(latest_iso)
        run_started = latest_epoch - 50  # comment is 50s AFTER run
        now_epoch = latest_epoch + 1000  # but 1000s after comment, past 600s window
        payload = [_comment(latest_iso, comment_id="c1", run_id=1)]
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", return_value=self._mock_run(payload)):
                result = bpr.check_verdict_freshness(
                    pr_number=566, expected_run_id=1,
                    run_started_epoch=run_started, now_epoch=now_epoch,
                )
        self.assertEqual(result["status"], bpr.GHOST)

    def test_cross_gate_false_fresh_blocked(self):
        # CROSS-GATE-FALSE-FRESH fix: a fresh comment from gate A
        # (run=999) must NOT certify a different gate's freshness (run=1).
        latest_iso = "2026-08-04T00:18:20Z"
        latest_epoch = _ts(latest_iso)
        run_started = latest_epoch - 100
        now_epoch = latest_epoch + 50
        # Comment names a different run (999) than expected (1)
        payload = [_comment(latest_iso, comment_id="c1", run_id=999)]
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", return_value=self._mock_run(payload)):
                result = bpr.check_verdict_freshness(
                    pr_number=566, expected_run_id=1,  # expecting run 1
                    run_started_epoch=run_started, now_epoch=now_epoch,
                )
        self.assertEqual(result["status"], bpr.GHOST)
        # The reason should mention the expected run_id=1 to indicate the mismatch

    def test_no_raw_comments_in_response(self):
        # RETURN-SURFACE fix: no "comments" key in any response.
        latest_iso = "2026-08-04T00:18:20Z"
        latest_epoch = _ts(latest_iso)
        run_started = latest_epoch - 100
        now_epoch = latest_epoch + 50
        payload = [_comment(latest_iso, comment_id="c1", run_id=1)]
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", return_value=self._mock_run(payload)):
                result = bpr.check_verdict_freshness(
                    pr_number=566, expected_run_id=1,
                    run_started_epoch=run_started, now_epoch=now_epoch,
                )
        self.assertNotIn("comments", result)
        self.assertNotIn("comment_id", result)


class TestIsStaleLock(unittest.TestCase):
    def test_no_lock_returns_false(self):
        self.assertFalse(bpr.is_stale_lock("/tmp/does-not-exist-babysit.lock"))

    def test_fresh_lock_returns_false(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".lock", delete=False) as f:
            f.write(f"pid={os.getpid()}\n")
            path = f.name
        self.assertFalse(bpr.is_stale_lock(path))


if __name__ == "__main__":
    unittest.main()
