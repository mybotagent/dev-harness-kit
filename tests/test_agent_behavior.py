"""test_agent_behavior.py — per-dim scorers + aggregate verdict.

These tests use a fake worktree fixture (`tests/fixtures/agent-behavior/`)
that has:
- a Conventional Commit message
- a `feat/<slug>` branch
- a `.dev-kit/hand-off/` directory with one file
- an eval-report.md with verdict
- an `eval/transcripts/<case>/` directory with one trace JSON

We exercise each scorer against this fixture and the aggregate verdict.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from lib.behavior_scorers import (
    DIM_AXES_BEHAVIOR,
    BehaviorReport,
    Context,
    DimensionScore,
    score_all,
    to_trace_log,
)
from lib.behavior_scorers.aggregate import compute, render_markdown
from lib.trace_log import TraceLog, TraceStep

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "agent-behavior"


@pytest.fixture
def golden_worktree(tmp_path: Path) -> Path:
    """Copy the fixture to a tmp dir so tests don't mutate the source."""
    import shutil

    if not FIXTURE_ROOT.is_dir():
        pytest.skip(f"fixture not found: {FIXTURE_ROOT}")
    shutil.copytree(FIXTURE_ROOT, tmp_path / "wt")
    return tmp_path / "wt"


def _init_git(worktree: Path) -> None:
    """Init a minimal git repo inside the fixture so process scorers work.

    Required for `process.score` and `safety.score` which call `git`.
    The git history is minimal (one commit on `feat/<slug>`).
    """
    subprocess.run(["git", "init", "-q", "-b", "main", str(worktree)], check=True)
    subprocess.run(["git", "-C", str(worktree), "config", "user.email", "test@test"], check=True)
    subprocess.run(["git", "-C", str(worktree), "config", "user.name", "Test"], check=True)
    # Empty initial commit on main
    subprocess.run(["git", "-C", str(worktree), "commit", "--allow-empty", "-q", "-m", "init"], check=True)
    # Worktree cut: create branch off main with one Conventional Commit
    subprocess.run(["git", "-C", str(worktree), "checkout", "-q", "-b", "feat/login-validation"], check=True)
    (worktree / "tests").mkdir(exist_ok=True)
    (worktree / "lib").mkdir(exist_ok=True)
    (worktree / "tests" / "test_login.py").write_text("def test_ok(): assert True\n")
    (worktree / "lib" / "login.py").write_text("def login(): return True\n")
    subprocess.run(["git", "-C", str(worktree), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(worktree), "commit", "-q", "-m", "feat(login): add login validation"],
        check=True,
    )
    # Set origin/main to current main commit so process/efficiency scorers can diff
    subprocess.run(
        ["git", "-C", str(worktree), "update-ref", "refs/remotes/origin/main",
         subprocess.run(["git", "-C", str(worktree), "rev-parse", "main"], capture_output=True, text=True).stdout.strip()],
        check=True,
    )


def test_dim_axes_behavior_is_seven() -> None:
    assert DIM_AXES_BEHAVIOR == (
        "D1_outcome", "D2_process", "D3_efficiency", "D4_safety",
        "D5_communication", "D6_robustness", "D7_trajectory",
    )


def test_score_all_returns_report_with_seven_dims(golden_worktree: Path) -> None:
    _init_git(golden_worktree)
    report = score_all(golden_worktree, case_id="test-case", ctx=Context(no_llm=True))
    assert isinstance(report, BehaviorReport)
    assert len(report.dimension_scores) == 7
    dims = {s.dim for s in report.dimension_scores}
    assert dims == set(DIM_AXES_BEHAVIOR)


def test_score_all_verdict_is_known(golden_worktree: Path) -> None:
    _init_git(golden_worktree)
    report = score_all(golden_worktree, case_id="test-case", ctx=Context(no_llm=True))
    assert report.verdict in {"OK", "DRIFT_WARNING", "ROT", "ESCALATED"}


def test_aggregate_compute_weights_sum_to_one() -> None:
    """If a dim is missing from weights, the weighted mean is renormalised.

    This protects against silent regressions in `WEIGHTS`.
    """
    scores = tuple(
        DimensionScore(dim=dim, value=4, evidence={})
        for dim in DIM_AXES_BEHAVIOR
    )
    weights_partial = {"D1_outcome": 0.5, "D2_process": 0.5}  # only 2 of 7
    report = compute(
        case_id="t", worktree=".", dim_scores=scores, weights=weights_partial,
    )
    # Only D1+D2 contribute; weighted_mean = 4.0.
    assert report.weighted_mean == 4.0


def test_aggregate_compute_deterministic_floor_forces_escalated() -> None:
    """deterministic_mean < 3.5 forces ESCALATED regardless of weighted_mean.

    With D1..D4 set to (1, 1, 1, 5) the deterministic mean is (1+1+1+5)/4 = 2.0,
    well below the 3.5 floor — ESCALATED must be forced even though the
    weighted mean is (1+1+1+5+5+5+5)/7 = 23/7 ≈ 3.29 (which would
    otherwise be DRIFT_WARNING). Previous version of this test set
    D1=1 and others=5, which only made deterministic_mean=4.0 and
    never tripped the floor — that was a tautology flagged by the
    maintenance gate.
    """
    scores = (
        DimensionScore(dim="D1_outcome", value=1, evidence={}),
        DimensionScore(dim="D2_process", value=1, evidence={}),
        DimensionScore(dim="D3_efficiency", value=1, evidence={}),
        DimensionScore(dim="D4_safety", value=5, evidence={}),  # one OK to keep
        DimensionScore(dim="D5_communication", value=5, evidence={}),
        DimensionScore(dim="D6_robustness", value=5, evidence={}),
        DimensionScore(dim="D7_trajectory", value=5, evidence={}),
    )
    weights = {dim: 1 / 7 for dim in DIM_AXES_BEHAVIOR}
    report = compute(case_id="t", worktree=".", dim_scores=scores, weights=weights)
    # deterministic_mean = (1+1+1+5)/4 = 2.0 < 3.5 → ESCALATED, not DRIFT
    assert report.deterministic_mean == 2.0
    assert report.verdict == "ESCALATED"


def test_aggregate_compute_escalated_when_all_deterministic_fail() -> None:
    """All deterministic dims = 1 → ESCALATED even if LLM dims are 5."""
    scores = (
        DimensionScore(dim="D1_outcome", value=1, evidence={}),
        DimensionScore(dim="D2_process", value=1, evidence={}),
        DimensionScore(dim="D3_efficiency", value=1, evidence={}),
        DimensionScore(dim="D4_safety", value=1, evidence={}),
        DimensionScore(dim="D5_communication", value=5, evidence={}),
        DimensionScore(dim="D6_robustness", value=5, evidence={}),
        DimensionScore(dim="D7_trajectory", value=5, evidence={}),
    )
    weights = {dim: 1 / 7 for dim in DIM_AXES_BEHAVIOR}
    report = compute(case_id="t", worktree=".", dim_scores=scores, weights=weights)
    assert report.verdict == "ESCALATED"
    assert report.deterministic_mean == 1.0


def test_to_trace_log_round_trips_through_save_load(tmp_path: Path) -> None:
    """to_trace_log() should produce a TraceLog that survives save/load."""
    scores = (
        DimensionScore(dim="D1_outcome", value=5, evidence={"tests": "passed"}),
        DimensionScore(dim="D2_process", value=4, evidence={"cc_ratio": 0.95}),
    )
    weights = {"D1_outcome": 0.5, "D2_process": 0.5}
    report = compute(case_id="round-trip", worktree=str(tmp_path), dim_scores=scores, weights=weights)
    log = to_trace_log(
        report,
        harness_version="0.3.175",
        agent="claude-code-4.8",
        steps=(
            TraceStep(ts="2026-07-31T00:00:00Z", skill="plan", phase="interview"),
        ),
    )
    out = log.save(tmp_path)
    loaded = TraceLog.load(out)
    assert loaded.case_id == "round-trip"
    assert loaded.harness_version == "0.3.175"
    assert loaded.judge_scores[0]["axes"]["D1_outcome"] == 5
    assert loaded.evidence["D1_outcome"] == {"tests": "passed"}


def test_render_markdown_contains_table() -> None:
    """render_markdown() should produce a markdown table with all 7 dims."""
    scores = tuple(
        DimensionScore(dim=dim, value=3, evidence={"x": 1})
        for dim in DIM_AXES_BEHAVIOR
    )
    weights = {dim: 1 / 7 for dim in DIM_AXES_BEHAVIOR}
    report = compute(case_id="md", worktree=".", dim_scores=scores, weights=weights)
    md = render_markdown(report)
    assert "# Agent Behavior Report" in md
    assert "| Dim | Score | Evidence |" in md
    for dim in DIM_AXES_BEHAVIOR:
        assert f"`{dim}`" in md


def test_communication_stub_returns_three_when_no_llm(golden_worktree: Path) -> None:
    """D5 stub returns 3 with `phase=0` evidence (Phase 0 contract)."""
    from lib.behavior_scorers.communication import score

    ds = score(golden_worktree, Context(no_llm=True))
    assert ds.dim == "D5_communication"
    assert ds.value == 3
    assert ds.evidence["phase"] == 0


def test_robustness_stub_returns_three(golden_worktree: Path) -> None:
    """D6 stub returns 3 with `phase=0` evidence (Phase 0 contract)."""
    from lib.behavior_scorers.robustness import score

    ds = score(golden_worktree, Context(no_llm=True))
    assert ds.dim == "D6_robustness"
    assert ds.value == 3
    assert ds.evidence["phase"] == 0
