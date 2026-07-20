"""evidence.py — typed evidence format.

One parsed finding is one Evidence object. The shape is locked so:

  - per-dim expert outputs can be validated once and then passed
    through deterministic filters and the verifier without re-parsing
  - downstream rendering (markdown report, suggested diff, hand-off
    table) consumes a uniform type
  - JSON round-trip is lossless (to_dict / from_dict)

The schema is deliberately conservative: required keys are the ones
the precision-over-recall contract demands (failure_scenario +
severity + confidence). Optional keys are surfaced when present:

  - `fix`       — verbatim code/patch to apply (no commentary). When the
                  engine emits suggested diffs, only `fix` flows into
                  the diff stream. Empty if the expert has no concrete
                  patch.
  - `fix_hint`  — human-readable suggestion. May include prose, an
                  explanation of *why* the fix matters, or a recap of
                  the failure scenario. Surface in REPORTS only;
                  never emit into actual diffs.
  - `good`      — counter-example the expert considered but rejected.

`fix` and `fix_hint` are independent. Setting one never pollutes the
other's sink.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class Severity(Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    NIT = "nit"

    def __str__(self) -> str:  # pragma: no cover (cosmetic)
        return self.value


SEVERITY_ORDER = [Severity.CRITICAL, Severity.MAJOR, Severity.MINOR, Severity.NIT]


class Verdict(Enum):
    CONFIRMED = "CONFIRMED"
    PLAUSIBLE = "PLAUSIBLE"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Evidence:
    """One parsed finding from a per-dim expert.

    All fields are populated by `parse_candidate`; downstream code
    never has to guard against None for required keys.

    Schema boundary contract — `fix` vs `fix_hint`:

      - `fix`      — verbatim code/patch to apply. NO prose, no
                     explanation, no commentary. Code-only.
                     This is the field the diff emitter reads.
      - `fix_hint` — human-readable suggestion for a report. MAY
                     contain prose, an explanation of the rationale,
                     or a recap of the failure scenario.
                     Surface in REPORTS only; never emit into actual
                     diffs.

    Both fields are independent. The split is enforced at the schema
    boundary so a future expert prompt that fills `fix_hint` cannot
    silently pollute the diff stream.

    Identity / verifier surface:

      - `evidence_id` — stable content-hashed identifier derived from
        the candidate payload. The reviewer / verifier / log pipeline
        dedupe by this id; positional list indices are not stable.
      - `verifier`    — name of the verifier pipeline that voted on
        this finding (e.g. "llm-judge", "static-rules").
      - `verdict`     — verifier decision (CONFIRMED | PLAUSIBLE |
        REJECTED). `None` until the verifier has run.
      - `verdict_reason` — human-readable rationale returned alongside
        the verdict. Engine surfaces it in Layer-2 PR summaries.

    Whole-file deletion contract:

      - `deletion_scope`    — "line" (default) or "whole-file".
        A delete-mode dim emits `git rm <file>` ONLY when scope is
        "whole-file" AND the dim charter allows delete.
      - `deletion_root_cause` — why the whole file is safe to remove
        (orphan module, dead export cluster, etc.). Optional.
      - `deletion_proof`   — dict of booleans (no_importers, no_callers,
        no_references, no_runtime_calls). Engine requires
        `no_importers AND no_callers` for a `git rm` to fire.
    """

    file: str
    line: int
    dim: str
    severity: Severity
    confidence: str
    title: str
    tldr: str
    failure_scenario: str
    fix: Optional[str] = None        # verbatim patch (code-only)
    fix_hint: Optional[str] = None   # human-readable suggestion text
    spans: Optional[Tuple[int, int]] = None
    good: Optional[str] = None
    evidence_id: str = ""
    verifier: Optional[str] = None
    verdict: Optional["Verdict"] = None
    verdict_reason: Optional[str] = None
    deletion_scope: str = "line"
    deletion_root_cause: Optional[str] = None
    deletion_proof: Optional[Dict[str, bool]] = None


_KNOWN_SEVERITIES = {s.value for s in Severity}
_ALLOWED_CONFIDENCE = {"high", "medium", "low"}


def parse_candidate(
    candidate: Dict[str, Any], dim_fallback: str = ""
) -> Evidence:
    """Coerce one expert JSON item into an Evidence.

    Raises ValueError on missing required fields or invalid enums.
    Missing `confidence` defaults to "medium" so a malformed expert
    output never trips the verifier — it just gets the medium floor.
    Missing `dim` falls back to `dim_fallback` (the outer Dimension
    name supplied by the engine loop) so expert JSON contracts can
    omit the redundant per-item dim field without rendering empty.
    """
    try:
        file = str(candidate["file"])
        line = int(candidate["line"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"evidence: missing/invalid file or line: {candidate!r}"
        ) from exc

    severity_raw = candidate.get("severity", "")
    if severity_raw not in _KNOWN_SEVERITIES:
        raise ValueError(
            f"evidence: severity must be one of {sorted(_KNOWN_SEVERITIES)}, "
            f"got {severity_raw!r}"
        )
    severity = Severity(severity_raw)

    confidence = candidate.get("confidence", "medium")
    if confidence not in _ALLOWED_CONFIDENCE:
        confidence = "medium"

    failure_scenario = candidate.get("failure_scenario", "") or ""
    title = candidate.get("title", "") or ""
    tldr = candidate.get("tldr", "") or ""
    dim = candidate.get("dim", "") or dim_fallback

    fix_hint = candidate.get("fix_hint")
    fix_raw = candidate.get("fix")
    good = candidate.get("good")
    spans_raw = candidate.get("spans")
    spans: Optional[Tuple[int, int]] = None
    if isinstance(spans_raw, (list, tuple)) and len(spans_raw) == 2:
        try:
            spans = (int(spans_raw[0]), int(spans_raw[1]))
        except (TypeError, ValueError):
            spans = None

    evidence_id = candidate.get("id") or _derive_evidence_id(
        file=file,
        line=line,
        dim=dim,
        title=title,
        failure_scenario=failure_scenario,
        candidate=candidate,
    )
    deletion_scope = candidate.get("deletion_scope", "line")
    if deletion_scope not in {"line", "whole-file"}:
        deletion_scope = "line"
    deletion_root_cause = candidate.get("deletion_root_cause")
    proof_raw = candidate.get("deletion_proof")
    if not isinstance(proof_raw, dict):
        proof_raw = None
    deletion_proof: Optional[Dict[str, bool]] = None
    if proof_raw is not None:
        deletion_proof = {str(k): bool(v) for k, v in proof_raw.items()}

    return Evidence(
        file=file,
        line=line,
        dim=dim,
        severity=severity,
        confidence=confidence,
        title=title,
        tldr=tldr,
        failure_scenario=failure_scenario,
        # `fix` is the verbatim code/patch (code-only). `fix_hint` is the
        # human-readable suggestion text. The two are kept independent so
        # a future expert that fills `fix_hint` cannot pollute the diff
        # stream — diffs only read `f.fix`.
        fix=fix_raw if isinstance(fix_raw, str) else None,
        fix_hint=fix_hint if isinstance(fix_hint, str) else None,
        spans=spans,
        good=good if isinstance(good, str) else None,
        evidence_id=evidence_id,
        deletion_scope=deletion_scope,
        deletion_root_cause=deletion_root_cause if isinstance(deletion_root_cause, str) else None,
        deletion_proof=deletion_proof,
    )


def _derive_evidence_id(
    *,
    file: str,
    line: int,
    dim: str,
    title: str,
    failure_scenario: str,
    candidate: Dict[str, Any],
) -> str:
    """Stable id derived from the candidate content.

    Falls back to a content hash when the expert JSON omits `id`.
    The hash is over the canonical JSON of the candidate minus the
    ephemeral fields (dim fallback, etc.) so two semantically identical
    candidates resolve to the same id even if dim arrives via a
    different code path.
    """
    payload = {
        "file": file,
        "line": line,
        "dim": dim,
        "title": title,
        "failure_scenario": failure_scenario,
    }
    for key in ("spans", "fix", "fix_hint", "good"):
        if key in candidate:
            payload[key] = candidate[key]
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def to_dict(ev: Evidence) -> Dict[str, Any]:
    """Lossless JSON-ready dict. Severity stored as its string value.

    The stable identity lives on the dict as `id` so a downstream
    JSON-only consumer can round-trip without inventing a new hash.
    `verdict` (when present) is stored as its string value; `None`
    becomes `null`.
    """
    d = asdict(ev)
    d["severity"] = ev.severity.value
    if "evidence_id" in d:
        d["id"] = d["evidence_id"]
    if d.get("verdict") is not None and hasattr(d["verdict"], "value"):
        d["verdict"] = d["verdict"].value
    return d


def from_dict(d: Dict[str, Any]) -> Evidence:
    # Accept the legacy `id` field on the dict; the parser already
    # looks up `candidate["id"]` for evidence_id.
    payload = dict(d)
    if "id" in payload and "evidence_id" not in payload:
        payload["evidence_id"] = payload["id"]
    verdict_raw = payload.get("verdict")
    if verdict_raw is not None:
        payload["verdict"] = Verdict(verdict_raw)
    return parse_candidate(payload)
