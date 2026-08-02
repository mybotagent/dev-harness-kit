"""robustness.py — D6 Robustness (scenario fixtures).

Phase 0 placeholder. Real scenario fixtures (compile-error, flaky-test,
missing-dep, conflicting-instructions, resource-exhaustion) land in
Phase 2 (proposal §03). For now this scorer returns a neutral
`value=3` with evidence showing the stub status.

When Phase 2 lands, this scorer will:
1. Run each scenario fixture in `eval/scenarios/*.yaml` against a
   clone of the worktree
2. Score each scenario 1..5 based on whether the agent recovered
   gracefully, escalated, or failed silently
3. Return the mean as the dim value
"""
from __future__ import annotations

from pathlib import Path

from lib.behavior_scorers.types import Context, DimensionScore


def score(worktree: Path, ctx: Context) -> DimensionScore:
    """Return a neutral placeholder until Phase 2 wires scenarios."""
    return DimensionScore(
        dim="D6_robustness",
        value=3,
        evidence={
            "status": "pending",
            "phase": 0,
            "reason": "scenario fixtures deferred to Phase 2",
        },
    )
