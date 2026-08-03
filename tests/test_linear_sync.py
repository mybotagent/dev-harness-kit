#!/usr/bin/env python3
"""tests/test_linear_sync.py — Regression tests for tools/linear_sync.py.

Covers #539 acceptance criteria:
  - configured  → create / update issue
  - disabled    → no-op, exit 0
  - unavailable → no-op, exit 0 (no LINEAR_API_KEY)
  - stale handoff → replaces the handoff, creates a new issue
  - duplicate issue → reuses the existing issue (no flood)

The Linear GraphQL endpoint is mocked so the suite is hermetic and
runs offline. urllib.request.urlopen is patched per-test.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import linear_sync  # noqa: E402  (sys.path tweak above)


@contextmanager
def _fake_repo(linear_api_key: str | None = "test-key",
               enabled_json: dict | None = None,
               handoff: dict | None = None,
               branch: str = "feat/issue-539-linear-autosync",
               repo_dirname: str = "fake-worktree",
               commit_subject: str = "",
               main_checkout: bool = False):
    """Run linear_sync against a temp directory with controlled config."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / repo_dirname
        repo.mkdir(parents=True, exist_ok=True)
        (repo / ".dev-kit" / "hand-off" / "linear").mkdir(parents=True)
        env = {
            "HOME": str(repo),
            "PATH": os.environ.get("PATH", ""),
        }
        if linear_api_key:
            env["LINEAR_API_KEY"] = linear_api_key
        if enabled_json is not None:
            (repo / ".dev-kit" / ".enabled.json").write_text(
                json.dumps(enabled_json), encoding="utf-8",
            )
        if handoff is not None:
            slug = "main" if main_checkout else repo_dirname
            (repo / ".dev-kit" / "hand-off" / "linear" / f"{slug}.json").write_text(
                json.dumps(handoff), encoding="utf-8",
            )
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(linear_sync, "_repo_root", return_value=repo), \
             mock.patch.object(linear_sync, "_current_branch", return_value=branch), \
             mock.patch.object(linear_sync, "_is_main_checkout", return_value=main_checkout), \
             mock.patch.object(linear_sync, "_latest_commit_subject", return_value=commit_subject), \
             mock.patch.object(linear_sync, "_resolve_team_id", return_value="team-test"), \
             mock.patch.object(linear_sync, "_last_commit_info",
                               return_value={"sha": "", "short": "", "subject": "",
                                              "author": "", "date": ""}), \
             mock.patch.object(linear_sync, "_changed_files_since", return_value=[]), \
             mock.patch.object(linear_sync, "_commit_body", return_value=""):
            yield repo


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _mocked_urlopen(handler):
    """Wrap handler(payload) → dict into a urlopen mock."""
    def _urlopen(req, timeout=5):  # noqa: ARG001
        body = json.loads(req.data.decode("utf-8"))
        result = handler(body)
        return _FakeResponse(json.dumps(result).encode("utf-8"))
    return _urlopen


class TestLinearSync(unittest.TestCase):
    def test_disabled_when_no_env_and_no_enabled_json(self):
        with _fake_repo(linear_api_key=None, enabled_json=None) as repo:
            with mock.patch("urllib.request.urlopen") as urlopen:
                self.assertEqual(linear_sync.sync(), 0)
                urlopen.assert_not_called()
                self.assertEqual(
                    list((repo / ".dev-kit" / "hand-off" / "linear").glob("*.json")),
                    [],
                )

    def test_disabled_when_enabled_json_linear_off(self):
        with _fake_repo(enabled_json={"mcp": {"linear": "off"}}):
            with mock.patch("urllib.request.urlopen") as urlopen:
                self.assertEqual(linear_sync.sync(), 0)
                urlopen.assert_not_called()

    def test_enabled_when_env_var_present(self):
        with _fake_repo(linear_api_key="test-key", enabled_json=None,
                        handoff={"prompt": "implement auto-sync"},
                        commit_subject="implement auto-sync") as repo:
            calls = []

            def handler(payload):
                calls.append(payload)
                q = payload["query"]
                if "projects(filter:" in q and "projectCreate" not in q:
                    return {"data": {"projects": {"nodes": [{"id": "proj-1", "name": "demo"}]}}}
                if "issues(filter:" in q:
                    return {"data": {"issues": {"nodes": []}}}
                if "issueCreate" in q:
                    return {"data": {"issueCreate": {"issue": {"id": "iss-1", "identifier": "DEMO-1"}}}}
                raise AssertionError(f"unexpected query: {q}")

            with mock.patch("urllib.request.urlopen", _mocked_urlopen(handler)):
                self.assertEqual(linear_sync.sync(), 0)
            handoff = json.loads(
                (repo / ".dev-kit" / "hand-off" / "linear" / "fake-worktree.json").read_text(encoding="utf-8")
            )
            self.assertEqual(handoff["action"], "created")
            self.assertIn("DEMO-1", handoff["issue"])
            self.assertEqual(handoff["branch"], "feat/issue-539-linear-autosync")
            self.assertGreaterEqual(len(calls), 2)  # project lookup + issue create

    def test_reuses_existing_issue_in_same_scope(self):
        with _fake_repo(linear_api_key="test-key",
                        handoff={"prompt": "implement auto-sync"},
                        commit_subject="implement auto-sync") as repo:
            def handler(payload):
                q = payload["query"]
                if "projects(filter:" in q and "projectCreate" not in q:
                    return {"data": {"projects": {"nodes": [{"id": "proj-1", "name": "demo"}]}}}
                if "issues(filter:" in q:
                    # Issue already exists with the same scope marker.
                    return {"data": {"issues": {"nodes": [
                        {"id": "iss-existing", "description": "<!-- scope:feat/issue-539-linear-autosync::implement auto sync -->\nold body"},
                    ]}}}
                if "issueUpdate" in q:
                    return {"data": {"issueUpdate": {"issue": {"id": "iss-existing"}}}}
                raise AssertionError(f"unexpected query: {q}")

            with mock.patch("urllib.request.urlopen", _mocked_urlopen(handler)):
                self.assertEqual(linear_sync.sync(), 0)
            handoff = json.loads(
                (repo / ".dev-kit" / "hand-off" / "linear" / "fake-worktree.json").read_text(encoding="utf-8")
            )
            self.assertEqual(handoff["action"], "updated")
            self.assertIn("iss-existing", handoff["issue"])

    def test_stale_handoff_with_different_prompt_creates_new_issue(self):
        """#539: 'A present, old, closed, or unrelated handoff is not
        sufficient evidence.' A different prompt = different scope =
        new issue, even if the handoff still points at one."""
        with _fake_repo(linear_api_key="test-key",
                        handoff={"prompt": "implement old unrelated feature"},
                        commit_subject="implement new unrelated feature") as repo:
            def handler(payload):
                q = payload["query"]
                if "projects(filter:" in q and "projectCreate" not in q:
                    return {"data": {"projects": {"nodes": [{"id": "proj-1", "name": "demo"}]}}}
                if "issues(filter:" in q:
                    # No match — the old handoff's issue is not in the current scope.
                    return {"data": {"issues": {"nodes": [
                        {"id": "iss-stale", "description": "<!-- scope:feat/x::old unrelated task -->\nstale body"},
                    ]}}}
                if "issueCreate" in q:
                    return {"data": {"issueCreate": {"issue": {"id": "iss-new", "identifier": "DEMO-9"}}}}
                raise AssertionError(f"unexpected query: {q}")

            with mock.patch("urllib.request.urlopen", _mocked_urlopen(handler)):
                self.assertEqual(linear_sync.sync(), 0)
            handoff = json.loads(
                (repo / ".dev-kit" / "hand-off" / "linear" / "fake-worktree.json").read_text(encoding="utf-8")
            )
            self.assertEqual(handoff["action"], "created")
            self.assertIn("DEMO-9", handoff["issue"])

    def test_handoff_carries_priority_meta(self):
        """Every hand-off write stamps a `_meta` block declaring
        priority 2 and the Linear API as the source of truth, so a
        reader can tell at a glance that the file is a cache."""
        with _fake_repo(linear_api_key="test-key",
                        handoff={"prompt": "implement auto-sync"},
                        commit_subject="implement auto-sync") as repo:
            def handler(payload):
                q = payload["query"]
                if "projects(filter:" in q and "projectCreate" not in q:
                    return {"data": {"projects": {"nodes": [{"id": "proj-1", "name": "demo"}]}}}
                if "issues(filter:" in q:
                    return {"data": {"issues": {"nodes": []}}}
                if "issueCreate" in q:
                    return {"data": {"issueCreate": {"issue": {"id": "iss-1", "identifier": "DEMO-1"}}}}
                raise AssertionError(f"unexpected query: {q}")

            with mock.patch("urllib.request.urlopen", _mocked_urlopen(handler)):
                self.assertEqual(linear_sync.sync(), 0)
            payload = json.loads(
                (repo / ".dev-kit" / "hand-off" / "linear" / "fake-worktree.json").read_text(encoding="utf-8")
            )
            self.assertIn("_meta", payload)
            self.assertEqual(payload["_meta"]["priority"], 2)
            self.assertEqual(payload["_meta"]["source_of_truth"], "linear_api")
            self.assertEqual(payload["_meta"]["kind"], "cache")
            self.assertEqual(payload["_meta"]["written_by"], "tools/linear_sync.py")

    def test_skips_read_only_prompts(self):
        """#539: 'Do not invoke Linear for read-only work such as
        inspect, review, security, or code-viz unless the user
        explicitly requests registration.'"""
        with _fake_repo(linear_api_key="test-key", handoff={"prompt": "ls -la"}):
            with mock.patch("urllib.request.urlopen") as urlopen:
                self.assertEqual(linear_sync.sync(), 0)
                urlopen.assert_not_called()

    def test_transport_failure_is_non_blocking(self):
        """#539: 'Linear failures are non-blocking for implicit
        workflow calls.' A urllib failure must not raise."""
        with _fake_repo(linear_api_key="test-key",
                        handoff={"prompt": "implement auto-sync"}):
            with mock.patch(
                "urllib.request.urlopen",
                side_effect=OSError("network down"),
            ):
                self.assertEqual(linear_sync.sync(), 0)  # does not raise

    def test_repo_name_falls_back_to_directory(self):
        """Canonical repo name = directory basename, matching #539's
        'project named exactly after the repository' rule."""
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "dev-harness-kit"
            nested.mkdir()
            self.assertEqual(linear_sync._repo_name(nested), "dev-harness-kit")

    def test_issue_body_is_structured(self):
        """Linear issues should land with a consistent template
        (Summary / Context / Files / Acceptance / Test plan / Related)
        and a leading scope marker so future syncs reuse the same issue."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "wt"
            repo.mkdir()
            scope = "fix/x::test"
            with mock.patch.object(linear_sync, "_changed_files_since",
                                   return_value=[("a.py", 10, 2), ("b.md", 4, 0)]), \
                 mock.patch.object(linear_sync, "_last_commit_info",
                                   return_value={"sha": "abcdef0", "short": "abcdef0",
                                                  "subject": "implement x",
                                                  "author": "Claude", "date": "1 minute ago"}):
                body = linear_sync._build_issue_body(
                    prompt="implement feature x",
                    branch="fix/x",
                    repo=repo,
                    scope=scope,
                )
            # Scope marker must be the very first line so _find_issue
            # can detect reuse by prefix match.
            self.assertTrue(body.startswith(f"<!-- scope:{scope} -->"))
            for section in (
                "## Summary",
                "## Context",
                "## Files changed",
                "## Test plan",
                "## Related",
            ):
                self.assertIn(section, body, f"missing section: {section}")
            self.assertIn("**Branch:**", body)
            self.assertIn("**Worktree slug:**", body)
            self.assertIn("**Auto-synced at:**", body)
            self.assertIn("`a.py`", body)
            self.assertIn("`abcdef0`", body)

    def test_issue_body_omits_optional_sections_when_unavailable(self):
        """`## Files changed` and the commit line should be absent
        when running outside a git checkout (e.g. from a unit test)."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "wt"
            repo.mkdir()
            body = linear_sync._build_issue_body(
                prompt="do thing",
                branch="fix/x",
                repo=repo,
                scope="fix/x::do thing",
            )
            self.assertNotIn("## Files changed", body)
            self.assertNotIn("**Last commit:**", body)
            self.assertNotIn("- PR:", body)
            # Required sections still present.
            self.assertIn("## Summary", body)
            self.assertIn("## Context", body)
            self.assertIn("## Test plan", body)
            self.assertIn("## Related", body)

    def test_issue_body_includes_pr_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "wt"
            repo.mkdir()
            pr = {
                "url": "https://github.com/owner/repo/pull/42",
                "number": "42",
                "title": "fix thing",
                "state": "OPEN",
                "draft": "false",
            }
            with mock.patch.object(linear_sync, "_detect_pr", return_value=pr):
                body = linear_sync._build_issue_body(
                    prompt="x", branch="fix/x", repo=repo, scope="fix/x::x",
                )
            self.assertIn("- PR: [#42 (open)](https://github.com/owner/repo/pull/42)", body)
            self.assertIn("fix thing", body)

    def test_detect_pr_returns_none_when_gh_missing(self):
        with mock.patch("subprocess.check_output",
                        side_effect=FileNotFoundError("gh not found")):
            self.assertIsNone(linear_sync._detect_pr(Path("/tmp")))

    def test_detect_pr_returns_none_on_gh_error(self):
        err = subprocess.CalledProcessError(1, "gh", b"")
        with mock.patch("subprocess.check_output", side_effect=err):
            self.assertIsNone(linear_sync._detect_pr(Path("/tmp")))

    def test_issue_body_appends_notes_section(self):
        """Operator-written `notes` in linear-config.json land as a
        '## Notes' section so Korean narrative (or any free-form
        context) survives into the Linear issue."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "wt"
            repo.mkdir()
            (repo / ".dev-kit").mkdir()
            (repo / ".dev-kit" / "linear-config.json").write_text(
                json.dumps({"enabled": True, "notes": "## 작업 메모\n- 한글 컨텍스트"}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"PATH": os.environ.get("PATH", "")}, clear=True), \
                 mock.patch.object(linear_sync, "_repo_root", return_value=repo):
                body = linear_sync._build_issue_body(
                    prompt="x", branch="fix/x", repo=repo, scope="fix/x::x",
                )
            self.assertIn("## Notes", body)
            self.assertIn("## 작업 메모", body)
            self.assertIn("한글 컨텍스트", body)
            # Notes must come BEFORE Related so the auto-link block
            # stays at the end.
            self.assertLess(body.index("## Notes"), body.index("## Related"))

    def test_issue_body_extracts_acceptance_criteria(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "wt"
            repo.mkdir()
            prompt = (
                "do the thing\n"
                "- [ ] first criterion\n"
                "- [x] already done item\n"
                "  - [ ] indented criterion\n"
            )
            criteria = linear_sync._extract_acceptance_criteria(prompt, "")
            self.assertIn("first criterion", criteria)
            self.assertIn("already done item", criteria)
            self.assertIn("indented criterion", criteria)

    def test_enabled_json_auto_state(self):
        with _fake_repo(linear_api_key=None,
                        enabled_json={"mcp": {"linear": "auto"}}):
            with mock.patch("urllib.request.urlopen") as urlopen:
                # No handoff, no prompt → no-op without API call.
                self.assertEqual(linear_sync.sync(), 0)
                urlopen.assert_not_called()

    def test_prompt_falls_back_to_commit_subject(self):
        """#539 follow-up: when the handoff has no `prompt`, derive
        the task description from the latest commit subject instead
        of bailing out."""
        with _fake_repo(linear_api_key="test-key", handoff=None,
                        commit_subject="implement linear auto-sync") as repo:
            def handler(payload):
                q = payload["query"]
                if "projects(filter:" in q and "projectCreate" not in q:
                    return {"data": {"projects": {"nodes": [{"id": "proj-1", "name": "demo"}]}}}
                if "issues(filter:" in q:
                    return {"data": {"issues": {"nodes": []}}}
                if "issueCreate" in q:
                    return {"data": {"issueCreate": {"issue": {"id": "iss-c", "identifier": "DEMO-7"}}}}
                raise AssertionError(f"unexpected query: {q}")

            with mock.patch("urllib.request.urlopen", _mocked_urlopen(handler)):
                self.assertEqual(linear_sync.sync(), 0)
            handoff = json.loads(
                (repo / ".dev-kit" / "hand-off" / "linear" / "fake-worktree.json").read_text(encoding="utf-8")
            )
            self.assertEqual(handoff["prompt"], "implement linear auto-sync")
            self.assertIn("DEMO-7", handoff["issue"])

    def test_stale_handoff_prompt_does_not_shadow_new_commit(self):
        """Adversarial review [high]: `_resolve_prompt` must NOT prefer
        a stale `handoff.prompt` from a previous task. When the
        operator moves to a new task in the same worktree (new
        commit, same branch), the scope must follow the new commit,
        not the cached prompt — otherwise the API lookup updates
        the previous task's issue instead of creating/selecting a
        new one.
        """
        with _fake_repo(
            linear_api_key="test-key",
            # Old task's prompt is still in the handoff.
            handoff={"prompt": "implement OLD task", "issue": "OLD-1"},
            # New task has a fresh commit subject.
            commit_subject="implement NEW task",
        ) as repo:
            def handler(payload):
                q = payload["query"]
                if "projects(filter:" in q and "projectCreate" not in q:
                    return {"data": {"projects": {"nodes": [{"id": "proj-1", "name": "demo"}]}}}
                if "issues(filter:" in q:
                    # No existing issue with the NEW scope.
                    return {"data": {"issues": {"nodes": []}}}
                if "issueCreate" in q:
                    return {"data": {"issueCreate": {"issue": {"id": "iss-new", "identifier": "NEW-1"}}}}
                raise AssertionError(f"unexpected query: {q}")

            with mock.patch("urllib.request.urlopen", _mocked_urlopen(handler)):
                self.assertEqual(linear_sync.sync(), 0)
            handoff = json.loads(
                (repo / ".dev-kit" / "hand-off" / "linear" / "fake-worktree.json").read_text(encoding="utf-8")
            )
            # The new commit subject wins, the old prompt is shadowed.
            self.assertEqual(handoff["prompt"], "implement NEW task")
            self.assertEqual(handoff["action"], "created")
            self.assertIn("NEW-1", handoff["issue"])
            self.assertNotIn("OLD-1", handoff["issue"])

    def test_worktree_config_explicit_off_blocks_sync(self):
        """A worktree that has run `linear off` must not sync even
        if `LINEAR_API_KEY` is set."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "wt"
            repo.mkdir()
            (repo / ".dev-kit").mkdir()
            (repo / ".dev-kit" / "linear-config.json").write_text(
                json.dumps({"enabled": False, "project_name": "x", "team_id": ""}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"LINEAR_API_KEY": "k", "PATH": os.environ.get("PATH", "")}, clear=True), \
                 mock.patch.object(linear_sync, "_repo_root", return_value=repo):
                with mock.patch("urllib.request.urlopen") as urlopen:
                    self.assertEqual(linear_sync.sync(), 0)
                    urlopen.assert_not_called()

    def test_env_file_loads_linear_api_key(self):
        """`.dev-kit/.env.linear` (untracked) is a fallback for
        users who don't want the key in their shell rc-file."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "wt"
            repo.mkdir()
            (repo / ".dev-kit").mkdir()
            (repo / ".dev-kit" / ".env.linear").write_text(
                "# comment\n"
                "LINEAR_API_KEY=file-token-xyz\n"
                "OTHER_VAR=kept\n",
                encoding="utf-8",
            )
            env = {"PATH": os.environ.get("PATH", ""), "HOME": str(repo)}
            with mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch.object(linear_sync, "_repo_root", return_value=repo):
                linear_sync._load_env_file(repo)
                self.assertEqual(os.environ.get("LINEAR_API_KEY"), "file-token-xyz")
                self.assertEqual(os.environ.get("OTHER_VAR"), "kept")

    def test_env_file_does_not_overwrite_existing_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "wt"
            repo.mkdir()
            (repo / ".dev-kit").mkdir()
            (repo / ".dev-kit" / ".env.linear").write_text(
                "LINEAR_API_KEY=file-token\n", encoding="utf-8",
            )
            env = {"PATH": os.environ.get("PATH", ""), "HOME": str(repo),
                   "LINEAR_API_KEY": "shell-token"}
            with mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch.object(linear_sync, "_repo_root", return_value=repo):
                linear_sync._load_env_file(repo)
                # Shell env wins.
                self.assertEqual(os.environ.get("LINEAR_API_KEY"), "shell-token")

    def test_env_file_strips_quotes_and_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "wt"
            repo.mkdir()
            (repo / ".dev-kit").mkdir()
            (repo / ".dev-kit" / ".env.linear").write_text(
                "LINEAR_API_KEY=\"abc123\"  # trailing comment\n"
                "PLAIN=value # also a comment\n",
                encoding="utf-8",
            )
            env = {"PATH": os.environ.get("PATH", ""), "HOME": str(repo)}
            with mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch.object(linear_sync, "_repo_root", return_value=repo):
                linear_sync._load_env_file(repo)
                self.assertEqual(os.environ.get("LINEAR_API_KEY"), "abc123")
                self.assertEqual(os.environ.get("PLAIN"), "value")

    def test_worktree_config_project_name_overrides_repo_basename(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "wt"
            repo.mkdir()
            (repo / ".dev-kit").mkdir()
            (repo / ".dev-kit" / "linear-config.json").write_text(
                json.dumps({"enabled": True, "project_name": "My Project", "team_id": "team-1"}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"LINEAR_API_KEY": "k", "PATH": os.environ.get("PATH", "")}, clear=True), \
                 mock.patch.object(linear_sync, "_repo_root", return_value=repo), \
                 mock.patch.object(linear_sync, "_is_main_checkout", return_value=False):
                self.assertEqual(linear_sync._project_name_override(repo), "My Project")
                self.assertEqual(linear_sync._team_id_override(repo), "team-1")


class TestLinearCLI(unittest.TestCase):
    def _run_cli(self, *args, repo_dirname: str = "wt", env_extra: dict | None = None):
        """Run the CLI in a fresh temp worktree.

        Returns ``(repo, code, stdout, stderr)`` after the temp dir is
        torn down. Tests that need to inspect files written by the CLI
        must do so via ``_read_config(repo)`` (which preserves the
        snapshot) before the helper exits.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / repo_dirname
            repo.mkdir(parents=True)
            (repo / ".dev-kit").mkdir()
            env = {"PATH": os.environ.get("PATH", ""), "HOME": str(repo)}
            if env_extra:
                env.update(env_extra)
            with mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch.object(linear_sync, "_repo_root", return_value=repo), \
                 mock.patch.object(linear_sync, "_is_main_checkout", return_value=False):
                import contextlib
                from io import StringIO
                buf_out, buf_err = StringIO(), StringIO()
                with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                    code = linear_sync.main(list(args))
                stdout = buf_out.getvalue()
                stderr = buf_err.getvalue()
                # Snapshot any config file before the temp dir is torn down.
                config_snapshot = None
                config_path = repo / ".dev-kit" / "linear-config.json"
                if config_path.is_file():
                    config_snapshot = config_path.read_text(encoding="utf-8")
            return repo, code, stdout, stderr, config_snapshot

    @staticmethod
    def _parse_config(snapshot: str | None) -> dict:
        if snapshot is None:
            return {}
        return json.loads(snapshot)

    def test_on_creates_worktree_config(self):
        _, code, out, _, snapshot = self._run_cli("on")
        self.assertEqual(code, 0)
        self.assertIn("linear: on", out)
        cfg = self._parse_config(snapshot)
        self.assertTrue(cfg["enabled"])

    def test_off_disables(self):
        _, code, _, _, snapshot = self._run_cli("off")
        self.assertEqual(code, 0)
        cfg = self._parse_config(snapshot)
        self.assertFalse(cfg["enabled"])

    def test_project_name_persists(self):
        _, code, out, _, snapshot = self._run_cli("project-name", "My Linear Project")
        self.assertEqual(code, 0)
        cfg = self._parse_config(snapshot)
        self.assertEqual(cfg["project_name"], "My Linear Project")
        self.assertIn("linear: project-name=My Linear Project", out)

    def test_status_prints_resolved_state(self):
        _, code, out, _, _ = self._run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("resolved_project", out)
        self.assertIn("linear_api_key_set", out)

    def test_setup_prints_checklist(self):
        _, code, out, _, _ = self._run_cli("setup")
        self.assertEqual(code, 0)
        self.assertIn("LINEAR_API_KEY", out)
        self.assertIn("linear_sync.py on", out)
        self.assertIn("project-name", out)

    def test_unknown_command_exits_2(self):
        _, code, out, _, _ = self._run_cli("bogus")
        self.assertEqual(code, 2)
        self.assertIn("unknown command", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
