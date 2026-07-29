"""sessions resource — ``lcs://sessions`` and ``lcs://sessions/<id>``.

Two URI forms:

  lcs://sessions
      → {"status": "ok", "data": {"sessions": [...], "summary": {...}}}
        List form: small per-session snapshot + summary block (see
        ``_fetch_sessions_list``).

  lcs://sessions/<id>
      → {"status": "ok|partial", "data": {id, role, cwd, current_task,
          last_tool, started_at}}
        Per-session detail. Source priority (first hit wins):
        1. ``<logs_root>/sessions/<id>.json`` — canonical dump.
        2. ``<logs_root>/<id>.json`` — top-level alias.
        3. ``<logs_root>/{claude-code,codex}/*<id>*.jsonl`` — transcripts.

Discovery endpoint (Gap 3, issue #455):
- The list form enumerates every canonical dump + transcript and
  emits a small per-session row (no ``cwd`` / ``_source_path`` —
  those are heavy and surfaced on the per-record URI).
- Empty index returns ``status="ok"`` with ``total: 0`` rather than
  ``status="partial"``: a missing index is *honest data*, not a
  partial read of an existing record.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
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


def _now_iso() -> str:
    """Current UTC time as ISO8601 with explicit +00:00 suffix."""
    return datetime.now(timezone.utc).isoformat()


def _list_canonical_sessions(logs_root: Path) -> dict[str, dict]:
    """Enumerate ``logs/sessions/*.json`` dumps → ``{sid: record}``.

    File name (without extension) is the session id. Malformed JSON
    is silently skipped — the canonical dumper is the trusted source
    here and a bad record is best surfaced via a ``partial`` response
    on the per-record URI, not by failing the entire list.
    """
    out: dict[str, dict] = {}
    sessions_dir = logs_root / "sessions"
    if not sessions_dir.is_dir():
        return out
    for path in sorted(sessions_dir.glob("*.json")):
        sid = path.stem
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict):
            # Inject id from the filename when the record omits it
            # so downstream code can rely on a single key.
            record.setdefault("id", sid)
            out[sid] = record
    return out


def _list_top_level_sessions(logs_root: Path) -> dict[str, dict]:
    """Enumerate top-level ``logs/*.json`` aliases → ``{sid: record}``.

    Skips anything that lives in a subdirectory (canonical
    ``sessions/`` and transcript ``{claude-code,codex}/`` are
    handled separately) so we don't double-count or shadow the
    canonical dumper.
    """
    out: dict[str, dict] = {}
    if not logs_root.is_dir():
        return out
    for path in sorted(logs_root.glob("*.json")):
        if path.parent != logs_root:
            continue
        sid = path.stem
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict):
            record.setdefault("id", sid)
            out[sid] = record
    return out


def _list_transcript_sessions(logs_root: Path) -> dict[str, dict]:
    """Walk ``logs/{claude-code,codex}/*.jsonl`` → ``{sid: record}``.

    Each jsonl contributes one synthesized record per distinct
    session id. ``_aggregate_jsonl`` already enforces the
    first-match-wins / last-match-wins aggregation rules so the
    small-list fields (``current_task``, ``last_tool``,
    ``started_at``) reflect the full transcript rather than just
    the first line.
    """
    out: dict[str, dict] = {}
    for subdir in _TRANSCRIPT_DIRS:
        dir_path = logs_root / subdir
        if not dir_path.is_dir():
            continue
        for jsonl in sorted(dir_path.glob("*.jsonl")):
            # Extract the session id(s) from this transcript. The
            # cheap filename-pre-filter doesn't apply here — we need
            # to walk lines to discover ids. ``_aggregate_jsonl`` is
            # id-specific so we can't reuse it for discovery; do a
            # one-pass scan instead.
            try:
                with jsonl.open(encoding="utf-8") as fh:
                    ids: set[str] = set()
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
                        sid = _record_session_id(record)
                        if sid:
                            ids.add(sid)
            except OSError:
                continue
            for sid in ids:
                if sid in out:
                    # First-hit-wins for the transcript-derived row;
                    # canonical / top-level JSON overrides below.
                    continue
                agg = _aggregate_jsonl(jsonl, sid)
                if agg is not None:
                    agg["_source_path"] = str(jsonl)
                    out[sid] = agg
    return out


class SessionsResource(Resource):
    """LCS resource for ``lcs://sessions[/<id>]``."""

    name = NAME

    def __init__(self, logs_root: Path) -> None:
        self._logs_root = logs_root

    def fetch(self, parsed: ParsedURI) -> dict:
        # List form: lcs://sessions (with or without trailing slash).
        if not parsed.path_segments[1:]:
            return self._fetch_sessions_list()

        # Per-session form: lcs://sessions/<id>.
        if len(parsed.path_segments) < 2 or not parsed.path_segments[1]:
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

    def _fetch_sessions_list(self) -> dict:
        """Build the ``lcs://sessions`` list payload + summary block.

        Source priority (first hit wins per session id):
        1. ``logs/sessions/<sid>.json`` (canonical Phase 0.4 dumps).
        2. ``logs/<sid>.json`` (top-level alias).
        3. ``logs/{claude-code,codex}/*.jsonl`` (transcripts).

        Empty index returns ``status="ok"`` (NOT ``partial``) — an
        empty index is honest data, not a partial read of an
        existing record.

        The list rows carry the small-list fields only:
        ``id, role, started_at, current_task, last_tool``. Heavy
        fields (``cwd``, ``_source_path``, ``_matched``) stay on
        the per-record URI.
        """
        canonical = _list_canonical_sessions(self._logs_root)
        top_level = _list_top_level_sessions(self._logs_root)
        transcripts = _list_transcript_sessions(self._logs_root)

        # Source priority: canonical > top-level > transcripts.
        merged: dict[str, dict] = {}
        for src in (canonical, top_level, transcripts):
            for sid, record in src.items():
                merged.setdefault(sid, record)

        rows: list[dict] = []
        by_role: dict[str, int] = {}
        for sid in sorted(merged.keys()):
            record = merged[sid]
            role = _detect_role(record) or "claude-code"
            row = {
                "id": sid,
                "role": role,
                "started_at": _extract_started_at(record),
                "current_task": _extract_task(record),
                "last_tool": _extract_last_tool(record),
            }
            rows.append(row)
            by_role[role] = by_role.get(role, 0) + 1

        return {
            "status": "ok",
            "data": {
                "sessions": rows,
                "summary": {
                    "total": len(rows),
                    "by_role": by_role,
                    "as_of": _now_iso(),
                },
            },
        }
