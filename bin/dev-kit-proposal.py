#!/usr/bin/env python3
"""dev-kit-proposal.py -- CLI driver for /dev-kit:proposal.

Reads a YAML proposal from `docs/proposals/<name>.yaml`, hands it to
`lib/render_proposal_html.py:render_from_yaml`, and writes the result
to `docs/proposals/<name>.html`.

The skill body (`skills/proposal/SKILL.md`) is read-only -- it cannot
Edit or Write. The actual file write happens in this CLI driver,
mirroring how `/dev-kit:report` keeps the skill body pure and writes
its artifact via `bin/dev-kit-report.py`.

Usage:
    python bin/dev-kit-proposal.py <name> [--project-root PATH]
    python bin/dev-kit-proposal.py --list [--project-root PATH]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR.parent / "lib"))

import render_proposal_html  # type: ignore  # noqa: E402
from atomic import atomic_write_text  # type: ignore  # noqa: E402

PROPOSALS_DIR = "docs/proposals"
SOURCE_EXT = ".yaml"
OUTPUT_EXT = ".html"


def list_proposals(root: Path) -> list[str]:
    pdir = root / PROPOSALS_DIR
    if not pdir.exists():
        return []
    return sorted(
        p.stem for p in pdir.glob(f"*{SOURCE_EXT}") if p.is_file()
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render HTML proposal from a YAML proposal file"
    )
    parser.add_argument(
        "name",
        nargs="?",
        help="proposal name (file: docs/proposals/<name>.yaml)",
    )
    parser.add_argument(
        "--project-root", default=".", help="project root (default: cwd)"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list available proposals and exit",
    )
    args = parser.parse_args()

    root = Path(args.project_root).resolve()

    if args.list:
        names = list_proposals(root)
        if not names:
            print(f"(no proposals found under {PROPOSALS_DIR}/)")
            return 0
        for n in names:
            print(n)
        return 0

    if not args.name:
        print(
            "error: proposal name required (or pass --list to see available)",
            file=sys.stderr,
        )
        return 2

    src = root / PROPOSALS_DIR / f"{args.name}{SOURCE_EXT}"
    out = root / PROPOSALS_DIR / f"{args.name}{OUTPUT_EXT}"
    if not src.exists():
        print(f"error: source not found: {src}", file=sys.stderr)
        print(f"hint: create {src} or run with --list", file=sys.stderr)
        return 1

    text = src.read_text(encoding="utf-8")
    try:
        html_doc = render_proposal_html.render_from_yaml(text)
    except (ValueError, KeyError) as e:
        print(f"error: failed to parse {src}: {e}", file=sys.stderr)
        return 1

    atomic_write_text(out, html_doc)
    size_kb = len(html_doc.encode("utf-8")) / 1024
    print(f"wrote {out} ({size_kb:.1f} KB, source: {src.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
