"""python3 -m lib.analysis_core --delete --target <feat>

CLI entry for the analysis engine. Replaces the 286-line wrapper
`skills/prune/scripts/discover_dependents.py` (deleted in PR-H) that
was a thin shim over ``run_analysis(mode="delete", ...)``. Now the
prune SKILL.md body can invoke this directly without an intermediate
script.

Usage:
    python3 -m lib.analysis_core --delete --target <feat> [--paths <p1> [<p2> ...]]
"""
from __future__ import annotations

import argparse
import sys

from .dimensions import group
from .runner import emit_suggested_diffs, run_analysis


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m lib.analysis_core",
        description="Single analysis engine for the 6 reasoning skills.",
    )
    p.add_argument(
        "--mode",
        choices=["read-only", "delete", "rewrite"],
        default="read-only",
    )
    p.add_argument(
        "--delete", action="store_const", const="delete", dest="mode",
        help="Shortcut for --mode delete (used by /dev-kit:prune Phase 2).",
    )
    p.add_argument(
        "--target",
        help="Feature target (passed through to candidates). For prune this "
             "is the feature name; for inspect it's the dimension name.",
    )
    p.add_argument(
        "--family",
        default="inspect",
        help="Dimension family (default 'inspect' = the prune Phase 2 sweep).",
    )
    p.add_argument(
        "--paths", nargs="+", default=["."],
        help="Root paths to scope the sweep (default: current dir).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = run_analysis(
        dimensions=group(args.family),
        mode=args.mode,
        paths=args.paths,
    )
    diffs = emit_suggested_diffs(result)
    if diffs:
        for d in diffs:
            print(f"{d.file}:{d.line}: {d.command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
