#!/usr/bin/env python3
"""test_lcs_branches_resource.py — Phase 1.4 (issue #350) branches resource.

Pins the ``lcs://branches/<name>`` contract:
- Returns the 6 spec fields (name, local_head, origin_head, ahead,
  behind, last_ci_run) for an existing branch.
- Returns ``slot_version`` when ``.claude-plugin/plugin.json`` is
  readable; omits it otherwise.
- Raises a partial error when the branch is missing locally.
- Dispatches the same way through the LCS server.
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

from lcs_resources.branches import (  # noqa: E402
    BranchesResource,
    _ahead_behind,
    _last_ci_run,
    _local_head,
    _origin_head,
    _slot_version,
)
from lcs_server import LCSServer, ResourceRegistry, parse_uri  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        capture_output=True, text=True, check=False,
    )


def _init_repo(repo_root: Path, branch: str = "main") -> Path:
    """Init a tiny git repo + commit one file + fake origin/main."""
    _git(repo_root, "init", "-q", "-b", branch)
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / "a.txt").write_text("hi\n", encoding="utf-8")
    _git(repo_root, "add", "a.txt")
    _git(repo_root, "commit", "-q", "-m", "init")
    # Set up a fake origin with a single commit so origin/<branch> resolves.
    bare = repo_root.parent / (repo_root.name + "-origin.git")
    _git(repo_root, "init", "--bare", "-q", str(bare))
    _git(repo_root, "remote", "add", "origin", str(bare))
    _git(repo_root, "push", "-q", "origin", branch)
    return repo_root


def _make_completed(returncode: int, stdout: str, stderr: str = "") -> subprocess.CompletedProcess:
    """Build a CompletedProcess with the given fields."""
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


class TestLocalHead(unittest.TestCase):
    def test_returns_sha_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            sha = _local_head(root, "main")
            self.assertIsNotNone(sha)
            self.assertEqual(len(sha), 40)

    def test_returns_none_on_missing_branch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            self.assertIsNone(_local_head(root, "nope"))


class TestOriginHead(unittest.TestCase):
    def test_returns_sha_on_pushed_branch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            sha = _origin_head(root, "main")
            self.assertIsNotNone(sha)
            self.assertEqual(len(sha), 40)

    def test_returns_none_when_no_upstream(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            _git(root, "checkout", "-q", "-b", "local-only")
            self.assertIsNone(_origin_head(root, "local-only"))


class TestAheadBehind(unittest.TestCase):
    def test_parses_tab_separated_counts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch(
                "lcs_resources.branches._run_git",
                return_value=_make_completed(0, "3\t1\n"),
            ):
                ahead, behind = _ahead_behind(root, "main")
            # git rev-list --left-right --count A...B output is
            # <left>\t<right> = <behind>\t<ahead> when A=origin/<branch>,
            # B=HEAD. So "3\t1" means 3 behind, 1 ahead.
            self.assertEqual(ahead, 1)
            self.assertEqual(behind, 3)

    def test_returns_zero_zero_on_missing_upstream(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch(
                "lcs_resources.branches._run_git",
                return_value=_make_completed(128, "fatal: bad ref\n"),
            ):
                self.assertEqual(_ahead_behind(root, "main"), (0, 0))

    def test_returns_zero_zero_on_malformed_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch(
                "lcs_resources.branches._run_git",
                return_value=_make_completed(0, "not a count\n"),
            ):
                self.assertEqual(_ahead_behind(root, "main"), (0, 0))


class TestSlotVersion(unittest.TestCase):
    def test_no_plugin_json_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(_slot_version(Path(td)))

    def test_reads_version_from_plugin_json(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".claude-plugin").mkdir()
            (root / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"version": "0.3.99"})
            )
            self.assertEqual(_slot_version(root), "0.3.99")

    def test_unparseable_json_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".claude-plugin").mkdir()
            (root / ".claude-plugin" / "plugin.json").write_text("not json")
            self.assertIsNone(_slot_version(root))


class TestLastCiRun(unittest.TestCase):
    def test_returns_none_when_gh_absent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("lcs_resources.branches.shutil.which", return_value=None):
                self.assertIsNone(_last_ci_run(root, "main"))

    def test_returns_run_dict_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = json.dumps([{
                "status": "completed",
                "conclusion": "success",
                "name": "test",
            }])
            with patch("lcs_resources.branches.shutil.which", return_value="/usr/bin/gh"), \
                 patch("lcs_resources.branches.subprocess.run",
                       return_value=_make_completed(0, payload)):
                result = _last_ci_run(root, "main")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["conclusion"], "success")
            self.assertEqual(result["name"], "test")

    def test_returns_none_when_no_runs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("lcs_resources.branches.shutil.which", return_value="/usr/bin/gh"), \
                 patch("lcs_resources.branches.subprocess.run",
                       return_value=_make_completed(0, "[]")):
                self.assertIsNone(_last_ci_run(root, "main"))


class TestBranchesResourceFetch(unittest.TestCase):
    def test_existing_branch_returns_all_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            (root / ".claude-plugin").mkdir()
            (root / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"version": "0.3.50"})
            )
            resource = BranchesResource(root)
            parsed = parse_uri("lcs://branches/main")
            # Mock gh to be absent so last_ci_run is deterministic.
            with patch("lcs_resources.branches.shutil.which", return_value=None):
                result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            data = result["data"]
            self.assertEqual(data["name"], "main")
            self.assertEqual(len(data["local_head"]), 40)
            self.assertEqual(len(data["origin_head"]), 40)
            self.assertEqual(data["ahead"], 0)
            self.assertEqual(data["behind"], 0)
            self.assertEqual(data["slot_version"], "0.3.50")
            self.assertIsNone(data["last_ci_run"])

    def test_unknown_branch_raises_partial(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            resource = BranchesResource(root)
            parsed = parse_uri("lcs://branches/nope")
            with self.assertRaises(Exception) as cm:
                resource.fetch(parsed)
            self.assertIn("no such branch", str(cm.exception))

    def test_url_encoded_branch_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            _git(root, "checkout", "-q", "-b", "feat/foo")
            resource = BranchesResource(root)
            parsed = parse_uri("lcs://branches/feat%2Ffoo")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["name"], "feat/foo")

    def test_no_plugin_json_omits_slot_version(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            resource = BranchesResource(root)
            parsed = parse_uri("lcs://branches/main")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            self.assertNotIn("slot_version", result["data"])

    def test_empty_branch_segment_raises_partial(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            resource = BranchesResource(root)
            parsed = parse_uri("lcs://branches/")
            with self.assertRaises(Exception) as cm:
                resource.fetch(parsed)
            self.assertIn("no branch name", str(cm.exception))


class TestLCSIntegration(unittest.TestCase):
    def test_branches_routes_through_lcs_server(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            registry = ResourceRegistry()
            registry.register(BranchesResource(root))
            server = LCSServer(registry)
            result = server.get("lcs://branches/main")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["name"], "main")
            self.assertEqual(len(result["data"]["local_head"]), 40)


if __name__ == "__main__":
    unittest.main()
