"""session_monitor_filter.py -- public metadata predicate + model filter.

Promoted out of ``tools/session_monitor.py`` so the picker can call the
same matching logic without re-entering the parent module (which would
recreate the import cycle that ``session_monitor_types`` was created to
break). The module deliberately depends only on the dataclasses so
``session_monitor``, ``session_monitor_picker``, and ``session_monitor_cli``
can all import it without forming a back-edge.
"""
from __future__ import annotations

from session_monitor_types import Session, WorktreeInfo


def session_matches(s: Session, w: WorktreeInfo, pattern: str) -> bool:
    pat = (pattern or "").strip().lower()
    if not pat:
        return True
    haystacks = (
        s.session_id, s.branch, s.model, s.source, s.log_path,
        w.dirname, s.status.value,
    )
    return any(pat in (h or "").lower() for h in haystacks)


def filter_model(model: list[WorktreeInfo], pattern: str) -> list[WorktreeInfo]:
    pat = (pattern or "").strip().lower()
    if not pat:
        return list(model)
    out: list[WorktreeInfo] = []
    for w in model:
        kept = [s for s in w.sessions if session_matches(s, w, pat)]
        if kept:
            out.append(WorktreeInfo(
                dirname=w.dirname, state=w.state, path=w.path,
                sessions=kept, last_commit_subject=w.last_commit_subject,
            ))
    return out
