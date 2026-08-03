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
               branch: str = "feat/issue-539-linear-autosync"):
    """Run linear_sync against a temp directory with controlled config."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / ".dev-kit" / "hand-off").mkdir(parents=True)
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
            (repo / ".dev-kit" / "hand-off" / "linear.json").write_text(
                json.dumps(handoff), encoding="utf-8",
            )
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(linear_sync, "_repo_root", return_value=repo), \
             mock.patch.object(linear_sync, "_current_branch", return_value=branch):
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
                self.assertFalse((repo / ".dev-kit" / "hand-off" / "linear.json").exists())

    def test_disabled_when_enabled_json_linear_off(self):
        with _fake_repo(enabled_json={"mcp": {"linear": "off"}}):
            with mock.patch("urllib.request.urlopen") as urlopen:
                self.assertEqual(linear_sync.sync(), 0)
                urlopen.assert_not_called()

    def test_enabled_when_env_var_present(self):
        with _fake_repo(linear_api_key="test-key", enabled_json=None,
                        handoff={"prompt": "implement auto-sync"}) as repo:
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
                (repo / ".dev-kit" / "hand-off" / "linear.json").read_text(encoding="utf-8")
            )
            self.assertEqual(handoff["action"], "created")
            self.assertIn("DEMO-1", handoff["issue"])
            self.assertEqual(handoff["branch"], "feat/issue-539-linear-autosync")
            self.assertGreaterEqual(len(calls), 2)  # project lookup + issue create

    def test_reuses_existing_issue_in_same_scope(self):
        with _fake_repo(linear_api_key="test-key",
                        handoff={"prompt": "implement auto-sync"}) as repo:
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
                (repo / ".dev-kit" / "hand-off" / "linear.json").read_text(encoding="utf-8")
            )
            self.assertEqual(handoff["action"], "updated")
            self.assertIn("iss-existing", handoff["issue"])

    def test_stale_handoff_with_different_prompt_creates_new_issue(self):
        """#539: 'A present, old, closed, or unrelated handoff is not
        sufficient evidence.' A different prompt = different scope =
        new issue, even if the handoff still points at one."""
        with _fake_repo(linear_api_key="test-key",
                        handoff={"prompt": "implement old unrelated feature"}) as repo:
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
                (repo / ".dev-kit" / "hand-off" / "linear.json").read_text(encoding="utf-8")
            )
            self.assertEqual(handoff["action"], "created")
            self.assertIn("DEMO-9", handoff["issue"])

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

    def test_enabled_json_auto_state(self):
        with _fake_repo(linear_api_key=None,
                        enabled_json={"mcp": {"linear": "auto"}}):
            with mock.patch("urllib.request.urlopen") as urlopen:
                # No handoff, no prompt → no-op without API call.
                self.assertEqual(linear_sync.sync(), 0)
                urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
