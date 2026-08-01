"""batch_eval.py — B3 Cross-worktree batch eval (R3 strategy).

When the same `case_id` is run against multiple worktrees (or replayed
across N seeds), the per-dim variance becomes a consistency signal:

    consistency_per_dim = 5 - normalized_variance, clamped to [1, 5]

The normalized variance uses N-1 degrees of freedom (sample variance)
and is compared against a constant scale (4.0) so that variance=1.0
maps to consistency=1.0, variance=0 maps to consistency=5.

Public API:
    batch_eval(task_spec, worktrees) -> dict
        Run `score_all()` against each worktree; per-dim consistency +
        per-worktree reports. Deterministic only (no LLM).
    aggregate_batch(reports) -> dict
        Weighted mean + worst-case across N reports.

Both functions are pure: no global state, no on-disk side effects.
"""
from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any, Dict, List, Mapping

from lib.behavior_scorers import Context, score_all
from lib.behavior_scorers.types import BehaviorReport


def _per_dim_values(reports: List[BehaviorReport]) -> Dict[str, List[int]]:
    """Bucket each dim's value across N reports.

    Missing dims (rare — normally all scorers register) are skipped
    and won't appear in the consistency dict.
    """
    buckets: Dict[str, List[int]] = {}
    for r in reports:
        for s in r.dimension_scores:
            buckets.setdefault(s.dim, []).append(int(s.value))
    return buckets


def _consistency(values: List[int]) -> float:
    """5 - sample variance normalized by scale=2.0, clamped to [1, 5].

    With scale=2.0:
    - variance=0 → consistency=5 (perfect agreement)
    - variance=2 → consistency=4
    - variance=4 → consistency=3
    - variance=8 → consistency=1 (clamped; n=2 values [1,5] hit this)

    Single report (N=1) is treated as vacuously consistent (5.0) —
    variance is undefined for one sample.
    """
    if len(values) <= 1:
        return 5.0
    if len(set(values)) == 1:
        return 5.0
    var = statistics.variance(values)
    score = 5.0 - (var / 2.0)
    return max(1.0, min(5.0, score))


def batch_eval(
    task_spec: Path,
    worktrees: List[Path],
    ctx: Context | None = None,
) -> Dict[str, Any]:
    """Run `score_all()` for each worktree under `task_spec.case_id`.

    Args:
        task_spec: path used solely to derive `case_id` (we use the
            basename stem, e.g. `login-validation.md` → `login-validation`).
        worktrees: list of worktree paths. Empty list raises ValueError.
        ctx: optional scorer Context (defaults to `Context(no_llm=True)`
            for CI-gate reproducibility).

    Returns:
        dict with keys: `case_id`, `n`, `per_worktree` (list of
        BehaviorReport dicts), `consistency` (dim → 1..5 float),
        `mean_consistency` (mean across dims).
    """
    if not worktrees:
        raise ValueError("batch_eval requires at least one worktree")

    case_id = Path(task_spec).stem
    if ctx is None:
        ctx = Context(no_llm=True)

    reports: List[BehaviorReport] = []
    for wt in worktrees:
        report = score_all(Path(wt), case_id=case_id, ctx=ctx)
        reports.append(report)

    dim_buckets = _per_dim_values(reports)
    consistency = {dim: round(_consistency(vals), 3) for dim, vals in dim_buckets.items()}
    mean_consistency = (
        round(sum(consistency.values()) / len(consistency), 3)
        if consistency else 5.0
    )

    return {
        "case_id": case_id,
        "n": len(reports),
        "per_worktree": [r.to_dict() for r in reports],
        "consistency": consistency,
        "mean_consistency": mean_consistency,
    }


def aggregate_batch(
    reports: List[BehaviorReport],
    weights: Mapping[str, float] | None = None,
) -> Dict[str, Any]:
    """Compute weighted mean + worst-case across N BehaviorReports.

    Args:
        reports: list of same-case-id reports.
        weights: optional dim→weight mapping. Defaults to
            `lib.behavior_scorers.WEIGHTS`.

    Returns:
        dict with keys: `n`, `weighted_mean` (mean across reports),
        `min_weighted_mean` (worst-case), `per_dim_mean`,
        `per_dim_min`.
    """
    if not reports:
        raise ValueError("aggregate_batch requires at least one report")

    if weights is None:
        from lib.behavior_scorers import WEIGHTS

        weights = WEIGHTS

    weighted_means: List[float] = []
    per_dim_values: Dict[str, List[int]] = {}
    for r in reports:
        weighted_means.append(r.weighted_mean)
        for s in r.dimension_scores:
            per_dim_values.setdefault(s.dim, []).append(int(s.value))

    return {
        "n": len(reports),
        "weighted_mean": round(sum(weighted_means) / len(weighted_means), 4),
        "min_weighted_mean": round(min(weighted_means), 4),
        "per_dim_mean": {
            dim: round(sum(vals) / len(vals), 3) for dim, vals in per_dim_values.items()
        },
        "per_dim_min": {
            dim: min(vals) for dim, vals in per_dim_values.items()
        },
    }


__all__ = ["batch_eval", "aggregate_batch"]
