"""trajectory.py — D7 Trajectory Quality (hybrid: heuristic + LLM).

Phase 0 ships the heuristic half. Phase 1 (issue #511) adds the
LLM-judge half. The final score is
``round(heuristic_value * 0.7 + llm_value * 0.3)`` when both are
present; with no LLM, the score is just the heuristic value.

Heuristic checks (proposal §01 D7):
- ``same_tool_3x``: same ``skill`` field appearing 3+ times → penalty
- ``read_before_edit_missing``: no ``Read`` tool calls before ``Edit``
  tool calls → penalty (agent may be writing without context)
- ``backtrack > 2``: 3+ "backtrack" patterns (judged by repeated
  identical ``phase`` strings in close succession) → penalty

Score mapping:
- 5: 0 penalties
- 4: 1 penalty
- 3: 2 penalties
- 1-2: 3 penalties (catastrophic loop)

LLM judge (Phase 1) reads the trajectory + heuristic evidence and
returns 4 axes (tool_selection, sequence_logic, branching_minimal,
convergence), each 1-5. The LLM value is ``round(mean(axes))``
clamped to 1..5. The combined value uses the 0.7/0.3 weights.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import llm_judge

from lib.behavior_scorers.types import Context, DimensionScore

PROMPT_NAME = "judge-trajectory"
_DIM = "trajectory"
_HEURISTIC_WEIGHT = 0.7
_LLM_WEIGHT = 0.3

# Judge prompts ship with the dev-harness-kit repo at <repo>/eval/prompts/.
# A worktree (the agent's working dir) does NOT carry them; resolve
# PROJECT_ROOT from this module's location so tests + real runs agree.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_latest_trace(worktree: Path) -> Dict[str, Any] | None:
    """Load the most recent trace JSON under `eval/transcripts/`."""
    transcripts = worktree / "eval" / "transcripts"
    if not transcripts.is_dir():
        return None
    case_dirs = [p for p in transcripts.iterdir() if p.is_dir()]
    if not case_dirs:
        return None
    latest_dir = max(case_dirs, key=lambda d: d.stat().st_mtime)
    traces = sorted(latest_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not traces:
        return None
    try:
        return json.loads(traces[-1].read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _heuristic(trace: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the three heuristic checks to a trace dict."""
    steps: List[Dict[str, Any]] = trace.get("steps", [])

    skill_counts = Counter(s.get("skill", "") for s in steps)
    same_tool_3x = sum(1 for c in skill_counts.values() if c >= 3)

    # Read-before-edit: simple proxy on the 'extra' field which carries
    # tool-specific metadata. Scorers that populate `extra.tool` set
    # the tool name; absent entries count as no-evidence.
    def _tools(s: Dict[str, Any]) -> List[str]:
        extra = s.get("extra") or {}
        tool = extra.get("tool")
        if isinstance(tool, str):
            return [tool]
        if isinstance(tool, list):
            return [str(t) for t in tool]
        return []

    tools_in_order: List[str] = []
    for s in steps:
        tools_in_order.extend(_tools(s))
    saw_read = any("Read" in t or "read" in t for t in tools_in_order)
    saw_edit = any("Edit" in t or "edit" in t or "Write" in t for t in tools_in_order)
    read_before_edit_missing = saw_edit and not saw_read

    # Backtrack detection: 3+ consecutive identical phase values.
    backtrack = 0
    prev = None
    run = 0
    for s in steps:
        phase = s.get("phase", "")
        if phase == prev:
            run += 1
        else:
            run = 1
            prev = phase
        if run >= 3:
            backtrack = max(backtrack, run)

    backtrack_too_many = backtrack >= 3

    penalties = sum(
        1 for v in (bool(same_tool_3x), read_before_edit_missing, backtrack_too_many) if v
    )
    return {
        "skill_counts": dict(skill_counts),
        "same_tool_3x_count": same_tool_3x,
        "read_before_edit_missing": read_before_edit_missing,
        "backtrack_max_run": backtrack,
        "backtrack_too_many": backtrack_too_many,
        "penalties": penalties,
    }


def _heuristic_value(penalties: int) -> int:
    """Map heuristic penalty count to a 1-5 value."""
    if penalties == 0:
        return 5
    if penalties == 1:
        return 4
    if penalties == 2:
        return 3
    return 1


def _clamp(value: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(round(value))))


def _format_prompt(worktree: Path, trace: Dict[str, Any], h: Dict[str, Any]) -> str:
    """Build the judge prompt from the template + substitutions.

    The template lives in the dev-harness-kit repo, not the worktree;
    resolve PROJECT_ROOT from the module location.
    """
    substitutions = {
        "case_id": trace.get("case_id", ""),
        "steps_json": json.dumps(trace.get("steps", []), indent=2),
        "heuristic_json": json.dumps(h, indent=2),
    }
    return llm_judge.format_prompt(PROJECT_ROOT, PROMPT_NAME, substitutions)


def _llm_value(result: Dict[str, Any]) -> int:
    """Compute the LLM dim value from a judge result dict.

    Returns the rounded mean of axes clamped to 1..5. Returns 3 when
    the judge produced no parseable scores — matches the deterministic
    fallback so the combined score is dominated by the heuristic.
    """
    scores = result.get("scores") if isinstance(result, dict) else None
    if not scores:
        return 3
    mean = sum(scores.values()) / max(1, len(scores))
    return _clamp(mean, 1, 5)


def score(worktree: Path, ctx: Context) -> DimensionScore:
    """Score D7 from heuristic (always) + LLM judge (when available)."""
    trace = _load_latest_trace(worktree)
    if trace is None:
        return DimensionScore(
            dim="D7_trajectory",
            value=3,
            evidence={"reason": "no trace available", "phase": 1},
        )

    h = _heuristic(trace)
    penalties = h["penalties"]
    heuristic_value = _heuristic_value(penalties)
    evidence: Dict[str, Any] = {
        **h,
        "phase": 1,
        "heuristic_value": heuristic_value,
    }

    # Deterministic-only path: return the heuristic as-is. The aggregate
    # still counts D7 (it is a deterministic dim only when no LLM runs).
    if ctx.is_deterministic_only() or ctx.llm_judge is None:
        evidence["no_llm"] = True
        evidence["value"] = heuristic_value
        return DimensionScore(dim="D7_trajectory", value=heuristic_value, evidence=evidence)

    prompt = _format_prompt(worktree, trace, h)
    if not prompt:
        evidence["status"] = "prompt_empty"
        evidence["value"] = heuristic_value
        return DimensionScore(dim="D7_trajectory", value=heuristic_value, evidence=evidence)

    axes = llm_judge.DIM_AXES[_DIM]
    try:
        result = ctx.llm_judge(prompt=prompt, axes=axes, dim=_DIM)
    except Exception as exc:  # noqa: BLE001 — never let one dim break the run
        evidence["status"] = "judge_error"
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        evidence["value"] = heuristic_value
        return DimensionScore(dim="D7_trajectory", value=heuristic_value, evidence=evidence)

    llm_v = _llm_value(result)
    combined = heuristic_value * _HEURISTIC_WEIGHT + llm_v * _LLM_WEIGHT
    value = _clamp(combined, 1, 5)

    scores = result.get("scores") if isinstance(result, dict) else {}
    evidence["llm_value"] = llm_v
    evidence["combined_raw"] = round(combined, 4)
    evidence["llm_axes"] = {
        k: (int(v) if (isinstance(v, float) and v.is_integer()) else v)
        for k, v in (scores or {}).items()
    }
    evidence["tokens_in"] = result.get("tokens_in", 0) if isinstance(result, dict) else 0
    evidence["tokens_out"] = result.get("tokens_out", 0) if isinstance(result, dict) else 0
    evidence["value"] = value

    return DimensionScore(dim="D7_trajectory", value=value, evidence=evidence)
