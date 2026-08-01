"""test_batch_eval.py — N=5 synthetic worktrees + consistency score."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from lib.behavior_scorers import Context
from lib.behavior_scorers.aggregate import compute
from lib.behavior_scorers.batch_eval import (
    _consistency,
    _per_dim_values,
    aggregate_batch,
    batch_eval,
)
from lib.behavior_scorers.types import BehaviorReport, DimensionScore


def _make_synthetic_worktree(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    """Create a synthetic git repo with a deterministic eval surface."""
    wt = tmp_path / name
    wt.mkdir()
    for path, content in files.items():
        full = wt / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    subprocess.run(["git", "init", "-q", "-b", "main", str(wt)], check=True)
    subprocess.run(["git", "-C", str(wt), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(wt), "config", "user.name", "T"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "--allow-empty", "-q", "-m", "init"],
        check=True,
    )
    subprocess.run(["git", "-C", str(wt), "checkout", "-q", "-b", "feat/test"], check=True)
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-q", "-m", "feat: synthetic fixture"],
        check=True,
    )
    head = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "main"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(wt), "update-ref", "refs/remotes/origin/main", head],
        check=True,
    )
    return wt


def test_per_dim_values_buckets_correctly() -> None:
    scores = [
        BehaviorReport(
            case_id="c",
            worktree=".",
            dimension_scores=(
                DimensionScore(dim="D1_outcome", value=5, evidence={}),
                DimensionScore(dim="D2_process", value=4, evidence={}),
            ),
            weighted_mean=4.5,
            deterministic_mean=4.5,
            verdict="OK",
        ),
        BehaviorReport(
            case_id="c",
            worktree=".",
            dimension_scores=(
                DimensionScore(dim="D1_outcome", value=3, evidence={}),
                DimensionScore(dim="D2_process", value=4, evidence={}),
            ),
            weighted_mean=3.5,
            deterministic_mean=3.5,
            verdict="DRIFT_WARNING",
        ),
    ]
    buckets = _per_dim_values(scores)
    assert buckets["D1_outcome"] == [5, 3]
    assert buckets["D2_process"] == [4, 4]


def test_consistency_identical() -> None:
    assert _consistency([5, 5, 5]) == 5.0


def test_consistency_single_value() -> None:
    assert _consistency([4]) == 5.0


def test_consistency_wide_spread_low() -> None:
    # n=2 values [1,5] → sample variance = 8.0 → consistency floor at 1.
    assert _consistency([1, 5]) == 1.0


def test_consistency_moderate_spread() -> None:
    # [3, 5] → variance 2.0 → consistency = 5 - 2/2 = 4.0
    score = _consistency([3, 5])
    assert score == 4.0


def test_aggregate_batch_weighted_means() -> None:
    scores = [
        BehaviorReport(
            case_id="c",
            worktree=".",
            dimension_scores=(
                DimensionScore(dim="D1_outcome", value=v, evidence={}),
                DimensionScore(dim="D2_process", value=v, evidence={}),
                DimensionScore(dim="D3_efficiency", value=v, evidence={}),
                DimensionScore(dim="D4_safety", value=v, evidence={}),
                DimensionScore(dim="D5_communication", value=v, evidence={}),
                DimensionScore(dim="D6_robustness", value=v, evidence={}),
                DimensionScore(dim="D7_trajectory", value=v, evidence={}),
                DimensionScore(dim="D8_reversibility", value=v, evidence={}),
                DimensionScore(dim="D9_side_effects", value=v, evidence={}),
            ),
            weighted_mean=float(v),
            deterministic_mean=float(v),
            verdict="OK",
        )
        for v in [5, 3, 4]
    ]
    weights = {s.dim: 1 / 9 for s in scores[0].dimension_scores}
    agg = aggregate_batch(scores, weights=weights)
    assert agg["n"] == 3
    assert agg["weighted_mean"] == 4.0  # (5+3+4)/3
    assert agg["min_weighted_mean"] == 3.0
    assert agg["per_dim_min"]["D1_outcome"] == 3


def test_aggregate_batch_empty_raises() -> None:
    with pytest.raises(ValueError):
        aggregate_batch([], weights={})


def test_batch_eval_runs_against_worktrees(tmp_path: Path) -> None:
    """End-to-end: build 5 synthetic worktrees and exercise batch_eval."""
    # Provide a "task.md" hint. The synthetic lib/foo.py is in scope.
    common_files = {
        "task.md": "touch `lib/foo.py` for the auth fix\n",
        "lib/foo.py": "def foo(): return 1\n",
        ".dev-kit/hand-off/r.md": "## next\n- all green\n",
        "tests/test_x.py": "def test_x(): assert True\n",
    }
    worktrees = []
    for i in range(5):
        wt = _make_synthetic_worktree(
            tmp_path, f"wt{i}",
            files={**common_files, "lib/foo.py": f"def foo(): return {i}\n"},
        )
        worktrees.append(wt)

    task_spec = tmp_path / "task.md"
    task_spec.write_text("do the thing\n")

    result = batch_eval(task_spec, worktrees, ctx=Context(no_llm=True))
    assert result["case_id"] == "task"
    assert result["n"] == 5
    assert len(result["per_worktree"]) == 5
    # `consistency` is per-dim; all should be 5.0 because each scorer
    # returns identical values across worktrees (the synthetic fixtures
    # are identical except for a literal int).
    assert "consistency" in result
    assert isinstance(result["mean_consistency"], float)


def test_batch_eval_detects_high_variance(tmp_path: Path) -> None:
    """If 5 worktrees score very differently on one dim, consistency drops."""
    # Bypass score_all() and just construct synthetic reports with
    # variance to verify the consistency math directly.
    high_var = []
    for v in [1, 1, 5, 5, 1]:
        scores = (
            DimensionScore(dim="D1_outcome", value=v, evidence={}),
            DimensionScore(dim="D2_process", value=4, evidence={}),
        )
        high_var.append(
            compute("c", ".", scores, weights={"D1_outcome": 0.5, "D2_process": 0.5})
        )
    bucket = _per_dim_values(high_var)
    # D1 has [1,1,5,5,1] → var = 4.8 → consistency = 5 - 2.4 = 2.6.
    c_d1 = _consistency(bucket["D1_outcome"])
    assert 1.0 <= c_d1 <= 3.0
    assert _consistency(bucket["D2_process"]) == 5.0


def test_batch_eval_empty_raises(tmp_path: Path) -> None:
    task_spec = tmp_path / "task.md"
    task_spec.write_text("nope\n")
    with pytest.raises(ValueError):
        batch_eval(task_spec, [], ctx=Context(no_llm=True))
