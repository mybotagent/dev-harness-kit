"""spend resource — ``lcs://spend/<window>``.

Aggregates token spend from session transcripts across a time window.
Three URI forms:

  lcs://spend/today
      → today's UTC day, 00:00 (inclusive) to 24:00 (exclusive).
  lcs://spend/last-hour
      → the 60 minutes ending at ``now``.
  lcs://spend/<iso-range>
      → ISO-8601 range, format ``YYYY-MM-DDTHH:MM:SSZ-YYYY-MM-DDTHH:MM:SSZ``.

Returns ``{"status": "ok", "data": {"window": {"since", "until"},
"by_session": [...], "by_worktree": [...], "by_skill": [...]}}``. Each
bucket row is ``{"key": <id>, "tokens": <int>}`` sorted by tokens desc,
ties broken by key ascending so output is deterministic.

Source: walks ``<logs_root>/{claude-code,codex}/**/*.jsonl`` for
TokenLog-shaped records (per the LCS spec, ``{ts, session_id, worktree,
skill, tokens, runtime}``). Missing logs / empty window → empty arrays,
not an error.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

from lcs_server import LCSError, ParsedURI, Resource

# Reuse the canonical token normalizer (Phase 0.4 tokens adapter) so the
# LCS resource matches the same Claude/Codex record shapes that
# tools/save_log.py writes. Without this, real transcripts are dropped.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
from runtime_adapters.tokens import normalize_token_log  # noqa: E402

NAME = "spend"

# TokenLog source directories. Matches ``tools/token_efficiency_analyzer.py``.
_TRANSCRIPT_DIRS = ("claude-code", "codex")

# Buckets returned by the resource, in the order they appear in ``data``.
_BUCKET_KEYS = ("session_id", "worktree", "skill")
_BUCKET_NAMES = ("by_session", "by_worktree", "by_skill")


def _now_utc() -> datetime:
    """Clock seam — overridden in tests for deterministic windows."""
    return datetime.now(tz=timezone.utc)


def _parse_window(segment: str,
                  *, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Parse a window segment into ``(since, until)`` UTC datetimes.

    ``segment`` is one of:
    - ``"today"`` — UTC day-of-now, [00:00, 24:00).
    - ``"last-hour"`` — 60 minutes ending at ``now``.
    - ``"<iso>-<iso>"`` — explicit ISO range; both endpoints MUST end
      in ``Z`` (UTC). ``since`` must be < ``until``; otherwise raises.

    Raises :class:`LCSError` for any other shape.
    """
    if segment == "today":
        anchor = (now or _now_utc()).astimezone(timezone.utc)
        since = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
        return since, since + timedelta(days=1)
    if segment == "last-hour":
        anchor = (now or _now_utc()).astimezone(timezone.utc)
        return anchor - timedelta(hours=1), anchor
    if "Z-" in segment:
        # Split on the range separator, NOT on the first '-' inside the
        # timestamp itself (e.g. '2026-07-24T00:00:00Z-...' would split
        # at year/month otherwise). The 'Z-' delimiter is the unambiguous
        # range boundary. Reattach 'Z' to the left side since we split
        # on the 'Z-' boundary.
        left_raw, right_raw = segment.split("Z-", 1)
        left_raw = left_raw + "Z"
        try:
            since = datetime.fromisoformat(left_raw.replace("Z", "+00:00"))
            until = datetime.fromisoformat(right_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LCSError(f"invalid iso range {segment!r}: {exc}") from exc
        if since >= until:
            raise LCSError(
                f"iso range 'since' must precede 'until' (got {segment!r})"
            )
        return since, until
    raise LCSError(
        f"unknown spend window {segment!r} "
        f"(expected 'today', 'last-hour', or '<iso>-<iso>')"
    )


def _iter_log_files(logs_root: Path):
    """Yield every ``*.jsonl`` under ``logs_root/{claude-code,codex}/**``."""
    if not logs_root.exists():
        return
    for sub in _TRANSCRIPT_DIRS:
        d = logs_root / sub
        if d.is_dir():
            yield from sorted(d.rglob("*.jsonl"))


def _parse_ts(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp; accept ``Z`` suffix."""
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _normalize_record(rec: dict, source_path: Path) -> dict | None:
    """Convert a Claude/Codex transcript record to canonical shape.

    Returns ``{ts, session_id, worktree, skill, tokens, runtime}`` or
    ``None`` if the record carries no usable usage data. Uses the Phase
    0.4 ``runtime_adapters.tokens`` normalizer so the LCS resource
    matches what ``tools/save_log.py`` actually writes.

    Worktree attribution falls back to the filename (save_log.py stores
    one file per session, often under a branch-derived subdir); skill
    attribution is unknown from a transcript, so it stays None (the
    by_skill bucket will simply be empty for production data).
    """
    # Skip records without any usage payload — these are user/assistant
    # text turns, not the assistant message that carries message.usage.
    # Production Claude records nest usage at message.usage; production
    # Codex records carry payload.info.total_token_usage. The
    # normalize_token_log helper handles both via raw usage extraction.
    payload = rec.get("payload")
    has_codex_total = (
        isinstance(payload, dict)
        and payload.get("type") == "token_count"
        and isinstance(payload.get("info"), dict)
        and "total_token_usage" in payload.get("info", {})
    )
    # Promote rec.message.usage to rec.usage so normalize_token_log sees it.
    if "usage" not in rec:
        msg = rec.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
            rec = {**rec, "usage": msg["usage"]}
    has_top_usage = isinstance(rec.get("usage"), dict)
    if not (has_top_usage or has_codex_total):
        return None

    # Timestamp: prefer "ts" (synthetic shape), else "timestamp" (Claude)
    # or "payload.timestamp" (Codex). Empty/missing → record skipped.
    ts_raw = rec.get("ts") or rec.get("timestamp")
    if ts_raw is None and isinstance(payload, dict):
        ts_raw = payload.get("timestamp")
    if ts_raw is None:
        return None
    ts = _parse_ts(str(ts_raw))
    if ts is None:
        return None

    # Session id: synthetic shape uses "session_id"; Claude uses
    # "sessionId" at top level; Codex uses "session_id" inside payload.
    session_id = (
        rec.get("session_id")
        or rec.get("sessionId")
        or (payload.get("session_id") if isinstance(payload, dict) else None)
    )
    if not session_id:
        return None

    # Tokens via the canonical normalizer (handles both shapes).
    tl = normalize_token_log(rec, window="")
    tokens = (
        tl.input_tokens
        + tl.output_tokens
        + tl.cache_read_tokens
        + tl.cache_creation_tokens
    )

    # Runtime: derive from file path component (claude-code | codex).
    runtime = "claude-code" if "claude-code" in str(source_path) else "codex"

    # Worktree from filename stem when save_log writes per-session files.
    worktree = source_path.stem if source_path.stem else None

    return {
        "ts": ts.isoformat(),
        "session_id": str(session_id),
        "worktree": worktree,
        "skill": None,
        "tokens": tokens,
        "runtime": runtime,
    }


def _load_token_logs(logs_root: Path, since: datetime,
                     until: datetime) -> list[dict]:
    """Read token-usage records from ``logs_root`` filtered by window.

    Accepts both the synthetic TokenLog shape (``{ts, session_id, ...,
    tokens}``) and the production Claude/Codex transcript shape
    (``message.usage`` / ``payload.info.total_token_usage``). Records
    without usage data are skipped. Window semantics: inclusive at
    ``since``, exclusive at ``until`` so adjacent windows don't double-
    count boundary records. Malformed JSON lines are skipped silently.
    """
    out: list[dict] = []
    for path in _iter_log_files(logs_root):
        try:
            with path.open(encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    # Synthetic shape: take as-is if window matches.
                    if "ts" in rec and "tokens" in rec and "session_id" in rec:
                        ts = _parse_ts(str(rec.get("ts", "")))
                        if ts is None or ts < since or ts >= until:
                            continue
                        out.append(rec)
                        continue
                    # Production shape: normalize then filter.
                    normalized = _normalize_record(rec, path)
                    if normalized is None:
                        continue
                    ts = _parse_ts(normalized["ts"])
                    if ts < since or ts >= until:
                        continue
                    out.append(normalized)
        except OSError:
            continue
    return out


def _aggregate(records: list[dict]) -> dict:
    """Bucket records by session/worktree/skill and return sorted totals."""
    buckets: dict[str, dict[str, int]] = {
        name: defaultdict(int) for name in _BUCKET_NAMES
    }
    for rec in records:
        for bucket_name, key_field in zip(_BUCKET_NAMES, _BUCKET_KEYS):
            key = rec.get(key_field)
            if key is None:
                continue
            buckets[bucket_name][str(key)] += int(rec.get("tokens", 0) or 0)

    def _sorted(mapping: dict[str, int]) -> list[dict]:
        # Tokens desc, key asc — deterministic output for tests + diffs.
        return [
            {"key": k, "tokens": v}
            for k, v in sorted(mapping.items(),
                               key=lambda kv: (-kv[1], kv[0]))
        ]

    return {name: _sorted(buckets[name]) for name in _BUCKET_NAMES}


class SpendResource(Resource):
    """LCS resource for ``lcs://spend/<window>``."""

    name = NAME

    def __init__(self, logs_root: Path | None = None) -> None:
        # Default to <repo_root>/logs; consumer can override (tests do).
        self._logs_root = logs_root or (Path.cwd() / "logs")
        self._now = _now_utc  # test seam

    def fetch(self, parsed: ParsedURI) -> dict:
        if len(parsed.path_segments) < 2:
            raise LCSError(
                "lcs://spend requires a window segment "
                "(today | last-hour | <iso>-<iso>)"
            )
        segment = unquote(parsed.path_segments[1])
        since, until = _parse_window(segment, now=self._now())
        records = _load_token_logs(self._logs_root, since, until)
        buckets = _aggregate(records)
        return {
            "status": "ok",
            "data": {
                "window": {
                    "since": since.isoformat(),
                    "until": until.isoformat(),
                },
                **buckets,
            },
        }
