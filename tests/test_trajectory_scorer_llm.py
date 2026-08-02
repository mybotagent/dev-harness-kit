"""test_trajectory_scorer_llm.py — Phase 1 D7 Trajectory Quality LLM half.

Covers:
- heuristic + LLM 0.7/0.3 weighting produces the expected value
- deterministic_only path returns heuristic_value unchanged
- judge errors / empty prompts fall back to heuristic without crashing
- 0 axes (judge returns {}) still produces a value
- trajectory prompt is built from judge-trajectory.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import llm_judge  # noqa: E402

from lib.behavior_scorers.trajectory import (  # noqa: E402
    _HEURISTIC_WEIGHT,
    _LLM_WEIGHT,
    _heuristic_value,
    _llm_value,
    score,
)
from lib.behavior_scorers.types import Context  # noqa: E402

# ----- helpers -----

def _make_trace_worktree(tmp_path: Path, steps: list) -> Path:
    """Create a worktree with a single eval/transcripts/<case>/*.json trace."""
    wt = tmp_path / "wt"
    case = wt / "eval" / "transcripts" / "test-case"
    case.mkdir(parents=True)
    (case / "trace.json").write_text(json.dumps({"steps": steps}))
    return wt


def _steps(*, repeated_skill: str = "", edit_after_read: bool = True,
            long_phase_runs: int = 0, no_read_at_all: bool = False) -> list:
    """Build a minimal trace that drives the heuristic checks.

    Each knob adds exactly one penalty when set:
    - repeated_skill: skill name to repeat 3+ times → same_tool_3x penalty
      (uses distinct phase per step so it does NOT trigger backtrack)
    - edit_after_read=False: forces read_before_edit_missing penalty
      (only when Edit appears without any Read tool call)
    - long_phase_runs: number of "X" phases repeated 3+ times → backtrack penalty
      (uses distinct skill names so it does NOT trigger same_tool_3x)
    - no_read_at_all: drops the Read step so edit_after_read=True still
      triggers read_before_edit_missing. Used for the "all 3 penalties"
      test.
    """
    out = [{"skill": "plan", "phase": "interview", "extra": {}}]
    if not no_read_at_all:
        out.append({"skill": "read", "phase": "read", "extra": {"tool": "Read"}})
    out.append({"skill": "edit", "phase": "edit", "extra": {"tool": "Edit"}})
    if long_phase_runs:
        for i in range(3):
            out.append({"skill": f"loop_skill_{i}", "phase": "X", "extra": {}})
    if repeated_skill:
        # 3 occurrences with DISTINCT phases so no backtrack is triggered.
        for i in range(3):
            out.append({"skill": repeated_skill, "phase": f"repeat_{i}", "extra": {}})
    out.append({"skill": "finish", "phase": "done", "extra": {}})
    return out


# ----- constants -----

def test_weights_sum_to_one() -> None:
    """The 0.7/0.3 weights must sum to 1.0 (no normalization drift)."""
    assert _HEURISTIC_WEIGHT + _LLM_WEIGHT == 1.0
    assert _HEURISTIC_WEIGHT == 0.7
    assert _LLM_WEIGHT == 0.3


def test_heuristic_value_mapping() -> None:
    """0 penalties → 5; 1 → 4; 2 → 3; 3+ → 1."""
    assert _heuristic_value(0) == 5
    assert _heuristic_value(1) == 4
    assert _heuristic_value(2) == 3
    assert _heuristic_value(3) == 1


def test_llm_value_with_scores() -> None:
    """Rounded mean clamped to 1..5."""
    assert _llm_value({"scores": {"tool_selection": 5, "sequence_logic": 5,
                                   "branching_minimal": 5, "convergence": 5}}) == 5
    assert _llm_value({"scores": {"tool_selection": 3, "sequence_logic": 3,
                                   "branching_minimal": 3, "convergence": 3}}) == 3
    assert _llm_value({"scores": {"tool_selection": 1, "sequence_logic": 1,
                                   "branching_minimal": 1, "convergence": 1}}) == 1


def test_llm_value_falls_back_to_three_on_empty() -> None:
    """Empty scores → 3 (matches deterministic placeholder)."""
    assert _llm_value({"scores": {}}) == 3
    assert _llm_value({}) == 3


# ----- deterministic_only path -----

def test_deterministic_only_returns_heuristic_value(tmp_path: Path) -> None:
    """When no LLM, score() returns heuristic_value (5 for clean trace)."""
    wt = _make_trace_worktree(tmp_path, _steps())
    ds = score(wt, Context(no_llm=True))
    assert ds.dim == "D7_trajectory"
    assert ds.value == 5  # 0 penalties
    assert ds.evidence["phase"] == 1
    assert ds.evidence["no_llm"] is True
    assert ds.evidence["heuristic_value"] == 5


def test_no_llm_with_penalty_returns_heuristic(tmp_path: Path) -> None:
    """Deterministic-only path still surfaces penalties in evidence."""
    wt = _make_trace_worktree(tmp_path, _steps(repeated_skill="build"))
    ds = score(wt, Context())
    assert ds.value == 4  # 1 penalty
    assert ds.evidence["no_llm"] is True
    assert ds.evidence["heuristic_value"] == 4


# ----- 0.7/0.3 combination -----

def test_combined_value_70_heuristic_30_llm(tmp_path: Path) -> None:
    """heuristic=5, llm=3 → round(5*0.7 + 3*0.3) = round(4.4) = 4."""
    wt = _make_trace_worktree(tmp_path, _steps())
    mock = MagicMock(return_value={
        "scores": {"tool_selection": 3, "sequence_logic": 3,
                    "branching_minimal": 3, "convergence": 3},
        "tokens_in": 1, "tokens_out": 1, "raw": "",
    })
    ds = score(wt, Context(llm_judge=mock))
    assert ds.value == 4
    assert ds.evidence["heuristic_value"] == 5
    assert ds.evidence["llm_value"] == 3
    assert ds.evidence["combined_raw"] == 4.4


def test_combined_value_lower_heuristic_higher_llm(tmp_path: Path) -> None:
    """heuristic=4, llm=5 → round(4*0.7 + 5*0.3) = round(4.3) = 4."""
    wt = _make_trace_worktree(tmp_path, _steps(repeated_skill="x"))
    mock = MagicMock(return_value={
        "scores": {"tool_selection": 5, "sequence_logic": 5,
                    "branching_minimal": 5, "convergence": 5},
        "tokens_in": 1, "tokens_out": 1, "raw": "",
    })
    ds = score(wt, Context(llm_judge=mock))
    assert ds.value == 4
    assert ds.evidence["heuristic_value"] == 4
    assert ds.evidence["llm_value"] == 5


def test_combined_value_clamped_to_one(tmp_path: Path) -> None:
    """heuristic=1 (3 penalties), llm=1 → round(1*0.7 + 1*0.3) = 1."""
    wt = _make_trace_worktree(tmp_path, _steps(
        repeated_skill="x", no_read_at_all=True, long_phase_runs=1,
    ))
    mock = MagicMock(return_value={
        "scores": {"tool_selection": 1, "sequence_logic": 1,
                    "branching_minimal": 1, "convergence": 1},
        "tokens_in": 1, "tokens_out": 1, "raw": "",
    })
    ds = score(wt, Context(llm_judge=mock))
    assert ds.value == 1


# ----- judge failures / fallbacks -----

def test_judge_exception_falls_back_to_heuristic(tmp_path: Path) -> None:
    """LLM raising → heuristic_value is returned, never crash."""
    wt = _make_trace_worktree(tmp_path, _steps())
    mock = MagicMock(side_effect=RuntimeError("net"))
    ds = score(wt, Context(llm_judge=mock))
    assert ds.value == 5
    assert ds.evidence["status"] == "judge_error"
    assert "net" in ds.evidence["error"]


def test_empty_judge_scores_falls_back_to_heuristic(tmp_path: Path) -> None:
    """LLM returns {} → llm_value=3 (clamped), still combines with heuristic."""
    wt = _make_trace_worktree(tmp_path, _steps())
    mock = MagicMock(return_value={"scores": {}, "tokens_in": 0, "tokens_out": 0, "raw": ""})
    ds = score(wt, Context(llm_judge=mock))
    # heuristic=5, llm=3 → round(5*0.7 + 3*0.3) = 4
    assert ds.value == 4
    assert ds.evidence["llm_value"] == 3


def test_no_trace_returns_placeholder(tmp_path: Path) -> None:
    """No trace on disk → value=3, phase=1, reason recorded."""
    wt = tmp_path / "wt"
    wt.mkdir()
    ds = score(wt, Context(llm_judge=MagicMock()))
    assert ds.value == 3
    assert ds.evidence["phase"] == 1
    assert ds.evidence["reason"] == "no trace available"


# ----- judge call wiring -----

def test_llm_judge_axes_are_trajectory(tmp_path: Path) -> None:
    """ctx.llm_judge is called with axes=trajectory and dim='trajectory'."""
    wt = _make_trace_worktree(tmp_path, _steps())
    mock = MagicMock(return_value={
        "scores": {"tool_selection": 4, "sequence_logic": 4,
                    "branching_minimal": 4, "convergence": 4},
        "tokens_in": 0, "tokens_out": 0, "raw": "",
    })
    score(wt, Context(llm_judge=mock))
    mock.assert_called_once()
    _, kwargs = mock.call_args
    assert kwargs["axes"] == llm_judge.DIM_AXES["trajectory"]
    assert kwargs["dim"] == "trajectory"
