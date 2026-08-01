import json
from pathlib import Path

import pytest

from lib.test_weakening_detector import (
    analyze,
    assertion_count_diff,
    coverage_drop,
    deleted_test_files,
    mock_skip_patterns,
)


def _write_coverage(path: Path, percent: float) -> None:
    path.write_text(json.dumps({"totals": {"percent_covered": percent, "covered_lines": 0, "num_statements": 0}}))


def test_coverage_drop_measures_percentage_points(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    _write_coverage(before, 90.0)
    _write_coverage(after, 80.0)
    assert coverage_drop(before, after) == 10.0


def test_coverage_drop_treats_ratio_shaped_inputs(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text(json.dumps({"totals": {"percent_covered": 0.9}}))
    after.write_text(json.dumps({"totals": {"percent_covered": 0.7}}))
    assert coverage_drop(before, after) == pytest.approx(20.0)


def test_assertion_count_diff_subtracts_pytest_summaries(tmp_path: Path) -> None:
    before = tmp_path / "before.txt"
    after = tmp_path / "after.txt"
    before.write_text("12 tests collected\n")
    after.write_text("9 tests collected\n")
    assert assertion_count_diff(before, after) == -3


def test_mock_skip_patterns_lists_test_files(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_clean.py").write_text("def test_x(): assert True\n")
    (tests / "test_skip.py").write_text("import pytest\n@pytest.skip('reason')\ndef test_x(): pass\n")
    (tests / "test_mocked.py").write_text("from unittest import mock\n@mock.patch('x')\ndef test_x(): pass\n")
    (tests / "test_xit.py").write_text("def test_x():\n    xit(lambda: None)\n")
    (tests / "helper.py").write_text("# references pytest.skip as text\n")
    files = mock_skip_patterns(tests)
    assert "test_skip.py" in files
    assert "test_mocked.py" in files
    assert "test_xit.py" in files
    assert "helper.py" not in files


def test_deleted_test_files_returns_only_removed_paths(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "tests").mkdir()
    (after / "tests").mkdir()
    (before / "tests" / "test_one.py").write_text("def test_one(): assert True\n")
    (after / "tests" / "test_one.py").write_text("def test_one(): assert True\n")
    assert deleted_test_files(before, after) == []


def test_deleted_test_files_detects_removal(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "tests").mkdir()
    (after / "tests").mkdir()
    (before / "tests" / "test_one.py").write_text("def test_one(): assert True\n")
    (before / "tests" / "test_removed.py").write_text("def test_removed(): pass\n")
    (after / "tests" / "test_one.py").write_text("def test_one(): assert True\n")
    assert deleted_test_files(before, after) == ["tests/test_removed.py"]


def test_analyze_penalty_floors_at_negative_two(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    worktree = tmp_path / "worktree"
    baseline.mkdir()
    worktree.mkdir()
    (baseline / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 90.0}}))
    (worktree / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 60.0}}))
    (baseline / "pytest-collect-only.txt").write_text("12 tests collected\n")
    (worktree / "pytest-collect-only.txt").write_text("8 tests collected\n")
    (baseline / "tests").mkdir()
    (worktree / "tests").mkdir()
    (worktree / "tests" / "test_x.py").write_text("@pytest.skip('reason')\ndef test_x(): pass\n")
    (baseline / "tests" / "test_removed.py").write_text("def test_removed(): pass\n")
    (worktree / "tests" / "test_x.py").write_text("def test_x(): pass\n")
    (worktree / "tests" / "test_skipped.py").write_text("@pytest.skip('reason')\ndef test_y(): pass\n")
    result = analyze(worktree, baseline)
    assert result["penalty"] == -2
    assert "coverage_drop" in result["signals_triggered"]
    assert "assertion_drop" in result["signals_triggered"]
    assert "mock_skip_patterns" in result["signals_triggered"]
    assert "deleted_test_files" in result["signals_triggered"]


def test_analyze_without_signals_keeps_value_unchanged(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    worktree = tmp_path / "worktree"
    baseline.mkdir()
    worktree.mkdir()
    (baseline / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 80.0}}))
    (worktree / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 85.0}}))
    (baseline / "pytest-collect-only.txt").write_text("10 tests collected\n")
    (worktree / "pytest-collect-only.txt").write_text("12 tests collected\n")
    (baseline / "tests").mkdir()
    (worktree / "tests").mkdir()
    (worktree / "tests" / "test_a.py").write_text("def test_a(): assert True\n")
    result = analyze(worktree, baseline)
    assert result["signals_triggered"] == []
    assert result["penalty"] == 0


def test_analyze_handles_missing_baseline_files(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / "tests").mkdir()
    (worktree / "tests" / "test_a.py").write_text("def test_a(): assert True\n")
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    result = analyze(worktree, baseline)
    assert result["signals_triggered"] == []
    assert result["penalty"] == 0
