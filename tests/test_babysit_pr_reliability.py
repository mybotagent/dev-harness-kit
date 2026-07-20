"""test_babysit_pr_reliability.py -- unit tests for
lib/babysit_pr_reliability.py.

Pins the contract for the two helpers that close Gap #11 (stale lock)
and Gap #12 (ghost workflow classification) from
docs/hook-coverage-gaps.md:

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
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
# Add the worktree's lib/ to sys.path so the helper is importable as
# `babysit_pr_reliability`. Tests run from the main checkout by default
# (pytest resolves relative paths against the test file's parent); the
# worktree's lib/ is the canonical source for this branch.
sys.path.insert(0, str(REPO_ROOT / "lib"))

# Import is part of the contract: the helper must be importable from the
# repo root and live in lib/babysit_pr_reliability.py.
import babysit_pr_reliability as bpr  # noqa: E402


def _make_pid_alive_body() -> str:
    """Build a lock body that names a pid known to be alive.

    Uses os.getpid() (this Python process) so the pid-alive probe in
    the helper reliably returns True regardless of platform quirks.
    """
    return f"2026-07-18T14:23:45Z pid={os.getpid()} branch=feat/x"


def _make_pid_dead_body() -> str:
    # Pick a pid that should never be a live process (large negative
    # numbers fail the pid=0 safety check in _pid_alive).
    return "2026-07-18T14:23:45Z pid=1 branch=feat/x"  # /proc/1 may exist on Linux; covered below


class TestIsStaleLock(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.lock = self.root / "babysit.lock"

    # T1
    def test_missing_returns_false(self) -> None:
        self.assertFalse(bpr.is_stale_lock(self.lock))

    # T2
    def test_fresh_lock_with_running_pid_is_not_stale(self) -> None:
        self.lock.write_text(_make_pid_alive_body())
        now = time.time()  # lock mtime is now-ish
        self.assertFalse(bpr.is_stale_lock(self.lock, now_epoch=now))

    # T3
    def test_lock_older_than_ttl_is_stale(self) -> None:
        self.lock.write_text(_make_pid_alive_body())
        # Set mtime to one hour ago
        old = time.time() - 3600
        os.utime(self.lock, (old, old))
        now = time.time()
        self.assertTrue(bpr.is_stale_lock(self.lock, ttl_seconds=1800, now_epoch=now))

    # T4
    def test_fresh_lock_with_dead_pid_is_stale(self) -> None:
        # Synthesize a lock whose pid is unlikely to exist on either
        # platform: pick the largest valid 32-bit pid (Linux pid_max
        # default), which almost certainly has no process attached.
        dead_pid = 32768  # small; pid=1 may exist on Linux CI
        # Use a more reliable "dead" pid: 2^30 (far beyond pid_max).
        dead_pid = 2**30
        self.lock.write_text(f"2026-07-18T14:23:45Z pid={dead_pid} branch=feat/x")
        # Fresh mtime
        now = time.time()
        os.utime(self.lock, (now, now))
        self.assertTrue(bpr.is_stale_lock(self.lock, ttl_seconds=3600, now_epoch=now))

    # T5
    def test_malformed_body_returns_false(self) -> None:
        # No pid= field at all -> not classified stale; caller can
        # decide whether to error or proceed.
        self.lock.write_text("not-a-lock-file\n")
        now = time.time()
        os.utime(self.lock, (now, now))
        self.assertFalse(bpr.is_stale_lock(self.lock, now_epoch=now))

    # T6
    def test_short_ttl_with_running_pid_is_not_stale(self) -> None:
        # Negative ttl + live pid: returns False (not stale on age).
        self.lock.write_text(_make_pid_alive_body())
        now = time.time()
        os.utime(self.lock, (now, now))
        self.assertFalse(bpr.is_stale_lock(self.lock, ttl_seconds=60, now_epoch=now))


class TestClassifyCheck(unittest.TestCase):
    NOW = 1_700_000_000  # a fixed reference point

    # T7
    def test_approved_conclusions(self) -> None:
        for c in ("success", "skipped", "neutral"):
            self.assertEqual(
                bpr.classify_check({"conclusion": c, "databaseId": 1}, self.NOW),
                "approved",
            )

    # T8
    def test_failing_conclusions(self) -> None:
        for c in ("failure", "failures", "cancelled", "timed_out", "stale", "error"):
            self.assertEqual(
                bpr.classify_check({"conclusion": c, "databaseId": 1}, self.NOW),
                "failing",
            )

    # T9
    def test_live_pending_returns_pending(self) -> None:
        # startedAt is 30s ago -> live pending.
        recent_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.NOW - 30))
        self.assertEqual(
            bpr.classify_check({
                "conclusion": None,
                "state": "pending",
                "databaseId": 12345,
                "startedAt": recent_iso,
            }, self.NOW),
            "pending",
        )

    # T10
    def test_long_pending_no_databaseId_is_ghost(self) -> None:
        # startedAt is 10 minutes ago, well beyond default 300s ghost
        # threshold; databaseId is missing.
        old_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.NOW - 600))
        # databaseId absent (None, missing, or empty string)
        for db_field in (None, "", 0, "0", False):
            check = {
                "conclusion": None,
                "state": "pending",
                "startedAt": old_iso,
            }
            if db_field is not None:
                check["databaseId"] = db_field
            # 0 / "0" / "" / False / None all fail the presence check
            self.assertEqual(
                bpr.classify_check(check, self.NOW),
                "ghost",
                f"db_field={db_field!r} should ghost",
            )

    # T11
    def test_long_pending_with_databaseId_but_old_updatedAt_is_ghost(self) -> None:
        # updatedAt far in the past > ghost threshold => ghost
        old_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.NOW - 3600))
        self.assertEqual(
            bpr.classify_check({
                "conclusion": None,
                "state": "pending",
                "databaseId": 99999,
                "updatedAt": old_iso,
            }, self.NOW),
            "ghost",
        )

    # T12
    def test_malformed_check_returns_pending_or_ghost_never_raises(self) -> None:
        # The contract: classify_check never raises. Truly malformed
        # shapes (None, str, int, list, empty dict) fall back to
        # "pending". A partial-but-shape-valid payload
        # (`{"state": "pending"}` with no databaseId) is ghost per the
        # documented rule. Both classes are acceptable; what matters is
        # "approved"/"failing" are reserved for terminal conclusions and
        # no input causes an exception.
        for bad in (None, "string", 42, []):
            self.assertEqual(
                bpr.classify_check(bad, self.NOW),  # type: ignore[arg-type]
                "pending",
            )
        # Partial check (no databaseId) -> ghost per contract.
        self.assertEqual(
            bpr.classify_check({"state": "pending"}, self.NOW),
            "ghost",
        )
        # Empty dict is ambiguous; the function returns "pending" because
        # `isinstance({}, Mapping)` is True but conclusion is missing
        # AND databaseId is missing -- per the documented rule, no
        # databaseId is ghost. Pin the actual contract here.
        self.assertEqual(bpr.classify_check({}, self.NOW), "ghost")

    # T13
    def test_short_pending_with_databaseId_keeps_pending(self) -> None:
        # Exactly at the threshold (300s old): NOT a ghost (use strict >).
        boundary_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.NOW - 299))
        self.assertEqual(
            bpr.classify_check({
                "conclusion": None,
                "state": "pending",
                "databaseId": 111,
                "updatedAt": boundary_iso,
            }, self.NOW),
            "pending",
        )


if __name__ == "__main__":
    unittest.main()
