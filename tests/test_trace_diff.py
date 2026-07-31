"""test_trace_diff.py — tools/trace_diff.py CLI behavior.

Covers:
- exit 0 when within threshold
- exit 1 when retry_total grows > 2
- exit 1 when token ratio exceeds threshold
- exit 1 when per-axis score drops > 1
- exit 1 when verdict drops (OK -> DRIFT_WARNING)
- axis delta formatting
"""
from __future__ import annotations

import json
from pathlib import Path

from tools.trace_diff import (
    Delta,
    check_thresholds,
    compute_deltas,
    main,
)


def _write_trace(path: Path, *, step_count: int = 5, retries: int = 0,
                 input_tokens: int = 100, output_tokens: int = 50,
                 latency_ms: int = 1000, verdict: str = "OK",
                 axes: dict | None = None) -> None:
    axes = axes or {}
    trace = {
        "schema_version": 1,
        "case_id": "x",
        "started_at": "2026-07-31T00:00:00Z",
        "ended_at": "2026-07-31T00:01:00Z",
        "harness_version": "0.3.175",
        "agent": "claude-code-4.8",
        "worktree_branch": "feat/x",
        "worktree_path": ".worktrees/x",
        "steps": [
            {
                "ts": f"2026-07-31T00:00:{i:02d}Z",
                "skill": "plan",
                "phase": "interview",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": latency_ms // max(step_count, 1),
                "retries": retries if i == 0 else 0,
                "exit_code": 0,
            }
            for i in range(step_count)
        ],
        "judge_scores": [{"rubric": "agent-behavior", "verdict": verdict, "axes": axes}],
        "evidence": {},
    }
    path.write_text(json.dumps(trace))


def test_compute_deltas_keys_and_ratios(tmp_path: Path) -> None:
    """compute_deltas() should return Delta for each of 4 metrics, with ratios."""
    baseline = {"step_count": 10, "retry_total": 0, "token_total": 1000, "latency_total_ms": 5000}
    current = {"step_count": 12, "retry_total": 1, "token_total": 1500, "latency_total_ms": 6000}
    deltas = compute_deltas(baseline, current)
    by_name = {d.name: d for d in deltas}
    assert set(by_name) == {"step_count", "retry_total", "token_total", "latency_total_ms"}
    assert by_name["step_count"].ratio == 1.2
    assert by_name["token_total"].ratio == 1.5
    assert by_name["retry_total"].absolute_delta == 1


def test_compute_deltas_handles_zero_baseline() -> None:
    """When baseline = 0 and current = 0, ratio is 1.0 (not division-by-zero)."""
    baseline = {"step_count": 0, "retry_total": 0, "token_total": 0, "latency_total_ms": 0}
    current = {"step_count": 0, "retry_total": 0, "token_total": 0, "latency_total_ms": 0}
    deltas = compute_deltas(baseline, current)
    for d in deltas:
        assert d.ratio == 1.0


def test_check_thresholds_retry_breach() -> None:
    deltas = (
        Delta(name="retry_total", baseline=0, current=5, ratio=float("inf"), absolute_delta=5),
    )
    breaches = check_thresholds(deltas, (), verdict_dropped=False, threshold=0.5)
    assert any(b.rule == "retry_total_delta>2" for b in breaches)


def test_check_thresholds_token_ratio_breach() -> None:
    """Token ratio > 1 + threshold (default 0.5) → breach."""
    deltas = (
        Delta(name="token_total", baseline=1000, current=2000, ratio=2.0, absolute_delta=1000),
    )
    breaches = check_thresholds(deltas, (), verdict_dropped=False, threshold=0.5)
    assert any("token_ratio_delta" in b.rule for b in breaches)


def test_check_thresholds_axis_score_drop_breach() -> None:
    """per-axis score drop > 1 → breach."""
    deltas = ()
    axes = (("D1_outcome", 5, 2),)  # dropped by 3
    breaches = check_thresholds(deltas, axes, verdict_dropped=False, threshold=0.5)
    assert any(b.rule == "axis_score_drop>1" for b in breaches)


def test_check_thresholds_verdict_drop_breach() -> None:
    deltas = ()
    breaches = check_thresholds(deltas, (), verdict_dropped=True, threshold=0.5)
    assert any(b.rule == "verdict_drop" for b in breaches)


def test_check_thresholds_no_breaches_when_stable() -> None:
    deltas = (
        Delta(name="step_count", baseline=10, current=10, ratio=1.0, absolute_delta=0),
        Delta(name="retry_total", baseline=1, current=1, ratio=1.0, absolute_delta=0),
        Delta(name="token_total", baseline=1000, current=1100, ratio=1.1, absolute_delta=100),
        Delta(name="latency_total_ms", baseline=5000, current=5500, ratio=1.1, absolute_delta=500),
    )
    breaches = check_thresholds(deltas, (), verdict_dropped=False, threshold=0.5)
    assert breaches == ()


def test_main_exit_zero_when_within_threshold(tmp_path: Path, capsys) -> None:
    """Two traces within threshold → exit 0."""
    base = tmp_path / "base.json"
    cur = tmp_path / "cur.json"
    _write_trace(base, step_count=5, retries=0, input_tokens=100, output_tokens=50,
                 latency_ms=1000, verdict="OK", axes={"D1_outcome": 5, "D2_process": 4})
    _write_trace(cur, step_count=5, retries=0, input_tokens=110, output_tokens=55,
                 latency_ms=1100, verdict="OK", axes={"D1_outcome": 5, "D2_process": 4})
    rc = main([str(base), str(cur)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "No threshold breaches" in captured.out


def test_main_exit_one_on_retry_breach(tmp_path: Path, capsys) -> None:
    """retry_total delta > 2 → exit 1."""
    base = tmp_path / "base.json"
    cur = tmp_path / "cur.json"
    _write_trace(base, retries=0)
    _write_trace(cur, retries=5)  # absolute_delta = 5 > 2
    rc = main([str(base), str(cur)])
    assert rc == 1


def test_main_missing_baseline_exits_one(tmp_path: Path, capsys) -> None:
    """Missing baseline file → exit 1 with stderr message."""
    cur = tmp_path / "cur.json"
    _write_trace(cur)
    rc = main([str(tmp_path / "missing.json"), str(cur)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "baseline not found" in captured.err


def test_main_missing_current_exits_one(tmp_path: Path, capsys) -> None:
    """Missing current file → exit 1 with stderr message."""
    base = tmp_path / "base.json"
    _write_trace(base)
    rc = main([str(base), str(tmp_path / "missing.json")])
    assert rc == 1
    captured = capsys.readouterr()
    assert "current not found" in captured.err
