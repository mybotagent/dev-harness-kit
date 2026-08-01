"""test_history.py — JSONL append + atomic write + iteration."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib.behavior_scorers.aggregate import compute
from lib.behavior_scorers.history import append_history, iter_history
from lib.behavior_scorers.types import DimensionScore


def _make_report(case_id: str, weighted_mean: float = 4.0):
    scores = (
        DimensionScore(dim="D1_outcome", value=4, evidence={}),
        DimensionScore(dim="D2_process", value=4, evidence={}),
        DimensionScore(dim="D3_efficiency", value=4, evidence={}),
        DimensionScore(dim="D4_safety", value=4, evidence={}),
        DimensionScore(dim="D5_communication", value=4, evidence={}),
        DimensionScore(dim="D6_robustness", value=4, evidence={}),
        DimensionScore(dim="D7_trajectory", value=4, evidence={}),
        DimensionScore(dim="D8_reversibility", value=4, evidence={}),
        DimensionScore(dim="D9_side_effects", value=4, evidence={}),
    )
    return compute(
        case_id=case_id,
        worktree="/tmp/wt",
        dim_scores=scores,
        weights={s.dim: 1 / 9 for s in scores},
    )


def test_append_creates_file(tmp_path: Path) -> None:
    hist = tmp_path / "history.jsonl"
    assert not hist.exists()
    report = _make_report("c1")
    append_history(report, hist)
    assert hist.is_file()
    lines = hist.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["case_id"] == "c1"
    assert "logged_at" in record


def test_append_multiple_lines(tmp_path: Path) -> None:
    hist = tmp_path / "history.jsonl"
    for i in range(5):
        append_history(_make_report(f"c{i}"), hist)
    lines = hist.read_text().strip().splitlines()
    assert len(lines) == 5
    for i, line in enumerate(lines):
        record = json.loads(line)
        assert record["case_id"] == f"c{i}"


def test_append_uses_explicit_timestamp(tmp_path: Path) -> None:
    hist = tmp_path / "history.jsonl"
    append_history(_make_report("c1"), hist, logged_at="2026-01-01T00:00:00Z")
    record = json.loads(hist.read_text().strip())
    assert record["logged_at"] == "2026-01-01T00:00:00Z"


def test_atomic_write_no_partial_file(tmp_path: Path) -> None:
    """After append_history, no .tmp sibling remains."""
    hist = tmp_path / "history.jsonl"
    append_history(_make_report("c1"), hist)
    siblings = list(tmp_path.iterdir())
    # The new implementation uses O_APPEND + fsync (no .tmp file).
    leftover_tmps = [
        p for p in siblings
        if p.name.startswith("history.jsonl.") and p.name.endswith(".tmp")
    ]
    assert leftover_tmps == []


def test_iter_history_yields_dicts(tmp_path: Path) -> None:
    hist = tmp_path / "history.jsonl"
    append_history(_make_report("a"), hist)
    append_history(_make_report("b"), hist)
    records = list(iter_history(hist))
    assert len(records) == 2
    assert records[0]["case_id"] == "a"
    assert records[1]["case_id"] == "b"


def test_iter_history_skips_blank_and_garbage(tmp_path: Path) -> None:
    hist = tmp_path / "history.jsonl"
    hist.write_text(
        "\n"
        + json.dumps({"case_id": "good1", "dimension_scores": []}) + "\n"
        + "this is not json\n"
        + "   \n"
        + json.dumps({"case_id": "good2", "dimension_scores": []}) + "\n"
    )
    records = list(iter_history(hist))
    assert len(records) == 2
    assert records[0]["case_id"] == "good1"
    assert records[1]["case_id"] == "good2"


def test_iter_history_missing_file(tmp_path: Path) -> None:
    hist = tmp_path / "missing.jsonl"
    # Should yield nothing, not raise.
    assert list(iter_history(hist)) == []


def test_append_refuses_symlink(tmp_path: Path) -> None:
    """append_history refuses to write through a symlink."""
    target = tmp_path / "real.jsonl"
    target.write_text("")  # exists but we want to refuse if path IS a symlink
    link = tmp_path / "link.jsonl"
    # Create a real symlink to something benign.
    if hasattr(os, "symlink"):
        try:
            os.symlink(str(target), str(link))
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
    # Function returns without raising AND without modifying target.
    report = _make_report("c1")
    append_history(report, link)
    assert target.read_text() == ""


def test_iter_history_refuses_symlink(tmp_path: Path) -> None:
    """iter_history refuses to read through a symlink (returns no records)."""
    target = tmp_path / "real.jsonl"
    target.write_text(json.dumps({"case_id": "x"}) + "\n")
    link = tmp_path / "link.jsonl"
    if hasattr(os, "symlink"):
        try:
            os.symlink(str(target), str(link))
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
    assert list(iter_history(link)) == []


def test_append_creates_parent_directory(tmp_path: Path) -> None:
    hist = tmp_path / "deep" / "nested" / "history.jsonl"
    assert not hist.parent.exists()
    append_history(_make_report("c1"), hist)
    assert hist.is_file()
