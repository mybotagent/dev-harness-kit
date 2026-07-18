"""test_skill_usage.py -- unit tests for tools/skill_usage.py.

Coverage:
- attributionSkill counts vs Skill tool_use invocations are tracked
  separately (two distinct signals).
- Window filter applies to both signals.
- cwd prefix filter scopes results to a target workspace.
- Empty / malformed lines are tolerated (no crash).
- last_seen timestamp is the maximum observed per skill.
- Per-cwd breakdown is preserved when requested.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import skill_usage  # noqa: E402

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "skill_usage" / "mixed.jsonl"


class TestAggregateCounts(unittest.TestCase):
    def test_window_default_captures_recent_turns(self):
        agg = skill_usage.aggregate_skill_usage(str(FIXTURE), window_days=30)
        self.assertEqual(agg["dev-kit:inspect"]["turns"], 4)
        self.assertEqual(agg["dev-kit:inspect"]["invocations"], 0)
        self.assertEqual(agg["dev-kit:feat-fix"]["turns"], 2)
        self.assertEqual(agg["dev-kit:feat-fix"]["invocations"], 2)
        self.assertEqual(agg["dev-kit:babysit-pr"]["turns"], 1)
        self.assertEqual(agg["dev-kit:babysit-pr"]["invocations"], 1)
        self.assertEqual(agg["dev-kit:prune"]["turns"], 1)
        self.assertEqual(agg["dev-kit:prune"]["invocations"], 0)

    def test_window_filter_excludes_old_records(self):
        agg = skill_usage.aggregate_skill_usage(str(FIXTURE), window_days=20)
        self.assertEqual(agg["dev-kit:inspect"]["turns"], 3)
        self.assertNotIn("dev-kit:prune", agg)

    def test_cwd_prefix_filter_scopes_to_workspace(self):
        agg = skill_usage.aggregate_skill_usage(
            str(FIXTURE), window_days=30, cwd_prefix="/repo/dev-harness-kit")
        self.assertEqual(agg["dev-kit:inspect"]["turns"], 3)
        self.assertEqual(agg["dev-kit:feat-fix"]["turns"], 2)
        self.assertEqual(agg["dev-kit:feat-fix"]["invocations"], 2)
        self.assertNotIn("dev-kit:babysit-pr", agg)

    def test_last_seen_is_max_observed(self):
        agg = skill_usage.aggregate_skill_usage(str(FIXTURE), window_days=30)
        self.assertEqual(agg["dev-kit:inspect"]["last_seen"],
                         "2026-07-10T10:00:25.000Z")
        self.assertEqual(agg["dev-kit:feat-fix"]["last_seen"],
                         "2026-07-10T10:00:20.000Z")

    def test_per_cwd_breakdown_when_requested(self):
        agg = skill_usage.aggregate_skill_usage(
            str(FIXTURE), window_days=30, include_per_cwd=True)
        inspect = agg["dev-kit:inspect"]
        self.assertIn("cwds", inspect)
        self.assertEqual(inspect["cwds"]["/repo/dev-harness-kit"]["turns"], 3)
        self.assertEqual(inspect["cwds"]["/repo/other-project"]["turns"], 1)


class TestMalformedInput(unittest.TestCase):
    def test_empty_file_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            path = fh.name
        try:
            agg = skill_usage.aggregate_skill_usage(path, window_days=30)
            self.assertEqual(agg, {})
        finally:
            Path(path).unlink()

    def test_blank_and_malformed_lines_skipped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write("\n")
            fh.write("not json\n")
            fh.write(json.dumps({"type": "assistant", "message": {}}) + "\n")
            path = fh.name
        try:
            agg = skill_usage.aggregate_skill_usage(path, window_days=30)
            self.assertEqual(agg, {})
        finally:
            Path(path).unlink()


class TestSkillNameExtraction(unittest.TestCase):
    def test_explicit_skill_tool_use_without_attribution_still_counts(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write(json.dumps({
                "type": "assistant", "isSidechain": False,
                "sessionId": "x", "cwd": "/r",
                "timestamp": "2026-07-15T10:00:00.000Z",
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "t1", "name": "Skill",
                     "input": {"skill": "dev-kit:foo"}}
                ]}
            }) + "\n")
            path = fh.name
        try:
            agg = skill_usage.aggregate_skill_usage(path, window_days=30)
            self.assertEqual(agg["dev-kit:foo"]["invocations"], 1)
            self.assertEqual(agg["dev-kit:foo"]["turns"], 0)
        finally:
            Path(path).unlink()

    def test_invalid_skill_field_in_tool_use_skipped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write(json.dumps({
                "type": "assistant", "isSidechain": False,
                "sessionId": "x", "cwd": "/r",
                "timestamp": "2026-07-15T10:00:00.000Z",
                "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "t1", "name": "Skill",
                     "input": {"skill": 123}}
                ]}
            }) + "\n")
            path = fh.name
        try:
            agg = skill_usage.aggregate_skill_usage(path, window_days=30)
            self.assertEqual(agg, {})
        finally:
            Path(path).unlink()


class TestPrintTable(unittest.TestCase):
    def test_print_table_renders_columns(self):
        agg = {
            "dev-kit:foo": {"turns": 5, "invocations": 2,
                            "last_seen": "2026-07-15T10:00:00.000Z"},
            "dev-kit:bar": {"turns": 1, "invocations": 1,
                            "last_seen": "2026-07-15T11:00:00.000Z"},
        }
        out = skill_usage.format_table(agg)
        self.assertIn("SKILL", out)
        self.assertIn("TURNS", out)
        self.assertIn("INVOCATIONS", out)
        self.assertIn("LAST_SEEN", out)
        foo_idx = out.index("dev-kit:foo")
        bar_idx = out.index("dev-kit:bar")
        self.assertLess(foo_idx, bar_idx)

    def test_print_json_emits_machine_readable(self):
        agg = {"dev-kit:foo": {"turns": 5, "invocations": 2,
                               "last_seen": "2026-07-15T10:00:00.000Z"}}
        out = skill_usage.format_json(agg)
        parsed = json.loads(out)
        self.assertEqual(parsed["dev-kit:foo"]["turns"], 5)
        self.assertEqual(parsed["dev-kit:foo"]["invocations"], 2)


if __name__ == "__main__":
    unittest.main()


class TestFilterByCwdPrefix(unittest.TestCase):
    def _agg(self):
        return {
            "dev-kit:foo": {
                "turns": 5, "invocations": 1,
                "last_seen": "2026-07-15T10:00:00.000Z",
                "cwds": {
                    "/repo/a": {"turns": 3, "invocations": 0,
                                "last_seen": "2026-07-14T10:00:00.000Z"},
                    "/repo/a/sub": {"turns": 2, "invocations": 1,
                                    "last_seen": "2026-07-15T10:00:00.000Z"},
                    "/repo/b": {"turns": 7, "invocations": 0,
                                "last_seen": "2026-07-15T10:00:00.000Z"},
                },
            },
            "dev-kit:bar": {
                "turns": 2, "invocations": 2,
                "last_seen": "2026-07-15T10:00:00.000Z",
                "cwds": {
                    "/repo/c": {"turns": 2, "invocations": 2,
                                "last_seen": "2026-07-15T10:00:00.000Z"},
                },
            },
        }

    def test_prefix_match_rolls_counts(self):
        agg = self._agg()
        out = skill_usage.filter_by_cwd_prefix(agg, "/repo/a")
        # /repo/a + /repo/a/sub both match; /repo/b does not.
        self.assertEqual(out["dev-kit:foo"]["turns"], 5)
        self.assertEqual(out["dev-kit:foo"]["invocations"], 1)
        # bar has no cwd under /repo/a -> dropped.
        self.assertNotIn("dev-kit:bar", out)

    def test_no_match_yields_empty(self):
        agg = self._agg()
        out = skill_usage.filter_by_cwd_prefix(agg, "/nope")
        self.assertEqual(out, {})

    def test_skips_aggregate_without_per_cwd(self):
        agg = {"dev-kit:x": {"turns": 5, "invocations": 0, "last_seen": None}}
        self.assertEqual(skill_usage.filter_by_cwd_prefix(agg, "/anything"), {})

    def test_empty_prefix_yields_empty(self):
        agg = self._agg()
        # Defensive: empty prefix would match everything; reject to
        # keep caller contract explicit.
        self.assertEqual(skill_usage.filter_by_cwd_prefix(agg, ""), {})
