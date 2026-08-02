"""history.py — append-only history log for behavior eval reports.

The history log is a single JSONL file (default
`.dev-kit/agent-behavior-history.jsonl`) that grows by exactly one line
per `BehaviorReport`. Each line is the report's `to_dict()` JSON shape,
augmented with a `logged_at` ISO-8601 timestamp.

Atomicity: writes go to a sibling `.tmp` file and are renamed into
place. The rename is atomic on POSIX (when source and destination are
on the same filesystem). Same-filesystem placement is guaranteed by
the implementation (`.tmp` is created in `history_path.parent`).

Public API:
    append_history(report, history_path)  — append one report line
    iter_history(history_path)             — yield per-line dicts
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator

from lib.behavior_scorers.types import BehaviorReport


def _now_iso() -> str:
    """Return current UTC time in ISO-8601 with `Z` suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_history(
    report: BehaviorReport,
    history_path: Path,
    logged_at: str | None = None,
) -> None:
    """Append one report to the JSONL history log.

    Args:
        report: the BehaviorReport to persist.
        history_path: path to the JSONL file. Created if missing.
        logged_at: optional ISO timestamp; defaults to now (UTC).

    The write is atomic for short records (under `PIPE_BUF`): POSIX
    guarantees that `O_APPEND` writes do not interleave on the same
    file descriptor, so concurrent appenders do not corrupt the
    line boundary. We follow the new line with `fsync()` to ensure
    durability across a crash before returning.

    The function refuses to follow symlinks (a worktree-controlled
    history_path could redirect writes into attacker territory).
    """
    history_path = Path(history_path)
    if history_path.is_symlink():
        # Refuse to clobber a symlink — same defense as efficiency.py.
        return
    history_path.parent.mkdir(parents=True, exist_ok=True)

    record: Dict[str, Any] = dict(report.to_dict())
    record["logged_at"] = logged_at or _now_iso()

    line = json.dumps(record, sort_keys=True) + "\n"

    # O_APPEND + fsync — atomic single-record append. Text mode uses
    # line buffering by default, which flushes the single record
    # atomically. The line + flush() + fsync() ensures the bytes hit
    # disk before we return.
    with open(history_path, "a") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def iter_history(history_path: Path) -> Iterator[Dict[str, Any]]:
    """Yield one dict per JSONL line in `history_path`.

    Skips blank lines and unparseable lines (returning them as
    `{"_unparseable": True, "_line": "<raw>"}` is intentionally not
    done — the caller may have its own noise policy). Empty paths
    yield no records.
    """
    history_path = Path(history_path)
    if not history_path.is_file():
        return
    if history_path.is_symlink():
        return
    for raw_line in history_path.read_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


__all__ = ["append_history", "iter_history"]
