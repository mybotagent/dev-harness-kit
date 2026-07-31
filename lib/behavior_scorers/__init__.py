"""behavior_scorers — per-dimension scorers for agent behavior evaluation.

Public API:
    DIM_AXES_BEHAVIOR  — tuple of dimension IDs (D1..D7)
    SCORER_REGISTRY    — maps dim_id -> scorer function (Scorer protocol)
    score_all()        — run all registered scorers on a worktree
    DimensionScore     — one dim's score + evidence
    BehaviorReport     — aggregated verdict
    Context            — optional dependencies passed to scorers

Each scorer is a pure function:

    scorer(worktree: Path, ctx: Context) -> DimensionScore

with optional dependencies passed via a `Context` object (used for the
D3 baseline lookup, LLM judge invocation, etc.). This keeps scorers
deterministic where possible and easy to test in isolation.

Phase 0 (issue #511): D1-D4 are deterministic; D5/D6/D7 are placeholders
that return `value=3, evidence={"status": "pending"}`. The full D5/D7
LLM judge wiring lands in Phase 1; D6 scenario fixtures land in Phase 2.
"""
from __future__ import annotations

from typing import Callable, Dict, Mapping

from lib.trace_log import TraceLog

from . import communication, efficiency, outcome, process, robustness, safety, trajectory
from .aggregate import compute as _aggregate_compute
from .aggregate import render_markdown as _render_markdown
from .types import DETERMINISTIC_DIMS, BehaviorReport, Context, DimensionScore

DIM_AXES_BEHAVIOR = (
    "D1_outcome",
    "D2_process",
    "D3_efficiency",
    "D4_safety",
    "D5_communication",
    "D6_robustness",
    "D7_trajectory",
)

# Registry: dim_id -> scorer function. Built at import time so partial
# imports (e.g. while writing a stub) do not break the others.
SCORER_REGISTRY: Dict[str, Callable] = {
    "D1_outcome": outcome.score,
    "D2_process": process.score,
    "D3_efficiency": efficiency.score,
    "D4_safety": safety.score,
    "D5_communication": communication.score,
    "D6_robustness": robustness.score,
    "D7_trajectory": trajectory.score,
}

# Per-dim weights for the weighted-mean aggregate. Must sum to 1.0.
WEIGHTS: Mapping[str, float] = {
    "D1_outcome": 0.30,
    "D2_process": 0.15,
    "D3_efficiency": 0.10,
    "D4_safety": 0.15,
    "D5_communication": 0.10,
    "D6_robustness": 0.10,
    "D7_trajectory": 0.10,
}


def score_all(
    worktree,
    case_id: str,
    ctx=None,
) -> BehaviorReport:
    """Run every registered scorer on `worktree` and aggregate.

    Order matters only for readability of the report; all scorers are
    independent. The aggregated verdict follows the rules in
    `aggregate.compute()`.
    """
    from pathlib import Path

    if ctx is None:
        ctx = Context()
    dim_scores = []
    for dim in DIM_AXES_BEHAVIOR:
        scorer = SCORER_REGISTRY[dim]
        try:
            ds = scorer(Path(worktree), ctx)
        except Exception as exc:  # noqa: BLE001 — never let one dim break the run
            ds = DimensionScore(
                dim=dim,
                value=1,
                evidence={"error": f"{type(exc).__name__}: {exc}"},
            )
        dim_scores.append(ds)
    return _aggregate_compute(
        case_id=case_id,
        worktree=str(worktree),
        dim_scores=tuple(dim_scores),
        weights=WEIGHTS,
    )


def render_report(report: BehaviorReport) -> str:
    """Convenience wrapper for `aggregate.render_markdown`."""
    return _render_markdown(report)


def to_trace_log(
    report: BehaviorReport,
    harness_version: str = "",
    agent: str = "",
    steps=None,
    started_at: str = "",
    ended_at: str = "",
) -> TraceLog:
    """Package a BehaviorReport + run metadata into a TraceLog.

    The caller picks `harness_version` and `agent` (typically from the
    plugin.json helper). `steps` is optional — Phase 1+ scorers will
    populate it.
    """
    from lib.trace_log import now_utc

    return TraceLog(
        case_id=report.case_id,
        started_at=started_at or now_utc(),
        ended_at=ended_at or now_utc(),
        harness_version=harness_version,
        agent=agent,
        worktree_path=report.worktree,
        steps=list(steps or ()),
        judge_scores=[{
            "judge": "rubric:agent-behavior",
            "axes": {s.dim: s.value for s in report.dimension_scores},
            "weighted_mean": report.weighted_mean,
            "deterministic_mean": report.deterministic_mean,
            "verdict": report.verdict,
            "escalate": report.verdict == "ESCALATED",
        }],
        evidence={s.dim: dict(s.evidence) for s in report.dimension_scores},
    )


__all__ = [
    "BehaviorReport",
    "Context",
    "DETERMINISTIC_DIMS",
    "DIM_AXES_BEHAVIOR",
    "DimensionScore",
    "SCORER_REGISTRY",
    "WEIGHTS",
    "render_report",
    "score_all",
    "to_trace_log",
]
