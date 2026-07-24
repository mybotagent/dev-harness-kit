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
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

from lcs_server import LCSError, ParsedURI, Resource

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


def _load_token_logs(logs_root: Path, since: datetime,
                     until: datetime) -> list[dict]:
    """Read TokenLog records from ``logs_root`` filtered by window.

    Window semantics: inclusive at ``since``, exclusive at ``until``
    (so adjacent windows don't double-count boundary records). Malformed
    JSON lines are skipped silently — they're an upstream capture bug,
    not something the spend resource should crash on.
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
                    ts = _parse_ts(str(rec.get("ts", "")))
                    if ts is None or ts < since or ts >= until:
                        continue
                    out.append(rec)
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
