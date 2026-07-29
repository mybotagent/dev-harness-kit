"""_summary — Gap-2 summary block for LCS aggregation resources.

Computes the operator-facing freshness block alongside every aggregation
so the reader sees active/stale counts and slot drift without eyeballing
per-row timestamps. Lives in its own module because Gap 3 will add the
list endpoints (``lcs://branches``, ``lcs://sessions``, ``lcs://prs``)
which need the same shape — duplicating the computation in three places
would be the easier-than-it-looks bug the proposal is trying to prevent.

Freshness contract
==================
``as_of`` is the ISO-8601 UTC timestamp captured at snapshot assembly
time. ``active`` counts entries whose ``last_touched`` is within 24h
of ``as_of``; ``stale`` counts the rest (including entries with a
missing timestamp — those cannot be fresh). ``active + stale == total``.

Slot drift
==========
Each entry's ``slot_version`` is parsed as a dotted tuple
(``"0.3.150"`` → ``(0, 3, 150)``) so comparisons are numeric, not
lexicographic. ``min``/``max`` are the lowest/highest parsed tuples
across the set; ``None`` and unparseable values are excluded from the
min/max computation but counted as "behind" in ``behind_count``
because they cannot be at the max slot.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

FRESHNESS_WINDOW = timedelta(hours=24)


def _parse_slot_version(raw: Any) -> tuple[int, ...] | None:
    """Parse a ``"0.3.150"`` slot version into a comparable tuple.

    Returns ``None`` for missing values or anything that does not look
    like ``"<int>.<int>...<int>"`` (e.g. ``None``, ``""``, ``"abc"``).
    Callers must not raise on bad input — the summary block degrades
    gracefully when individual worktrees lack a ``.claude-plugin/``.
    """
    if not isinstance(raw, str) or not raw:
        return None
    parts = raw.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def summarize_worktrees(entries: list[dict]) -> dict:
    """Build the Gap-2 summary block for a list of worktree entries.

    Each entry must carry ``last_touched`` (ISO-8601 string or ``None``)
    and ``slot_version`` (string or ``None``) — the two fields the
    summary aggregates. Missing fields are tolerated and degrade to
    "stale" / "behind" respectively.
    """
    as_of_dt = datetime.now(timezone.utc)
    cutoff = as_of_dt - FRESHNESS_WINDOW

    active = 0
    stale = 0
    parsed_versions: list[tuple[int, ...]] = []

    for entry in entries:
        ts_raw = entry.get("last_touched")
        if isinstance(ts_raw, str) and ts_raw:
            try:
                ts_dt = datetime.fromisoformat(ts_raw)
            except ValueError:
                ts_dt = None
            if ts_dt is not None and ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=timezone.utc)
            if ts_dt is not None and ts_dt >= cutoff:
                active += 1
            else:
                stale += 1
        else:
            stale += 1

        parsed = _parse_slot_version(entry.get("slot_version"))
        if parsed is not None:
            parsed_versions.append(parsed)

    if parsed_versions:
        max_tuple = max(parsed_versions)
        min_tuple = min(parsed_versions)
        min_str = ".".join(str(p) for p in min_tuple)
        max_str = ".".join(str(p) for p in max_tuple)
        behind_count = 0
        for entry in entries:
            parsed = _parse_slot_version(entry.get("slot_version"))
            if parsed is None or parsed < max_tuple:
                behind_count += 1
    else:
        min_str = None
        max_str = None
        behind_count = 0

    return {
        "total": len(entries),
        "active": active,
        "stale": stale,
        "slot_drift": {
            "min": min_str,
            "max": max_str,
            "behind_count": behind_count,
        },
        "as_of": as_of_dt.isoformat(),
    }
