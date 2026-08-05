"""Tests for tools/linear_pr_sync.py — pure logic only (no network)."""

import argparse
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import linear_pr_sync as lps  # type: ignore


def ns(**kwargs):
    """Build a Namespace that mirrors cmd_sync's args."""
    p = argparse.ArgumentParser()
    p.add_argument("--branch", default="feat/x")
    p.add_argument("--event", default="opened")
    p.add_argument("--merged", default="false")
    p.add_argument("--pr-number", default=None)
    p.add_argument("--pr-title", default=None)
    p.add_argument("--pr-draft", default="false")
    return p.parse_args([]).__class__(
        **{
            "branch": "feat/x",
            "event": "opened",
            "merged": "false",
            "pr_number": None,
            "pr_title": None,
            "pr_draft": "false",
            **kwargs,
        }
    )


def target_state(args):
    """Replicate cmd_sync's mapping logic."""
    t = lps.EVENT_STATE_MAP.get(args.event)
    if args.event == "closed":
        t = "Done" if args.merged == "true" else "Canceled"
    return t


class TestEventStateMap(unittest.TestCase):
    def test_all_major_events_mapped(self):
        self.assertEqual(lps.EVENT_STATE_MAP["opened"], "In Progress")
        self.assertEqual(lps.EVENT_STATE_MAP["ready_for_review"], "In Review")
        self.assertEqual(lps.EVENT_STATE_MAP["reopened"], "In Review")
        self.assertEqual(lps.EVENT_STATE_MAP["synchronize"], "In Review")
        self.assertEqual(lps.EVENT_STATE_MAP["edited"], "In Review")
        self.assertEqual(lps.EVENT_STATE_MAP["closed"], "Done")  # refined by --merged


class TestHasApiKeyRename(unittest.TestCase):
    def test_new_name_returns_true_when_key_present(self):
        with patch.dict(os.environ, {"LINEAR_API_KEY": "test"}):
            self.assertTrue(lps._has_api_key())

    def test_new_name_returns_false_when_key_absent(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(lps._has_api_key())

    def test_legacy_name_still_works(self):
        with patch.dict(os.environ, {"LINEAR_API_KEY": "test"}):
            self.assertTrue(lps._required())
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(lps._required())


class TestClosedRefinesMerged(unittest.TestCase):
    def test_merged_true_promotes_to_done(self):
        self.assertEqual(target_state(ns(event="closed", merged="true")), "Done")

    def test_merged_false_promotes_to_canceled(self):
        self.assertEqual(target_state(ns(event="closed", merged="false")), "Canceled")

    def test_default_merged_is_false(self):
        # Default ns.merged = "false" → Canceled
        self.assertEqual(target_state(ns(event="closed")), "Canceled")


class TestDraftOpenedIsNoOp(unittest.TestCase):
    def test_draft_opened_returns_zero_without_touching_linear(self):
        args = ns(event="opened", pr_draft="true")
        with (
            patch.object(lps, "_has_api_key", return_value=True),
            patch.object(lps, "_project_id") as project_id,
            patch.object(lps, "_issue_by_branch") as issue_lookup,
            patch.object(lps, "_state_id") as state_id,
            patch.object(lps, "_create_issue") as create_issue,
            patch.object(lps, "_update_state") as update_state,
        ):
            self.assertEqual(lps.cmd_sync(args), 0)
            project_id.assert_not_called()
            issue_lookup.assert_not_called()
            state_id.assert_not_called()
            create_issue.assert_not_called()
            update_state.assert_not_called()

    def test_non_draft_opened_proceeds_normally(self):
        args = ns(event="opened", pr_draft="false", pr_number="570")
        issue = {"identifier": "SHO-1", "state": {"name": "In Progress"}}
        with (
            patch.object(lps, "_has_api_key", return_value=True),
            patch.object(lps, "_project_id", return_value="project"),
            patch.object(lps, "_issue_by_branch", return_value=None),
            patch.object(lps, "_state_id", return_value="state"),
            patch.object(lps, "_create_issue", return_value=issue) as create,
        ):
            self.assertEqual(lps.cmd_sync(args), 0)
            create.assert_called_once()


class TestIssueLookup(unittest.TestCase):
    def test_matches_complete_scope_marker_only(self):
        issues = [
            {"identifier": "SHO-1", "description": "<!-- scope:feat/x-extra::auto-sync -->"},
            {"identifier": "SHO-2", "description": "<!-- scope:feat/x::auto-sync -->"},
        ]
        with patch.object(lps, "_iter_issues", return_value=issues):
            self.assertEqual(lps._issue_by_branch("feat/x", "project")["identifier"], "SHO-2")


class TestIssuePagination(unittest.TestCase):
    def test_follows_cursor_and_scopes_to_project(self):
        pages = [
            {"data": {"issues": {"nodes": [{"id": "1"}], "pageInfo": {"hasNextPage": True, "endCursor": "next"}}}},
            {"data": {"issues": {"nodes": [{"id": "2"}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}},
        ]
        with patch.object(lps, "_request", side_effect=pages) as request:
            self.assertEqual([i["id"] for i in lps._iter_issues("project")], ["1", "2"])
            self.assertEqual(request.call_args_list[0].args[1], {"projectId": "project", "cursor": None})
            self.assertEqual(request.call_args_list[1].args[1], {"projectId": "project", "cursor": "next"})
            self.assertIn("project", request.call_args_list[0].args[0])


class TestTitleConstruction(unittest.TestCase):
    def test_missing_title_does_not_duplicate_pr_prefix(self):
        args = ns(pr_number="570")
        issue = {"identifier": "SHO-1", "state": {"name": "In Progress"}}
        with (
            patch.object(lps, "_has_api_key", return_value=True),
            patch.object(lps, "_project_id", return_value="project"),
            patch.object(lps, "_issue_by_branch", return_value=None),
            patch.object(lps, "_state_id", return_value="state"),
            patch.object(lps, "_create_issue", return_value=issue) as create,
        ):
            self.assertEqual(lps.cmd_sync(args), 0)
            self.assertEqual(create.call_args.args[3], "PR #570")


class TestSmoke(unittest.TestCase):
    def test_returns_failure_when_a_required_state_is_missing(self):
        with (
            patch.object(lps, "_has_api_key", return_value=True),
            patch.object(lps, "_project_id", return_value="project"),
            patch.object(lps, "_state_id", side_effect=lambda name: None if name == "Done" else name),
        ):
            self.assertEqual(lps.cmd_smoke(argparse.Namespace()), 1)

    def test_returns_one_when_api_key_is_missing(self):
        # Smoke is strict: missing API key is a config drift failure
        # (per maintenance review M5). The operator must add the
        # LINEAR_API_KEY secret rather than silencing the gate.
        with patch.object(lps, "_has_api_key", return_value=False):
            self.assertEqual(lps.cmd_smoke(argparse.Namespace()), 1)


class TestNoApiKeyIsNonBlocking(unittest.TestCase):
    def test_request_returns_none_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(lps._request("{ me { id } }"))


if __name__ == "__main__":
    unittest.main()
