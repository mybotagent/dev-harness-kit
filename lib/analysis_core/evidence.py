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

from dataclasses import dataclass, field, asdict
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
    )


def to_dict(ev: Evidence) -> Dict[str, Any]:
    """Lossless JSON-ready dict. Severity stored as its string value."""
    d = asdict(ev)
    d["severity"] = ev.severity.value
    return d


def from_dict(d: Dict[str, Any]) -> Evidence:
    return parse_candidate(d)
