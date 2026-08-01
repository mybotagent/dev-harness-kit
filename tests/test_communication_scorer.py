"""test_communication_scorer.py — Phase 1 D5 Communication Quality tests.

Covers:
- deterministic_only path returns the placeholder (value=3, phase=0)
- llm_judge not configured falls back to the same placeholder
- LLM invocation is wired through ctx.llm_judge(prompt, axes, dim)
- axis parsing produces the rounded mean clamped to 1..5
- hand-off / commit / PR-description inputs are substituted into the prompt
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import llm_judge  # noqa: E402

from lib.behavior_scorers.communication import (  # noqa: E402
    PROMPT_NAME,
    _clamp,
    _format_axes_for_evidence,
    _format_prompt,
    _read_commit_messages,
    _read_handoff_notes,
    _read_pr_description,
    score,
)
from lib.behavior_scorers.types import Context, DimensionScore  # noqa: E402

# ----- helpers -----

def _make_worktree(tmp_path: Path, *, with_handoff: bool = False) -> Path:
    """Create a minimal worktree dir with optional hand-off files."""
    wt = tmp_path / "wt"
    wt.mkdir()
    if with_handoff:
        handoff = wt / ".dev-kit" / "hand-off"
        handoff.mkdir(parents=True)
        (handoff / "01-plan.md").write_text("Plan: do the thing.\n")
        (handoff / "02-result.md").write_text("Result: did the thing.\n")
    return wt


# ----- deterministic-only path -----

def test_deterministic_only_returns_placeholder(tmp_path: Path) -> None:
    """ctx.no_llm=True → value=3, evidence.phase=0."""
    wt = _make_worktree(tmp_path, with_handoff=True)
    ds = score(wt, Context(no_llm=True))
    assert isinstance(ds, DimensionScore)
    assert ds.dim == "D5_communication"
    assert ds.value == 3
    assert ds.evidence["phase"] == 0
    assert ds.evidence["no_llm"] is True


def test_no_llm_judge_callable_returns_placeholder(tmp_path: Path) -> None:
    """ctx.llm_judge=None (default Context) → placeholder path."""
    wt = _make_worktree(tmp_path)
    ds = score(wt, Context())  # llm_judge defaults to None
    assert ds.value == 3
    assert ds.evidence["no_llm"] is True


# ----- LLM invocation path -----

def test_llm_judge_called_with_axes_and_dim(tmp_path: Path) -> None:
    """When ctx.llm_judge is set, score() invokes it with axes=communication."""
    wt = _make_worktree(tmp_path, with_handoff=True)
    mock = MagicMock(return_value={
        "scores": {"clarity": 5, "completeness": 4, "actionability": 3,
                    "verifiability": 4, "conciseness": 4},
        "tokens_in": 100,
        "tokens_out": 50,
        "raw": "",
    })
    ctx = Context(llm_judge=mock)
    ds = score(wt, ctx)

    # The judge was called exactly once with axes=communication and dim.
    mock.assert_called_once()
    _, kwargs = mock.call_args
    assert kwargs["axes"] == llm_judge.DIM_AXES["communication"]
    assert kwargs["dim"] == "communication"
    # The prompt is a non-empty string with the substitutions applied.
    assert isinstance(kwargs["prompt"], str)
    assert "Plan: do the thing." in kwargs["prompt"]
    # Axes mean = (5+4+3+4+4)/5 = 4 → dim value 4.
    assert ds.value == 4
    assert ds.evidence["phase"] == 1


def test_axis_mean_is_rounded_and_clamped(tmp_path: Path) -> None:
    """Mean → round → clamp(1..5)."""
    wt = _make_worktree(tmp_path)
    mock = MagicMock(return_value={
        "scores": {"clarity": 1, "completeness": 1, "actionability": 1,
                    "verifiability": 1, "conciseness": 1},
        "tokens_in": 0, "tokens_out": 0, "raw": "",
    })
    ds = score(wt, Context(llm_judge=mock))
    assert ds.value == 1

    mock.return_value["scores"] = {"clarity": 5, "completeness": 5,
                                    "actionability": 5, "verifiability": 5,
                                    "conciseness": 5}
    ds = score(wt, Context(llm_judge=mock))
    assert ds.value == 5


def test_missing_template_returns_placeholder(tmp_path: Path) -> None:
    """When the prompt template is missing, return value=3 (graceful)."""
    wt = _make_worktree(tmp_path)
    # Patch format_prompt to return empty so the scorer hits the
    # prompt_empty branch. The prompts live in the dev-harness-kit
    # repo (PROJECT_ROOT), so deleting files in the test worktree
    # has no effect.
    from unittest.mock import patch

    import lib.behavior_scorers.communication as comm_mod

    with patch.object(comm_mod.llm_judge, "format_prompt", return_value=""):
        mock = MagicMock()
        ds = score(wt, Context(llm_judge=mock))
    assert ds.value == 3
    assert ds.evidence["status"] == "prompt_empty"
    mock.assert_not_called()


def test_judge_exception_returns_placeholder(tmp_path: Path) -> None:
    """Judge raising → value=3 with judge_error evidence (never crashes)."""
    wt = _make_worktree(tmp_path)
    mock = MagicMock(side_effect=RuntimeError("api timeout"))
    ds = score(wt, Context(llm_judge=mock))
    assert ds.value == 3
    assert ds.evidence["status"] == "judge_error"
    assert "api timeout" in ds.evidence["error"]


def test_empty_scores_returns_placeholder(tmp_path: Path) -> None:
    """Judge returns {} → value=3, status=no_scores (don't crash)."""
    wt = _make_worktree(tmp_path)
    mock = MagicMock(return_value={"scores": {}, "tokens_in": 0, "tokens_out": 0, "raw": ""})
    ds = score(wt, Context(llm_judge=mock))
    assert ds.value == 3
    assert ds.evidence["status"] == "no_scores"


# ----- input collection helpers -----

def test_read_handoff_notes_sorted(tmp_path: Path) -> None:
    """Hand-off notes are joined in sorted filename order."""
    wt = _make_worktree(tmp_path)
    handoff = wt / ".dev-kit" / "hand-off"
    handoff.mkdir(parents=True)
    (handoff / "b-second.md").write_text("B")
    (handoff / "a-first.md").write_text("A")
    text = _read_handoff_notes(wt)
    assert text.index("A") < text.index("B")


def test_read_handoff_notes_empty_dir(tmp_path: Path) -> None:
    """No .dev-kit/hand-off dir → empty string."""
    wt = _make_worktree(tmp_path)
    assert _read_handoff_notes(wt) == ""


def test_read_pr_description_handles_no_git(tmp_path: Path) -> None:
    """Non-git worktree → empty PR description (no crash)."""
    wt = _make_worktree(tmp_path)
    assert _read_pr_description(wt) == ""


def test_read_commit_messages_handles_no_git(tmp_path: Path) -> None:
    """Non-git worktree → empty commit messages (no crash)."""
    wt = _make_worktree(tmp_path)
    assert _read_commit_messages(wt, n=10) == ""


# ----- evidence formatting -----

def test_format_axes_for_evidence_casts_integral_floats() -> None:
    """Float axes that are integral get cast to int in evidence."""
    raw = {"clarity": 5.0, "completeness": 4.0}
    out = _format_axes_for_evidence(raw)
    assert out["clarity"] == 5
    assert isinstance(out["clarity"], int)


def test_format_axes_for_evidence_keeps_fractional() -> None:
    """Fractional axes stay float in evidence."""
    raw = {"clarity": 4.5}
    out = _format_axes_for_evidence(raw)
    assert out["clarity"] == 4.5


# ----- clamp helper -----

@pytest.mark.parametrize("value,lo,hi,expected", [
    (3.4, 1, 5, 3),
    (3.5, 1, 5, 4),  # banker's rounding is fine here; we test >=.5 → up
    (5.0, 1, 5, 5),
    (0.0, 1, 5, 1),
    (10.0, 1, 5, 5),
    (-1.0, 1, 5, 1),
])
def test_clamp_helper(value: float, lo: int, hi: int, expected: int) -> None:
    assert _clamp(value, lo, hi) == expected


# ----- format_prompt integration -----

def test_format_prompt_substitutes_keys(tmp_path: Path) -> None:
    """_format_prompt() loads judge-communication.md and substitutes keys."""
    wt = _make_worktree(tmp_path, with_handoff=True)
    prompt = _format_prompt(wt)
    assert isinstance(prompt, str)
    assert "${HAND_OFF}" not in prompt
    assert "${PR_DESCRIPTION}" not in prompt
    assert "${COMMIT_MESSAGES}" not in prompt


def test_prompt_name_constant_matches_template() -> None:
    """PROMPT_NAME points to the existing contract template."""
    assert PROMPT_NAME == "judge-communication"
