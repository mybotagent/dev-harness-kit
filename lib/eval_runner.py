#!/usr/bin/env python3
"""eval_runner.py — Agent-behavior evaluator.

Discovers case fixtures in `eval/cases/{review,security,plan}/*.json`,
replays recorded agent outputs from `eval/transcripts/<dim>/<case>.json`,
runs the per-dim LLM-as-judge prompt, and writes
`.dev-kit/eval-report.md`.

Unit of eval: a case fixture + a recorded agent transcript -> per-dim
axis scores -> verdict. Three dims (review / security / plan) each with
its own axis set (see `llm_judge.DIM_AXES`). No code discovery; no file
freshness. Code-sanity is folded into the review judge via a 20-checkbox
rubric (see `eval/prompts/judge-code-sanity.md`).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
import llm_judge  # type: ignore
from atomic import atomic_write_json, now_iso  # noqa: E402

SUPPORTED_DIMS: tuple = ("review", "security", "plan")
PROMPT_BY_DIM: Dict[str, str] = {
    "review": "judge-review.md",
    "security": "judge-security.md",
    "plan": "judge-plan.md",
}


@dataclass
class CaseResult:
    """One case outcome from run_eval.

    Mutable because _judge_case populates fields incrementally before
    returning; converted to dict at the API boundary via asdict().
    """
    case_id: str = ""
    dim: str = ""
    scores: Dict[str, float] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    raw: str = ""
    verdict: str = ""
    score: float = 0.0
    error: Optional[str] = None


def mock_skipped(case: Dict, axes: tuple) -> CaseResult:
    return CaseResult(
        case_id=case["case_id"], dim=case["dim"],
        scores={ax: 0.0 for ax in axes},
        raw="TRANSCRIPT_MISSING", verdict="SKIPPED", score=0.0,
    )


def mock_drift_warning(case: Dict, axes: tuple) -> CaseResult:
    return CaseResult(
        case_id=case["case_id"], dim=case["dim"],
        scores={ax: 7.0 for ax in axes},
        raw="DRY_RUN", verdict="DRIFT_WARNING", score=7.0,
    )


def real_result(case: Dict, *, scores: Dict[str, float],
                tokens_in: int, tokens_out: int,
                raw: str, verdict: str, score: float) -> CaseResult:
    return CaseResult(
        case_id=case["case_id"], dim=case["dim"],
        scores=scores, tokens_in=tokens_in, tokens_out=tokens_out,
        raw=raw, verdict=verdict, score=score,
    )


def exception_rot(case: Dict, axes: tuple, exc: Exception) -> CaseResult:
    return CaseResult(
        case_id=case["case_id"], dim=case["dim"],
        scores={ax: 0.0 for ax in axes},
        raw=str(exc), verdict="ROT", score=0.0, error=str(exc),
    )


# ---------- discovery ----------

def discover_cases(project_root: Path) -> List[Dict]:
    """Find all evaluable cases in `eval/cases/<dim>/*.json`.

    Returns list of `{case_id, dim, category, input_path, input_inline,
    expected, schema_version, raw_path}` dicts. Skips dim directories
    that don't exist (e.g. a dim not yet seeded).
    """
    cases: List[Dict] = []
    cases_dir = project_root / "eval" / "cases"
    if not cases_dir.exists():
        return cases
    for dim in SUPPORTED_DIMS:
        dim_dir = cases_dir / dim
        if not dim_dir.exists():
            continue
        for case_path in sorted(dim_dir.glob("*.json")):
            try:
                data = json.loads(case_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("dim") not in SUPPORTED_DIMS:
                # Wrong dim or missing dim field; skip.
                continue
            if data.get("dim") != dim:
                # Case lives under one dim dir but claims another; skip.
                continue
            data.setdefault("case_id", case_path.stem)
            data["raw_path"] = str(case_path.relative_to(project_root))
            cases.append(data)
    return cases


# ---------- transcript I/O ----------

def transcript_path(project_root: Path, dim: str, case_id: str) -> Path:
    return project_root / "eval" / "transcripts" / dim / f"{case_id}.json"


def load_transcript(project_root: Path, dim: str, case_id: str) -> Optional[Dict]:
    """Return recorded transcript or None if not present / not parseable."""
    p = transcript_path(project_root, dim, case_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_transcript(project_root: Path, dim: str, case_id: str, data: Dict) -> Path:
    """Atomic write of a transcript. Returns the path written."""
    p = transcript_path(project_root, dim, case_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, data)
    return p


# ---------- judgment ----------

def _judge_case(
    project_root: Path,
    case: Dict,
    transcript: Optional[Dict],
    config: Dict,
) -> CaseResult:
    """Run the per-dim LLM-as-judge on a case. Returns a CaseResult.

    If `transcript` is None, the case is marked as SKIPPED (a setup gap,
    not a regression) with axis scores of 0.0 and verdict "SKIPPED".
    """
    dim = case["dim"]
    axes = llm_judge.DIM_AXES[dim]
    if transcript is None:
        return mock_skipped(case, axes)
    prompt_name = PROMPT_BY_DIM[dim]
    substitutions = {
        "CASE_ID": case.get("case_id", ""),
        "DIM": dim,
        "CATEGORY": case.get("category", ""),
        "INPUT": _read_input(project_root, case),
        "AGENT_OUTPUT": json.dumps(transcript.get("agent_output", {}), indent=2),
        "EXPECTED": json.dumps(case.get("expected", {}), indent=2),
        "RUBRIC": _read_rubric(project_root),
    }
    prompt = llm_judge.format_prompt(project_root, prompt_name, substitutions)
    if not prompt:
        # Fallback inline prompt if the per-dim template is missing.
        prompt = (
            f"You are an eval judge for the {dim} dimension. "
            f"Compare the agent output against the expected behavior and "
            f"return a JSON object with these axes: {list(axes)}. "
            f"Each axis is 0-10. ONLY a JSON object, no prose."
        )
    raw = llm_judge.call_judge(
        provider=config["provider"],
        api_key=config["api_key"],
        model=config["model"],
        prompt=prompt,
        axes=axes,
        base_url=config.get("base_url", "https://api.minimax.io/anthropic"),
    )
    scores = raw.get("scores") or {}
    # Keep only the requested dim's axes (drop any extra fields the model
    # might emit). Missing axes default to 0 so the verdict is well-defined.
    scores = {ax: float(scores.get(ax, 0.0)) for ax in axes}
    score = llm_judge.score_aggregate(scores) if scores else 0.0
    verdict = llm_judge.verdict_from_score(score) if score > 0 else "ROT"
    return real_result(
        case,
        scores=scores,
        tokens_in=raw.get("tokens_in", 0),
        tokens_out=raw.get("tokens_out", 0),
        raw=(raw.get("raw") or "")[:500],
        verdict=verdict,
        score=score,
    )


def _read_input(project_root: Path, case: Dict) -> str:
    """Render the case input. If `input_path` exists, read it; else use
    `input_inline`. Returns a string suitable for embedding in a prompt.
    """
    inline = case.get("input_inline")
    if inline is not None:
        return inline
    rel = case.get("input_path")
    if rel:
        p = project_root / rel
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except OSError:
                return f"(unreadable: {rel})"
        return f"(missing: {rel})"
    return ""


def _read_rubric(project_root: Path) -> str:
    """Return the shared code-sanity rubric prompt body (review dim only
    needs the full rubric; others get a one-liner reminder)."""
    p = project_root / "eval" / "prompts" / "judge-code-sanity.md"
    if not p.exists():
        return "(code-sanity rubric not found)"
    return p.read_text(encoding="utf-8")


# ---------- public API ----------

def judge_case(
    project_root: Path,
    case: Dict,
    transcript: Optional[Dict] = None,
    config: Optional[Dict] = None,
) -> Dict:
    """Score a single case. If `transcript` is None it is loaded from
    `eval/transcripts/<dim>/<case_id>.json`.

    Returns a plain dict (asdict of CaseResult) for backward compatibility
    with callers that subscript into the result.
    """
    if config is None:
        config = llm_judge.load_config(project_root)
    if transcript is None:
        transcript = load_transcript(project_root, case["dim"], case["case_id"])
    return asdict(_judge_case(project_root, case, transcript, config))


# ---------- report ----------

def write_report(
    project_root: Path,
    results: List[Dict],
    config: Optional[Dict] = None,
) -> Path:
    """Write `.dev-kit/eval-report.md` with a per-dim table + verdict counts."""
    path = project_root / ".dev-kit" / "eval-report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = [
        "# Eval Report — agent-behavior (dev-harness-kit)",
        f"> Generated: {now_iso()}",
        f"> Provider: {config.get('provider', 'minimax') if config else 'minimax'}",
        f"> Model: {config.get('model', 'MiniMax-M3[1m]') if config else 'MiniMax-M3[1m]'}",
        "",
        "## Summary",
    ]
    by_verdict: Dict[str, int] = {"OK": 0, "DRIFT_WARNING": 0, "ROT": 0, "SKIPPED": 0}
    for r in results:
        by_verdict[r.get("verdict", "OK")] += 1
    lines.append(f"- Total cases: {len(results)}")
    for v in ("OK", "DRIFT_WARNING", "ROT", "SKIPPED"):
        lines.append(f"- {v}: {by_verdict[v]}")
    lines.append("")
    # Per-dim table.
    lines.append("## Per-Dimension Scores")
    by_dim: Dict[str, List[Dict]] = {d: [] for d in SUPPORTED_DIMS}
    for r in results:
        by_dim.setdefault(r.get("dim", "?"), []).append(r)
    for dim, dim_results in by_dim.items():
        if not dim_results:
            continue
        scored = [r for r in dim_results if r.get("verdict") != "SKIPPED"]
        if not scored:
            lines.append(f"### {dim} (no cases with transcripts)")
            lines.append("")
            continue
        axes = llm_judge.DIM_AXES[dim]
        axis_means: Dict[str, float] = {}
        for ax in axes:
            vals = [r["scores"].get(ax, 0.0) for r in scored]
            axis_means[ax] = round(sum(vals) / max(1, len(vals)), 2)
        overall = round(
            sum(axis_means.values()) / max(1, len(axis_means)), 2
        )
        lines.append(f"### {dim} (n={len(scored)}, overall={overall})")
        lines.append("")
        lines.append("| Axis | Mean |")
        lines.append("|---|---|")
        for ax in axes:
            lines.append(f"| `{ax}` | {axis_means[ax]} |")
        lines.append("")
    # Per-case detail.
    lines.append("## Per-Case Results")
    for r in results:
        verdict = r.get("verdict", "?")
        score = r.get("score", 0)
        case_id = r.get("case_id", "?")
        dim = r.get("dim", "?")
        axes_str = ", ".join(
            f"{ax}={r.get('scores', {}).get(ax, '-')}"
            for ax in llm_judge.DIM_AXES.get(dim, ())
        )
        lines.append(f"- **{verdict}** `{case_id}` (dim={dim}) score={score} ({axes_str})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------- top-level driver ----------

def run_eval(
    project_root: Path,
    config: Optional[Dict] = None,
    *,
    dry_run: bool = False,
    dim: Optional[str] = None,
    case: Optional[str] = None,
) -> Dict:
    """Run the agent-behavior eval.

    Args:
        project_root: project root.
        config: llm_judge config (defaults to load_config()).
        dry_run: skip real LLM calls; mock each case at 7.0/DRIFT_WARNING.
        dim: restrict to one of {review, security, plan}. None = all.
        case: restrict to a single case_id. None = all.
    """
    if config is None:
        config = llm_judge.load_config(project_root)
    if dim is not None and dim not in SUPPORTED_DIMS:
        raise ValueError(
            f"unknown dim={dim!r}; must be one of {SUPPORTED_DIMS}"
        )

    cases = discover_cases(project_root)
    if dim is not None:
        cases = [c for c in cases if c["dim"] == dim]
    if case is not None:
        cases = [c for c in cases if c["case_id"] == case]

    results: List[CaseResult] = []
    if dry_run or not config.get("api_key"):
        # Mock each case at 7.0 / DRIFT_WARNING, except SKIPPED for cases
        # with no transcript (a real setup gap).
        for c in cases:
            t = load_transcript(project_root, c["dim"], c["case_id"])
            if t is None:
                results.append(mock_skipped(c, llm_judge.DIM_AXES[c["dim"]]))
                continue
            results.append(mock_drift_warning(c, llm_judge.DIM_AXES[c["dim"]]))
    else:
        for c in cases:
            t = load_transcript(project_root, c["dim"], c["case_id"])
            try:
                results.append(_judge_case(project_root, c, t, config))
            except Exception as e:
                results.append(exception_rot(c, llm_judge.DIM_AXES[c["dim"]], e))

    results_dicts = [asdict(r) for r in results]
    write_report(project_root, results_dicts, config)
    summary: Dict[str, int] = {v: 0 for v in ("OK", "DRIFT_WARNING", "ROT", "SKIPPED")}
    for r in results:
        summary[r.verdict or "OK"] += 1
    return {
        "results": results_dicts,
        "config": {k: v for k, v in config.items() if k != "api_key"},
        "summary": summary,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run agent-behavior eval")
    parser.add_argument("--project-root", default=".", help="project root")
    parser.add_argument("--dry-run", action="store_true", help="skip LLM calls")
    parser.add_argument(
        "--dim",
        choices=SUPPORTED_DIMS,
        help="restrict to one dimension (default: all)",
    )
    parser.add_argument("--case", help="restrict to a single case_id")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    report = run_eval(
        root,
        dry_run=args.dry_run,
        dim=args.dim,
        case=args.case,
    )
    print(json.dumps(report["summary"], indent=2))
