"""replay_regression.py — replay N golden cases vs baseline, exit on regression.

Usage:
    python -m tools.replay_regression <golden_dir>
    python -m tools.replay_regression <golden_dir> --threshold 0.5
    python -m tools.replay_regression <golden_dir> --md-comment

Expects the layout::

    <golden_dir>/<case_id>/baseline.json
    <golden_dir>/<case_id>/current.json

Each pair is a TraceLog v1 JSON (`lib.trace_log.SCHEMA_VERSION == 1`). For
every case the tool reuses `tools/trace_diff` primitives to compute deltas
+ threshold breaches, then aggregates a per-case `CaseResult` record.

Exit codes:
    0  — all cases clean (no threshold breach, no verdict drop, no error)
    1  — at least one case regressed OR at least one case errored
    2  — usage error (missing arg, non-directory golden_dir, bad threshold)

Stdlib only — no new deps.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Insert repo root for lib/tools import when run as `python -m tools.replay_regression`.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.behavior_scorers.efficiency import compute_metrics  # noqa: E402
from tools.trace_diff import (  # noqa: E402
    Delta,
    ThresholdBreach,
    _score_axis_deltas,
    _verdict_drop,
    check_thresholds,
    compute_deltas,
)


@dataclass(frozen=True)
class CaseResult:
    """Outcome of replaying one golden case (baseline vs current).

    A case is "clean" iff `error is None and len(breaches) == 0`.
    Any non-empty `error` or `breaches` flag the case as a regression.
    """

    case_id: str
    baseline_path: Path
    current_path: Path
    deltas: Tuple[Delta, ...]
    axis_deltas: Tuple[Tuple[str, int, int], ...]
    breaches: Tuple[ThresholdBreach, ...]
    verdict_dropped: bool
    error: Optional[str] = None

    @property
    def is_clean(self) -> bool:
        return self.error is None and not self.breaches


@dataclass(frozen=True)
class ReplaySummary:
    """Aggregate of all per-case results."""

    golden_dir: Path
    threshold: float
    cases: Tuple[CaseResult, ...]

    @property
    def clean_count(self) -> int:
        return sum(1 for c in self.cases if c.is_clean)

    @property
    def regressed_count(self) -> int:
        return sum(1 for c in self.cases if not c.is_clean)


def _resolve_case_dir(name: str, golden_dir: Path) -> Path:
    return golden_dir / name


def _safe_load_trace(path: Path) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """Load a trace JSON + metrics, refusing symlinks.

    Mirrors `compute_metrics()`'s guard: a worktree-controlled symlink
    can redirect reads to attacker-chosen JSON. Real files only. Any
    I/O / parse failure surfaces as a short error string (no leakage
    of stack traces into the replay report).
    """
    if path.is_symlink():
        raise ValueError(f"refusing to follow symlink: {path}")
    raw = json.loads(path.read_text())
    metrics = compute_metrics(path)  # also raises ValueError on symlink
    return raw, metrics


def _replay_case(case_dir: Path, threshold: float) -> CaseResult:
    """Replay one case dir; populates error on any failure."""
    case_id = case_dir.name
    baseline = case_dir / "baseline.json"
    current = case_dir / "current.json"

    if not baseline.is_file():
        return CaseResult(
            case_id=case_id, baseline_path=baseline, current_path=current,
            deltas=(), axis_deltas=(), breaches=(), verdict_dropped=False,
            error="missing baseline.json",
        )
    if not current.is_file():
        return CaseResult(
            case_id=case_id, baseline_path=baseline, current_path=current,
            deltas=(), axis_deltas=(), breaches=(), verdict_dropped=False,
            error="missing current.json",
        )

    try:
        baseline_raw, baseline_metrics = _safe_load_trace(baseline)
        current_raw, current_metrics = _safe_load_trace(current)
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        return CaseResult(
            case_id=case_id, baseline_path=baseline, current_path=current,
            deltas=(), axis_deltas=(), breaches=(), verdict_dropped=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    deltas = compute_deltas(baseline_metrics, current_metrics)
    axis_deltas = _score_axis_deltas(baseline_raw, current_raw)
    verdict_dropped = _verdict_drop(baseline_raw, current_raw)
    breaches = check_thresholds(deltas, axis_deltas, verdict_dropped, threshold)
    return CaseResult(
        case_id=case_id, baseline_path=baseline, current_path=current,
        deltas=deltas, axis_deltas=axis_deltas, breaches=breaches,
        verdict_dropped=verdict_dropped,
    )


def replay_directory(golden_dir: Path, threshold: float) -> ReplaySummary:
    """Replay every case subdir under `golden_dir` (sorted).

    Non-directory entries (loose files at the top level) are ignored —
    the contract says cases are subdirectories.
    """
    case_dirs = sorted(p for p in golden_dir.iterdir() if p.is_dir())
    cases = tuple(_replay_case(d, threshold) for d in case_dirs)
    return ReplaySummary(golden_dir=golden_dir, threshold=threshold, cases=cases)


def _verdict_for(raw: Dict[str, Any]) -> str:
    scores = raw.get("judge_scores") or [{}]
    return (scores[0] or {}).get("verdict", "")


def render_plain(summary: ReplaySummary) -> str:
    """Plain-text table summary suitable for terminal output."""
    lines = [
        f"Replay regression: {summary.golden_dir}",
        f"Threshold: {summary.threshold:.0%}",
        f"Cases: {len(summary.cases)} clean={summary.clean_count} regressed={summary.regressed_count}",
        "─" * 60,
    ]
    header = f"{'case_id':<22} {'verdict':<14} {'breaches':<9} {'error'}"
    lines.append(header)
    lines.append("─" * 60)
    for c in summary.cases:
        verdict_col = "ERR" if c.error else ("DROPPED" if c.verdict_dropped else "ok")
        breach_col = str(len(c.breaches))
        error_col = c.error or ""
        lines.append(f"{c.case_id:<22} {verdict_col:<14} {breach_col:<9} {error_col}")
    lines.append("─" * 60)
    for c in summary.cases:
        if not c.deltas:
            continue
        lines.append(f"[{c.case_id}] deltas:")
        for d in c.deltas:
            lines.append(f"  {d.render()}")
    for c in summary.cases:
        if not c.breaches:
            continue
        lines.append(f"[{c.case_id}] breaches:")
        for b in c.breaches:
            lines.append(f"  - {b.rule}: {b.detail}")
    return "\n".join(lines)


def render_markdown(summary: ReplaySummary) -> str:
    """GitHub-comment-ready markdown (table + breach details)."""
    lines = [
        f"## Replay regression — `{summary.golden_dir.name}`",
        "",
        f"- Threshold: `{summary.threshold:.0%}`",
        f"- Cases: **{len(summary.cases)}** "
        f"(clean: {summary.clean_count}, regressed: {summary.regressed_count})",
        "",
        "| Case | Baseline | Current | Verdict | Breaches |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in summary.cases:
        baseline_v = ""
        current_v = ""
        try:
            raw_base = json.loads(c.baseline_path.read_text()) if c.baseline_path.is_file() else {}
            raw_cur = json.loads(c.current_path.read_text()) if c.current_path.is_file() else {}
            baseline_v = _verdict_for(raw_base) or "-"
            current_v = _verdict_for(raw_cur) or "-"
        except (OSError, json.JSONDecodeError):
            baseline_v = "-"
            current_v = "-"
        status = "OK" if c.is_clean else "REGRESSED"
        breaches = "; ".join(f"{b.rule}" for b in c.breaches) or "-"
        if c.error:
            breaches = f"`error: {c.error}`"
        verdict_marker = " (DROPPED)" if c.verdict_dropped else ""
        lines.append(
            f"| `{c.case_id}` | {baseline_v} | {current_v}{verdict_marker} | "
            f"{status} | {breaches} |"
        )
    lines.append("")

    regressed = [c for c in summary.cases if not c.is_clean]
    if regressed:
        lines.append("### Breach details")
        lines.append("")
        for c in regressed:
            lines.append(f"- **`{c.case_id}`**")
            if c.error:
                lines.append(f"  - error: `{c.error}`")
            if c.verdict_dropped:
                lines.append("  - verdict dropped (worse tier)")
            for b in c.breaches:
                lines.append(f"  - `{b.rule}` — {b.detail}")
        lines.append("")
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.replay_regression",
        description="Replay N golden-case (baseline, current) pairs and detect regressions.",
    )
    parser.add_argument(
        "golden_dir", type=Path,
        help="Directory containing case subdirs each with baseline.json + current.json",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.5,
        help="ratio delta threshold (default 0.5 = 50%%)",
    )
    parser.add_argument(
        "--md-comment", action="store_true",
        help="render GitHub-comment-ready markdown instead of plain text",
    )
    args = parser.parse_args(argv)

    if not args.golden_dir.is_dir():
        print(f"error: golden_dir not found: {args.golden_dir}", file=sys.stderr)
        return 2
    if args.threshold < 0:
        print("error: --threshold must be >= 0", file=sys.stderr)
        return 2

    summary = replay_directory(args.golden_dir, args.threshold)
    output = render_markdown(summary) if args.md_comment else render_plain(summary)
    print(output)
    if summary.regressed_count:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
