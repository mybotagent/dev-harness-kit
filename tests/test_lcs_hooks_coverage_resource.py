#!/usr/bin/env python3
"""test_lcs_hooks_coverage_resource.py — Phase 1.8 (issue #353) hooks coverage resource.

Pins the ``lcs://hooks/coverage`` contract:
- Reads BOTH ``.claude/hooks.json`` and ``.codex/hooks.json``.
- Walks ``hooks/*.sh`` for the matchers list.
- Returns ``data.events`` = sorted union of event names from both manifests.
- Returns ``data.matchers`` = sorted list of ``*.sh`` filenames in ``hooks/``.
- Missing/malformed manifests degrade to ``status="partial"`` with the
  readable subset preserved under ``data``.
- URI dispatch: ``hooks/coverage`` wins over a generic ``hooks`` resource
  (longest-prefix match per Phase 1.1 server).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))

from lcs_resources.hooks_coverage import (  # noqa: E402
    HooksCoverageResource,
    _list_handlers,
)
from lcs_server import (  # noqa: E402
    LCSPartialError,
    LCSServer,
    Resource,
    ResourceRegistry,
    parse_uri,
)


def _write_claude(repo_root: Path, hooks: dict) -> Path:
    """Write ``.claude/hooks.json`` and return the path."""
    path = repo_root / ".claude" / "hooks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    return path


def _write_codex(repo_root: Path, hooks: dict) -> Path:
    """Write ``.codex/hooks.json`` and return the path."""
    path = repo_root / ".codex" / "hooks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    return path


def _write_handler(repo_root: Path, name: str) -> Path:
    """Write a ``hooks/<name>.sh`` file and return the path."""
    path = repo_root / "hooks" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")
    return path


class TestListHandlers(unittest.TestCase):
    def test_no_hooks_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(_list_handlers(Path(td)), [])

    def test_only_sh_files_included(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_handler(root, "a.sh")
            _write_handler(root, "b.sh")
            # Non-sh files in hooks/ should NOT appear as matchers.
            (root / "hooks" / "README.md").write_text("docs\n", encoding="utf-8")
            (root / "hooks" / "hooks.json").write_text("{}\n", encoding="utf-8")
            self.assertEqual(_list_handlers(root), ["a.sh", "b.sh"])

    def test_sorted_lexicographically(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_handler(root, "z.sh")
            _write_handler(root, "a.sh")
            _write_handler(root, "m.sh")
            self.assertEqual(_list_handlers(root), ["a.sh", "m.sh", "z.sh"])


class TestHooksCoverageResourceFetch(unittest.TestCase):
    def test_collection_form_reads_both_runtimes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_claude(root, {
                "PreToolUse": [{"hooks": [{"command": "echo claude-pre"}]}],
                "SessionStart": [{"hooks": [{"command": "echo claude-start"}]}],
            })
            _write_codex(root, {
                "Stop": [{"hooks": [{"command": "echo codex-stop"}]}],
                "SessionStart": [{"hooks": [{"command": "echo codex-start"}]}],
            })
            _write_handler(root, "x.sh")
            resource = HooksCoverageResource(root)
            parsed = parse_uri("lcs://hooks/coverage")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(
                result["data"]["events"],
                ["PreToolUse", "SessionStart", "Stop"],
            )
            self.assertEqual(result["data"]["matchers"], ["x.sh"])

    def test_collection_form_only_claude(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_claude(root, {
                "PreToolUse": [{"hooks": [{"command": "echo claude-pre"}]}],
                "UserPromptSubmit": [{"hooks": [{"command": "echo claude-usr"}]}],
            })
            resource = HooksCoverageResource(root)
            parsed = parse_uri("lcs://hooks/coverage")
            with self.assertRaises(LCSPartialError) as cm:
                resource.fetch(parsed)
            self.assertEqual(
                cm.exception.data["events"],
                ["PreToolUse", "UserPromptSubmit"],
            )
            self.assertIn("no .codex/hooks.json", cm.exception.missing)

    def test_collection_form_only_codex(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_codex(root, {
                "SessionStart": [{"hooks": [{"command": "echo codex-start"}]}],
                "Stop": [{"hooks": [{"command": "echo codex-stop"}]}],
            })
            resource = HooksCoverageResource(root)
            parsed = parse_uri("lcs://hooks/coverage")
            with self.assertRaises(LCSPartialError) as cm:
                resource.fetch(parsed)
            self.assertEqual(
                cm.exception.data["events"],
                ["SessionStart", "Stop"],
            )
            self.assertIn("no .claude/hooks.json", cm.exception.missing)

    def test_no_hooks_files(self):
        # Neither manifest exists AND hooks/ is empty (or missing) → ok
        # with empty events/matchers. Treated as "no configuration".
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            resource = HooksCoverageResource(root)
            parsed = parse_uri("lcs://hooks/coverage")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["events"], [])
            self.assertEqual(result["data"]["matchers"], [])

    def test_handlers_listed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_handler(root, "pre-commit.sh")
            _write_handler(root, "pre-push.sh")
            _write_handler(root, "worktree-guard.sh")
            resource = HooksCoverageResource(root)
            parsed = parse_uri("lcs://hooks/coverage")
            result = resource.fetch(parsed)
            self.assertEqual(
                result["data"]["matchers"],
                ["pre-commit.sh", "pre-push.sh", "worktree-guard.sh"],
            )

    def test_missing_claude_hooks_json_partial(self):
        # .codex present, .claude absent → status:partial via LCSPartialError;
        # .codex events are preserved under data; .claude is in missing list.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_codex(root, {
                "Stop": [{"hooks": [{"command": "echo codex-stop"}]}],
            })
            resource = HooksCoverageResource(root)
            parsed = parse_uri("lcs://hooks/coverage")
            with self.assertRaises(LCSPartialError) as cm:
                resource.fetch(parsed)
            self.assertEqual(cm.exception.data["events"], ["Stop"])
            self.assertIn("no .claude/hooks.json", cm.exception.missing)

    def test_malformed_claude_hooks_json_partial(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            claude_path = root / ".claude" / "hooks.json"
            claude_path.parent.mkdir(parents=True, exist_ok=True)
            claude_path.write_text("{this is not json", encoding="utf-8")
            resource = HooksCoverageResource(root)
            parsed = parse_uri("lcs://hooks/coverage")
            with self.assertRaises(LCSPartialError) as cm:
                resource.fetch(parsed)
            missing_entries = cm.exception.missing
            self.assertTrue(
                any(e.startswith("malformed .claude/hooks.json") for e in missing_entries),
                msg=f"expected a malformed .claude/hooks.json entry in {missing_entries!r}",
            )

    def test_malformed_codex_hooks_json_partial(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex_path = root / ".codex" / "hooks.json"
            codex_path.parent.mkdir(parents=True, exist_ok=True)
            codex_path.write_text("[oops", encoding="utf-8")
            resource = HooksCoverageResource(root)
            parsed = parse_uri("lcs://hooks/coverage")
            with self.assertRaises(LCSPartialError) as cm:
                resource.fetch(parsed)
            missing_entries = cm.exception.missing
            self.assertTrue(
                any(e.startswith("malformed .codex/hooks.json") for e in missing_entries),
                msg=f"expected a malformed .codex/hooks.json entry in {missing_entries!r}",
            )


class TestLCSIntegration(unittest.TestCase):
    def test_uri_routes_through_lcs_server(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_claude(root, {
                "PreToolUse": [{"hooks": [{"command": "echo x"}]}],
            })
            _write_codex(root, {
                "Stop": [{"hooks": [{"command": "echo y"}]}],
            })
            _write_handler(root, "y.sh")
            registry = ResourceRegistry()
            registry.register(HooksCoverageResource(root))
            server = LCSServer(registry)
            result = server.get("lcs://hooks/coverage")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["events"], ["PreToolUse", "Stop"])
            self.assertEqual(result["data"]["matchers"], ["y.sh"])

    def test_segment_matching(self):
        # Register both a generic "hooks" resource AND "hooks/coverage".
        # The longest-prefix match in the LCS server must resolve to
        # "hooks/coverage", not "hooks" with "coverage" as a path param.
        class _GenericHooks(Resource):
            name = "hooks"

            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch(self, parsed) -> dict:
                self.calls.append("/".join(parsed.path_segments))
                return {"status": "ok", "data": {"called_as": "generic"}}

        class _SpyCoverage(HooksCoverageResource):
            def __init__(self, repo_root: Path) -> None:
                super().__init__(repo_root)
                self.calls: list[str] = []

            def fetch(self, parsed):
                self.calls.append("/".join(parsed.path_segments))
                return super().fetch(parsed)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_claude(root, {
                "PreToolUse": [{"hooks": [{"command": "echo x"}]}],
            })
            _write_codex(root, {
                "Stop": [{"hooks": [{"command": "echo y"}]}],
            })
            registry = ResourceRegistry()
            generic = _GenericHooks()
            coverage = _SpyCoverage(root)
            registry.register(generic)
            registry.register(coverage)
            server = LCSServer(registry)
            result = server.get("lcs://hooks/coverage")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(
                result["data"]["events"], ["PreToolUse", "Stop"],
            )
            # The generic hooks resource should NOT have been called.
            self.assertEqual(generic.calls, [])
            self.assertEqual(coverage.calls, ["hooks/coverage"])


if __name__ == "__main__":
    unittest.main()
