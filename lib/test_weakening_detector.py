"""Detect relative test-suite weakening between a baseline and worktree."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SKIP_RE = re.compile(r"mock|pytest\.skip|xit\(|it\.skip")
_TEST_FILE_RE = re.compile(r"(^test_.*|.*_test)\.(py|pyw|js|jsx|ts|tsx)$", re.IGNORECASE)


def _coverage_total(path: Path) -> float | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    totals = data.get("totals", data) if isinstance(data, dict) else {}
    if not isinstance(totals, dict):
        return None
    for key in ("percent_covered", "coverage", "covered_percent"):
        value = totals.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    covered, statements = totals.get("covered_lines"), totals.get("num_statements")
    if isinstance(covered, (int, float)) and isinstance(statements, (int, float)) and statements:
        return 100.0 * float(covered) / float(statements)
    return None


def coverage_drop(before_path: str | Path, after_path: str | Path) -> float:
    """Return the before-minus-after coverage percentage-point change."""
    before, after = _coverage_total(Path(before_path)), _coverage_total(Path(after_path))
    if before is None or after is None:
        return 0.0
    # coverage.py JSON reports percentages, but accept ratio-shaped fixtures too.
    if before <= 1.0 and after <= 1.0:
        before, after = before * 100, after * 100
    return max(0.0, before - after)


def _read_assertion_count(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    counts = re.findall(r"(?:collected\s+|^\s*)(\d+)\s+(?:tests?|items?)\s+collected", text, re.MULTILINE)
    if counts:
        return int(counts[-1])
    counts = re.findall(r"(\d+)\s+(?:tests?|items?)\s+collected", text)
    if counts:
        return int(counts[-1])
    collected_nodes = [line for line in text.splitlines() if "::" in line]
    if collected_nodes:
        return len(collected_nodes)
    # A source file is also a useful "or similar" input for lightweight callers.
    return len(re.findall(r"\bassert\b", text))


def assertion_count_diff(before_path: str | Path, after_path: str | Path) -> int:
    """Return collected assertion/test count after minus before."""
    return _read_assertion_count(Path(after_path)) - _read_assertion_count(Path(before_path))


def mock_skip_patterns(test_dir: Path) -> list[str]:
    """List test files containing mocking or skip constructs."""
    found: list[str] = []
    if not test_dir.is_dir():
        return found
    for path in sorted(test_dir.rglob("*")):
        if not path.is_file() or not _TEST_FILE_RE.match(path.name):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _SKIP_RE.search(text):
            found.append(str(path.relative_to(test_dir)))
    return found


def _test_listing(tree: str | Path) -> set[str]:
    path = Path(tree)
    if path.is_dir():
        return {
            str(candidate.relative_to(path))
            for candidate in path.rglob("*")
            if candidate.is_file() and _TEST_FILE_RE.match(candidate.name)
        }
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    return {
        line.strip()
        for line in text.splitlines()
        if line.strip() and _TEST_FILE_RE.search(Path(line.strip()).name)
    }


def deleted_test_files(before_tree: str | Path, after_tree: str | Path) -> list[str]:
    """Return test paths present in the baseline tree but absent afterwards."""
    return sorted(_test_listing(before_tree) - _test_listing(after_tree))


def _find_file(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def analyze(worktree: Path, baseline_path: Path) -> dict[str, Any]:
    """Run all weakening signals and cap the combined relative penalty at -2."""
    worktree, baseline_path = Path(worktree), Path(baseline_path)
    before_coverage = baseline_path if baseline_path.is_file() and _coverage_total(baseline_path) is not None else _find_file(baseline_path, ("coverage.json", ".coverage.json"))
    after_coverage = _find_file(worktree, ("coverage.json", ".coverage.json"))
    drop = coverage_drop(before_coverage, after_coverage) if before_coverage and after_coverage else 0.0

    before_assertions = baseline_path if baseline_path.is_file() and _read_assertion_count(baseline_path) else _find_file(baseline_path, ("pytest-collect-only.txt", "pytest-collect.txt", "collect-only.txt"))
    after_assertions = _find_file(worktree, ("pytest-collect-only.txt", "pytest-collect.txt", "collect-only.txt"))
    assertion_delta = assertion_count_diff(before_assertions, after_assertions) if before_assertions and after_assertions else 0

    baseline_tests = baseline_path / "tests" if baseline_path.is_dir() and (baseline_path / "tests").is_dir() else baseline_path
    current_tests = worktree / "tests" if (worktree / "tests").is_dir() else worktree
    skips = mock_skip_patterns(current_tests)
    deleted = deleted_test_files(baseline_tests, current_tests) if baseline_path.exists() else []

    signals: list[str] = []
    if drop > 0:
        signals.append("coverage_drop")
    if assertion_delta < 0:
        signals.append("assertion_drop")
    if skips:
        signals.append("mock_skip_patterns")
    if deleted:
        signals.append("deleted_test_files")
    penalty = max(-2, -len(signals))
    return {
        "coverage_drop_pct": drop,
        "assertion_delta": assertion_delta,
        "mock_skip_files": skips,
        "deleted_tests": deleted,
        "penalty": penalty,
        "signals_triggered": signals,
    }


__all__ = [
    "analyze",
    "assertion_count_diff",
    "coverage_drop",
    "deleted_test_files",
    "mock_skip_patterns",
]
