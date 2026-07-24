#!/usr/bin/env python3
"""test_lcs_spend_resource.py — issue #351 ``lcs://spend/<window>`` resource.

Pins the spend resource contract:
- URI forms: ``lcs://spend/today``, ``lcs://spend/last-hour``,
  ``lcs://spend/<iso>-<iso>``.
- Returns ``{"status": "ok", "data": {"window": {since, until},
   "by_session": [...], "by_worktree": [...], "by_skill": [...]}}``.
- Each bucket row is ``{"key": <id>, "tokens": <int>}`` sorted by tokens
  desc, with ties broken by key ascending (deterministic for tests).
- ``_parse_window`` raises ``LCSError`` on malformed ranges.
- Empty logs directory returns empty arrays (not an error).
- Filter by ``[since, until)`` — inclusive since, exclusive until.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))

from lcs_resources.spend import (  # noqa: E402
    SpendResource,
    _aggregate,
    _load_token_logs,
    _parse_window,
)
from lcs_server import LCSError, LCSServer, ResourceRegistry, parse_uri  # noqa: E402


def _record(ts: str, session_id: str, worktree: str, skill: str,
            tokens: int, runtime: str = "claude-code") -> dict:
    """Build a TokenLog-shaped record."""
    return {
        "ts": ts,
        "session_id": session_id,
        "worktree": worktree,
        "skill": skill,
        "tokens": tokens,
        "runtime": runtime,
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


# ──────────────────────────────────────────────────────────────────
# _parse_window
# ──────────────────────────────────────────────────────────────────

class TestParseWindow(unittest.TestCase):
    def test_today_returns_utc_day_bounds(self):
        # Pin "now" so the test is deterministic: 2026-07-15 12:00 UTC.
        now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        since, until = _parse_window("today", now=now)
        self.assertEqual(since, datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(until, datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc))

    def test_last_hour_returns_60_minute_range(self):
        now = datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc)
        since, until = _parse_window("last-hour", now=now)
        self.assertEqual(until, now)
        self.assertEqual(since, now - timedelta(hours=1))

    def test_iso_range_parses_both_endpoints(self):
        since, until = _parse_window("2026-07-24T00:00:00Z-2026-07-25T00:00:00Z")
        self.assertEqual(since, datetime(2026, 7, 24, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(until, datetime(2026, 7, 25, 0, 0, tzinfo=timezone.utc))

    def test_iso_range_reversed_raises(self):
        with self.assertRaises(LCSError):
            _parse_window("2026-07-25T00:00:00Z-2026-07-24T00:00:00Z")

    def test_iso_range_invalid_format_raises(self):
        with self.assertRaises(LCSError):
            _parse_window("2026-07-24/2026-07-25")

    def test_iso_range_missing_z_suffix_raises(self):
        with self.assertRaises(LCSError):
            _parse_window("2026-07-24T00:00:00-2026-07-25T00:00:00")

    def test_unknown_keyword_raises(self):
        with self.assertRaises(LCSError):
            _parse_window("yesterday")


# ──────────────────────────────────────────────────────────────────
# _load_token_logs
# ──────────────────────────────────────────────────────────────────

class TestLoadTokenLogs(unittest.TestCase):
    def test_returns_empty_when_no_logs(self):
        with tempfile.TemporaryDirectory() as td:
            logs_root = Path(td)
            since = datetime(2026, 7, 1, tzinfo=timezone.utc)
            until = datetime(2026, 7, 31, tzinfo=timezone.utc)
            self.assertEqual(_load_token_logs(logs_root, since, until), [])

    def test_loads_records_inside_window(self):
        with tempfile.TemporaryDirectory() as td:
            logs_root = Path(td)
            inside = _record("2026-07-15T10:00:00Z", "s1", "main", "skill-a", 100)
            _write_jsonl(
                logs_root / "claude-code" / "s1.jsonl",
                [inside],
            )
            since = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)
            until = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)
            loaded = _load_token_logs(logs_root, since, until)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["session_id"], "s1")
            self.assertEqual(loaded[0]["tokens"], 100)

    def test_filters_records_outside_window(self):
        with tempfile.TemporaryDirectory() as td:
            logs_root = Path(td)
            before = _record("2026-07-14T23:59:59Z", "s1", "main", "skill-a", 50)
            inside = _record("2026-07-15T10:00:00Z", "s1", "main", "skill-a", 100)
            after = _record("2026-07-16T00:00:01Z", "s1", "main", "skill-a", 75)
            _write_jsonl(
                logs_root / "claude-code" / "s1.jsonl",
                [before, inside, after],
            )
            since = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)
            until = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)
            loaded = _load_token_logs(logs_root, since, until)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["tokens"], 100)

    def test_loads_both_claude_code_and_codex(self):
        with tempfile.TemporaryDirectory() as td:
            logs_root = Path(td)
            cc = _record("2026-07-15T10:00:00Z", "s1", "main", "skill-a", 100,
                         runtime="claude-code")
            cod = _record("2026-07-15T11:00:00Z", "s2", "main", "skill-b", 200,
                          runtime="codex")
            _write_jsonl(logs_root / "claude-code" / "s1.jsonl", [cc])
            _write_jsonl(logs_root / "codex" / "s2.jsonl", [cod])
            since = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)
            until = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)
            loaded = _load_token_logs(logs_root, since, until)
            self.assertEqual(len(loaded), 2)
            tokens = sorted(r["tokens"] for r in loaded)
            self.assertEqual(tokens, [100, 200])

    def test_skips_malformed_jsonl_lines(self):
        with tempfile.TemporaryDirectory() as td:
            logs_root = Path(td)
            path = logs_root / "claude-code" / "s1.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(_record("2026-07-15T10:00:00Z", "s1", "main",
                                   "skill-a", 100))
                + "\nnot valid json\n"
                + json.dumps(_record("2026-07-15T11:00:00Z", "s1", "main",
                                     "skill-a", 50))
                + "\n"
            )
            since = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)
            until = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)
            loaded = _load_token_logs(logs_root, since, until)
            self.assertEqual(len(loaded), 2)


# ──────────────────────────────────────────────────────────────────
# _aggregate
# ──────────────────────────────────────────────────────────────────

class TestAggregate(unittest.TestCase):
    def test_aggregates_by_session_worktree_skill(self):
        records = [
            _record("2026-07-15T10:00:00Z", "s1", "main", "skill-a", 100),
            _record("2026-07-15T11:00:00Z", "s1", "main", "skill-b", 50),
            _record("2026-07-15T12:00:00Z", "s2", "feat-x", "skill-a", 200),
        ]
        out = _aggregate(records)
        self.assertEqual(
            out["by_session"],
            [{"key": "s2", "tokens": 200}, {"key": "s1", "tokens": 150}],
        )
        self.assertEqual(
            out["by_worktree"],
            [{"key": "feat-x", "tokens": 200}, {"key": "main", "tokens": 150}],
        )
        self.assertEqual(
            out["by_skill"],
            [{"key": "skill-a", "tokens": 300}, {"key": "skill-b", "tokens": 50}],
        )

    def test_empty_records_returns_empty_lists(self):
        out = _aggregate([])
        self.assertEqual(out["by_session"], [])
        self.assertEqual(out["by_worktree"], [])
        self.assertEqual(out["by_skill"], [])

    def test_ties_broken_by_key_ascending(self):
        records = [
            _record("2026-07-15T10:00:00Z", "z-session", "main", "skill-a", 100),
            _record("2026-07-15T11:00:00Z", "a-session", "main", "skill-a", 100),
        ]
        out = _aggregate(records)
        self.assertEqual(
            out["by_session"],
            [{"key": "a-session", "tokens": 100},
             {"key": "z-session", "tokens": 100}],
        )


# ──────────────────────────────────────────────────────────────────
# SpendResource.fetch end-to-end
# ──────────────────────────────────────────────────────────────────

class TestSpendResourceFetch(unittest.TestCase):
    def _seed(self, logs_root: Path) -> None:
        records = [
            _record("2026-07-15T10:00:00Z", "s1", "main", "skill-a", 100),
            _record("2026-07-15T11:00:00Z", "s2", "feat-x", "skill-b", 250),
        ]
        _write_jsonl(logs_root / "claude-code" / "s1.jsonl", [records[0]])
        _write_jsonl(logs_root / "codex" / "s2.jsonl", [records[1]])

    def test_today_form(self):
        with tempfile.TemporaryDirectory() as td:
            logs_root = Path(td)
            self._seed(logs_root)
            resource = SpendResource(logs_root)
            # Pin now so "today" lands inside the seeded window.
            resource._now = lambda: datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
            parsed = parse_uri("lcs://spend/today")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            data = result["data"]
            self.assertEqual(data["window"]["since"], "2026-07-15T00:00:00+00:00")
            self.assertEqual(data["window"]["until"], "2026-07-16T00:00:00+00:00")
            self.assertEqual(len(data["by_session"]), 2)
            self.assertEqual(data["by_session"][0], {"key": "s2", "tokens": 250})

    def test_last_hour_form(self):
        with tempfile.TemporaryDirectory() as td:
            logs_root = Path(td)
            self._seed(logs_root)
            resource = SpendResource(logs_root)
            # Pin now = 12:30; "last-hour" is [11:30, 12:30]; only the
            # 11:00 record is inside (11:00 < 11:30 → false; but seeded
            # records were at 10:00 and 11:00 — wait, 11:00 < 11:30 so
            # it's OUTSIDE the window).
            # Use a "now" that catches the 11:00 record.
            resource._now = lambda: datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
            parsed = parse_uri("lcs://spend/last-hour")
            result = resource.fetch(parsed)
            data = result["data"]
            self.assertEqual(data["window"]["since"], "2026-07-15T11:00:00+00:00")
            self.assertEqual(data["window"]["until"], "2026-07-15T12:00:00+00:00")
            # 10:00 < 11:00 (excluded); 11:00 is in [11:00, 12:00).
            self.assertEqual(len(data["by_session"]), 1)
            self.assertEqual(data["by_session"][0]["key"], "s2")

    def test_iso_range_form(self):
        with tempfile.TemporaryDirectory() as td:
            logs_root = Path(td)
            self._seed(logs_root)
            resource = SpendResource(logs_root)
            parsed = parse_uri("lcs://spend/2026-07-15T00:00:00Z-2026-07-15T23:59:59Z")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            data = result["data"]
            self.assertEqual(len(data["by_session"]), 2)
            self.assertEqual(data["by_session"][0]["tokens"], 250)

    def test_empty_logs_returns_empty_arrays(self):
        with tempfile.TemporaryDirectory() as td:
            logs_root = Path(td)
            resource = SpendResource(logs_root)
            parsed = parse_uri("lcs://spend/today")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            data = result["data"]
            self.assertEqual(data["by_session"], [])
            self.assertEqual(data["by_worktree"], [])
            self.assertEqual(data["by_skill"], [])

    def test_default_logs_root_is_repo_logs(self):
        resource = SpendResource()
        # Sanity: the default must point at <something>/logs. We can't
        # assert the exact path (CWD-dependent) so just check the
        # contract: logs_root ends in "logs".
        self.assertEqual(resource._logs_root.name, "logs")

    def test_invalid_uri_segment_raises(self):
        with tempfile.TemporaryDirectory() as td:
            resource = SpendResource(Path(td))
            parsed = parse_uri("lcs://spend/garbage")
            with self.assertRaises(LCSError):
                resource.fetch(parsed)


# ──────────────────────────────────────────────────────────────────
# LCS integration
# ──────────────────────────────────────────────────────────────────

class TestLCSIntegration(unittest.TestCase):
    def test_spend_routes_through_lcs_server(self):
        with tempfile.TemporaryDirectory() as td:
            logs_root = Path(td)
            _write_jsonl(
                logs_root / "claude-code" / "s1.jsonl",
                [_record("2026-07-15T10:00:00Z", "s1", "main", "skill-a", 100)],
            )
            registry = ResourceRegistry()
            resource = SpendResource(logs_root)
            resource._now = lambda: datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
            registry.register(resource)
            server = LCSServer(registry)
            result = server.get("lcs://spend/today")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["by_session"],
                             [{"key": "s1", "tokens": 100}])


if __name__ == "__main__":
    unittest.main()
