#!/usr/bin/env python3
"""Render `tools/session_monitor.py --list` output to a README-friendly PNG.

Runs the CLI in non-interactive `--list` mode against the captured logs,
wraps the ANSI-coloured output in a minimal HTML shell (monospace,
auto-sizing, no JavaScript), and screenshots it via Playwright + Chrome.

Used to regenerate ``docs/screenshots/session-monitor.png`` so the README
preview stays in sync with the latest session-monitor output.

Requires:
- Python 3.10+
- ``playwright`` (``pip install playwright && playwright install chromium``)
- Google Chrome installed at a path Playwright's ``channel="chrome"`` can find
  (e.g. ``/Applications/Google Chrome.app`` on macOS).

Usage::

    python3 tools/render_session_monitor.py [--repo NAME] [--days N] \
        [png_path] [viewport_w]

Examples (regenerate the screenshot shown in README.md)::

    # Default: repo=dev-harness-kit, days=30, output=docs/screenshots/session-monitor.png
    python3 tools/render_session_monitor.py

    # Custom window
    python3 tools/render_session_monitor.py --days 7 docs/screenshots/session-monitor-7d.png
"""
from __future__ import annotations

import argparse
import html
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# ANSI SGR -> CSS color map. Mirrors session_monitor_format._STATUS_COLOR
# and session_monitor_picker._ANSI closely enough for the rendered output.
_ANSI_COLOR = {
    "30": "color: #1f2328",          # black (used for muted rows)
    "31": "color: #cf222e",          # red (live)
    "32": "color: #1a7f37",          # green (idle / success)
    "33": "color: #9a6700",          # yellow (warning / stale)
    "34": "color: #0969da",          # blue (info)
    "35": "color: #8250df",          # magenta
    "36": "color: #1b7c83",          # cyan (branch / paths)
    "37": "color: #6e7781",          # grey (muted)
    "90": "color: #6e7781",          # bright black
    "91": "color: #cf222e",
    "92": "color: #1a7f37",
    "93": "color: #9a6700",
    "94": "color: #0969da",
    "95": "color: #8250df",
    "96": "color: #1b7c83",
    "97": "color: #1f2328",
}


def _ansi_to_html(text: str) -> str:
    """Convert ANSI-coloured stdout to inline-styled HTML.

    Preserves the leading whitespace (the listing is column-aligned) by
    wrapping the whole document in a ``<pre>`` and converting only the SGR
    escape sequences to inline ``<span style=...>``.
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\x1b" and i + 1 < len(text) and text[i + 1] == "[":
            # CSI sequence: ESC [ ... letter
            j = i + 2
            while j < len(text) and text[j] not in "ABCDEFGHJKSTfmnsulh":
                j += 1
            if j < len(text):
                params = text[i + 2:j]
                final = text[j]
                if final == "m":
                    # SGR (colour/style)
                    if params in ("", "0", "00"):
                        out.append("</span>")
                    else:
                        # First colour code wins; ignore secondary ones
                        # (the source uses compound sequences like 1;36)
                        head = params.split(";")[0]
                        style = _ANSI_COLOR.get(head, "")
                        out.append(f'<span style="{style}">' if style else "<span>")
                # Other CSI finals (cursor moves, clear-line) are dropped.
                i = j + 1
                continue
        if ch == "\n":
            out.append("\n")
        elif ch == " ":
            out.append(" ")
        elif ch == "\t":
            out.append("    ")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        elif ch == "&":
            out.append("&amp;")
        else:
            out.append(html.escape(ch))
        i += 1
    return "".join(out)


_HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>session-monitor --list</title>
<style>
  html, body {{
    margin: 0;
    padding: 0;
    background: #0d1117;
    color: #e6edf3;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
    font-size: 14px;
    line-height: 1.45;
  }}
  .frame {{
    padding: 22px 28px;
    max-width: {width}px;
    box-sizing: border-box;
  }}
  pre {{
    margin: 0;
    white-space: pre;
    overflow-x: auto;
  }}
</style>
</head><body><div class="frame"><pre>{body}</pre></div></body></html>
"""


def _build_html(stdout: str, viewport_w: int) -> str:
    return _HTML_TEMPLATE.format(width=viewport_w - 56, body=_ansi_to_html(stdout))


def _run_session_monitor(repo: str, days: int) -> str:
    """Run ``tools/session_monitor.py --list`` and capture stdout."""
    cmd = [
        sys.executable,
        "tools/session_monitor.py",
        "--list",
        "--repo", repo,
        "--days", str(days),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    # The CLI writes a [session-monitor] N sessions banner to stderr but the
    # body goes to stdout. Combine so the screenshot reflects what a user
    # would see in their terminal.
    return proc.stdout


def render(png_path: Path, repo: str, days: int, viewport_w: int = 1200,
           viewport_h: int = 1400, scale: int = 1) -> None:
    """Render the session-monitor --list output as a PNG.

    Defaults to a single-screen viewport (1200x1400 at 1x scale) so the
    README screenshot stays small enough to render quickly in a browser.
    Pass ``--full-page`` via a wider viewport_h to capture every worktree
    group.
    """
    stdout = _run_session_monitor(repo, days)
    html_doc = _build_html(stdout, viewport_w)

    # Stage HTML next to the PNG so it can be diffed or re-rendered later.
    html_path = png_path.with_suffix(".html")
    html_path.write_text(html_doc, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(
            viewport={"width": viewport_w, "height": viewport_h},
            device_scale_factor=scale,
        )
        page = ctx.new_page()
        page.goto("file://" + str(html_path.resolve()), wait_until="networkidle")
        page.wait_for_timeout(300)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(png_path), full_page=False)
        browser.close()
    print(f"[ok] {png_path}  ({png_path.stat().st_size:,} bytes)")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", default="dev-harness-kit", help="repo basename to filter on (default: dev-harness-kit)")
    parser.add_argument("--days", type=int, default=30, help="look-back window (default: 30)")
    parser.add_argument("png", nargs="?", default="docs/screenshots/session-monitor.png",
                        help="output PNG path (default: docs/screenshots/session-monitor.png)")
    parser.add_argument("viewport_w", nargs="?", type=int, default=1200,
                        help="viewport width in CSS px (default: 1200)")
    args = parser.parse_args(argv)

    render(Path(args.png), args.repo, args.days, args.viewport_w)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
