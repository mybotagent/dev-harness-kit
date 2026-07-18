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

import hashlib
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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

    Evidence identity: the surviving item keeps the explicit `id` if
    any. Otherwise it falls back to the deterministic content hash
    (`Evidence.evidence_id`). Either way, the surviving id is stable
    so downstream verifier decisions and log keys stay valid across
    dedupe.
    """
    import dataclasses
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
    # Final pass: drop duplicates that share `evidence_id` with a survivor,
    # keeping the strongest severity (stable ids trump positional dedupe).
    final: List[Evidence] = []
    seen_ids: dict = {}
    for it in out:
        if it.evidence_id and it.evidence_id in seen_ids:
            prev = final[seen_ids[it.evidence_id]]
            if list(Severity).index(it.severity) < list(Severity).index(prev.severity):
                final[seen_ids[it.evidence_id]] = it
            continue
        seen_ids[it.evidence_id or id(it)] = len(final)
        final.append(it)
    return final


class Verifier:
    """Stable identity for verifier decisions.

    Verdict identity MUST be stable across calls and processes so log
    aggregations can dedupe per (verifier, evidence_id, voter). The ID
    is content-hashed — same triple always returns the same string;
    changing any component returns a different string (modulo SHA-256
    collision resistance, negligible in practice).
    """

    @staticmethod
    def new_id(verifier: str, evidence_id: str, voter: str) -> str:
        """Return a deterministic 16-char hex identifier.

        Args:
            verifier: name of the verifier pipeline (e.g. "llm-judge",
                "static-rules", "ci-doctor").
            evidence_id: stable per-finding key — name or content hash.
            voter: who cast the vote (e.g. "gpt-4o", "rule-engine").

        Returns:
            16-char SHA-256 prefix of the sorted-canonicalized triple.
        """
        key = f"{verifier}|{evidence_id}|{voter}".encode("utf-8")
        return hashlib.sha256(key).hexdigest()[:16]


def apply_verifier(
    items: Sequence[Evidence],
    verdicts: Iterable[Tuple[Any, Any, str]],
    verifier: str = "default",
) -> List[Evidence]:
    """Apply verifier decisions by stable evidence_id (preferred) or
    by positional index (legacy). REJECTED items are dropped; the
    verdict + reason survive on the surviving items as Evidence fields.

    Accepts:
      - (evidence_id: str, verdict, reason) — preferred
      - (positional_index: int, verdict, reason) — legacy path, still
        supported so existing callers can pass list indices

    Stricter mapping rules:
      - REJECTED items are dropped.
      - CONFIRMED / PLAUSIBLE items are KEPT and their Evidence.verdict
        + Evidence.verdict_reason + Evidence.verifier fields are filled.
      - Unknown ids / indices are silently ignored.
      - When both `id` and `idx` shapes appear in the same input, the
        `id` shape wins on conflicts (verdict-by-id is authoritative).

    `verdict` may arrive as either a `Verdict` enum or its string
    value; both are normalized before the comparison so callers can
    pass the literal they already have.
    """
    def _to_verdict(v: Any) -> Verdict:
        if isinstance(v, Verdict):
            return v
        return Verdict(str(v))

    by_id: Dict[str, Tuple[Verdict, str]] = {}
    by_idx: Dict[int, Tuple[Verdict, str]] = {}
    for entry in verdicts:
        idx_or_id, verdict, reason = entry
        norm = _to_verdict(verdict)
        if isinstance(idx_or_id, int) and not isinstance(idx_or_id, bool):
            by_idx[idx_or_id] = (norm, reason)
        else:
            by_id[str(idx_or_id)] = (norm, reason)
    out: List[Evidence] = []
    for idx, it in enumerate(items):
        vote = by_id.get(it.evidence_id)
        if vote is None:
            vote = by_idx.get(idx)
        if vote is None:
            out.append(it)
            continue
        verdict, reason = vote
        if verdict == Verdict.REJECTED:
            continue
        out.append(_with_verdict(it, verifier, verdict, reason))
    return out


def _with_verdict(
    item: Evidence,
    verifier: str,
    verdict: Verdict,
    reason: str,
) -> Evidence:
    """Return a copy of `item` with verifier fields populated.

    The Evidence dataclass is frozen; `dataclasses.replace` is the only
    legal mutation. Keeping this helper private so callers cannot
    fabricate verdict metadata outside the verifier pipeline.
    """
    import dataclasses
    return dataclasses.replace(
        item,
        verifier=verifier,
        verdict=verdict,
        verdict_reason=reason,
    )


def threshold_by_mode(
    items: Sequence[Evidence],
    mode: str,
    floor_by_dim: Optional[Mapping[str, Sequence[str]]] = None,
) -> List[Evidence]:
    """Drop findings weaker than the mode's severity floor.

    - read-only → keep everything (incl. nits)
    - delete    → drop nits (a deletion must justify itself)
    - rewrite   → drop nits (a rewrite must justify itself)

    Per-dimension `severity_floor` (passed in by the engine) is
    ALWAYS applied regardless of mode: a `read-only` owasp-a05 NIT is
    still dropped because owasp-a05's `severity_floor` excludes NIT.
    The mode threshold is additive on top of the dim floor.
    """
    if mode == "read-only":
        out = list(items)
    elif mode in ("delete", "rewrite"):
        out = [it for it in items if it.severity != Severity.NIT]
    else:
        out = list(items)
    if not floor_by_dim:
        return out
    kept: List[Evidence] = []
    for it in out:
        allowed = floor_by_dim.get(it.dim)
        if not allowed:
            kept.append(it)
            continue
        if it.severity.value in {str(s) for s in allowed}:
            kept.append(it)
    return kept
