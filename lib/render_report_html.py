"""render_report_html.py -- Pure function to render eval + inspect markdown reports
as a single self-contained HTML document.

Reuses no external assets. No JavaScript. Inline CSS only. The output is
safe to email, archive, or open from `file://`. Defensive HTML escaping
on every interpolated value.

Mirror patterns: `lib/eval_runner.py:write_report` (input shape),
`eval/prompts/judge-code-sanity.md` (color scheme).
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

KST = timezone(timedelta(hours=9))

# Verdict -> CSS class. Used for both eval (OK / DRIFT_WARNING / ROT /
# SKIPPED) and inspect (Critical / Major drift / Minor drift / Healthy).
VERDICT_CLASS = {
    "OK": "verdict-ok",
    "DRIFT_WARNING": "verdict-warn",
    "ROT": "verdict-bad",
    "SKIPPED": "verdict-skip",
    "Critical": "verdict-bad",
    "Major drift": "verdict-warn",
    "Minor drift": "verdict-soft",
    "Healthy": "verdict-ok",
}

INLINE_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       max-width: 1100px; margin: 2rem auto; padding: 0 1.5rem; line-height: 1.5;
       color: #1a1a1a; background: #fafafa; }
@media (prefers-color-scheme: dark) {
  body { color: #e6e6e6; background: #1a1a1a; }
  .card { background: #242424; }
  table { background: #242424; }
  th { background: #2e2e2e; }
  tr:nth-child(even) td { background: #1f1f1f; }
}
h1 { border-bottom: 2px solid #888; padding-bottom: 0.5rem; }
h2 { margin-top: 2.5rem; border-bottom: 1px solid #ccc; padding-bottom: 0.3rem; }
h3 { margin-top: 1.5rem; }
.meta { color: #666; font-size: 0.9em; }
.cards { display: flex; flex-wrap: wrap; gap: 1rem; margin: 1rem 0; }
.card { background: white; border: 1px solid #ddd; border-radius: 6px;
        padding: 0.8rem 1.2rem; min-width: 140px; }
.card .label { font-size: 0.8em; color: #666; text-transform: uppercase;
               letter-spacing: 0.05em; }
.card .value { font-size: 1.8em; font-weight: 600; }
table { border-collapse: collapse; width: 100%; margin: 0.8rem 0;
        background: white; }
th, td { border: 1px solid #ddd; padding: 0.5rem 0.7rem; text-align: left; }
th { background: #f0f0f0; font-weight: 600; }
tr:nth-child(even) td { background: #f8f8f8; }
.bar { display: inline-block; height: 0.7em; background: #4a9eff;
       vertical-align: middle; border-radius: 2px; }
.finding { background: white; border: 1px solid #ddd; border-left: 4px solid #888;
           border-radius: 4px; padding: 0.6rem 1rem; margin: 0.5rem 0; }
.finding-high { border-left-color: #d33; }
.finding-med  { border-left-color: #e6a700; }
.finding-low  { border-left-color: #4a9eff; }
.finding pre { background: #f4f4f4; padding: 0.4rem 0.6rem; border-radius: 3px;
               overflow-x: auto; font-size: 0.9em; }
.verdict-ok    { color: #157a3a; font-weight: 600; }
.verdict-warn  { color: #a06400; font-weight: 600; }
.verdict-soft  { color: #7a5a00; }
.verdict-bad   { color: #b03030; font-weight: 600; }
.verdict-skip  { color: #888; }
.missing { background: #fff8e0; border: 1px solid #e0c060; border-radius: 4px;
           padding: 0.8rem 1rem; margin: 1rem 0; }
footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #ccc;
         color: #888; font-size: 0.85em; }
"""


def _esc(s: object) -> str:
    """Defensive HTML escape. Any non-string is coerced to str first."""
    return html.escape(str(s), quote=True)


def _now_iso() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %z")


def _parse_sections(md: str) -> Dict[str, str]:
    """Split markdown into sections keyed by '## ' or '### ' header text.

    Returns {header: body}. Body is text after the header line up to the
    next header (## or ###) or EOF. The top '# ' title (if any) is
    preserved as key '_title' (with the '# ' prefix stripped). Both
    '##' and '###' start a new section.
    """
    sections: Dict[str, List[str]] = {"_title": []}
    current: str = "_title"
    for line in md.splitlines():
        if line.startswith("## ") or line.startswith("### "):
            current = line.lstrip("# ").strip()
            sections[current] = []
        elif current == "_title" and line.startswith("# "):
            sections["_title"].append(line[2:].strip())
        else:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


# ---------- eval parsing ----------


def _parse_eval_summary(body: str) -> Dict[str, int]:
    """Pull 'Total cases / OK / DRIFT_WARNING / ROT / SKIPPED' from bullets."""
    out: Dict[str, int] = {}
    for line in body.splitlines():
        m = re.match(r"^[-*]\s+(\w+):\s*(\d+)\s*$", line.strip())
        if m:
            key, val = m.group(1), int(m.group(2))
            if key in ("Total", "OK", "DRIFT_WARNING", "ROT", "SKIPPED"):
                out[key] = val
    return out


def _parse_eval_per_dim(header: str, body: str) -> List[Tuple[str, int, float, List[Tuple[str, float]]]]:
    """Return [(dim, n, overall, [(axis, mean), ...])] from one '### dim' block.

    The dim name + counts come from the header line; the axes table
    comes from the body.
    """
    m = re.match(r"^(\w+)\s*\(n=(\d+),\s*overall=([0-9.]+)\)\s*$", header)
    if not m:
        return []
    dim, n, overall = m.group(1), int(m.group(2)), float(m.group(3))
    axes: List[Tuple[str, float]] = []
    for line in body.splitlines():
        am = re.match(r"^\|\s*`?(\w+)`?\s*\|\s*([0-9.]+)\s*\|\s*$", line)
        if am:
            axes.append((am.group(1), float(am.group(2))))
    return [(dim, n, overall, axes)]


def _parse_eval_per_case(body: str) -> List[Dict[str, str]]:
    """Parse '- **verdict** `case_id` (dim=...) score=N (axis1=N, ...)' lines."""
    out: List[Dict[str, str]] = []
    pat = re.compile(
        r"^[-*]\s+\*\*(\w+)\*\*\s+`([^`]+)`\s+\(dim=(\w+)\)\s+score=([0-9.]+)\s+\((.+)\)\s*$"
    )
    for line in body.splitlines():
        m = pat.match(line.strip())
        if m:
            out.append({
                "verdict": m.group(1),
                "case_id": m.group(2),
                "dim": m.group(3),
                "score": m.group(4),
                "axes": m.group(5),
            })
    return out


# ---------- inspect parsing ----------


def _parse_inspect_header(body: str) -> Dict[str, str]:
    """Pull '**Verdict:**', '**Coverage:**', '**Precision:**' from header body."""
    out: Dict[str, str] = {}
    for line in body.splitlines():
        m = re.match(r"^\*\*(\w+):\*\*\s+(.+?)\s*$", line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _parse_inspect_findings(body: str) -> List[Dict[str, str]]:
    """Parse '- [HIGH | CONFIRMED] title -- path:line' blocks into structured rows.

    The block continues with '  Dim: ...', '  TL;DR: ...', '  Scenario: ...',
    '  Fix: ...' lines until the next '- ' bullet or end of section.
    """
    findings: List[Dict[str, str]] = []
    current: Dict[str, str] | None = None
    bullet_re = re.compile(r"^- \[(\w+)\s*\|\s*(\w+)\]\s+(.+?)\s+--\s+(.+?)$")
    # Field regex: "  Key: value" -- the value stops at the next "--"
    # bullet separator, which is the only place the renderer ever
    # sees a stray "--" inside a finding block.
    field_re = re.compile(r"^\s{2,}([\w ;/]+?):\s+(.+)$")
    for line in body.splitlines():
        bm = bullet_re.match(line)
        if bm:
            if current is not None:
                findings.append(current)
            current = {
                "severity": bm.group(1),
                "confidence": bm.group(2),
                "title": bm.group(3),
                "anchor": bm.group(4),
                "Dim": "",
                "TL;DR": "",
                "Scenario": "",
                "Fix": "",
            }
            continue
        if current is not None:
            fm = field_re.match(line)
            if fm and fm.group(1) in ("Dim", "TL;DR", "Scenario", "Fix"):
                # Strip any trailing "--" fragment that may have leaked
                # from a malformed input line.
                val = fm.group(2).strip()
                if " -- " in val:
                    val = val.split(" -- ", 1)[0].strip()
                current[fm.group(1)] = val
            elif line.strip() == "":
                # blank line inside a finding block -- keep accumulating
                continue
            elif line.startswith("  ") and current.get("Scenario"):
                # continuation of last multi-line field
                pass
            elif line.startswith("- "):
                # new bullet -- flush current
                findings.append(current)
                current = None
    if current is not None:
        findings.append(current)
    return findings


def _parse_inspect_per_dim_table(body: str) -> List[Tuple[str, int, int, int]]:
    """Parse the '| dim | HIGH | MED | LOW |' table."""
    out: List[Tuple[str, int, int, int]] = []
    for line in body.splitlines():
        m = re.match(r"^\|\s*`?(\w+)`?\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*$", line)
        if m and m.group(1) not in ("dim", "---"):
            out.append((m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))))
    return out


# ---------- HTML renderers ----------


def _render_eval_cards(summary: Dict[str, int]) -> str:
    cells = []
    for label, key in (("Total", "Total"), ("OK", "OK"), ("Drift", "DRIFT_WARNING"),
                       ("ROT", "ROT"), ("Skipped", "SKIPPED")):
        v = summary.get(key, 0)
        cls = VERDICT_CLASS.get(key, "")
        cells.append(
            f'<div class="card"><div class="label">{_esc(label)}</div>'
            f'<div class="value {_esc(cls)}">{_esc(v)}</div></div>'
        )
    return '<div class="cards">' + "".join(cells) + "</div>"


def _render_eval_per_dim(per_dim_blocks: List[Tuple[str, int, float, List[Tuple[str, float]]]]) -> str:
    if not per_dim_blocks:
        return ""
    out = ['<table><tr><th>Dim</th><th>n</th><th>Overall</th><th>Axes</th></tr>']
    for dim, n, overall, axes in per_dim_blocks:
        axes_html = "<br>".join(
            f'`{_esc(ax)}` <span class="bar" style="width:{int(v*10)}px"></span> {_esc(v)}'
            for ax, v in axes
        )
        out.append(
            f"<tr><td><b>{_esc(dim)}</b></td><td>{_esc(n)}</td>"
            f"<td>{_esc(overall)}</td><td>{axes_html}</td></tr>"
        )
    out.append("</table>")
    return "".join(out)


def _render_eval_per_case(cases: List[Dict[str, str]]) -> str:
    if not cases:
        return '<p class="meta">No per-case results.</p>'
    out = ['<table><tr><th>Verdict</th><th>Case</th><th>Dim</th><th>Score</th><th>Axes</th></tr>']
    for c in cases:
        cls = VERDICT_CLASS.get(c["verdict"], "")
        out.append(
            f'<tr><td class="{_esc(cls)}">{_esc(c["verdict"])}</td>'
            f'<td><code>{_esc(c["case_id"])}</code></td>'
            f'<td>{_esc(c["dim"])}</td>'
            f'<td>{_esc(c["score"])}</td>'
            f'<td><code>{_esc(c["axes"])}</code></td></tr>'
        )
    out.append("</table>")
    return "".join(out)


def _render_inspect_findings(findings: List[Dict[str, str]]) -> str:
    if not findings:
        return '<p class="meta">No findings.</p>'
    out = []
    for f in findings:
        sev = f["severity"].lower()
        cls = {
            "high": "finding-high",
            "med": "finding-med",
            "medium": "finding-med",
            "low": "finding-low",
        }.get(sev, "")
        out.append(f'<div class="finding {_esc(cls)}">')
        out.append(
            f'<div><b>[{_esc(f["severity"])} | {_esc(f["confidence"])}]</b> '
            f'{_esc(f["title"])} '
            f'<code class="meta">{_esc(f["anchor"])}</code></div>'
        )
        if f.get("Dim"):
            out.append(f'<div class="meta"><b>Dim:</b> {_esc(f["Dim"])}</div>')
        if f.get("TL;DR"):
            out.append(f'<div><b>TL;DR:</b> {_esc(f["TL;DR"])}</div>')
        if f.get("Scenario"):
            out.append(f'<div><b>Scenario:</b> {_esc(f["Scenario"])}</div>')
        if f.get("Fix"):
            out.append(f'<div><b>Fix:</b> {_esc(f["Fix"])}</div>')
        out.append("</div>")
    return "".join(out)


def _render_inspect_per_dim(rows: List[Tuple[str, int, int, int]]) -> str:
    if not rows:
        return ""
    out = ['<table><tr><th>Dim</th><th>HIGH</th><th>MED</th><th>LOW</th></tr>']
    for dim, h, m, l in rows:
        out.append(
            f"<tr><td><b>{_esc(dim)}</b></td><td>{_esc(h)}</td>"
            f"<td>{_esc(m)}</td><td>{_esc(l)}</td></tr>"
        )
    out.append("</table>")
    return "".join(out)


# ---------- public API ----------


def render(eval_report_md: str, inspect_report_md: str, *, now: str | None = None) -> str:
    """Render two markdown reports as one self-contained HTML document.

    Both arguments may be empty strings; missing/empty inputs render a
    'not found' banner in the corresponding section rather than failing.

    Returns a UTF-8 HTML string. No I/O is performed.
    """
    eval_sections = _parse_sections(eval_report_md) if eval_report_md else {}
    inspect_sections = _parse_sections(inspect_report_md) if inspect_report_md else {}

    eval_summary = _parse_eval_summary(eval_sections.get("Summary", ""))
    # Per-dim blocks are ### sub-headers under '## Per-Dimension Scores'.
    # The new _parse_sections treats ### as a section break, so they
    # appear as their own top-level keys.
    eval_per_dim_blocks: List[Tuple[str, int, float, List[Tuple[str, float]]]] = []
    for header, body in eval_sections.items():
        if header in ("_title", "Summary", "Per-Dimension Scores", "Per-Case Results"):
            continue
        if not re.match(r"^[a-z]+\s*\(n=", header):
            continue
        parsed = _parse_eval_per_dim(header, body)
        eval_per_dim_blocks.extend(parsed)
    eval_per_case = _parse_eval_per_case(eval_sections.get("Per-Case Results", ""))

    if inspect_report_md:
        # The header body is everything in the _title section (it contains
        # the "**Verdict:** ..." block-quoted lines).
        inspect_header = _parse_inspect_header(inspect_sections.get("_title", ""))
        # Findings: any section whose header starts with HIGH/MED/LOW.
        inspect_findings_high: List[Dict[str, str]] = []
        inspect_findings_med: List[Dict[str, str]] = []
        inspect_findings_low: List[Dict[str, str]] = []
        for header, body in inspect_sections.items():
            if header.startswith("HIGH"):
                inspect_findings_high = _parse_inspect_findings(body)
            elif header.startswith("MED"):
                inspect_findings_med = _parse_inspect_findings(body)
            elif header.startswith("LOW"):
                inspect_findings_low = _parse_inspect_findings(body)
        inspect_per_dim = _parse_inspect_per_dim_table(
            inspect_sections.get("Per-dimension summary", "")
        )
    else:
        inspect_header = {}
        inspect_findings_high = []
        inspect_findings_med = []
        inspect_findings_low = []
        inspect_per_dim = []

    title = "dev-harness-kit -- Code Quality Report"
    parts: List[str] = []
    parts.append(f'<!DOCTYPE html>\n<html lang="en">\n<head>')
    parts.append(f'<meta charset="utf-8">')
    parts.append(f'<title>{_esc(title)}</title>')
    parts.append(f'<style>{INLINE_CSS}</style>')
    parts.append('</head>\n<body>')
    parts.append(f'<h1>{_esc(title)}</h1>')
    parts.append(f'<p class="meta">Generated {_esc(now or _now_iso())}</p>')

    # ---- eval section ----
    parts.append('<h2>Eval</h2>')
    if not eval_report_md:
        parts.append('<div class="missing">No eval report found at '
                     '<code>.dev-kit/eval-report.md</code>. Run '
                     '<code>/dev-kit:eval</code> first.</div>')
    else:
        parts.append(_render_eval_cards(eval_summary))
        if eval_per_dim_blocks:
            parts.append('<h3>Per-dimension scores</h3>')
            parts.append(_render_eval_per_dim(eval_per_dim_blocks))
        if eval_per_case:
            parts.append('<h3>Per-case results</h3>')
            parts.append(_render_eval_per_case(eval_per_case))

    # ---- inspect section ----
    parts.append('<h2>Inspect</h2>')
    if not inspect_report_md:
        parts.append('<div class="missing">No inspect report found at '
                     '<code>.dev-kit/inspect-report.md</code>. Run '
                     '<code>/dev-kit:inspect</code> first.</div>')
    else:
        verdict = inspect_header.get("Verdict", "Unknown")
        verdict_cls = VERDICT_CLASS.get(verdict, "")
        parts.append(f'<p><b>Verdict:</b> <span class="{_esc(verdict_cls)}">{_esc(verdict)}</span></p>')
        coverage = inspect_header.get("Coverage", "")
        precision = inspect_header.get("Precision", "")
        if coverage:
            parts.append(f'<p class="meta"><b>Coverage:</b> {_esc(coverage)}</p>')
        if precision:
            parts.append(f'<p class="meta"><b>Precision:</b> {_esc(precision)}</p>')
        if inspect_per_dim:
            parts.append('<h3>Per-dimension</h3>')
            parts.append(_render_inspect_per_dim(inspect_per_dim))
        if inspect_findings_high:
            parts.append(f'<h3>HIGH ({len(inspect_findings_high)})</h3>')
            parts.append(_render_inspect_findings(inspect_findings_high))
        if inspect_findings_med:
            parts.append(f'<h3>MED ({len(inspect_findings_med)})</h3>')
            parts.append(_render_inspect_findings(inspect_findings_med))
        if inspect_findings_low:
            parts.append(f'<h3>LOW ({len(inspect_findings_low)})</h3>')
            parts.append(_render_inspect_findings(inspect_findings_low))

    # ---- footer ----
    parts.append('<footer>Generated by <code>/dev-kit:report</code>. '
                 'No external assets, no JavaScript.</footer>')
    parts.append('</body>\n</html>\n')
    return "".join(parts)
