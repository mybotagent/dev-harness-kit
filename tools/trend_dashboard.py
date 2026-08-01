"""trend_dashboard.py — render a static HTML trend dashboard from history.

Usage:
    python -m tools.trend_dashboard .dev-kit/agent-behavior-history.jsonl > trends.html

Reads the append-only JSONL history produced by
`lib.behavior_scorers.history.append_history()`. Computes 1-week
rolling averages per dimension (calendar-week boundary, UTC) and
emits a single self-contained HTML file. No JS, no external assets.

The dashboard renders:
- A summary header (cases, windows, span).
- One SVG line chart per dimension that has >= 2 reports in the file.
- A summary table of per-dim trend slope (last 2 weeks → positive /
  negative / flat).

Deterministic: same input JSONL → identical HTML. No LLM, no network.
"""
from __future__ import annotations

import argparse
import html
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.behavior_scorers.history import iter_history  # noqa: E402

_WINDOW_DAYS = 7


@dataclass(frozen=True)
class DimPoint:
    """One dimension's value at a given timestamp."""
    ts: datetime
    value: int


def _parse_ts(raw: str) -> datetime | None:
    """Parse ISO-8601 timestamp; return None on failure."""
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _window_key(ts: datetime) -> str:
    """Return the calendar-week start (Monday 00:00 UTC) for `ts`."""
    monday = ts - timedelta(days=ts.weekday(), hours=ts.hour,
                            minutes=ts.minute, seconds=ts.second,
                            microseconds=ts.microsecond)
    return monday.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_points(history_path: Path) -> Tuple[Dict[str, List[DimPoint]], datetime | None, datetime | None]:
    """Read the JSONL log and bucket each dim's value by logged_at."""
    by_dim: Dict[str, List[DimPoint]] = defaultdict(list)
    earliest: datetime | None = None
    latest: datetime | None = None

    for record in iter_history(history_path):
        ts = _parse_ts(record.get("logged_at", ""))
        if ts is None:
            continue
        earliest = ts if earliest is None else min(earliest, ts)
        latest = ts if latest is None else max(latest, ts)
        for s in record.get("dimension_scores", []):
            dim = s.get("dim")
            value = s.get("value")
            if not isinstance(dim, str) or not isinstance(value, (int, float)):
                continue
            by_dim[dim].append(DimPoint(ts=ts, value=int(value)))

    for points in by_dim.values():
        points.sort(key=lambda p: p.ts)
    return dict(by_dim), earliest, latest


def _rolling_weekly(
    points: List[DimPoint],
    earliest: datetime,
    latest: datetime,
) -> List[Tuple[str, float]]:
    """Compute the mean per 1-week rolling window.

    Each window starts at the floor of the timestamp's calendar week.
    Windows with no records are skipped.
    """
    bucket: Dict[str, List[int]] = defaultdict(list)
    for p in points:
        key = _window_key(p.ts)
        bucket[key].append(p.value)
    out: List[Tuple[str, float]] = []
    for key in sorted(bucket.keys()):
        vals = bucket[key]
        out.append((key, round(sum(vals) / len(vals), 3)))
    return out


def _trend_slope(series: List[Tuple[str, float]]) -> str:
    """Classify the last-2-windows slope.

    Returns 'increasing', 'decreasing', or 'flat'. Series with fewer
    than 2 points returns 'flat'.
    """
    if len(series) < 2:
        return "flat"
    a = series[-2][1]
    b = series[-1][1]
    delta = b - a
    if delta > 0.05:
        return "increasing"
    if delta < -0.05:
        return "decreasing"
    return "flat"


def _svg_line_chart(series: List[Tuple[str, float]], dim: str) -> str:
    """Render an inline SVG line chart for one dim's series."""
    if len(series) < 2:
        return ""

    width = 600
    height = 120
    pad = 24
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad

    y_min = 1.0
    y_max = 5.0
    span = max(0.01, y_max - y_min)

    def _x(i: int) -> float:
        if len(series) == 1:
            return pad + inner_w / 2
        return pad + (inner_w * i / (len(series) - 1))

    def _y(v: float) -> float:
        return pad + inner_h * (1.0 - (v - y_min) / span)

    points = " ".join(
        f"{_x(i):.1f},{_y(v):.1f}" for i, (_, v) in enumerate(series)
    )

    # Grid lines at integer dim values 1..5.
    grid_lines = "".join(
        f"<line x1='{pad}' y1='{_y(v):.1f}' x2='{width - pad}' y2='{_y(v):.1f}' "
        f"stroke='var(--border)' stroke-dasharray='2 4'/>"
        for v in (1, 2, 3, 4, 5)
    )
    y_labels = "".join(
        f"<text x='{pad - 4}' y='{_y(v):.1f}' text-anchor='end' "
        f"dominant-baseline='middle' font-size='10' fill='var(--muted)'>{v}</text>"
        for v in (1, 2, 3, 4, 5)
    )

    # X-axis labels: first and last window.
    x_label_first = (
        f"<text x='{pad}' y='{height - 4}' font-size='10' fill='var(--muted)'>"
        f"{html.escape(series[0][0][:10])}</text>"
    )
    x_label_last = (
        f"<text x='{width - pad}' y='{height - 4}' text-anchor='end' "
        f"font-size='10' fill='var(--muted)'>{html.escape(series[-1][0][:10])}</text>"
    )

    return (
        f"<figure class='chart'>"
        f"<figcaption>{html.escape(dim)}</figcaption>"
        f"<svg viewBox='0 0 {width} {height}' preserveAspectRatio='xMidYMid meet' "
        f"role='img' aria-label='Trend chart for {html.escape(dim)}'>"
        f"{grid_lines}{y_labels}{x_label_first}{x_label_last}"
        f"<polyline points='{points}' fill='none' stroke='var(--accent)' "
        f"stroke-width='2'/>"
        f"</svg></figure>"
    )


def render_html(
    by_dim: Dict[str, List[DimPoint]],
    earliest: datetime | None,
    latest: datetime | None,
    history_path: Path,
) -> str:
    """Render the entire dashboard as a single self-contained HTML page."""
    charts: List[str] = []
    rows: List[str] = []
    all_series: List[List[Tuple[str, float]]] = []
    if earliest and latest:
        for dim in sorted(by_dim.keys()):
            series = _rolling_weekly(by_dim[dim], earliest, latest)
            all_series.append(series)
            if len(series) >= 2:
                charts.append(_svg_line_chart(series, dim))
            slope = _trend_slope(series)
            arrow = {"increasing": "↗", "decreasing": "↘", "flat": "→"}.get(slope, "→")
            rows.append(
                f"<tr><td><code>{html.escape(dim)}</code></td>"
                f"<td style='text-align:right'>{len(by_dim[dim])}</td>"
                f"<td style='text-align:right'>{len(series)}</td>"
                f"<td style='text-align:right'>{html.escape(arrow)} {slope}</td></tr>"
            )

    n_reports_total = sum(len(v) for v in by_dim.values())
    span = (
        f"{(latest - earliest).days + 1} days"
        if (earliest and latest) else "0 days"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Behavior Trend Dashboard</title>
<style>
:root {{
  color-scheme: light dark;
  --fg: #1d1d1f; --bg: #fbfbfd; --muted: #5b5b62; --border: #d2d2d7;
  --card-bg: #ffffff; --th-bg: #f5f5f7; --row-alt: #fafafa;
  --accent: #0a84ff;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --fg: #f5f5f7; --bg: #1c1c1e; --muted: #aeaeb2; --border: #38383a;
    --card-bg: #2c2c2e; --th-bg: #3a3a3c; --row-alt: #232325;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif;
  max-width: 980px; margin: 0 auto; padding: 3rem 1.5rem 5rem;
  line-height: 1.6; color: var(--fg); background: var(--bg);
  -webkit-font-smoothing: antialiased;
}}
h1 {{ font-size: 2rem; margin: 0 0 0.4rem; }}
.meta {{ color: var(--muted); font-size: 0.92rem; margin: 0 0 2rem; }}
.cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 2rem; }}
.card {{
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 12px; padding: 1rem 1.2rem;
}}
.card .label {{ color: var(--muted); font-size: 0.78rem;
  text-transform: uppercase; letter-spacing: 0.04em; }}
.card .value {{ font-size: 1.4rem; font-weight: 600; margin-top: 0.2rem; }}
.chart {{
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 12px; padding: 0.8rem 1rem; margin: 0 0 1rem;
}}
.chart figcaption {{ color: var(--muted); font-size: 0.85rem;
  text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 0.4rem; }}
.chart svg {{ width: 100%; height: auto; display: block; }}
table {{ border-collapse: collapse; width: 100%; margin: 1.5rem 0;
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 8px; font-size: 0.92rem; overflow: hidden; }}
th, td {{ padding: 0.6rem 0.9rem; text-align: left; border-bottom: 1px solid var(--border); }}
th {{ background: var(--th-bg); font-weight: 600; }}
tr:last-child td {{ border-bottom: 0; }}
tr:nth-child(even) td {{ background: var(--row-alt); }}
footer {{ margin-top: 4rem; color: var(--muted); font-size: 0.85rem; }}
</style>
</head>
<body>
<h1>Behavior Trend Dashboard</h1>
<p class="meta">
  Source: <code>{html.escape(str(history_path))}</code> ·
  Rolling window: {_WINDOW_DAYS} days
</p>

<div class="cards">
  <div class="card"><div class="label">Total reports</div>
    <div class="value">{n_reports_total}</div></div>
  <div class="card"><div class="label">Dimensions</div>
    <div class="value">{len(by_dim)}</div></div>
  <div class="card"><div class="label">Span</div>
    <div class="value">{html.escape(span)}</div></div>
</div>

<h2>1-week rolling average per dimension</h2>
{(''.join(charts) if charts else "<p class='meta'>Not enough data yet (need ≥ 2 reports per dim).</p>")}

<h2>Trend (last 2 windows)</h2>
<table>
  <thead><tr><th>Dim</th><th style="text-align:right">Reports</th>
    <th style="text-align:right">Windows</th><th style="text-align:right">Slope</th></tr></thead>
  <tbody>
    {''.join(rows) or "<tr><td colspan='4' style='color:var(--muted)'>No data.</td></tr>"}
  </tbody>
</table>

<footer>Generated by <code>tools/trend_dashboard.py</code> · agent-behavior-eval R3</footer>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.trend_dashboard",
        description="Render a static HTML 1-week-rolling trend dashboard from a behavior history JSONL log",
    )
    parser.add_argument(
        "history", type=Path,
        help="path to the agent-behavior-history.jsonl file",
    )
    args = parser.parse_args(argv)
    by_dim, earliest, latest = _load_points(args.history)
    print(render_html(by_dim, earliest, latest, args.history))
    return 0


if __name__ == "__main__":
    sys.exit(main())
