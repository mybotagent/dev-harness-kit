#!/usr/bin/env python3
"""test_lcs_discovery.py — Gap 3 (issue #455) discovery endpoints.

Pins the list-form contracts for the three id-keyed resources:

- ``lcs://branches`` returns a small per-branch row set
  ({name, local_head, ahead, behind, last_ci_conclusion}) plus a
  ``summary`` block ({total, local_only, ahead_of_origin,
  behind_origin, as_of}).
- ``lcs://sessions`` returns a per-session row set
  ({id, role, started_at, current_task, last_tool}) plus a
  ``summary`` block ({total, by_role, as_of}). Empty index is
  ``status: "ok"`` (NOT ``partial``) with ``total: 0``.
- ``lcs://prs`` (alias for ``pr`` resource) returns a per-PR row set
  ({n, title, head, ci_state, review_state}) plus a ``summary``
  block ({total, open, closed, merged, as_of}).

Also pins the alias mechanism in ``lcs_server.ResourceRegistry``:
- Resources may declare ``aliases`` (tuple[str, ...]).
- Registration auto-indexes aliases; lookup falls back to them
  when no primary longest-match hits.
- Clashes (alias == resource name, alias == alias) raise
  ``LCSError``.
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

from lcs_resources.branches import BranchesResource  # noqa: E402
from lcs_resources.pr import PRResource  # noqa: E402
from lcs_resources.sessions import SessionsResource  # noqa: E402
from lcs_server import (  # noqa: E402
    LCSError,
    LCSServer,
    ResourceRegistry,
    parse_uri,
)


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
    bare = repo_root.parent / (repo_root.name + "-origin.git")
    _git(repo_root, "init", "--bare", "-q", str(bare))
    _git(repo_root, "remote", "add", "origin", str(bare))
    _git(repo_root, "push", "-q", "origin", branch)
    return repo_root


def _make_proc(returncode: int, stdout: str, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def _gh_proc(payload, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["gh"], returncode=returncode,
        stdout=json.dumps(payload), stderr=stderr,
    )


# Field sets (the discovery endpoints must NOT include these extras).
BRANCH_LIST_FIELDS = {"name", "local_head", "ahead", "behind", "last_ci_conclusion"}
BRANCH_SUMMARY_FIELDS = {"total", "local_only", "ahead_of_origin", "behind_origin", "as_of"}
SESSION_LIST_FIELDS = {"id", "role", "started_at", "current_task", "last_tool"}
SESSION_SUMMARY_FIELDS = {"total", "by_role", "as_of"}
PR_LIST_FIELDS = {"n", "title", "head", "ci_state", "review_state"}
PR_SUMMARY_FIELDS = {"total", "open", "closed", "merged", "as_of"}


# ──────────────────────────────────────────────────────────────────
# lcs://branches (list)
# ──────────────────────────────────────────────────────────────────

class TestBranchesListEndpoint(unittest.TestCase):
    def test_list_returns_branches_and_summary(self):
        """lcs://branches returns the small-list payload + summary."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            _git(root, "checkout", "-q", "-b", "local-only")
            _git(root, "checkout", "-q", "main")
            _git(root, "branch", "ahead-branch")
            resource = BranchesResource(root)
            parsed = parse_uri("lcs://branches")

            # for-each-ref output: one branch per line, "<short>\t<sha>".
            for_each = (
                "main\t" + "a" * 40 + "\n"
                "local-only\t" + "b" * 40 + "\n"
                "ahead-branch\t" + "c" * 40 + "\n"
            )
            # rev-list output: origin/<branch>...<branch> -> "<behind>\t<ahead>"
            rev_list_main = "0\t2\n"        # 2 ahead, 0 behind
            rev_list_local = "fatal: no upstream\n"  # no origin -> (0, 0)
            rev_list_ahead = "0\t0\n"        # clean

            def fake_run_git(args, cwd):
                joined = " ".join(args)
                if joined.startswith("rev-list"):
                    branch = args[-1].split("...", 1)[1]
                    if branch == "main":
                        return _make_proc(0, rev_list_main)
                    if branch == "local-only":
                        return _make_proc(128, rev_list_local)
                    if branch == "ahead-branch":
                        return _make_proc(0, rev_list_ahead)
                if "for-each-ref" in joined:
                    # Differentiate local refs vs origin refs.
                    if "refs/remotes/origin/" in joined:
                        return _make_proc(0, "origin/main\n")
                    return _make_proc(0, for_each)
                return _make_proc(0, "")

            with patch("lcs_resources.branches._run_git", side_effect=fake_run_git), \
                 patch("lcs_resources.branches.shutil.which", return_value=None):
                result = resource.fetch(parsed)

            self.assertEqual(result["status"], "ok")
            data = result["data"]
            self.assertIn("branches", data)
            self.assertIn("summary", data)

            # Field-set assertion: every row has exactly the small-list
            # fields and nothing else.
            for row in data["branches"]:
                self.assertEqual(set(row.keys()), BRANCH_LIST_FIELDS)

            # Summary field-set assertion.
            self.assertEqual(set(data["summary"].keys()), BRANCH_SUMMARY_FIELDS)
            self.assertEqual(data["summary"]["total"], 3)
            # Only "main" has an upstream (origin/main was pushed);
            # local-only and ahead-branch count as local_only.
            self.assertEqual(data["summary"]["local_only"], 2)
            self.assertEqual(data["summary"]["ahead_of_origin"], 1)
            self.assertEqual(data["summary"]["behind_origin"], 0)
            self.assertIsInstance(data["summary"]["as_of"], str)
            self.assertTrue(data["summary"]["as_of"].endswith("+00:00"))

            # Per-row correctness: local-only must show ahead=behind=0
            # because there's no origin ref to compare against.
            local_row = next(r for r in data["branches"] if r["name"] == "local-only")
            self.assertEqual(local_row["ahead"], 0)
            self.assertEqual(local_row["behind"], 0)
            self.assertIsNone(local_row["last_ci_conclusion"])

            main_row = next(r for r in data["branches"] if r["name"] == "main")
            self.assertEqual(main_row["ahead"], 2)
            self.assertEqual(main_row["behind"], 0)

    def test_list_empty_repo_returns_empty_list(self):
        """Repo with no branches returns total: 0, not an error."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            resource = BranchesResource(root)
            parsed = parse_uri("lcs://branches")
            with patch("lcs_resources.branches._run_git",
                       return_value=_make_proc(0, "")), \
                 patch("lcs_resources.branches.shutil.which", return_value=None):
                result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["branches"], [])
            self.assertEqual(result["data"]["summary"]["total"], 0)
            self.assertEqual(result["data"]["summary"]["local_only"], 0)
            self.assertEqual(result["data"]["summary"]["ahead_of_origin"], 0)
            self.assertEqual(result["data"]["summary"]["behind_origin"], 0)

    def test_list_for_each_ref_failure_returns_partial(self):
        """git for-each-ref failure -> status=partial with empty list."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            resource = BranchesResource(root)
            parsed = parse_uri("lcs://branches")
            with patch("lcs_resources.branches._run_git",
                       return_value=_make_proc(128, "fatal: not a git repo\n")), \
                 patch("lcs_resources.branches.shutil.which", return_value=None):
                result = resource.fetch(parsed)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["data"]["branches"], [])
            self.assertIn("git for-each-ref failed", result["missing"][0])

    def test_list_payload_is_small(self):
        """List payload is bounded - no per-record heavy fields."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            resource = BranchesResource(root)
            parsed = parse_uri("lcs://branches")
            with patch("lcs_resources.branches._run_git",
                       return_value=_make_proc(0, "")), \
                 patch("lcs_resources.branches.shutil.which", return_value=None):
                result = resource.fetch(parsed)
            payload = json.dumps(result)
            # Empty fixture: under 1 KB.
            self.assertLess(len(payload), 1024)


# ──────────────────────────────────────────────────────────────────
# lcs://sessions (list)
# ──────────────────────────────────────────────────────────────────

class TestSessionsListEndpoint(unittest.TestCase):
    def test_empty_index_returns_status_ok_not_partial(self):
        """No canonical + no transcripts -> total: 0, status='ok'."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            resource = SessionsResource(root)
            parsed = parse_uri("lcs://sessions")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["sessions"], [])
            summary = result["data"]["summary"]
            self.assertEqual(summary["total"], 0)
            self.assertEqual(summary["by_role"], {})
            self.assertTrue(summary["as_of"].endswith("+00:00"))

    def test_canonical_source_is_enumerated(self):
        """logs/sessions/*.json dumps populate the list."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sessions").mkdir(parents=True)
            (root / "sessions" / "alpha.json").write_text(json.dumps({
                "id": "alpha", "role": "claude-code",
                "current_task": "task A", "last_tool": "Edit",
                "started_at": "2026-07-01T00:00:00Z",
            }))
            (root / "sessions" / "beta.json").write_text(json.dumps({
                "id": "beta", "role": "codex",
                "current_task": "task B", "last_tool": "Bash",
                "started_at": "2026-07-02T00:00:00Z",
            }))
            resource = SessionsResource(root)
            parsed = parse_uri("lcs://sessions")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            sessions = result["data"]["sessions"]
            self.assertEqual(len(sessions), 2)
            for row in sessions:
                self.assertEqual(set(row.keys()), SESSION_LIST_FIELDS)
                self.assertIn(row["role"], ("claude-code", "codex"))
            summary = result["data"]["summary"]
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["by_role"], {"claude-code": 1, "codex": 1})

    def test_transcripts_fall_back_to_jsonl_scan(self):
        """No canonical dumps, transcripts present -> still list."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "claude-code").mkdir()
            with (root / "claude-code" / "sess-X.jsonl").open("w") as fh:
                fh.write(json.dumps({
                    "sessionId": "sess-X", "type": "user",
                    "timestamp": "2026-07-10T10:00:00Z",
                    "cwd": "/w/X",
                    "message": {"role": "user", "content": "hello"},
                }) + "\n")
                fh.write(json.dumps({
                    "sessionId": "sess-X", "type": "assistant",
                    "tool_name": "Edit",
                }) + "\n")
            resource = SessionsResource(root)
            parsed = parse_uri("lcs://sessions")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            sessions = result["data"]["sessions"]
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["id"], "sess-X")
            self.assertEqual(sessions[0]["role"], "claude-code")
            self.assertEqual(sessions[0]["last_tool"], "Edit")
            # Field-set: no cwd leaks into the list form.
            self.assertEqual(set(sessions[0].keys()), SESSION_LIST_FIELDS)
            self.assertNotIn("cwd", sessions[0])
            self.assertEqual(result["data"]["summary"]["by_role"], {"claude-code": 1})

    def test_top_level_json_alias_is_enumerated(self):
        """logs/<id>.json (top-level) is included alongside canonical."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "alt.json").write_text(json.dumps({
                "id": "alt", "role": "codex",
                "current_task": "alt task", "last_tool": None,
                "started_at": "2026-07-05T00:00:00Z",
            }))
            resource = SessionsResource(root)
            parsed = parse_uri("lcs://sessions")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            ids = [s["id"] for s in result["data"]["sessions"]]
            self.assertEqual(ids, ["alt"])

    def test_list_payload_is_small(self):
        """No heavy fields (cwd, _source_path, _matched) leak into list."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sessions").mkdir(parents=True)
            (root / "sessions" / "x.json").write_text(json.dumps({
                "id": "x", "role": "claude-code",
                "current_task": "t", "last_tool": "Read",
                "started_at": "2026-07-01T00:00:00Z",
                "cwd": "/some/heavy/path",
            }))
            resource = SessionsResource(root)
            parsed = parse_uri("lcs://sessions")
            result = resource.fetch(parsed)
            row = result["data"]["sessions"][0]
            self.assertNotIn("cwd", row)
            self.assertNotIn("_source_path", row)
            self.assertNotIn("_matched", row)


# ──────────────────────────────────────────────────────────────────
# lcs://prs (list, via PRResource alias)
# ──────────────────────────────────────────────────────────────────

class TestPRsListEndpoint(unittest.TestCase):
    def _pr_payload(self) -> list:
        return [
            {
                "number": 12,
                "title": "Add list form for branches",
                "headRefName": "feat/branches-list",
                "state": "OPEN",
                "statusCheckRollup": [
                    {"conclusion": "SUCCESS", "status": "COMPLETED"},
                ],
                "reviewDecision": "APPROVED",
            },
            {
                "number": 11,
                "title": "Older change",
                "headRefName": "feat/older",
                "state": "OPEN",
                "statusCheckRollup": [
                    {"conclusion": "SUCCESS", "status": "COMPLETED"},
                    {"conclusion": "FAILURE", "status": "COMPLETED"},
                ],
                "reviewDecision": "CHANGES_REQUESTED",
            },
            {
                "number": 10,
                "title": "Already merged",
                "headRefName": "feat/merged",
                "state": "MERGED",
                "statusCheckRollup": [],
                "reviewDecision": None,
            },
            {
                "number": 9,
                "title": "Closed without merge",
                "headRefName": "feat/closed",
                "state": "CLOSED",
                "statusCheckRollup": [],
                "reviewDecision": None,
            },
        ]

    def test_list_returns_prs_and_summary(self):
        with tempfile.TemporaryDirectory() as td:
            resource = PRResource(Path(td))
            parsed = parse_uri("lcs://prs")
            with patch("lcs_resources.pr._run_gh",
                       return_value=_gh_proc(self._pr_payload())):
                result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            data = result["data"]
            self.assertIn("prs", data)
            self.assertIn("summary", data)

            # Field-set assertion: every row has exactly the small-list
            # fields and nothing else.
            for row in data["prs"]:
                self.assertEqual(set(row.keys()), PR_LIST_FIELDS)

            # Summary field-set assertion.
            self.assertEqual(set(data["summary"].keys()), PR_SUMMARY_FIELDS)
            self.assertEqual(data["summary"]["total"], 4)
            self.assertEqual(data["summary"]["open"], 2)
            self.assertEqual(data["summary"]["closed"], 1)
            self.assertEqual(data["summary"]["merged"], 1)

            # Per-row correctness.
            approved = next(r for r in data["prs"] if r["n"] == 12)
            self.assertEqual(approved["title"], "Add list form for branches")
            self.assertEqual(approved["head"], "feat/branches-list")
            self.assertEqual(approved["ci_state"], "success")
            self.assertEqual(approved["review_state"], "APPROVED")

            changes_req = next(r for r in data["prs"] if r["n"] == 11)
            self.assertEqual(changes_req["ci_state"], "failure")
            self.assertEqual(changes_req["review_state"], "CHANGES_REQUESTED")

            merged = next(r for r in data["prs"] if r["n"] == 10)
            self.assertEqual(merged["ci_state"], None)
            self.assertIsNone(merged["review_state"])

    def test_list_gh_absent_returns_partial(self):
        """gh binary missing -> status=partial, missing=['gh unavailable']."""
        with tempfile.TemporaryDirectory() as td:
            resource = PRResource(Path(td))
            parsed = parse_uri("lcs://prs")
            with patch("lcs_resources.pr._run_gh", side_effect=FileNotFoundError("gh")):
                result = resource.fetch(parsed)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["data"]["prs"], [])
            self.assertEqual(result["data"]["summary"]["total"], 0)
            self.assertIn("gh unavailable", result["missing"])

    def test_list_gh_command_failure_returns_partial(self):
        with tempfile.TemporaryDirectory() as td:
            resource = PRResource(Path(td))
            parsed = parse_uri("lcs://prs")
            with patch("lcs_resources.pr._run_gh",
                       return_value=_gh_proc([], returncode=1,
                                              stderr="auth failed")):
                result = resource.fetch(parsed)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["data"]["prs"], [])

    def test_list_payload_is_small(self):
        """No heavy fields (status, checks, reviews, unresolved_threads)."""
        with tempfile.TemporaryDirectory() as td:
            resource = PRResource(Path(td))
            parsed = parse_uri("lcs://prs")
            with patch("lcs_resources.pr._run_gh",
                       return_value=_gh_proc(self._pr_payload())):
                result = resource.fetch(parsed)
            payload = json.dumps(result)
            # 4 PRs in fixture; the heavy fields stripped - well under 8 KB.
            self.assertLess(len(payload), 8192)


# ──────────────────────────────────────────────────────────────────
# Regression: existing per-record handlers still work unchanged
# ──────────────────────────────────────────────────────────────────

class TestRegressionPerRecordStillWorks(unittest.TestCase):
    def test_branches_per_record_unaffected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _init_repo(root)
            registry = ResourceRegistry()
            registry.register(BranchesResource(root))
            server = LCSServer(registry)
            result = server.get("lcs://branches/main")
            self.assertEqual(result["status"], "ok")
            data = result["data"]
            # Per-record fields include origin_head, slot_version, last_ci_run.
            self.assertIn("origin_head", data)
            self.assertIn("local_head", data)
            self.assertIn("ahead", data)
            self.assertIn("behind", data)
            self.assertIn("last_ci_run", data)

    def test_sessions_per_record_unaffected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sessions").mkdir(parents=True)
            (root / "sessions" / "abc.json").write_text(json.dumps({
                "id": "abc", "role": "claude-code",
                "cwd": "/w", "current_task": "t",
                "last_tool": "Edit", "started_at": "2026-07-01T00:00:00Z",
            }))
            registry = ResourceRegistry()
            registry.register(SessionsResource(root))
            server = LCSServer(registry)
            result = server.get("lcs://sessions/abc")
            self.assertEqual(result["status"], "ok")
            data = result["data"]
            # Per-record fields include cwd.
            self.assertIn("cwd", data)
            self.assertEqual(data["cwd"], "/w")

    def test_pr_per_record_unaffected(self):
        with tempfile.TemporaryDirectory() as td:
            registry = ResourceRegistry()
            registry.register(PRResource(Path(td)))
            server = LCSServer(registry)
            payload = {
                "number": 42, "title": "t", "state": "OPEN",
                "statusCheckRollup": [], "reviews": [], "comments": [],
            }
            with patch("lcs_resources.pr._run_gh", return_value=_gh_proc(payload)):
                result = server.get("lcs://pr/42")
            self.assertEqual(result["status"], "ok")
            data = result["data"]
            # Per-record fields include status, checks, reviews, unresolved_threads.
            self.assertIn("status", data)
            self.assertIn("checks", data)
            self.assertIn("reviews", data)
            self.assertIn("unresolved_threads", data)


# ──────────────────────────────────────────────────────────────────
# Alias mechanism in lcs_server
# ──────────────────────────────────────────────────────────────────

class TestAliasMechanism(unittest.TestCase):
    def test_alias_routes_via_dispatcher(self):
        """lcs://prs (alias) resolves to the PRResource handler."""
        registry = ResourceRegistry()
        resource = PRResource(Path(tempfile.gettempdir()))
        registry.register(resource)
        server = LCSServer(registry)
        # PRResource declares aliases = ('prs',). lcs://prs invokes
        # the LIST form, which calls gh pr list (expects a JSON array),
        # not gh pr view (expects an object).
        list_payload = [{
            "number": 1, "title": "x", "headRefName": "feat/x",
            "state": "OPEN", "statusCheckRollup": [],
            "reviewDecision": None,
        }]
        with patch("lcs_resources.pr._run_gh",
                   return_value=_gh_proc(list_payload)):
            alias_result = server.get("lcs://prs")
        self.assertEqual(alias_result["status"], "ok")
        self.assertEqual(len(alias_result["data"]["prs"]), 1)
        self.assertEqual(alias_result["data"]["prs"][0]["n"], 1)

    def test_alias_via_resource_class_attribute(self):
        """PRResource declares aliases = ('prs',)."""
        self.assertEqual(getattr(PRResource, "aliases", ()), ("prs",))

    def test_resource_with_no_aliases_works(self):
        """Defaults: empty aliases tuple, no behavior change."""

        class Plain:
            name = "plain"

            def fetch(self, parsed):
                return {"status": "ok", "data": {"x": 1}}

        registry = ResourceRegistry()
        registry.register(Plain())
        self.assertEqual(registry.get("plain").name, "plain")
        server = LCSServer(registry)
        self.assertEqual(server.get("lcs://plain")["data"], {"x": 1})

    def test_alias_clash_with_resource_name_raises(self):
        """A resource's name colliding with another resource's alias raises."""

        class A:
            name = "alpha"
            aliases = ("beta",)

            def fetch(self, parsed):
                return {}

        class B:
            name = "beta"

            def fetch(self, parsed):
                return {}

        registry = ResourceRegistry()
        registry.register(A())
        with self.assertRaises(LCSError) as cm:
            registry.register(B())
        self.assertIn("alias", str(cm.exception).lower())

    def test_alias_alias_clash_raises(self):
        """Two resources sharing an alias raises."""

        class A:
            name = "alpha"
            aliases = ("shared",)

            def fetch(self, parsed):
                return {}

        class B:
            name = "beta"
            aliases = ("shared",)

            def fetch(self, parsed):
                return {}

        registry = ResourceRegistry()
        registry.register(A())
        with self.assertRaises(LCSError) as cm:
            registry.register(B())
        self.assertIn("alias", str(cm.exception).lower())

    def test_primary_name_takes_precedence_over_alias(self):
        """If 'alpha' is registered and 'beta' aliases 'alpha',
        lcs://alpha still goes to the alpha resource."""

        class Beta:
            name = "alpha"
            aliases = ("beta",)

            def __init__(self):
                self.calls = []

            def fetch(self, parsed):
                self.calls.append(parsed)
                return {"status": "ok", "data": {"via": "beta"}}

        b = Beta()
        registry = ResourceRegistry()
        registry.register(b)
        server = LCSServer(registry)
        result = server.get("lcs://alpha")
        self.assertEqual(result["data"], {"via": "beta"})

    def test_alias_dispatched_to_alias_target(self):
        """Longest-match exact-name first; alias fallback only after."""

        class A:
            name = "alpha"

            def fetch(self, parsed):
                return {"status": "ok", "data": {"hit": "primary"}}

        class B:
            name = "beta"
            aliases = ("aleph",)

            def fetch(self, parsed):
                return {"status": "ok", "data": {"hit": "alias"}}

        registry = ResourceRegistry()
        registry.register(A())
        registry.register(B())
        server = LCSServer(registry)
        # 'alpha' resolves to A (primary wins, B is never used).
        self.assertEqual(server.get("lcs://alpha")["data"], {"hit": "primary"})
        # 'beta' resolves to B via primary name.
        self.assertEqual(server.get("lcs://beta")["data"], {"hit": "alias"})
        # 'aleph' resolves to B via the alias index.
        self.assertEqual(server.get("lcs://aleph")["data"], {"hit": "alias"})


# ──────────────────────────────────────────────────────────────────
# Integration: lcs://prs routed via the LCS server
# ──────────────────────────────────────────────────────────────────

class TestPRsDispatchViaAlias(unittest.TestCase):
    def test_prs_resolves_to_PRResource_via_server(self):
        with tempfile.TemporaryDirectory() as td:
            registry = ResourceRegistry()
            registry.register(PRResource(Path(td)))
            server = LCSServer(registry)
            payload = [{
                "number": 7, "title": "Alias works",
                "headRefName": "feat/alias", "state": "OPEN",
                "statusCheckRollup": [],
                "reviewDecision": "REVIEW_REQUIRED",
            }]
            with patch("lcs_resources.pr._run_gh", return_value=_gh_proc(payload)):
                result = server.get("lcs://prs")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(result["data"]["prs"]), 1)
            self.assertEqual(result["data"]["prs"][0]["n"], 7)
            self.assertEqual(result["data"]["prs"][0]["review_state"],
                             "REVIEW_REQUIRED")


if __name__ == "__main__":
    unittest.main()
