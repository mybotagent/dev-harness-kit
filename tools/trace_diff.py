"""trace_diff.py — compare two TraceLog JSON files.

Usage:
    python -m tools.trace_diff baseline.json current.json
    python -m tools.trace_diff --threshold 0.5 baseline.json current.json

Reads two TraceLog JSON files (schema v1), aggregates metrics from
each (step count, retries, tokens, latency), and emits a per-axis
score delta alongside an aggregate verdict.

Exit code:
    0  — within threshold OR verdict unchanged
    1  — threshold breach OR verdict dropped

The thresholds are tunable via `--threshold`. The default matches
proposal §02 "Diff 도구" rules:
    retry_count_delta   > 2
    token_ratio_delta   > 0.5  (50% increase)
    latency_ratio_delta > 0.5
    per_axis_score_drop > 1
    verdict_drop        (OK -> DRIFT/ROT/ESCALATED)

Stdlib only — no new deps.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

# Insert repo root for lib import when run as `python -m tools.trace_diff`.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.behavior_scorers.efficiency import compute_metrics  # noqa: E402


@dataclass(frozen=True)
class Delta:
    name: str
    baseline: int
    current: int
    ratio: float  # current / baseline, 1.0 if baseline == 0 and current == 0
    absolute_delta: int

    def render(self) -> str:
        sign = "+" if self.absolute_delta >= 0 else ""
        ratio_str = "inf" if self.ratio == float("inf") else f"{self.ratio:.2f}"
        return (
            f"{self.name:<14} {self.baseline:>6} -> {self.current:<6} "
            f"({sign}{self.absolute_delta}, ratio={ratio_str})"
        )


def _safe_ratio(base: int, cur: int) -> float:
    if base == 0:
        return 1.0 if cur == 0 else float("inf")
    return cur / base


def compute_deltas(baseline: Dict[str, int], current: Dict[str, int]) -> Tuple[Delta, ...]:
    """Return per-metric deltas in a stable order."""
    keys = ("step_count", "retry_total", "token_total", "latency_total_ms")
    out = []
    for k in keys:
        b = baseline.get(k, 0)
        c = current.get(k, 0)
        out.append(Delta(
            name=k,
            baseline=b,
            current=c,
            ratio=_safe_ratio(b, c),
            absolute_delta=c - b,
        ))
    return tuple(out)


def _score_axis_deltas(baseline: Dict[str, Any], current: Dict[str, Any]) -> Tuple[Tuple[str, int, int], ...]:
    """Extract (dim, base_score, cur_score) tuples from two judge_scores blocks."""
    out = []
    base_scores = baseline.get("judge_scores") or [{}]
    cur_scores = current.get("judge_scores") or [{}]
    base_axes = (base_scores[0] or {}).get("axes", {}) if base_scores else {}
    cur_axes = (cur_scores[0] or {}).get("axes", {}) if cur_scores else {}
    for dim in sorted(set(base_axes) | set(cur_axes)):
        out.append((dim, base_axes.get(dim, 0), cur_axes.get(dim, 0)))
    return tuple(out)


def _verdict_drop(base: Dict[str, Any], cur: Dict[str, Any]) -> bool:
    base_v = ((base.get("judge_scores") or [{}])[0] or {}).get("verdict", "")
    cur_v = ((cur.get("judge_scores") or [{}])[0] or {}).get("verdict", "")
    order = {"OK": 4, "DRIFT_WARNING": 3, "ROT": 2, "ESCALATED": 1}
    return order.get(cur_v, 0) < order.get(base_v, 0)


@dataclass(frozen=True)
class ThresholdBreach:
    rule: str
    detail: str


def _axis_dropped(b: int, c: int) -> bool:
    """True when an axis score dropped by more than 1 (both ends valid)."""
    return b > 0 and c > 0 and (b - c) > 1


def check_thresholds(
    deltas: Tuple[Delta, ...],
    axis_deltas: Tuple[Tuple[str, int, int], ...],
    verdict_dropped: bool,
    threshold: float,
) -> Tuple[ThresholdBreach, ...]:
    """Return all threshold breaches (zero or more)."""
    breaches = []
    for d in deltas:
        if d.name == "retry_total" and d.absolute_delta > 2:
            breaches.append(ThresholdBreach(
                "retry_total_delta>2",
                f"retry_total delta={d.absolute_delta:+d}",
            ))
        if d.name == "token_total" and d.ratio != float("inf") and d.ratio > 1 + threshold:
            breaches.append(ThresholdBreach(
                f"token_ratio_delta>{threshold}",
                f"token_total ratio={d.ratio:.2f}",
            ))
        if d.name == "latency_total_ms" and d.ratio != float("inf") and d.ratio > 1 + threshold:
            breaches.append(ThresholdBreach(
                f"latency_ratio_delta>{threshold}",
                f"latency_total_ms ratio={d.ratio:.2f}",
            ))
    for dim, b, c in axis_deltas:
        if _axis_dropped(b, c):
            breaches.append(ThresholdBreach(
                "axis_score_drop>1",
                f"{dim}: {b} -> {c}",
            ))
    if verdict_dropped:
        breaches.append(ThresholdBreach(
            "verdict_drop",
            "verdict moved to a worse tier",
        ))
    return tuple(breaches)


def render_report(
    baseline_path: Path,
    current_path: Path,
    deltas: Tuple[Delta, ...],
    axis_deltas: Tuple[Tuple[str, int, int], ...],
    breaches: Tuple[ThresholdBreach, ...],
    verdict_dropped: bool,
    threshold: float,
) -> str:
    lines = [
        f"Trace diff: {baseline_path} -> {current_path}",
        "─" * 50,
    ]
    for d in deltas:
        lines.append(d.render())
    lines.append("─" * 50)
    if axis_deltas:
        lines.append("Per-axis score delta:")
        for dim, b, c in axis_deltas:
            marker = " ⚠️" if _axis_dropped(b, c) else ""
            lines.append(f"  {dim:<22} {b:>2} -> {c:<2}{marker}")
        lines.append("─" * 50)
    if breaches:
        lines.append(f"Threshold ({threshold:.0%}) breaches:")
        for b in breaches:
            lines.append(f"  ⚠️  {b.rule}: {b.detail}")
    else:
        lines.append("No threshold breaches.")
    lines.append("─" * 50)
    if verdict_dropped:
        lines.append("Verdict: DROPPED ⚠️")
    else:
        lines.append("Verdict: stable")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.trace_diff",
        description="Compare two TraceLog JSON files",
    )
    parser.add_argument("baseline", type=Path, help="baseline trace JSON")
    parser.add_argument("current", type=Path, help="current trace JSON")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="ratio delta threshold (default 0.5 = 50%%)",
    )
    args = parser.parse_args(argv)

    if not args.baseline.is_file():
        print(f"error: baseline not found: {args.baseline}", file=sys.stderr)
        return 1
    if not args.current.is_file():
        print(f"error: current not found: {args.current}", file=sys.stderr)
        return 1

    baseline_raw = json.loads(args.baseline.read_text())
    current_raw = json.loads(args.current.read_text())

    baseline_metrics = compute_metrics(args.baseline)
    current_metrics = compute_metrics(args.current)
    deltas = compute_deltas(baseline_metrics, current_metrics)

    axis_deltas = _score_axis_deltas(baseline_raw, current_raw)
    verdict_dropped = _verdict_drop(baseline_raw, current_raw)
    breaches = check_thresholds(deltas, axis_deltas, verdict_dropped, args.threshold)

    print(render_report(
        args.baseline, args.current,
        deltas, axis_deltas, breaches,
        verdict_dropped, args.threshold,
    ))
    return 1 if breaches else 0


if __name__ == "__main__":
    sys.exit(main())
