#!/usr/bin/env python3
"""test_lcs_sessions_resource.py — Phase 1.4 (issue #352) sessions resource.

Pins the ``lcs://sessions/<id>`` contract:
- Canonical ``logs/sessions/<id>.json`` is the first source checked.
- Top-level ``logs/<id>.json`` is the second.
- ``logs/{claude-code,codex}/*<id>*.jsonl`` is the transcript fallback.
- Unknown id returns ``status="partial"`` with ``missing=["no session <id>"]``.
- 6 fields exposed: ``id, role, cwd, current_task, last_tool, started_at``.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))

from lcs_resources.sessions import (  # noqa: E402
    SessionsResource,
    _derive_cwd,
    _detect_role,
    _extract_last_tool,
    _extract_started_at,
    _extract_task,
    _load_session_json,
    _scan_jsonl_for_session,
)
from lcs_server import LCSServer, ResourceRegistry, parse_uri  # noqa: E402


def _write_canonical(logs_root: Path, sid: str, **overrides) -> dict:
    """Write ``logs/sessions/<sid>.json`` and return its parsed contents."""
    record = {
        "id": sid,
        "role": "claude-code",
        "cwd": "/var/folders/abc/T/example",
        "current_task": "fix the login bug",
        "last_tool": "Edit",
        "started_at": "2026-07-09T10:00:00.000Z",
    }
    record.update(overrides)
    (logs_root / "sessions").mkdir(parents=True, exist_ok=True)
    (logs_root / "sessions" / f"{sid}.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    return record


def _write_jsonl(logs_root: Path, role_dir: str, sid: str, lines: list[dict]) -> Path:
    """Write ``logs/<role_dir>/<sid>.jsonl`` with the given line dicts."""
    dir_path = logs_root / role_dir
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{sid}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")
    return path


# ──────────────────────────────────────────────────────────────────
# _load_session_json
# ──────────────────────────────────────────────────────────────────

class TestLoadSessionJson(unittest.TestCase):
    def test_canonical_sessions_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_canonical(root, "abc")
            loaded = _load_session_json(root, "abc")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["id"], "abc")
            self.assertEqual(loaded["role"], "claude-code")

    def test_nonexistent_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertIsNone(_load_session_json(root, "missing"))

    def test_top_level_json_alias(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = {"id": "alt", "role": "codex", "cwd": "/x"}
            (root / "alt.json").write_text(json.dumps(payload), encoding="utf-8")
            loaded = _load_session_json(root, "alt")
            self.assertEqual(loaded["role"], "codex")
            self.assertEqual(loaded["cwd"], "/x")

    def test_jsonl_fallback_in_claude_code_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_jsonl(root, "claude-code", "sess-1", [
                {"sessionId": "sess-1", "type": "user",
                 "timestamp": "2026-07-09T10:00:00Z",
                 "cwd": "/work/sess-1",
                 "message": {"role": "user", "content": "hello"}},
            ])
            loaded = _load_session_json(root, "sess-1")
            self.assertIsNotNone(loaded)
            # Synthesized canonical shape: id/cwd/timestamp aggregated
            # from the matching line.
            self.assertEqual(loaded["id"], "sess-1")
            self.assertEqual(loaded["cwd"], "/work/sess-1")
            self.assertEqual(loaded["_source_path"].split("/")[-2], "claude-code")
            self.assertEqual(loaded["_matched"], 1)

    def test_jsonl_fallback_in_codex_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_jsonl(root, "codex", "sess-2", [
                {"session_id": "sess-2", "type": "user",
                 "timestamp": "2026-07-09T10:00:00Z",
                 "cwd": "/work/sess-2",
                 "message": {"role": "user", "content": "hi"}},
            ])
            loaded = _load_session_json(root, "sess-2")
            self.assertIsNotNone(loaded)
            self.assertEqual(_detect_role(loaded), "codex")
            self.assertEqual(loaded["id"], "sess-2")

    def test_jsonl_scan_ignores_unrelated_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_jsonl(root, "claude-code", "sess-other", [
                {"sessionId": "sess-other", "type": "user"},
            ])
            self.assertIsNone(_load_session_json(root, "sess-target"))

    def test_malformed_canonical_json_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sessions").mkdir(parents=True, exist_ok=True)
            (root / "sessions" / "broken.json").write_text("{not json", encoding="utf-8")
            self.assertIsNone(_load_session_json(root, "broken"))


# ──────────────────────────────────────────────────────────────────
# _detect_role
# ──────────────────────────────────────────────────────────────────

class TestDetectRole(unittest.TestCase):
    def test_claude_code_path(self):
        self.assertEqual(_detect_role(Path("/x/logs/claude-code/a.jsonl")), "claude-code")

    def test_codex_path(self):
        self.assertEqual(_detect_role(Path("/x/logs/codex/a.jsonl")), "codex")

    def test_record_role_field_wins(self):
        record = {"_source_path": "/x/logs/codex/a.jsonl", "role": "claude-code"}
        self.assertEqual(_detect_role(record), "claude-code")

    def test_record_falls_back_to_source_path(self):
        record = {"_source_path": "/x/logs/codex/a.jsonl"}
        self.assertEqual(_detect_role(record), "codex")

    def test_path_with_no_role_dir_returns_empty(self):
        self.assertEqual(_detect_role(Path("/tmp/foo.jsonl")), "")


# ──────────────────────────────────────────────────────────────────
# _derive_cwd
# ──────────────────────────────────────────────────────────────────

class TestDeriveCwd(unittest.TestCase):
    def test_explicit_cwd_field_used(self):
        record = {"cwd": "/work/proj"}
        self.assertEqual(_derive_cwd(record, fallback="/elsewhere"), "/work/proj")

    def test_missing_cwd_falls_back(self):
        record = {"id": "x"}
        self.assertEqual(_derive_cwd(record, fallback="/elsewhere"), "/elsewhere")

    def test_non_string_cwd_falls_back(self):
        record = {"cwd": 42}
        self.assertEqual(_derive_cwd(record, fallback="/elsewhere"), "/elsewhere")


# ──────────────────────────────────────────────────────────────────
# Record extractors (best-effort jsonl derivation)
# ──────────────────────────────────────────────────────────────────

class TestExtractors(unittest.TestCase):
    def test_extract_task_from_message_string(self):
        record = {"message": {"role": "user", "content": "fix the bug"}}
        self.assertEqual(_extract_task(record), "fix the bug")

    def test_extract_task_from_message_blocks(self):
        record = {"message": {"role": "user", "content": [
            {"type": "text", "text": "first text"},
            {"type": "text", "text": "ignored"},
        ]}}
        self.assertEqual(_extract_task(record), "first text")

    def test_extract_task_prefers_explicit_field(self):
        record = {"current_task": "explicit", "message": {"content": "other"}}
        self.assertEqual(_extract_task(record), "explicit")

    def test_extract_task_empty_when_no_signal(self):
        self.assertEqual(_extract_task({}), "")

    def test_extract_last_tool_from_tool_name(self):
        self.assertEqual(_extract_last_tool({"tool_name": "Read"}), "Read")
        self.assertEqual(_extract_last_tool({"toolName": "Bash"}), "Bash")
        self.assertEqual(_extract_last_tool({"last_tool": "Grep"}), "Grep")

    def test_extract_last_tool_none_when_absent(self):
        self.assertIsNone(_extract_last_tool({}))
        self.assertIsNone(_extract_last_tool({"tool_name": ""}))

    def test_extract_started_at_prefers_started_at(self):
        record = {"started_at": "2026-01-01T00:00:00Z", "timestamp": "2026-02-02T00:00:00Z"}
        self.assertEqual(_extract_started_at(record), "2026-01-01T00:00:00Z")

    def test_extract_started_at_falls_back_to_timestamp(self):
        self.assertEqual(_extract_started_at({"timestamp": "2026-02-02T00:00:00Z"}),
                         "2026-02-02T00:00:00Z")

    def test_extract_started_at_empty_when_absent(self):
        self.assertEqual(_extract_started_at({}), "")


# ──────────────────────────────────────────────────────────────────
# SessionsResource.fetch end-to-end
# ──────────────────────────────────────────────────────────────────

class TestSessionsResourceFetch(unittest.TestCase):
    def test_canonical_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_canonical(root, "sess-canon")
            resource = SessionsResource(root)
            parsed = parse_uri("lcs://sessions/sess-canon")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            data = result["data"]
            self.assertEqual(data["id"], "sess-canon")
            self.assertEqual(data["role"], "claude-code")
            self.assertEqual(data["cwd"], "/var/folders/abc/T/example")
            self.assertEqual(data["current_task"], "fix the login bug")
            self.assertEqual(data["last_tool"], "Edit")
            self.assertEqual(data["started_at"], "2026-07-09T10:00:00.000Z")
            for key in ("id", "role", "cwd", "current_task", "last_tool", "started_at"):
                self.assertIn(key, data)

    def test_jsonl_source_derives_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_jsonl(root, "claude-code", "sess-tx", [
                {"sessionId": "sess-tx", "type": "user",
                 "timestamp": "2026-07-09T10:00:00Z",
                 "cwd": "/work/sess-tx",
                 "message": {"role": "user", "content": "first prompt"}},
                {"sessionId": "sess-tx", "type": "assistant",
                 "timestamp": "2026-07-09T10:00:01Z",
                 "message": {"role": "assistant", "content": []},
                 "tool_name": "Edit"},
            ])
            resource = SessionsResource(root)
            parsed = parse_uri("lcs://sessions/sess-tx")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            data = result["data"]
            self.assertEqual(data["id"], "sess-tx")
            self.assertEqual(data["role"], "claude-code")
            self.assertEqual(data["cwd"], "/work/sess-tx")
            self.assertEqual(data["current_task"], "first prompt")
            self.assertEqual(data["last_tool"], "Edit")
            self.assertEqual(data["started_at"], "2026-07-09T10:00:00Z")

    def test_unknown_id_raises_LCSPartialError(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            resource = SessionsResource(root)
            parsed = parse_uri("lcs://sessions/nope")
            from lcs_server import LCSPartialError
            with self.assertRaises(LCSPartialError) as cm:
                resource.fetch(parsed)
            self.assertEqual(cm.exception.data, {"id": "nope"})
            self.assertEqual(cm.exception.missing, ["no session nope"])

    def test_missing_session_id_segment(self):
        # ``lcs://sessions//`` (truly empty id) still raises; bare
        # ``lcs://sessions`` now routes to the list form (Gap 3,
        # issue #455 discovery endpoint).
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            resource = SessionsResource(root)
            parsed = parse_uri("lcs://sessions//")
            from lcs_server import LCSPartialError
            with self.assertRaises(LCSPartialError) as cm:
                resource.fetch(parsed)
            self.assertIn("missing session id", cm.exception.missing[0])

    def test_bare_sessions_returns_list_form(self):
        # ``lcs://sessions`` (no path params) now returns the list
        # form added by Gap 3 (issue #455 discovery endpoint).
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            resource = SessionsResource(root)
            parsed = parse_uri("lcs://sessions")
            result = resource.fetch(parsed)
            self.assertEqual(result["status"], "ok")
            self.assertIn("sessions", result["data"])
            self.assertIn("summary", result["data"])

    def test_url_encoded_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_canonical(root, "feat-xyz")
            resource = SessionsResource(root)
            # %2D is "-"; round-trip is identical here, but the
            # parse path still exercises the unquote call.
            parsed = parse_uri("lcs://sessions/feat%2Dxyz")
            result = resource.fetch(parsed)
            self.assertEqual(result["data"]["id"], "feat-xyz")


# ──────────────────────────────────────────────────────────────────
# LCSServer integration
# ──────────────────────────────────────────────────────────────────

class TestLCSIntegration(unittest.TestCase):
    def test_routes_through_lcs_server(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_canonical(root, "sess-int", role="codex",
                             current_task="integrate", cwd="/p")
            registry = ResourceRegistry()
            registry.register(SessionsResource(root))
            server = LCSServer(registry)
            result = server.get("lcs://sessions/sess-int")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["id"], "sess-int")
            self.assertEqual(result["data"]["role"], "codex")
            self.assertEqual(result["data"]["cwd"], "/p")

    def test_unknown_id_returns_partial_via_server(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = ResourceRegistry()
            registry.register(SessionsResource(root))
            server = LCSServer(registry)
            result = server.get("lcs://sessions/nope")
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["data"], {"id": "nope"})
            self.assertEqual(result["missing"], ["no session nope"])


# ──────────────────────────────────────────────────────────────────
# _scan_jsonl_for_session direct (smoke)
# ──────────────────────────────────────────────────────────────────

class TestScanJsonlDirect(unittest.TestCase):
    def test_returns_record_with_source_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = _write_jsonl(root, "claude-code", "abc", [
                {"sessionId": "abc", "type": "user",
                 "message": {"role": "user", "content": "hi"}},
            ])
            record = _scan_jsonl_for_session(root, "abc")
            self.assertIsNotNone(record)
            self.assertEqual(record["_source_path"], str(path))
            self.assertEqual(record["id"], "abc")

    def test_skips_malformed_lines(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dir_path = root / "claude-code"
            dir_path.mkdir(parents=True, exist_ok=True)
            path = dir_path / "mix.jsonl"
            with path.open("w", encoding="utf-8") as fh:
                fh.write("not-json\n")
                fh.write(json.dumps({"sessionId": "mix", "type": "user"}) + "\n")
            record = _scan_jsonl_for_session(root, "mix")
            self.assertIsNotNone(record)
            self.assertEqual(record["id"], "mix")
            self.assertEqual(record["_matched"], 1)


if __name__ == "__main__":
    unittest.main()
