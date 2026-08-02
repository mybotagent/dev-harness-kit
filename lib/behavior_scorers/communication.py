"""communication.py — D5 Communication Quality (LLM judge).

Phase 1 wires the LLM judge. The judge prompt at
``eval/prompts/judge-communication.md`` receives the hand-off notes,
PR description, and last 10 commit messages, and must return five
1-5 axis scores (clarity, completeness, actionability, verifiability,
conciseness). The dim value is ``round(mean(axes))`` clamped to 1..5.

When ``ctx.is_deterministic_only()`` is true (no LLM available, or
``no_llm=True``) the scorer returns the Phase 0 placeholder
``value=3, evidence={"phase":0, "no_llm": True}`` so the registry
stays deterministic in CI.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List

import llm_judge

from lib.behavior_scorers.types import Context, DimensionScore

PROMPT_NAME = "judge-communication"
PROMPT_KEYS = ("hand_off", "pr_description", "commit_messages")
_DIM = "communication"

# The dev-harness-kit repo ships its judge prompts at <repo>/eval/prompts/.
# A worktree (the agent's working dir) does NOT carry those prompts; the
# scorers look them up relative to this module's location so test fixtures
# and real runs both work without an extra `project_root` plumb-through.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_handoff_notes(worktree: Path) -> str:
    """Join every `.dev-kit/hand-off/*.md` file in sorted order.

    Missing dir or empty list → empty string. The judge still scores
    based on the other two inputs.
    """
    handoff_dir = worktree / ".dev-kit" / "hand-off"
    if not handoff_dir.is_dir():
        return ""
    files = sorted(p for p in handoff_dir.glob("*.md") if p.is_file())
    if not files:
        return ""
    chunks: List[str] = []
    for p in files:
        try:
            chunks.append(
                f"## {p.name}\n\n{p.read_text(encoding='utf-8', errors='replace')}"
            )
        except OSError:
            continue
    return "\n\n".join(chunks)


def _read_pr_description(worktree: Path) -> str:
    """Read the latest commit's message body via ``git log -1 --format=%b``.

    Returns "" when the worktree is not a git repo or git fails. The
    PR-description slot is optional in the judge prompt; empty is OK.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(worktree), "log", "-1", "--format=%b"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    return (proc.stdout or "").strip()


def _read_commit_messages(worktree: Path, n: int = 10) -> str:
    """Return the last ``n`` commit messages, joined by newlines.

    Empty string when git fails or there are no commits.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(worktree), "log", f"-{n}", "--format=%s%n%b"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    return (proc.stdout or "").strip()


def _clamp(value: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(round(value))))


def _format_axes_for_evidence(raw_axes: Dict[str, float]) -> Dict[str, Any]:
    """Coerce LLM judge axes into JSON-friendly types for evidence.

    parse_scores_json returns floats; the judge's system prompt asks
    for integers 1-5 but the parser accepts anything 0-10. Cast to
    int when the value is integral, leave as float otherwise.
    """
    out: Dict[str, Any] = {}
    for k, v in raw_axes.items():
        if isinstance(v, float) and v.is_integer():
            out[k] = int(v)
        else:
            out[k] = v
    return out


def _format_prompt(worktree: Path) -> str:
    """Build the judge prompt from the template + substitutions.

    Lifted out of score() so tests can exercise the template path
    without touching ctx.llm_judge. The template lives in the
    dev-harness-kit repo (not the agent's worktree), so we resolve
    ``PROJECT_ROOT`` from the module location.
    """
    substitutions = {
        "hand_off": _read_handoff_notes(worktree) or "(no hand-off notes)",
        "pr_description": _read_pr_description(worktree) or "(no PR description)",
        "commit_messages": _read_commit_messages(worktree, n=10) or "(no commits)",
    }
    return llm_judge.format_prompt(PROJECT_ROOT, PROMPT_NAME, substitutions)


def score(worktree: Path, ctx: Context) -> DimensionScore:
    """Return the D5 Communication Quality score.

    Deterministic-only path: placeholder ``value=3`` with
    ``evidence={"phase": 0, "no_llm": True}``.

    Full LLM path: format the prompt, call ``ctx.llm_judge(prompt,
    axes, dim)``, round the axis mean to an integer clamped to 1..5.
    """
    if ctx.is_deterministic_only() or ctx.llm_judge is None:
        return DimensionScore(
            dim="D5_communication",
            value=3,
            evidence={
                "status": "pending",
                "phase": 0,
                "no_llm": True,
                "reason": "deterministic-only path; LLM judge wiring is a no-op",
            },
        )

    prompt = _format_prompt(worktree)
    if not prompt:
        return DimensionScore(
            dim="D5_communication",
            value=3,
            evidence={
                "phase": 1,
                "status": "prompt_empty",
                "reason": "format_prompt returned empty (template missing?)",
            },
        )

    axes = llm_judge.DIM_AXES[_DIM]
    try:
        result = ctx.llm_judge(prompt=prompt, axes=axes, dim=_DIM)
    except Exception as exc:  # noqa: BLE001 — never let one dim break the run
        return DimensionScore(
            dim="D5_communication",
            value=3,
            evidence={
                "phase": 1,
                "status": "judge_error",
                "error": f"{type(exc).__name__}: {exc}",
            },
        )

    scores = result.get("scores") if isinstance(result, dict) else None
    if not scores:
        return DimensionScore(
            dim="D5_communication",
            value=3,
            evidence={
                "phase": 1,
                "status": "no_scores",
                "raw": (result.get("raw", "") if isinstance(result, dict) else "")[:500],
            },
        )

    mean = sum(scores.values()) / max(1, len(scores))
    value = _clamp(mean, 1, 5)

    return DimensionScore(
        dim="D5_communication",
        value=value,
        evidence={
            "phase": 1,
            "axes": _format_axes_for_evidence(scores),
            "tokens_in": result.get("tokens_in", 0),
            "tokens_out": result.get("tokens_out", 0),
        },
    )
