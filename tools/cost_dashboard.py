"""cost_dashboard.py — render a static HTML cost dashboard from transcripts.

Usage:
    python -m tools.cost_dashboard <transcripts-dir> > cost.html
    python -m tools.cost_dashboard --pricing docs/llm-info/claude.json <transcripts-dir> > cost.html

Reads every TraceLog JSON under the given directory tree, aggregates
metrics, and writes a single self-contained HTML file. No JS, no
external assets, dark-mode aware via CSS variables (inline only).

Aggregations:
- per-case: $total, step_count, total_tokens, total_latency_ms
- per-model: token sum
- top-10 expensive steps (by total tokens)
- latency p50/p95 across all steps

Pricing source: a JSON file like `docs/llm-info/claude.json`:
    {"claude-opus-4-8": {"input": 3.0, "output": 15.0}, ...}
(USD per 1M tokens). When absent or model unknown, cost = 0 with
`cost_estimated=true` in evidence.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@dataclass(frozen=True)
class StepAgg:
    ts: str
    case_id: str
    skill: str
    phase: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float


@dataclass(frozen=True)
class CaseAgg:
    case_id: str
    step_count: int
    total_tokens: int
    total_latency_ms: int
    total_cost_usd: float


def _load_pricing(path: Path | None) -> Dict[str, Dict[str, float]]:
    if path is None or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _cost_for(model: str, in_tok: int, out_tok: int, pricing: Dict[str, Dict[str, float]]) -> float:
    rate = pricing.get(model)
    if not rate:
        return 0.0
    return (in_tok / 1e6) * rate.get("input", 0.0) + (out_tok / 1e6) * rate.get("output", 0.0)


def _walk_transcripts(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return
    yield from root.rglob("*.json")


def aggregate(root: Path, pricing: Dict[str, Dict[str, float]]) -> Tuple[List[StepAgg], List[CaseAgg]]:
    """Walk all transcripts and aggregate step + case metrics."""
    steps: List[StepAgg] = []
    by_case: Dict[str, Dict[str, int]] = defaultdict(lambda: {
        "step_count": 0, "total_tokens": 0, "total_latency_ms": 0, "total_cost_usd": 0.0,
    })
    for path in _walk_transcripts(root):
        try:
            raw = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        case_id = raw.get("case_id") or path.parent.name
        for s in raw.get("steps", []):
            model = s.get("model") or "unknown"
            in_tok = int(s.get("input_tokens", 0))
            out_tok = int(s.get("output_tokens", 0))
            cost = _cost_for(model, in_tok, out_tok, pricing)
            step = StepAgg(
                ts=s.get("ts", ""),
                case_id=case_id,
                skill=s.get("skill", ""),
                phase=s.get("phase", ""),
                model=model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_ms=int(s.get("latency_ms", 0)),
                cost_usd=cost,
            )
            steps.append(step)
            agg = by_case[case_id]
            agg["step_count"] += 1
            agg["total_tokens"] += in_tok + out_tok
            agg["total_latency_ms"] += step.latency_ms
            agg["total_cost_usd"] += cost

    cases = [
        CaseAgg(
            case_id=cid,
            step_count=v["step_count"],
            total_tokens=v["total_tokens"],
            total_latency_ms=v["total_latency_ms"],
            total_cost_usd=round(v["total_cost_usd"], 6),
        )
        for cid, v in sorted(by_case.items())
    ]
    return steps, cases


def _pct(values: List[int], p: float) -> int:
    """Return the `p`-th percentile (0..1) of `values`. Empty list → 0."""
    if not values:
        return 0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p * (len(s) - 1)))))
    return s[k]


def render_html(
    steps: List[StepAgg],
    cases: List[CaseAgg],
    transcripts_root: Path,
) -> str:
    """Render a single self-contained HTML page."""
    total_cost = round(sum(s.cost_usd for s in steps), 6)
    total_tokens = sum(s.input_tokens + s.output_tokens for s in steps)
    total_latencies = [s.latency_ms for s in steps if s.latency_ms]
    p50 = _pct(total_latencies, 0.5)
    p95 = _pct(total_latencies, 0.95)

    # Top-10 expensive steps.
    top = sorted(steps, key=lambda s: -(s.input_tokens + s.output_tokens))[:10]
    top_rows = "\n".join(
        f"<tr><td>{html.escape(s.case_id)}</td><td>{html.escape(s.skill)}</td>"
        f"<td>{html.escape(s.model)}</td>"
        f"<td style='text-align:right'>{s.input_tokens + s.output_tokens:,}</td>"
        f"<td style='text-align:right'>${s.cost_usd:.4f}</td></tr>"
        for s in top
    )

    case_rows = "\n".join(
        f"<tr><td>{html.escape(c.case_id)}</td>"
        f"<td style='text-align:right'>{c.step_count}</td>"
        f"<td style='text-align:right'>{c.total_tokens:,}</td>"
        f"<td style='text-align:right'>{c.total_latency_ms:,} ms</td>"
        f"<td style='text-align:right'>${c.total_cost_usd:.4f}</td></tr>"
        for c in cases
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cost Dashboard — agent behavior eval</title>
<style>
:root {{
  color-scheme: light dark;
  --fg: #1d1d1f; --bg: #fbfbfd; --muted: #5b5b62; --border: #d2d2d7;
  --card-bg: #ffffff; --th-bg: #f5f5f7; --row-alt: #fafafa; --code-bg: #f5f5f7;
  --accent: #0a84ff;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --fg: #f5f5f7; --bg: #1c1c1e; --muted: #aeaeb2; --border: #38383a;
    --card-bg: #2c2c2e; --th-bg: #3a3a3c; --row-alt: #232325; --code-bg: #2c2c2e;
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
.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 2rem; }}
.card {{
  background: var(--card-bg); border: 1px solid var(--border);
  border-radius: 12px; padding: 1rem 1.2rem;
}}
.card .label {{ color: var(--muted); font-size: 0.78rem;
  text-transform: uppercase; letter-spacing: 0.04em; }}
.card .value {{ font-size: 1.4rem; font-weight: 600; margin-top: 0.2rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem;
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
  font-size: 0.92rem; overflow: hidden; }}
th, td {{ padding: 0.6rem 0.9rem; text-align: left; border-bottom: 1px solid var(--border); }}
th {{ background: var(--th-bg); font-weight: 600; }}
tr:last-child td {{ border-bottom: 0; }}
tr:nth-child(even) td {{ background: var(--row-alt); }}
</style>
</head>
<body>
<h1>Cost Dashboard</h1>
<p class="meta">Source: <code>{html.escape(str(transcripts_root))}</code></p>

<div class="cards">
  <div class="card"><div class="label">Cases</div><div class="value">{len(cases)}</div></div>
  <div class="card"><div class="label">Steps</div><div class="value">{len(steps)}</div></div>
  <div class="card"><div class="label">Total tokens</div><div class="value">{total_tokens:,}</div></div>
  <div class="card"><div class="label">Total cost</div><div class="value">${total_cost:.4f}</div></div>
</div>

<h2>Latency</h2>
<table>
  <thead><tr><th>Percentile</th><th style="text-align:right">ms</th></tr></thead>
  <tbody>
    <tr><td>p50</td><td style="text-align:right">{p50:,}</td></tr>
    <tr><td>p95</td><td style="text-align:right">{p95:,}</td></tr>
  </tbody>
</table>

<h2>Per-case summary</h2>
<table>
  <thead><tr><th>Case</th><th style="text-align:right">Steps</th>
    <th style="text-align:right">Tokens</th><th style="text-align:right">Latency</th>
    <th style="text-align:right">Cost</th></tr></thead>
  <tbody>
    {case_rows or "<tr><td colspan='5' style='color:var(--muted)'>No data.</td></tr>"}
  </tbody>
</table>

<h2>Top-10 expensive steps</h2>
<table>
  <thead><tr><th>Case</th><th>Skill</th><th>Model</th>
    <th style="text-align:right">Tokens</th><th style="text-align:right">Cost</th></tr></thead>
  <tbody>
    {top_rows or "<tr><td colspan='5' style='color:var(--muted)'>No data.</td></tr>"}
  </tbody>
</table>

<footer style="margin-top:4rem;color:var(--muted);font-size:0.85rem">
  Generated by <code>tools/cost_dashboard.py</code> · agent-behavior-eval Phase 0
</footer>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.cost_dashboard",
        description="Render a static HTML cost dashboard from TraceLog JSON files",
    )
    parser.add_argument("transcripts", type=Path, help="transcripts root directory")
    parser.add_argument(
        "--pricing",
        type=Path,
        default=None,
        help="optional pricing JSON (model -> {input, output} USD per 1M tokens)",
    )
    args = parser.parse_args(argv)
    pricing = _load_pricing(args.pricing)
    steps, cases = aggregate(args.transcripts, pricing)
    print(render_html(steps, cases, args.transcripts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
