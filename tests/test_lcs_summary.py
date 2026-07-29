#!/usr/bin/env python3
"""test_lcs_summary.py — Gap 2 (issue #455): aggregation summary block.

Pins the ``summary`` block contract on ``lcs://worktrees`` so operators
can read freshness at a glance instead of eyeballing per-row timestamps.

Contract (proposal §"Gap 2 -- summary + staleness dimension on
aggregations"):

  data.summary.total           # int, == len(data.worktrees)
  data.summary.active          # int, last_touched within 24h of as_of
  data.summary.stale           # int, last_touched >= 24h of as_of
  data.summary.slot_drift.min  # lowest parsed slot_version, or None
  data.summary.slot_drift.max  # highest parsed slot_version, or None
  data.summary.slot_drift.behind_count
                               # count of worktrees whose slot_version
                               # is missing or strictly less than max
  data.summary.as_of           # ISO-8601 UTC, within 60s of call time
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))

from lcs_resources._summary import summarize_worktrees  # noqa: E402
from lcs_resources.worktrees import WorktreesResource  # noqa: E402
from lcs_server import LCSServer, ResourceRegistry, parse_uri  # noqa: E402

# ──────────────────────────────────────────────────────────────────
# Synthetic-fixture tests — exercise the helper directly with known
# inputs so the contract is pinned without depending on git worktree
# mtimes / plugin.json shapes.
# ──────────────────────────────────────────────────────────────────


class TestSummaryHelperShape(unittest.TestCase):
    def test_total_equals_len(self):
        entries = [
            {"last_touched": "2026-07-28T14:49:00+00:00", "slot_version": "0.3.150"},
            {"last_touched": "2026-07-21T05:18:00+00:00", "slot_version": "0.3.100"},
        ]
        summary = summarize_worktrees(entries)
        self.assertEqual(summary["total"], 2)

    def test_active_plus_stale_equals_total(self):
        # Mix of fresh, stale, and missing-timestamp entries.
        as_of = datetime(2026, 7, 29, 15, 0, 0, tzinfo=timezone.utc)
        entries = [
            {"last_touched": "2026-07-29T14:00:00+00:00", "slot_version": "0.3.150"},
            {"last_touched": "2026-07-20T00:00:00+00:00", "slot_version": "0.3.100"},
            {"last_touched": None, "slot_version": "0.3.100"},
        ]
        summary = summarize_worktrees(entries, as_of=as_of)
        self.assertEqual(summary["active"] + summary["stale"], summary["total"])
        self.assertEqual(summary["total"], 3)
        # Two stale (one past 24h, one None), one fresh.
        self.assertEqual(summary["stale"], 2)
        self.assertEqual(summary["active"], 1)

    def test_active_window_is_24h_from_as_of(self):
        as_of = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
        entries = [
            {"last_touched": (as_of - timedelta(hours=23)).isoformat(),
             "slot_version": "0.3.150"},
            {"last_touched": (as_of - timedelta(hours=25)).isoformat(),
             "slot_version": "0.3.150"},
        ]
        summary = summarize_worktrees(entries, as_of=as_of)
        self.assertEqual(summary["active"], 1)
        self.assertEqual(summary["stale"], 1)
        self.assertEqual(summary["as_of"], as_of.isoformat())

    def test_freshness_boundaries_and_future_timestamp(self):
        as_of = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
        cutoff = as_of - timedelta(hours=24)
        entries = [
            {"last_touched": cutoff.isoformat(), "slot_version": "0.3.150"},
            {"last_touched": (cutoff - timedelta(seconds=1)).isoformat(),
             "slot_version": "0.3.150"},
            {"last_touched": (as_of + timedelta(seconds=1)).isoformat(),
             "slot_version": "0.3.150"},
        ]
        summary = summarize_worktrees(entries, as_of=as_of)
        self.assertEqual(summary["active"], 1)
        self.assertEqual(summary["stale"], 2)

    def test_as_of_is_iso8601_utc(self):
        entries = [{"last_touched": "2026-07-28T14:49:00+00:00", "slot_version": "0.3.150"}]
        summary = summarize_worktrees(entries)
        # parseable as ISO-8601
        parsed = datetime.fromisoformat(summary["as_of"])
        # UTC-aware
        self.assertIsNotNone(parsed.tzinfo)
        # within 60 seconds of "now"
        now = datetime.now(timezone.utc)
        self.assertLess(abs((now - parsed).total_seconds()), 60)

    def test_slot_drift_min_max(self):
        entries = [
            {"last_touched": "2026-07-28T14:49:00+00:00", "slot_version": "0.3.150"},
            {"last_touched": "2026-07-21T05:18:00+00:00", "slot_version": "0.3.100"},
            {"last_touched": "2026-07-25T05:18:00+00:00", "slot_version": "0.3.120"},
        ]
        summary = summarize_worktrees(entries)
        self.assertEqual(summary["slot_drift"]["min"], "0.3.100")
        self.assertEqual(summary["slot_drift"]["max"], "0.3.150")

    def test_slot_drift_behind_count(self):
        # 3 worktrees total; one at max (0.3.150), one below (0.3.100),
        # one missing — both below and missing count as "behind".
        entries = [
            {"last_touched": "2026-07-28T14:49:00+00:00", "slot_version": "0.3.150"},
            {"last_touched": "2026-07-21T05:18:00+00:00", "slot_version": "0.3.100"},
            {"last_touched": "2026-07-22T05:18:00+00:00", "slot_version": None},
        ]
        summary = summarize_worktrees(entries)
        self.assertEqual(summary["slot_drift"]["behind_count"], 2)
        self.assertEqual(summary["total"], 3)

    def test_slot_drift_unparseable_treated_as_behind(self):
        entries = [
            {"last_touched": "2026-07-28T14:49:00+00:00", "slot_version": "0.3.150"},
            {"last_touched": "2026-07-21T05:18:00+00:00", "slot_version": "garbage"},
        ]
        summary = summarize_worktrees(entries)
        # Unparseable slot_version is not at max → counts as behind.
        self.assertEqual(summary["slot_drift"]["behind_count"], 1)
        # Unparseable entries are excluded from min/max computation.
        self.assertEqual(summary["slot_drift"]["min"], "0.3.150")
        self.assertEqual(summary["slot_drift"]["max"], "0.3.150")

    def test_no_versions_means_no_drift(self):
        entries = [
            {"last_touched": "2026-07-28T14:49:00+00:00", "slot_version": None},
            {"last_touched": "2026-07-21T05:18:00+00:00", "slot_version": None},
        ]
        summary = summarize_worktrees(entries)
        self.assertIsNone(summary["slot_drift"]["min"])
        self.assertIsNone(summary["slot_drift"]["max"])
        self.assertEqual(summary["slot_drift"]["behind_count"], 0)

    def test_empty_entries(self):
        summary = summarize_worktrees([])
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["active"], 0)
        self.assertEqual(summary["stale"], 0)
        self.assertEqual(summary["slot_drift"]["behind_count"], 0)
        self.assertIsNone(summary["slot_drift"]["min"])
        self.assertIsNone(summary["slot_drift"]["max"])

    def test_proposal_example_14_worktrees(self):
        """The exact proposal example: 14 entries, 1 active (at max),
        13 stale (all below max). behind_count == 13."""
        as_of = datetime(2026, 7, 29, 15, 0, 0, tzinfo=timezone.utc)
        entries = [{"last_touched": (as_of - timedelta(minutes=11)).isoformat(),
                    "slot_version": "0.3.150"}]
        for _ in range(13):
            entries.append({"last_touched": (as_of - timedelta(days=8)).isoformat(),
                            "slot_version": "0.3.100"})
        summary = summarize_worktrees(entries, as_of=as_of)
        self.assertEqual(summary["total"], 14)
        self.assertEqual(summary["active"], 1)
        self.assertEqual(summary["stale"], 13)
        self.assertEqual(summary["slot_drift"]["min"], "0.3.100")
        self.assertEqual(summary["slot_drift"]["max"], "0.3.150")
        self.assertEqual(summary["slot_drift"]["behind_count"], 13)


# ──────────────────────────────────────────────────────────────────
# Integration tests — exercise the live resource through
# WorktreesResource + LCSServer to confirm the summary block is
# actually attached on the wire.
# ──────────────────────────────────────────────────────────────────


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        capture_output=True, text=True, check=False,
    )


def _init_repo(repo_root: Path, branch: str = "main") -> Path:
    _git(repo_root, "init", "-q", "-b", branch)
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / "a.txt").write_text("hi\n", encoding="utf-8")
    _git(repo_root, "add", "a.txt")
    _git(repo_root, "commit", "-q", "-m", "init")
    return repo_root


class TestWorktreesResourceSummaryBlock(unittest.TestCase):
    """Integration tests — the resource must attach a summary block to
    every collection response (data has both 'worktrees' and 'summary').
    """

    def test_summary_present_on_collection_response(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            resource = WorktreesResource(root)
            result = resource.fetch(parse_uri("lcs://worktrees"))
            self.assertEqual(result["status"], "ok")
            self.assertIn("summary", result["data"])
            self.assertIn("worktrees", result["data"])

    def test_summary_total_matches_worktree_count(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            resource = WorktreesResource(root)
            result = resource.fetch(parse_uri("lcs://worktrees"))
            self.assertEqual(
                result["data"]["summary"]["total"],
                len(result["data"]["worktrees"]),
            )

    def test_summary_active_plus_stale_equals_total(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            resource = WorktreesResource(root)
            result = resource.fetch(parse_uri("lcs://worktrees"))
            s = result["data"]["summary"]
            self.assertEqual(s["active"] + s["stale"], s["total"])

    def test_summary_as_of_is_parseable_iso8601(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            resource = WorktreesResource(root)
            result = resource.fetch(parse_uri("lcs://worktrees"))
            as_of = result["data"]["summary"]["as_of"]
            # ISO-8601 shape: YYYY-MM-DDTHH:MM:SS[.ffffff][+HH:MM | Z]
            self.assertRegex(
                as_of,
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.*\+\d{2}:\d{2}$",
            )
            parsed = datetime.fromisoformat(as_of)
            now = datetime.now(timezone.utc)
            self.assertLess(abs((now - parsed).total_seconds()), 60)

    def test_summary_slot_drift_keys_present(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            resource = WorktreesResource(root)
            result = resource.fetch(parse_uri("lcs://worktrees"))
            drift = result["data"]["summary"]["slot_drift"]
            self.assertIn("min", drift)
            self.assertIn("max", drift)
            self.assertIn("behind_count", drift)

    def test_summary_via_lcs_server(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            registry = ResourceRegistry()
            registry.register(WorktreesResource(root))
            server = LCSServer(registry)
            result = server.get("lcs://worktrees")
            self.assertEqual(result["status"], "ok")
            self.assertIn("summary", result["data"])
            self.assertEqual(
                result["data"]["summary"]["total"],
                len(result["data"]["worktrees"]),
            )

    def test_item_form_unaffected_by_summary_block(self):
        """The summary block is for the *collection* form. The item
        form (lcs://worktrees/<branch>) returns a single worktree dict
        and must not gain a summary key — that would be misleading."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            resource = WorktreesResource(root)
            result = resource.fetch(parse_uri("lcs://worktrees/main"))
            self.assertEqual(result["status"], "ok")
            self.assertNotIn("summary", result["data"])
            self.assertEqual(result["data"]["branch"], "main")


if __name__ == "__main__":
    unittest.main()
