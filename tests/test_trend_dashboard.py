"""test_trend_dashboard.py — smoke test for the trend dashboard HTML output."""
from __future__ import annotations

import io
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.trend_dashboard import (
    DimPoint,
    _load_points,
    _rolling_weekly,
    _trend_slope,
    main,
    render_html,
)

FIXTURE = Path(__file__).parent / "fixtures" / "agent-behavior" / "history-sample" / "history.jsonl"


def test_load_points_smoke() -> None:
    if not FIXTURE.is_file():
        pytest.skip("history-sample fixture missing")
    by_dim, earliest, latest = _load_points(FIXTURE)
    # Fixture covers 7 days (Jul 25 → Aug 1, all UTC).
    assert earliest is not None and latest is not None
    assert (latest - earliest).days >= 6
    assert "D1_outcome" in by_dim
    assert any(p.value == 4 for p in by_dim["D1_outcome"])


def test_rolling_weekly_groups_by_week() -> None:
    if not FIXTURE.is_file():
        pytest.skip("history-sample fixture missing")
    by_dim, earliest, latest = _load_points(FIXTURE)
    if earliest is None or latest is None:
        pytest.skip("no data points")
    series = _rolling_weekly(by_dim["D1_outcome"], earliest, latest)
    assert len(series) >= 1
    # Each entry is (window_start_iso, mean_value).
    for key, mean_val in series:
        assert "T" in key
        assert 1.0 <= mean_val <= 5.0


def test_trend_slope_classification() -> None:
    assert _trend_slope([("a", 3.0), ("b", 5.0)]) == "increasing"
    assert _trend_slope([("a", 5.0), ("b", 3.0)]) == "decreasing"
    assert _trend_slope([("a", 4.0), ("b", 4.02)]) == "flat"
    assert _trend_slope([]) == "flat"
    assert _trend_slope([("a", 4.0)]) == "flat"


def test_render_html_emits_full_page() -> None:
    if not FIXTURE.is_file():
        pytest.skip("history-sample fixture missing")
    by_dim, earliest, latest = _load_points(FIXTURE)
    html = render_html(by_dim, earliest, latest, FIXTURE)
    assert "<!doctype html>" in html.lower()
    assert "Behavior Trend Dashboard" in html
    assert "1-week rolling average" in html
    assert "<svg" in html or "Not enough data" in html


def test_main_writes_to_stdout() -> None:
    if not FIXTURE.is_file():
        pytest.skip("history-sample fixture missing")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main([str(FIXTURE)])
    assert rc == 0
    out = buf.getvalue()
    assert "<!doctype html>" in out.lower()
    # Output must be non-empty HTML.
    assert len(out) > 1_000


def test_load_points_handles_missing_file(tmp_path: Path) -> None:
    by_dim, earliest, latest = _load_points(tmp_path / "missing.jsonl")
    assert by_dim == {}
    assert earliest is None
    assert latest is None


def test_render_html_minimal() -> None:
    """Empty data still produces a valid page."""
    html = render_html({}, None, None, Path("/dev/null"))
    assert "<!doctype html>" in html.lower()
    assert "Behavior Trend Dashboard" in html


def test_render_html_with_one_dim_one_point() -> None:
    """Single point → no SVG but the row still renders."""
    points = [DimPoint(ts=datetime(2026, 7, 25, tzinfo=timezone.utc), value=4)]
    html = render_html({"D1_outcome": points}, points[0].ts, points[0].ts, Path("/dev/null"))
    assert "D1_outcome" in html
    assert "Not enough data" in html or "<svg" not in html
