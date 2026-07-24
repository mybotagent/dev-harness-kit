"""sessions resource — ``lcs://sessions/<id>``.

Exposes one runtime session as a normalized JSON snapshot. URI form:

  lcs://sessions/<id>
      → {"status": "ok|partial", "data": {id, role, cwd,
          current_task, last_tool, started_at}}
        missing=<list> when only partial info is available.

Source priority (first hit wins):
  1. ``<logs_root>/sessions/<id>.json`` — canonical session state dump
     written by Phase 0.4 ``sessions.py``. Schema = the 6 fields below.
  2. ``<logs_root>/<id>.json`` — same canonical schema, top-level.
  3. ``<logs_root>/{claude-code,codex}/*<id>*.jsonl`` — transcript-derived.
     We scan line-by-line, parse each line, and take the first record
     whose ``sessionId`` / ``session_id`` matches ``<id>``. From that
     record set we extract the same 6 fields.

If no record is found in any source, the resource returns a
``status="partial"`` envelope with ``missing=["no session <id>"]`` so
the LCS server surfaces the gap to the caller without aborting.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

from lcs_server import LCSPartialError, ParsedURI, Resource

NAME = "sessions"

# Where role-specific transcripts live under logs_root.
_TRANSCRIPT_DIRS = ("claude-code", "codex")

# JSONL fields we recognize as the session id (Claude Code uses
# ``sessionId``; Codex tends to use ``session_id``).
_SESSION_ID_KEYS = ("sessionId", "session_id", "id")


def _load_session_json(logs_root: Path, sid: str) -> dict | None:
    """Return the canonical session record for ``sid`` or ``None``.

    Lookup order: ``sessions/<sid>.json`` (canonical Phase 0.4 dump),
    then ``<sid>.json`` (top-level alias), then a scan of the
    role-specific transcript directories for a jsonl line whose
    session-id field matches ``sid``. The first match in either jsonl
    directory wins; we return the parsed record dict verbatim so
    callers can read whichever fields the source actually carried.
    """
    for relative in (Path("sessions") / f"{sid}.json", Path(f"{sid}.json")):
        candidate = logs_root / relative
        if candidate.is_file():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
    return _scan_jsonl_for_session(logs_root, sid)


def _scan_jsonl_for_session(logs_root: Path, sid: str) -> dict | None:
    """Walk ``logs_root/{claude-code,codex}/*.jsonl`` for ``sid``.

    Returns a synthesized record dict aggregating every line whose
    session id matches ``sid``, or ``None`` if no line matches. The
    aggregate form is required because ``last_tool`` must come from
    the *last* matching record (not the first) and ``current_task`` /
    ``cwd`` / ``started_at`` come from the *first* matching record —
    returning only the first hit would silently drop the last tool.

    Filename containment (``*<sid>*.jsonl``) is a cheap pre-filter so
    a repo with thousands of transcripts doesn't pay a full scan.
    """
    for subdir in _TRANSCRIPT_DIRS:
        dir_path = logs_root / subdir
        if not dir_path.is_dir():
            continue
        for jsonl in sorted(dir_path.glob(f"*{sid}*.jsonl")):
            aggregate = _aggregate_jsonl(jsonl, sid)
            if aggregate is not None:
                aggregate["_source_path"] = str(jsonl)
                return aggregate
    return None


def _aggregate_jsonl(jsonl: Path, sid: str) -> dict | None:
    """Scan one jsonl file for ``sid`` and aggregate matching records.

    Returns a synthesized dict that carries the canonical 6-field
    surface (``id``, ``role``, ``cwd``, ``current_task``, ``last_tool``,
    ``started_at``) plus ``_matched`` (count of matching lines). The
    synthesized dict is what :func:`_load_session_json` returns to
    callers, so :meth:`SessionsResource.fetch` can read all 6 fields
    uniformly whether the source was a canonical json dump or a
    transcript-derived aggregation.
    """
    matched = 0
    synthesized = {
        "id": sid,
        "role": "",
        "cwd": "",
        "current_task": "",
        "last_tool": None,
        "started_at": "",
    }
    try:
        with jsonl.open(encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                if _record_session_id(record) != sid:
                    continue
                matched += 1
                # First-match-wins fields (cwd, current_task, started_at).
                if not synthesized["cwd"]:
                    synthesized["cwd"] = record.get("cwd") or ""
                if not synthesized["current_task"]:
                    synthesized["current_task"] = _extract_task(record)
                if not synthesized["started_at"]:
                    synthesized["started_at"] = (
                        record.get("started_at") or record.get("timestamp") or ""
                    )
                # Last-match-wins field (last_tool).
                tool = _extract_last_tool(record)
                if tool:
                    synthesized["last_tool"] = tool
    except OSError:
        return None
    if matched == 0:
        return None
    synthesized["_matched"] = matched
    return synthesized


def _record_session_id(record: dict) -> str | None:
    """Extract the session-id field from a raw transcript record.

    Tries the three common keys and returns the first string value.
    """
    for key in _SESSION_ID_KEYS:
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _detect_role(record_or_path: dict | Path) -> str:
    """Return ``"claude-code"`` or ``"codex"`` from a record or source path.

    Path takes priority when the input is a Path (it's unambiguous).
    For a record dict, we look for an explicit ``role`` field first;
    if absent or unrecognized, we fall back to the source path stored
    under ``_source_path`` (set by :func:`_scan_jsonl_for_session`).
    """
    if isinstance(record_or_path, Path):
        return _role_from_path(record_or_path)
    if isinstance(record_or_path, dict):
        role = record_or_path.get("role")
        if isinstance(role, str) and role in _TRANSCRIPT_DIRS:
            return role
        source = record_or_path.get("_source_path")
        if isinstance(source, str):
            return _role_from_path(Path(source))
    return ""


def _role_from_path(path: Path) -> str:
    """Infer role from a path's parent directory name."""
    for subdir in _TRANSCRIPT_DIRS:
        if subdir in path.parts:
            return subdir
    return ""


def _derive_cwd(record: dict, fallback: str) -> str:
    """Return the session's cwd, preferring the record's ``cwd`` field.

    If the record lacks ``cwd`` (e.g. older transcripts), scan the
    canonical session json (if available) for a ``cwd`` field. As a
    last resort return ``fallback`` so the caller never gets ``None``
    where a string is expected.
    """
    if isinstance(record, dict):
        cwd = record.get("cwd")
        if isinstance(cwd, str) and cwd:
            return cwd
    return fallback


def _extract_task(record: dict) -> str:
    """Best-effort ``current_task`` from a transcript record.

    Tries the record's top-level ``task`` / ``current_task`` field
    first, then the first ``user`` message's text content. Returns
    an empty string when nothing usable is present so the envelope
    shape is stable.
    """
    if not isinstance(record, dict):
        return ""
    for key in ("current_task", "task"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    message = record.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content:
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str) and text:
                        return text
    return ""


def _extract_last_tool(record: dict) -> str | None:
    """Best-effort ``last_tool`` from a transcript record.

    Prefers an explicit ``last_tool`` field; otherwise looks at the
    ``tool_name`` / ``toolName`` field. Returns ``None`` (not ``""``)
    when no tool info is present so consumers can distinguish
    "unknown" from "definitively no tool used".
    """
    if not isinstance(record, dict):
        return None
    for key in ("last_tool", "tool_name", "toolName"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_started_at(record: dict) -> str:
    """Best-effort ``started_at`` (ISO8601) from a transcript record."""
    if isinstance(record, dict):
        value = record.get("started_at") or record.get("timestamp")
        if isinstance(value, str) and value:
            return value
    return ""


class SessionsResource(Resource):
    """LCS resource for ``lcs://sessions/<id>``."""

    name = NAME

    def __init__(self, logs_root: Path) -> None:
        self._logs_root = logs_root

    def fetch(self, parsed: ParsedURI) -> dict:
        if len(parsed.path_segments) < 2:
            raise LCSPartialError(
                data={"id": ""},
                missing=["missing session id in URI"],
            )
        sid = unquote(parsed.path_segments[1])
        record = _load_session_json(self._logs_root, sid)
        if record is None:
            raise LCSPartialError(
                data={"id": sid},
                missing=[f"no session {sid}"],
            )
        return {
            "status": "ok",
            "data": {
                "id": sid,
                "role": _detect_role(record) or "claude-code",
                "cwd": _derive_cwd(record, fallback=str(self._logs_root)),
                "current_task": _extract_task(record),
                "last_tool": _extract_last_tool(record),
                "started_at": _extract_started_at(record),
            },
        }
