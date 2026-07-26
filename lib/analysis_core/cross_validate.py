"""cross_validate.py — adversarial cross-check helper for 3-judge fan-out.

Phase 3 eval extension (issue #366). When a per-case eval fans out to
three independent judges (one per "vote"), disagreement is a signal the
operator should review rather than average away. This module centralises
the disagreement math so both the `evaluate` skill and any direct
caller route through the same threshold + escalation marker.

Public API:
    cross_validate_scores(scores_per_judge: list[dict]) -> dict
        Returns:
            {
                "escalate": bool,         # True iff variance > threshold
                "variance": float,        # population variance of means
                "mean": dict[str, float], # per-axis mean across judges
                "per_judge": list[dict],  # one entry per input dict
            }

Threshold is fixed at 0.5 (population variance of axis means across
the three judges). The function is deterministic — same input → same
output — and is the only place the threshold lives.

Backwards-compat: callers that previously averaged scores manually can
swap in `cross_validate_scores(...)` without touching the upstream
judge code.
"""
from __future__ import annotations

from typing import Dict, List

# Variance threshold (population variance of axis means across judges).
# A variance > 0.5 across the three judges' mean axis score is the
# escalation signal. The constant lives here so any future change to
# the threshold is a single-file edit + a single test update.
ESCALATE_VARIANCE_THRESHOLD = 0.5


def _mean_axis(scores_per_judge: List[Dict[str, float]]) -> Dict[str, float]:
    """Mean of each axis across all judges. Skips an axis if no judge
    reported it (empty dict would otherwise raise)."""
    if not scores_per_judge:
        return {}
    axes: set = set()
    for s in scores_per_judge:
        axes.update(s.keys())
    out: Dict[str, float] = {}
    for ax in sorted(axes):
        vals = [s[ax] for s in scores_per_judge if ax in s]
        if not vals:
            continue
        out[ax] = round(sum(vals) / len(vals), 2)
    return out


def _per_judge_mean(scores_per_judge: List[Dict[str, float]]) -> List[float]:
    """One mean per judge (across the axes that judge reported)."""
    means: List[float] = []
    for s in scores_per_judge:
        vals = list(s.values())
        means.append(round(sum(vals) / max(1, len(vals)), 2) if vals else 0.0)
    return means


def _population_variance(values: List[float]) -> float:
    """Population variance (n divisor). Deterministic + no numpy dep."""
    if not values:
        return 0.0
    mu = sum(values) / len(values)
    return round(sum((v - mu) ** 2 for v in values) / len(values), 4)


def cross_validate_scores(scores_per_judge: List[Dict[str, float]]) -> Dict:
    """Aggregate 3-judge scores; flag escalation when they disagree.

    Args:
        scores_per_judge: list of per-judge score dicts (one dict per
            judge). Each dict maps axis name → float score.

    Returns:
        dict with keys:
          - ``escalate``: True iff the population variance of the
            per-judge means exceeds ``ESCALATE_VARIANCE_THRESHOLD``.
          - ``variance``: the variance computed.
          - ``mean``: per-axis mean across judges.
          - ``per_judge``: the input list, verbatim (so callers can
            keep the audit trail of which judge said what).
          - ``threshold``: the constant used (for downstream rendering).

    The function is pure: no I/O, no clock, no randomness. Same input
    yields same output. Tests pin all four keys + the threshold.
    """
    mean = _mean_axis(scores_per_judge)
    judge_means = _per_judge_mean(scores_per_judge)
    variance = _population_variance(judge_means)
    return {
        "escalate": variance > ESCALATE_VARIANCE_THRESHOLD,
        "variance": variance,
        "mean": mean,
        "per_judge": scores_per_judge,
        "threshold": ESCALATE_VARIANCE_THRESHOLD,
    }
