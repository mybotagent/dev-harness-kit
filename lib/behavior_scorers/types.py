"""types.py — shared dataclasses for behavior_scorers.

Holds `Context`, `DimensionScore`, `BehaviorReport`, and the canonical
`DETERMINISTIC_DIMS` tuple. Lives in its own module so the package
sub-modules can import these without triggering the package's full
`__init__` (which would create circular imports).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass(frozen=True)
class Context:
    """Optional dependencies passed to each scorer.

    Phase 0 only uses `baseline_path` (for D3 efficiency comparison).
    Phase 1 will add `llm_judge` (callable for LLM-based scorers).
    Phase 2 will add `history_path` (for trend tracking).
    """

    baseline_path: Optional[Path] = None
    llm_judge: Optional[Callable[..., Dict[str, Any]]] = None
    history_path: Optional[Path] = None
    no_llm: bool = False

    def is_deterministic_only(self) -> bool:
        """True when LLM judges should be skipped (CI gate path)."""
        return self.no_llm or self.llm_judge is None


@dataclass(frozen=True)
class DimensionScore:
    """One dimension's score + evidence (debug data for the reviewer).

    `value` is 1-5; `evidence` is a JSON-serializable mapping.
    """

    dim: str
    value: int
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"dim": self.dim, "value": self.value, "evidence": dict(self.evidence)}


@dataclass(frozen=True)
class BehaviorReport:
    """Aggregated report for one worktree."""

    case_id: str
    worktree: str
    dimension_scores: Tuple[DimensionScore, ...]
    weighted_mean: float
    deterministic_mean: float
    verdict: str  # OK | DRIFT_WARNING | ROT | ESCALATED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "worktree": self.worktree,
            "dimension_scores": [s.to_dict() for s in self.dimension_scores],
            "weighted_mean": self.weighted_mean,
            "deterministic_mean": self.deterministic_mean,
            "verdict": self.verdict,
        }


# Canonical source of truth for which dims are deterministic (no LLM).
# Kept in lockstep with the WEIGHTS dict in `__init__.py`.
# R2 (#513): D8_reversibility + D9_side_effects are pure deterministic
# heuristics, so they join the deterministic floor.
DETERMINISTIC_DIMS: Tuple[str, ...] = (
    "D1_outcome", "D2_process", "D3_efficiency", "D4_safety",
    "D8_reversibility", "D9_side_effects",
)
