"""registry.py — runtime dimension registration (plugin-author API).

Phase 0 ships seven dims (D1..D7) wired at import time. This module
exists so plugin authors can add new dimensions later (Phase 2+)
without re-importing the whole package.

Mutates `lib.behavior_scorers.SCORER_REGISTRY` and `WEIGHTS` lazily.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional


def register(dim: str, scorer: Callable, weight: Optional[float] = None) -> None:
    """Add a new dimension to the registry at runtime.

    Reserved for plugin authors. Adding an eighth dim is intentional
    work and should land in its own proposal (see
    docs/proposals/agent-behavior-eval/04-open-questions.yaml Q4 for
    candidates like D8 Reversibility / D9 Side-effect Awareness).

    Args:
        dim: dimension id, e.g. `"D8_reversibility"`.
        scorer: function `(worktree: Path, ctx: Context) -> DimensionScore`.
        weight: optional weight; if `None`, the dim is not weighted
            into the aggregate verdict. Use for diagnostic dims that
            should not gate the PR.
    """
    import lib.behavior_scorers as pkg

    if dim in pkg.SCORER_REGISTRY:
        raise ValueError(
            f"dimension {dim!r} already registered; pick a distinct id"
        )
    pkg.SCORER_REGISTRY[dim] = scorer
    if weight is not None:
        set_weight(dim, weight)


def set_weight(dim: str, weight: float) -> None:
    """Update the weight of a registered dim (Phase 2+ use)."""
    import lib.behavior_scorers as pkg

    if dim not in pkg.SCORER_REGISTRY:
        raise KeyError(f"unknown dimension {dim!r}")
    new_weights: Dict[str, float] = dict(pkg.WEIGHTS)
    new_weights[dim] = weight
    pkg.WEIGHTS = new_weights  # type: ignore[attr-defined]


__all__ = ["register", "set_weight"]
