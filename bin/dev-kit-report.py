#!/usr/bin/env python3
"""dev-kit-report.py -- CLI driver for /dev-kit:report.

Reads `.dev-kit/eval-report.md` and `.dev-kit/inspect-report.md` from
the project root, hands them to `lib/render_report_html.py:render`,
and writes the result to `.dev-kit/report.html`.

The skill body (`skills/report/SKILL.md`) is read-only -- it cannot
Edit or Write. The actual file write happens in this CLI driver,
mirroring how the inspect skill keeps the skill body pure and writes
its artifact via a separate mechanism.

Usage:
    python bin/dev-kit-report.py [--project-root PATH]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make lib/ importable when invoked from anywhere.
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR.parent / "lib"))

import render_report_html  # type: ignore  # noqa: E402
from atomic import atomic_write_text  # type: ignore  # noqa: E402

EVAL_REPORT = "eval-report.md"
INSPECT_REPORT = "inspect-report.md"
OUTPUT = "report.html"
MISSING_BANNER = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>dev-harness-kit -- report</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif;
       max-width: 800px; margin: 4rem auto; padding: 0 1.5rem; color: #1a1a1a; }
.missing { background: #fff8e0; border: 1px solid #e0c060; border-radius: 4px;
           padding: 1rem 1.2rem; margin: 1rem 0; }
code { background: #f0f0f0; padding: 0.1em 0.3em; border-radius: 3px; }
</style></head><body>
<h1>dev-harness-kit -- report</h1>
<div class="missing">
  <p><b>No reports found.</b> Run one of these first:</p>
  <ul>
    <li><code>/dev-kit:evaluate</code> -- writes <code>.dev-kit/eval-report.md</code></li>
    <li><code>/dev-kit:inspect</code> -- writes <code>.dev-kit/inspect-report.md</code></li>
  </ul>
</div>
</body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render HTML report from eval + inspect markdown")
    parser.add_argument("--project-root", default=".", help="project root (default: cwd)")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    dev_kit = root / ".dev-kit"

    eval_path = dev_kit / EVAL_REPORT
    inspect_path = dev_kit / INSPECT_REPORT
    out_path = dev_kit / OUTPUT

    eval_md = eval_path.read_text(encoding="utf-8") if eval_path.exists() else ""
    inspect_md = inspect_path.read_text(encoding="utf-8") if inspect_path.exists() else ""

    if not eval_md and not inspect_md:
        # Write a minimal page that says "run a skill first", but still
        # succeed with exit 0 -- the absence of reports is a normal
        # state for a fresh project, not a failure of this driver.
        atomic_write_text(out_path, MISSING_BANNER)
        print(f"wrote {out_path} (no reports found; banner page)")
        return 0

    html_doc = render_report_html.render(eval_md, inspect_md)
    atomic_write_text(out_path, html_doc)
    size_kb = len(html_doc.encode("utf-8")) / 1024
    sources = []
    if eval_md:
        sources.append(EVAL_REPORT)
    if inspect_md:
        sources.append(INSPECT_REPORT)
    print(f"wrote {out_path} ({size_kb:.1f} KB, sources: {', '.join(sources)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
