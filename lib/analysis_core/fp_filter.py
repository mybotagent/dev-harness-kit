"""fp_filter.py — false-positive filter pipeline.

The precision-over-recall contract is enforced here in three steps:

  1. deterministic_filter  — drop findings that have no failure_scenario
     or that pair low confidence with non-blocking severity. Always on.

  2. dedupe                — collapse identical anchors (same file + line
     + dim) keeping the strongest severity; collapse cross-dim root-cause
     duplicates by matching on (file + line) with overlapping categories.

  3. apply_verifier        — caller passes the verifier agent's verdict
     list. REJECTED items are dropped unconditionally. CONFIRMED and
     PLAUSIBLE survive.

  4. threshold_by_mode     — final severity floor. read-only keeps nits;
     delete and rewrite drop them (nits don't justify a mutation).

Each step is a pure function that takes a list and returns a list, so
the SKILL.md body can compose them with or without the verifier pass.
"""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from .evidence import Evidence, Severity, Verdict


def deterministic_filter(items: Sequence[Evidence]) -> List[Evidence]:
    """Drop findings that cannot survive precision-over-recall scrutiny.

    Rules:
      - empty/missing failure_scenario → drop
      - confidence=low AND severity in {minor, nit} → drop
    """
    out: List[Evidence] = []
    for it in items:
        if not it.failure_scenario.strip():
            continue
        if it.confidence == "low" and it.severity in (Severity.MINOR, Severity.NIT):
            continue
        out.append(it)
    return out


def dedupe(items: Sequence[Evidence]) -> List[Evidence]:
    """Collapse identical anchors, keeping the strongest severity.

    Anchor key = (file, line, dim). On collision, the higher-severity
    finding wins. Cross-dim duplicates at the same (file, line) keep
    the *stronger* finding regardless of arrival order — never silently
    drop a CRITICAL because a MINOR surfaced first.
    """
    by_anchor: dict = {}
    fl_index: dict = {}  # (file, line) -> index in `out`
    out: List[Evidence] = []
    for it in items:
        key = (it.file, it.line, it.dim)
        if key in by_anchor:
            existing = by_anchor[key]
            # higher severity wins (lower index in SEVERITY_ORDER = stronger)
            if list(Severity).index(it.severity) < list(Severity).index(existing.severity):
                by_anchor[key] = it
                # Replace in output list too.
                for idx, e in enumerate(out):
                    if (e.file, e.line, e.dim) == key:
                        out[idx] = it
                        fl_index[(it.file, it.line)] = idx
                        break
            continue
        # Cross-dim root-cause collapse: same (file, line) but different dim.
        fl_key = (it.file, it.line)
        if fl_key in fl_index:
            existing_idx = fl_index[fl_key]
            existing = out[existing_idx]
            # Keep the stronger of the two — never drop CRITICAL behind MINOR.
            if list(Severity).index(it.severity) < list(Severity).index(existing.severity):
                # Replace: pop old dim's anchor, register new one.
                old_key = (existing.file, existing.line, existing.dim)
                by_anchor.pop(old_key, None)
                by_anchor[key] = it
                out[existing_idx] = it
                fl_index[fl_key] = existing_idx
            continue
        fl_index[fl_key] = len(out)
        by_anchor[key] = it
        out.append(it)
    return out


def apply_verifier(
    items: Sequence[Evidence],
    verdicts: Iterable[Tuple[int, Verdict, str]],
) -> List[Evidence]:
    """Drop items the verifier REJECTED; keep CONFIRMED + PLAUSIBLE.

    `verdicts` is a list of (index, verdict, reason) tuples in the order
    of the input `items`. Indices that don't match any item are silently
    ignored (the verifier is allowed to be noisy on the edges).
    """
    drop = {idx for idx, verdict, _reason in verdicts if verdict == Verdict.REJECTED}
    return [it for idx, it in enumerate(items) if idx not in drop]


def threshold_by_mode(
    items: Sequence[Evidence], mode: str
) -> List[Evidence]:
    """Drop findings weaker than the mode's severity floor.

    - read-only → keep everything (incl. nits)
    - delete    → drop nits (a deletion must justify itself)
    - rewrite   → drop nits (a rewrite must justify itself)
    """
    if mode == "read-only":
        return list(items)
    if mode in ("delete", "rewrite"):
        return [it for it in items if it.severity != Severity.NIT]
    # Unknown mode → no threshold applied; caller is expected to validate.
    return list(items)
