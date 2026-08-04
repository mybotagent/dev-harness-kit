"""Tests for lib/babysit_pr_reliability.py — is_stale_lock, classify_check,
and check_verdict_freshness.

Pins the contract for the three helpers in
`docs/hooks/hook-coverage-gaps.md`:

  is_stale_lock(path, ttl_seconds, *, now_epoch=None)
    T1: missing path returns False (nothing to be stale)
    T2: fresh lock with running pid returns False
    T3: lock older than TTL returns True (clock skew safe)
    T4: fresh lock but stale pid returns True
    T5: lock with malformed body returns False (be conservative)
    T6: lock with pid= field but TTL not exceeded AND pid alive =>
        False

  classify_check(check, now_epoch, *, ghost_threshold_seconds=300)
    T7: approved conclusions return "approved"
    T8: failing conclusions return "failing"
    T9: live-pending (recent startedAt) returns "pending"
    T10: long-pending without databaseId returns "ghost"
    T11: long-pending with databaseId but old updatedAt returns "ghost"
    T12: malformed check returns "pending" (never raises)
    T13: short-pending keep returning "pending"
    T14: fresh requested/queued/expected/waiting check with a
         databaseId but no startedAt/updatedAt at all (age zero)
         returns "pending", not "ghost" (issue #481 regression)
    T15: same states, but with a stale (past-threshold) updatedAt,
         still correctly return "ghost"

  check_verdict_freshness(pr_number, run_started_epoch, now_epoch)
    T16: transport error returns GHOST
    T17: no claude[bot] comments with **Verdict:** returns GHOST
    T18: latest verdict comment newer than run returns FRESH
    T19: latest verdict comment older than run returns STALE
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))

import babysit_pr_reliability as bpr  # noqa: E402

# --------------------------------------------------------------------------- #
# is_stale_lock (Gap #11)
# --------------------------------------------------------------------------- #


def _make_pid_alive_body() -> str:
    return f"2026-07-18T14:23:45Z pid={os.getpid()} branch=feat/x"


def _make_pid_dead_body() -> str:
    # PIDs in the 90000-99999 range are typically not in use. The
    # _pid_alive helper uses os.kill(pid, 0) which raises ESRCH for
    # any non-existent pid.
    return "2026-07-18T14:23:45Z pid=99999 branch=feat/x"


class TestModuleConstants(unittest.TestCase):
    """Issue #310: the lock TTL (1800) and ghost-check threshold (300)
    live as module-level constants so the values are not duplicated
    between function defaults and docstrings. Re-exports keep the
    constants importable as `bpr.LOCK_TTL_SECONDS` / `bpr.GHOST_CHECK_THRESHOLD_SECONDS`.
    """

    def test_lock_ttl_constant_matches_prior_default(self):
        self.assertEqual(bpr.LOCK_TTL_SECONDS, 1800)
        self.assertEqual(bpr.is_stale_lock.__defaults__[0], bpr.LOCK_TTL_SECONDS)

    def test_ghost_check_threshold_constant_matches_prior_default(self):
        self.assertEqual(bpr.GHOST_CHECK_THRESHOLD_SECONDS, 300)
        sig_default = bpr.classify_check.__kwdefaults__["ghost_threshold_seconds"]
        self.assertEqual(sig_default, bpr.GHOST_CHECK_THRESHOLD_SECONDS)

    def test_constants_are_reexported(self):
        # The library re-exports both so callers can `from babysit_pr_reliability
        # import LOCK_TTL_SECONDS` without poking `bpr.` for the common case.
        self.assertTrue(hasattr(bpr, "LOCK_TTL_SECONDS"))
        self.assertTrue(hasattr(bpr, "GHOST_CHECK_THRESHOLD_SECONDS"))


class TestIsStaleLock(unittest.TestCase):
    def test_missing_returns_false(self) -> None:
        self.assertFalse(bpr.is_stale_lock("/tmp/__definitely_does_not_exist__.lock"))

    def test_fresh_lock_with_running_pid_is_not_stale(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".lock", delete=False) as f:
            f.write(_make_pid_alive_body())
            path = f.name
        try:
            self.assertFalse(bpr.is_stale_lock(path))
        finally:
            os.unlink(path)

    def test_lock_older_than_ttl_is_stale(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".lock", delete=False) as f:
            f.write(_make_pid_alive_body())
            path = f.name
        try:
            # Pretend the lock is 31 minutes old.
            now = time.time() + (31 * 60)
            self.assertTrue(bpr.is_stale_lock(path, now_epoch=now))
        finally:
            os.unlink(path)

    def test_fresh_lock_with_dead_pid_is_stale(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".lock", delete=False) as f:
            f.write(_make_pid_dead_body())
            path = f.name
        try:
            self.assertTrue(bpr.is_stale_lock(path))
        finally:
            os.unlink(path)

    def test_malformed_body_returns_false(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".lock", delete=False) as f:
            f.write("not a real lock file at all\n")
            path = f.name
        try:
            # Malformed body must NOT be misclassified as stale — being
            # conservative means returning False (the next babysit-pr
            # run will overwrite or re-evaluate).
            self.assertFalse(bpr.is_stale_lock(path))
        finally:
            os.unlink(path)

    def test_short_ttl_with_running_pid_is_not_stale(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".lock", delete=False) as f:
            f.write(_make_pid_alive_body())
            path = f.name
        try:
            self.assertFalse(bpr.is_stale_lock(path, ttl_seconds=60))
        finally:
            os.unlink(path)


# --------------------------------------------------------------------------- #
# classify_check (Gap #12)
# --------------------------------------------------------------------------- #


class TestClassifyCheck(unittest.TestCase):
    NOW = 1_700_000_000  # arbitrary fixed epoch for deterministic comparisons

    def test_approved_conclusions(self) -> None:
        for c in ("success", "skipped", "neutral", "SUCCESS", "Skipped"):
            with self.subTest(conclusion=c):
                self.assertEqual(
                    bpr.classify_check({"conclusion": c, "databaseId": 1}, self.NOW),
                    "approved",
                )

    def test_failing_conclusions(self) -> None:
        for c in ("failure", "cancelled", "timed_out", "stale", "error", "FAILURE"):
            with self.subTest(conclusion=c):
                self.assertEqual(
                    bpr.classify_check({"conclusion": c, "databaseId": 1}, self.NOW),
                    "failing",
                )

    def test_live_pending_returns_pending(self) -> None:
        check = {
            "conclusion": None,
            "databaseId": 1,
            "startedAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:10Z",  # 10s old — well under 300s
        }
        self.assertEqual(bpr.classify_check(check, self.NOW), "pending")

    def test_long_pending_no_databaseId_is_ghost(self) -> None:
        check = {
            "conclusion": None,
            "databaseId": None,
            "startedAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:10Z",
        }
        self.assertEqual(bpr.classify_check(check, self.NOW), "ghost")

    def test_long_pending_with_databaseId_but_old_updatedAt_is_ghost(self) -> None:
        # updatedAt 1h in the past -- well past the 300s ghost threshold.
        old_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.NOW - 3600))
        check = {
            "conclusion": None,
            "databaseId": 1,
            "startedAt": old_iso,
            "updatedAt": old_iso,
        }
        self.assertEqual(bpr.classify_check(check, self.NOW), "ghost")

    def test_malformed_check_returns_pending_or_ghost_never_raises(self) -> None:
        # Malformed input must never raise.
        for payload in (None, 42, "string", [], {"conclusion": 12345}):
            with self.subTest(payload=payload):
                result = bpr.classify_check(payload, self.NOW)  # type: ignore[arg-type]
                self.assertIn(result, {"pending", "ghost", "approved", "failing"})

    def test_short_pending_with_databaseId_keeps_pending(self) -> None:
        # updatedAt 5s in the past -- well under the 300s threshold.
        recent_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.NOW - 5))
        check = {
            "conclusion": None,
            "databaseId": 1,
            "startedAt": recent_iso,
            "updatedAt": recent_iso,
        }
        self.assertEqual(bpr.classify_check(check, self.NOW), "pending")

    def test_fresh_requested_check_with_no_timestamp_is_pending_not_ghost(self) -> None:
        # Issue #481 regression: a freshly requested/queued check has
        # no startedAt/updatedAt, so it must be pending, not ghost.
        for state in ("expected", "waiting", "requested", "queued"):
            with self.subTest(state=state):
                check = {
                    "conclusion": None,
                    "databaseId": 1,
                    "state": state,
                }
                self.assertEqual(bpr.classify_check(check, self.NOW), "pending")

    def test_stale_requested_check_past_threshold_is_still_ghost(self) -> None:
        # If the requested check's updatedAt IS set but older than
        # the threshold, it's a ghost.
        for state in ("expected", "waiting", "requested", "queued"):
            with self.subTest(state=state):
                old_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.NOW - 3600))
                check = {
                    "conclusion": None,
                    "databaseId": 1,
                    "state": state,
                    "updatedAt": old_iso,
                }
                self.assertEqual(bpr.classify_check(check, self.NOW), "ghost")


# --------------------------------------------------------------------------- #
# check_verdict_freshness (SHO-179)
# --------------------------------------------------------------------------- #


def _ts(iso: str) -> float:
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


class TestCheckVerdictFreshness(unittest.TestCase):
    def _mock_run(self, payload):
        fake = MagicMock()
        fake.returncode = 0
        fake.stdout = json.dumps(payload)
        return fake

    def test_returns_ghost_on_transport_error(self):
        # SubprocessError covers CalledProcessError / TimeoutExpired /
        # any gh-side failure. The helper must swallow it and return
        # GHOST (fail-closed) rather than raising.
        import subprocess as _sp
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", side_effect=_sp.SubprocessError("boom")):
                result = bpr.check_verdict_freshness(
                    pr_number=566, run_started_epoch=0, now_epoch=0,
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
                    pr_number=566, run_started_epoch=0, now_epoch=0,
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
                    pr_number=566, run_started_epoch=run_started, now_epoch=now_epoch,
                )
        self.assertEqual(result["status"], bpr.FRESH)
        self.assertEqual(result["comment_id"], "c1")
        self.assertEqual(result["comment_age_seconds"], 100)

    def test_returns_stale_when_latest_comment_before_run_within_window(self):
        # Comment 100s older than run; age 300s < 600s window -> STALE.
        latest = "2026-08-04T00:08:20Z"
        latest_epoch = _ts(latest)
        run_started = latest_epoch + 100
        now_epoch = run_started + 200
        payload = [
            {"user": {"login": "claude[bot]"},
             "body": "**Verdict:** Approve",
             "updated_at": latest, "id": "c1"},
        ]
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", return_value=self._mock_run(payload)):
                result = bpr.check_verdict_freshness(
                    pr_number=566, run_started_epoch=run_started, now_epoch=now_epoch,
                )
        self.assertEqual(result["status"], bpr.STALE)
        self.assertEqual(result["comment_id"], "c1")
        self.assertEqual(result["comment_age_seconds"], 300)

    def test_returns_ghost_when_latest_comment_past_freshness_window(self):
        # Comment older than run AND older than the freshness window
        # (VERDICT_FRESHNESS_WINDOW_SECONDS = 600) -> GHOST (fail-closed).
        latest = "2026-08-04T00:00:00Z"
        latest_epoch = _ts(latest)
        run_started = latest_epoch + 100  # comment 100s older than run
        now_epoch = latest_epoch + 700   # but 700s old from now -> past window
        payload = [
            {"user": {"login": "claude[bot]"},
             "body": "**Verdict:** Approve",
             "updated_at": latest, "id": "c1"},
        ]
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "sh-ai-x/dev-harness-kit"}):
            with patch("subprocess.run", return_value=self._mock_run(payload)):
                result = bpr.check_verdict_freshness(
                    pr_number=566, run_started_epoch=run_started, now_epoch=now_epoch,
                )
        self.assertEqual(result["status"], bpr.GHOST)
        self.assertEqual(result["comment_id"], "c1")
        self.assertEqual(result["comment_age_seconds"], 700)


if __name__ == "__main__":
    unittest.main()
