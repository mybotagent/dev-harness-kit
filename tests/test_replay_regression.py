"""test_replay_regression.py — tools/replay_regression.py CLI behavior.

Covers:
- All 5 golden cases clean → exit 0
- One case has regression → exit 1 with breach in output
- Missing case dir files → recorded as error in result, still exits 1
- Missing golden_dir (or non-directory arg) → exit 2 setup error
- Symlinked baseline.json → error recorded, exit 1
- --md-comment mode produces markdown table

Stdlib only; uses tmp_path fixtures (mirrors `tests/test_trace_diff.py`).
"""
from __future__ import annotations

import json
from pathlib import Path

from tools.replay_regression import (
    CaseResult,
    ReplaySummary,
    main,
    render_markdown,
    render_plain,
    replay_directory,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "agent-behavior" / "golden"


def _write_trace(path: Path, *, step_count: int = 4, retries: int = 0,
                 input_tokens: int = 100, output_tokens: int = 50,
                 latency_ms: int = 1000, verdict: str = "OK",
                 axes: dict | None = None) -> None:
    """Write a minimal schema-v1 trace JSON (mirrors `_write_trace` in test_trace_diff)."""
    axes = axes or {"D1_outcome": 5, "D2_process": 4}
    steps: list[dict] = []
    per_step_latency = max(latency_ms // max(step_count, 1), 1)
    for i in range(step_count):
        steps.append({
            "ts": f"2026-07-31T10:00:{i:02d}Z",
            "skill": "plan",
            "phase": "interview",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": per_step_latency,
            "retries": retries if i == 0 else 0,
            "exit_code": 0,
        })
    trace = {
        "schema_version": 1,
        "case_id": path.parent.name,
        "started_at": "2026-07-31T10:00:00Z",
        "ended_at": "2026-07-31T10:05:00Z",
        "harness_version": "0.3.175",
        "agent": "claude-code-4.8",
        "worktree_branch": "feat/x",
        "worktree_path": ".worktrees/x",
        "steps": steps,
        "judge_scores": [{"rubric": "agent-behavior", "verdict": verdict, "axes": axes}],
        "evidence": {},
    }
    path.write_text(json.dumps(trace))


def _write_case(tmp_path: Path, case_id: str, *, baseline_kwargs: dict, current_kwargs: dict) -> Path:
    """Create `<tmp>/<case_id>/baseline.json` + `current.json` from kwargs."""
    case_dir = tmp_path / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    _write_trace(case_dir / "baseline.json", **baseline_kwargs)
    _write_trace(case_dir / "current.json", **current_kwargs)
    return case_dir


# ---------------------------------------------------------------------------
# Replay + main(): exit code matrix
# ---------------------------------------------------------------------------


def test_main_all_clean_exits_zero(tmp_path: Path, capsys) -> None:
    """5 synthetic clean cases (no regressions) → exit 0.

    The on-disk fixtures under `FIXTURE_ROOT` include 3 intentional
    regression cases (drift-warning, rot, l1-violation) — those exercise
    the regression-detection path covered by `test_main_one_regression_*`.
    """
    for case_id in ("c1", "c2", "c3", "c4", "c5"):
        _write_case(tmp_path, case_id, baseline_kwargs={}, current_kwargs={})
    rc = main([str(tmp_path)])
    assert rc == 0, "synthetic clean set must exit 0"
    captured = capsys.readouterr()
    assert "clean=5 regressed=0" in captured.out


def test_main_one_regression_exits_one(tmp_path: Path, capsys) -> None:
    """One case drops an axis score by > 1 → exit 1 + breach visible in output."""
    _write_case(tmp_path, "clean-ok", baseline_kwargs={}, current_kwargs={})
    _write_case(
        tmp_path, "axis-drop",
        baseline_kwargs={"axes": {"D1_outcome": 5, "D2_process": 4}},
        current_kwargs={"axes": {"D1_outcome": 2, "D2_process": 4}},  # drop by 3
    )
    rc = main([str(tmp_path), "--threshold", "0.5"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "axis-drop" in captured.out
    assert "axis_score_drop>1" in captured.out


def test_main_missing_current_file_records_error_and_exits_one(tmp_path: Path, capsys) -> None:
    """If `current.json` is absent but `baseline.json` exists → per-case error → exit 1."""
    case = tmp_path / "half-written"
    case.mkdir()
    _write_trace(case / "baseline.json")
    # Deliberately do NOT write current.json
    rc = main([str(tmp_path)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "missing current.json" in captured.out
    assert "half-written" in captured.out


def test_main_missing_golden_dir_exits_two(tmp_path: Path, capsys) -> None:
    """Nonexistent golden_dir → setup error → exit 2 + stderr message."""
    rc = main([str(tmp_path / "does-not-exist")])
    assert rc == 2
    captured = capsys.readouterr()
    assert "golden_dir not found" in captured.err


def test_main_negative_threshold_exits_two(tmp_path: Path, capsys) -> None:
    """threshold < 0 is a setup error → exit 2 + stderr message."""
    (tmp_path / "ok").mkdir()
    _write_trace(tmp_path / "ok" / "baseline.json")
    _write_trace(tmp_path / "ok" / "current.json")
    rc = main([str(tmp_path), "--threshold", "-0.1"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "--threshold must be >= 0" in captured.err


def test_main_symlinked_baseline_records_error_and_exits_one(tmp_path: Path, capsys) -> None:
    """Symlinked baseline.json must be recorded as an error (no traversal) → exit 1."""
    # Build a real trace file outside the golden dir, then symlink to it.
    real = tmp_path / "real-baseline.json"
    _write_trace(real)
    case = tmp_path / "symlink-case"
    case.mkdir()
    (case / "current.json").write_text(json.dumps({  # broken on purpose; baseline is symlink
        "schema_version": 1, "case_id": "symlink-case",
        "steps": [], "judge_scores": [{"verdict": "OK", "axes": {}}], "evidence": {}
    }))
    (case / "baseline.json").symlink_to(real)

    rc = main([str(tmp_path)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "symlink" in captured.out.lower()
    assert "symlink-case" in captured.out


# ---------------------------------------------------------------------------
# --md-comment output
# ---------------------------------------------------------------------------


def test_main_md_comment_exits_zero_when_clean(tmp_path: Path, capsys) -> None:
    """Golden fixtures under --md-comment render a markdown table; clean case exits 0."""
    _write_case(tmp_path, "clean", baseline_kwargs={}, current_kwargs={})
    rc = main([str(tmp_path), "--md-comment"])
    assert rc == 0
    captured = capsys.readouterr()
    out = captured.out
    assert "## Replay regression" in out
    assert "| Case | Baseline | Current | Verdict | Breaches |" in out
    assert "`clean`" in out


def test_main_md_comment_lists_breach_for_regression(tmp_path: Path, capsys) -> None:
    """--md-comment output mentions the breached case + rule name under Breach details."""
    _write_case(tmp_path, "ok", baseline_kwargs={}, current_kwargs={})
    _write_case(
        tmp_path, "rotty",
        baseline_kwargs={
            "input_tokens": 100, "output_tokens": 50,
            "verdict": "DRIFT_WARNING", "axes": {"D1_outcome": 4, "D2_process": 4},
        },
        current_kwargs={
            "input_tokens": 300, "output_tokens": 150,  # ~3x token ratio
            "verdict": "ROT",
            "axes": {"D1_outcome": 4, "D2_process": 4},
        },
    )
    rc = main([str(tmp_path), "--md-comment"])
    assert rc == 1
    captured = capsys.readouterr()
    out = captured.out
    assert "### Breach details" in out
    assert "`rotty`" in out
    assert "verdict_drop" in out or "token_ratio_delta" in out


# ---------------------------------------------------------------------------
# Pure-function primitives
# ---------------------------------------------------------------------------


def test_replay_directory_handles_empty_dir(tmp_path: Path) -> None:
    """No case subdirs → empty summary with both counts at 0."""
    summary = replay_directory(tmp_path, threshold=0.5)
    assert isinstance(summary, ReplaySummary)
    assert summary.cases == ()
    assert summary.clean_count == 0
    assert summary.regressed_count == 0


def test_replay_directory_skips_loose_files(tmp_path: Path) -> None:
    """Loose files at the top level are ignored (only directories are cases)."""
    (tmp_path / "stray.txt").write_text("not a case")
    _write_case(tmp_path, "real-case", baseline_kwargs={}, current_kwargs={})
    summary = replay_directory(tmp_path, threshold=0.5)
    assert len(summary.cases) == 1
    assert summary.cases[0].case_id == "real-case"


def test_render_plain_contains_breach_rule(tmp_path: Path) -> None:
    """Plain-text renderer surfaces the breached rule name under [case] breaches:."""
    _write_case(
        tmp_path, "bad-retry",
        baseline_kwargs={"retries": 0},
        current_kwargs={"retries": 5},  # absolute_delta = 5 > 2
    )
    summary = replay_directory(tmp_path, threshold=0.5)
    text = render_plain(summary)
    assert "retry_total_delta>2" in text
    assert "bad-retry" in text


def test_render_markdown_table_shape(tmp_path: Path) -> None:
    """Markdown renderer emits a 5-column table header + one row per case."""
    _write_case(tmp_path, "x", baseline_kwargs={}, current_kwargs={})
    _write_case(tmp_path, "y", baseline_kwargs={}, current_kwargs={})
    summary = replay_directory(tmp_path, threshold=0.5)
    md = render_markdown(summary)
    assert "| Case | Baseline | Current | Verdict | Breaches |" in md
    assert "| `x` |" in md
    assert "| `y` |" in md


def test_case_result_is_clean_when_no_breaches_no_error() -> None:
    """`CaseResult.is_clean` is True iff both error is None and breaches empty."""
    case = CaseResult(
        case_id="x", baseline_path=Path("/tmp/x/baseline.json"),
        current_path=Path("/tmp/x/current.json"),
        deltas=(), axis_deltas=(), breaches=(), verdict_dropped=False,
    )
    assert case.is_clean is True


def test_case_result_not_clean_when_breach_present() -> None:
    """A non-empty `breaches` tuple flips `is_clean` to False (regardless of error)."""
    from tools.trace_diff import ThresholdBreach
    case = CaseResult(
        case_id="x", baseline_path=Path("/tmp/x/baseline.json"),
        current_path=Path("/tmp/x/current.json"),
        deltas=(), axis_deltas=(),
        breaches=(ThresholdBreach("verdict_drop", "worse tier"),),
        verdict_dropped=True, error=None,
    )
    assert case.is_clean is False


def test_case_result_not_clean_when_error_set() -> None:
    """An error string (symlink, missing file, parse failure) flips is_clean False."""
    case = CaseResult(
        case_id="x", baseline_path=Path("/tmp/x/baseline.json"),
        current_path=Path("/tmp/x/current.json"),
        deltas=(), axis_deltas=(), breaches=(), verdict_dropped=False,
        error="ValueError: refusing to follow symlink",
    )
    assert case.is_clean is False
