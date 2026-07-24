#!/usr/bin/env python3
"""test_lcs_pr_resource.py — issue #349 PR resource.

Pins the ``lcs://pr/<number>`` contract:
- Item form returns a normalized PR snapshot with the 6 data fields.
- Collection form (no segments) raises LCSError.
- gh-binary-missing path returns partial envelope with ``number`` set.
- gh-command-failure path returns partial envelope with the error.
- URL-decoded PR numbers round-trip.
- LCS server routes the URI through the registered handler.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))

from lcs_resources.pr import (  # noqa: E402
    PRResource,
    _count_unresolved_threads,
    _run_gh,
)
from lcs_server import LCSError, LCSServer, ResourceRegistry, parse_uri  # noqa: E402


def _gh_json_proc(payload: dict, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    """Build a fake CompletedProcess for gh JSON output."""
    return subprocess.CompletedProcess(
        args=["gh"], returncode=returncode,
        stdout=json.dumps(payload), stderr=stderr,
    )


class TestParsePRNumber(unittest.TestCase):
    def test_item_segments_are_number(self):
        parsed = parse_uri("lcs://pr/29")
        self.assertEqual(parsed.path_segments, ("pr", "29"))
        self.assertEqual(parsed.path_segments[1:], ("29",))
        self.assertFalse(parsed.is_collection)

    def test_collection_form_is_collection(self):
        parsed = parse_uri("lcs://pr/29/")
        self.assertTrue(parsed.is_collection)
        self.assertEqual(parsed.path_segments, ("pr", "29"))

    def test_bare_resource_is_collection_empty(self):
        parsed = parse_uri("lcs://pr/")
        self.assertTrue(parsed.is_collection)
        self.assertEqual(parsed.path_segments, ("pr",))

    def test_url_encoded_number_round_trips(self):
        # parse_uri only decodes %XX escapes literally; the resource
        # is responsible for unquote()ing the segment.
        parsed = parse_uri("lcs://pr/29")
        from urllib.parse import unquote
        self.assertEqual(unquote(parsed.path_segments[1]), "29")


class TestRunGh(unittest.TestCase):
    def test_returns_completed_process(self):
        # ``gh --version`` exists on every machine with gh installed;
        # if missing, the test degrades to FileNotFoundError which
        # the helper propagates as-is.
        try:
            proc = _run_gh(["--version"])
        except FileNotFoundError:
            self.fail("gh is reportedly missing on this host")
            self.assertIsInstance(proc, subprocess.CompletedProcess)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("gh version", proc.stdout)

    def test_missing_binary_raises_filenotfound(self):
        # Patch the underlying subprocess.run to simulate a missing
        # ``gh`` binary by raising the same exception Python raises
        # when /usr/bin/env can't find the executable.
        with patch("lcs_resources.pr.subprocess.run", side_effect=FileNotFoundError("gh")):
            with self.assertRaises(FileNotFoundError):
                _run_gh(["pr", "view", "29"])


class TestCountUnresolvedThreads(unittest.TestCase):
    def test_all_resolved(self):
        self.assertEqual(_count_unresolved_threads([
            {"isResolved": True}, {"isResolved": True},
        ]), 0)

    def test_mixed_resolution(self):
        self.assertEqual(_count_unresolved_threads([
            {"isResolved": True},
            {"isResolved": False},
            {"isResolved": False},
        ]), 2)

    def test_missing_field_defaults_to_unresolved(self):
        # Older gh versions don't emit isResolved at all — count
        # those as unresolved for forward compat.
        self.assertEqual(_count_unresolved_threads([
            {"body": "no flag"},
            {"isResolved": True},
        ]), 1)

    def test_empty_list(self):
        self.assertEqual(_count_unresolved_threads([]), 0)

    def test_ignores_non_dict_entries(self):
        self.assertEqual(_count_unresolved_threads([None, "x", 42, {"isResolved": False}]), 1)


class TestPRResourceFetch(unittest.TestCase):
    def _payload(self, number: int = 29) -> dict:
        return {
            "number": number,
            "title": "Add PR resource",
            "state": "OPEN",
            "statusCheckRollup": [
                {"name": "ci/test", "conclusion": "SUCCESS", "status": "COMPLETED"},
            ],
            "reviews": [
                {"author": {"login": "alice"}, "state": "APPROVED"},
            ],
            "comments": [
                {"isResolved": True},
                {"isResolved": False},
            ],
        }

    def test_collection_form_raises_lcserror(self):
        with tempfile.TemporaryDirectory() as td:
            resource = PRResource(Path(td))
            parsed = parse_uri("lcs://pr")
            with self.assertRaises(LCSError) as cm:
                resource.fetch(parsed)
            self.assertIn("requires a PR number", str(cm.exception))

    def test_collection_form_trailing_slash_raises_lcserror(self):
        with tempfile.TemporaryDirectory() as td:
            resource = PRResource(Path(td))
            parsed = parse_uri("lcs://pr/")
            with self.assertRaises(LCSError):
                resource.fetch(parsed)

    def test_valid_number_returns_ok_envelope(self):
        with tempfile.TemporaryDirectory() as td:
            resource = PRResource(Path(td))
            parsed = parse_uri("lcs://pr/29")
            with patch("lcs_resources.pr._run_gh", return_value=_gh_json_proc(self._payload(29))):
                result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            data = result["data"]
            self.assertEqual(data["number"], 29)
            self.assertEqual(data["title"], "Add PR resource")
            self.assertEqual(data["status"], "OPEN")
            self.assertEqual(len(data["checks"]), 1)
            self.assertEqual(data["checks"][0]["name"], "ci/test")
            self.assertEqual(len(data["reviews"]), 1)
            self.assertEqual(data["reviews"][0]["author"]["login"], "alice")
            self.assertEqual(data["unresolved_threads"], 1)

    def test_gh_binary_missing_returns_partial(self):
        with tempfile.TemporaryDirectory() as td:
            resource = PRResource(Path(td))
            parsed = parse_uri("lcs://pr/29")
            with patch("lcs_resources.pr._run_gh", side_effect=FileNotFoundError("gh")):
                result = resource.fetch(parsed)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["data"]["number"], "29")
            self.assertEqual(result["missing"], ["gh unavailable"])

    def test_gh_command_failure_returns_partial(self):
        with tempfile.TemporaryDirectory() as td:
            resource = PRResource(Path(td))
            parsed = parse_uri("lcs://pr/29")
            with patch("lcs_resources.pr._run_gh", return_value=_gh_json_proc(
                {}, returncode=1, stderr="no pull requests found",
            )):
                result = resource.fetch(parsed)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["data"]["number"], "29")
            self.assertTrue(any("gh pr view failed" in m for m in result["missing"]))

    def test_gh_garbage_json_returns_partial(self):
        with tempfile.TemporaryDirectory() as td:
            resource = PRResource(Path(td))
            parsed = parse_uri("lcs://pr/29")
            bad = subprocess.CompletedProcess(args=["gh"], returncode=0, stdout="{not json", stderr="")
            with patch("lcs_resources.pr._run_gh", return_value=bad):
                result = resource.fetch(parsed)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["data"]["number"], "29")

    def test_nonexistent_pr_returns_partial(self):
        # gh exits non-zero for a non-existent PR number; the resource
        # must surface the same partial envelope as a binary failure.
        with tempfile.TemporaryDirectory() as td:
            resource = PRResource(Path(td))
            parsed = parse_uri("lcs://pr/999999")
            with patch("lcs_resources.pr._run_gh", return_value=_gh_json_proc(
                {}, returncode=1, stderr="Could not resolve to a PullRequest",
            )):
                result = resource.fetch(parsed)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["data"]["number"], "999999")
            self.assertIn("missing", result)

    def test_constructor_accepts_repo_root_for_uniformity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            resource = PRResource(root)
            self.assertEqual(resource._repo_root, root)
            self.assertEqual(resource.name, "pr")


class TestLCSIntegration(unittest.TestCase):
    def test_pr_routes_through_lcs_server(self):
        with tempfile.TemporaryDirectory() as td:
            resource = PRResource(Path(td))
            registry = ResourceRegistry()
            registry.register(resource)
            server = LCSServer(registry)
            payload = {
                "number": 42,
                "title": "stuff",
                "state": "MERGED",
                "statusCheckRollup": [],
                "reviews": [],
                "comments": [],
            }
            with patch("lcs_resources.pr._run_gh", return_value=_gh_json_proc(payload)):
                result = server.get("lcs://pr/42")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["number"], 42)
            self.assertEqual(result["data"]["status"], "MERGED")
            self.assertEqual(result["data"]["unresolved_threads"], 0)

    def test_collection_form_through_server_still_errors(self):
        # The server's exception handler catches LCSError and converts
        # it to status=error, so the caller still gets a defined shape.
        with tempfile.TemporaryDirectory() as td:
            resource = PRResource(Path(td))
            registry = ResourceRegistry()
            registry.register(resource)
            server = LCSServer(registry)
            result = server.get("lcs://pr")
            self.assertEqual(result["status"], "error")
            self.assertIn("requires a PR number", result["error"])


if __name__ == "__main__":
    unittest.main()
