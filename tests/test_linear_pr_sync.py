"""Tests for tools/linear_pr_sync.py — pure logic only (no network)."""

import argparse
import os
import sys
import unittest
from pathlib import Path

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
    p.add_argument("--pr-url", default=None)
    return p.parse_args([]).__class__(**{
        "branch": "feat/x",
        "event": "opened",
        "merged": "false",
        "pr_number": None,
        "pr_title": None,
        "pr_url": None,
        **kwargs,
    })


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


class TestClosedRefinesMerged(unittest.TestCase):
    def test_merged_true_promotes_to_done(self):
        self.assertEqual(target_state(ns(event="closed", merged="true")), "Done")

    def test_merged_false_promotes_to_canceled(self):
        self.assertEqual(target_state(ns(event="closed", merged="false")), "Canceled")

    def test_default_merged_is_false(self):
        # Default ns.merged = "false" → Canceled
        self.assertEqual(target_state(ns(event="closed")), "Canceled")


class TestProjectNameResolution(unittest.TestCase):
    def test_default_project_name(self):
        # No env override → dev-harness-kit
        os.environ.pop("LINEAR_PROJECT_NAME", None)
        self.assertEqual(lps.PROJECT_NAME, "dev-harness-kit")

    def test_env_override(self):
        os.environ["LINEAR_PROJECT_NAME"] = "custom-project"
        # Re-import to pick up env
        import importlib
        importlib.reload(lps)
        self.assertEqual(lps.PROJECT_NAME, "custom-project")
        os.environ.pop("LINEAR_PROJECT_NAME", None)
        importlib.reload(lps)


class TestNoApiKeyIsNonBlocking(unittest.TestCase):
    def test_request_returns_none_without_key(self):
        os.environ.pop("LINEAR_API_KEY", None)
        import importlib
        importlib.reload(lps)
        self.assertIsNone(lps._request("{ me { id } }"))


if __name__ == "__main__":
    unittest.main()
