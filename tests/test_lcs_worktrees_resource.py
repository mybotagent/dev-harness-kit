#!/usr/bin/env python3
"""test_lcs_worktrees_resource.py — Phase 1.3 (issue #348) worktrees resource.

Pins the ``lcs://worktrees`` and ``lcs://worktrees/<branch>`` contract:
- Collection form returns a list of normalized worktree entries.
- Item form filters by branch name (URL-decoded).
- Each entry exposes the 7 fields from the issue spec.
- Subprocess failures degrade to per-entry partial fields (status
  remains "ok" for the whole list — one bad worktree doesn't kill
  the others).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))

from lcs_resources.worktrees import (  # noqa: E402
    WorktreesResource,
    _hooks_wired,
    _last_touched,
    _list_worktrees_porcelain,
    _slot_version,
    _status_porcelain,
)
from lcs_server import LCSServer, ResourceRegistry, parse_uri  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        capture_output=True, text=True, check=False,
    )


def _init_repo_with_worktree(repo_root: Path, branch: str = "main") -> Path:
    """Init a tiny git repo + commit one file. Returns repo_root."""
    _git(repo_root, "init", "-q", "-b", branch)
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / "a.txt").write_text("hi\n", encoding="utf-8")
    _git(repo_root, "add", "a.txt")
    _git(repo_root, "commit", "-q", "-m", "init")
    return repo_root


class TestListWorktreesPorcelain(unittest.TestCase):
    def test_main_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo_with_worktree(root)
            blocks = _list_worktrees_porcelain(root)
            self.assertEqual(len(blocks), 1)
            self.assertEqual(blocks[0]["branch"], "main")
            self.assertIn("head", blocks[0])
            self.assertEqual(blocks[0].get("detached"), None)

    def test_with_linked_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo_with_worktree(root)
            wt = root.parent / (td.split("/")[-1] + "-wt")
            _git(root, "worktree", "add", "-b", "feat", str(wt))
            blocks = _list_worktrees_porcelain(root)
            self.assertEqual(len(blocks), 2)
            branches = sorted(b["branch"] for b in blocks)
            self.assertEqual(branches, ["feat", "main"])


class TestStatusPorcelain(unittest.TestCase):
    def test_clean_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo_with_worktree(root)
            self.assertEqual(_status_porcelain(root), [])

    def test_dirty_file_appears(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo_with_worktree(root)
            (root / "b.txt").write_text("uncommitted", encoding="utf-8")
            files = _status_porcelain(root)
            self.assertEqual(len(files), 1)
            self.assertIn("b.txt", files[0])


class TestHooksWired(unittest.TestCase):
    def test_no_githooks_dir_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo_with_worktree(root)
            self.assertFalse(_hooks_wired(root))

    def test_githooks_dir_and_matching_config_returns_true(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo_with_worktree(root)
            (root / ".githooks").mkdir()
            (root / ".githooks" / "pre-commit").write_text("#!/bin/sh\n")
            _git(root, "config", "core.hooksPath", ".githooks")
            self.assertTrue(_hooks_wired(root))


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


class TestLastTouched(unittest.TestCase):
    def test_returns_iso_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo_with_worktree(root)
            ts = _last_touched(root)
            self.assertIsNotNone(ts)
            self.assertIn("T", ts)
            self.assertTrue(ts.endswith("+00:00"))


class TestWorktreesResourceFetch(unittest.TestCase):
    def test_collection_form(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo_with_worktree(root)
            resource = WorktreesResource(root)
            parsed = parse_uri("lcs://worktrees")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(result["data"]["worktrees"]), 1)
            entry = result["data"]["worktrees"][0]
            self.assertEqual(entry["branch"], "main")
            self.assertFalse(entry["dirty"])
            self.assertEqual(entry["dirty_files"], [])
            self.assertFalse(entry["hooks_wired"])
            self.assertIsNotNone(entry["last_touched"])

    def test_item_form_filters_by_branch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo_with_worktree(root)
            wt = root.parent / (td.split("/")[-1] + "-wt")
            _git(root, "worktree", "add", "-b", "feat", str(wt))
            resource = WorktreesResource(root)
            parsed = parse_uri("lcs://worktrees/feat")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["branch"], "feat")
            self.assertEqual(Path(result["data"]["path"]).resolve(), wt.resolve())

    def test_item_form_with_url_encoded_branch(self):
        # Branches containing "/" must be URL-encoded in the URI.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo_with_worktree(root)
            wt = root.parent / (td.split("/")[-1] + "-wt")
            _git(root, "worktree", "add", "-b", "feat/foo", str(wt))
            resource = WorktreesResource(root)
            parsed = parse_uri("lcs://worktrees/feat%2Ffoo")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["branch"], "feat/foo")

    def test_item_form_unknown_branch_returns_data_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo_with_worktree(root)
            resource = WorktreesResource(root)
            parsed = parse_uri("lcs://worktrees/nope")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            self.assertIsNone(result["data"])
            self.assertIn("missing", result)

    def test_partial_failure_on_bad_worktree(self):
        # If git worktree list itself fails, the resource raises and
        # the LCS server converts to status=partial.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # No git init here — git worktree list will fail.
            resource = WorktreesResource(root)
            parsed = parse_uri("lcs://worktrees")
            with self.assertRaises(Exception) as cm:
                resource.fetch(parsed)
            # Exception carries the partial envelope.
            self.assertIn("worktree list failed", str(cm.exception))


class TestLCSIntegration(unittest.TestCase):
    def test_worktrees_routes_through_lcs_server(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo_with_worktree(root)
            registry = ResourceRegistry()
            registry.register(WorktreesResource(root))
            server = LCSServer(registry)
            result = server.get("lcs://worktrees")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(result["data"]["worktrees"]), 1)
            result = server.get("lcs://worktrees/main")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["branch"], "main")


if __name__ == "__main__":
    unittest.main()
