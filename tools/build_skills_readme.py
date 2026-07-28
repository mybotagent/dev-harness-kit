#!/usr/bin/env python3
"""build_skills_readme.py — Regenerate skills/README.md from SKILL.md frontmatter.

Reads every skills/<name>/SKILL.md, parses the YAML frontmatter, and writes
a fresh skills/README.md that reflects the current skill surface. Categories
are auto-grouped; counts and alphabetical table are computed from the on-disk
list, so the README no longer drifts when skills are added or removed.

Usage:
    python3 tools/build_skills_readme.py [--dry-run] [--out PATH]

Default output is skills/README.md (overwrites the hand-maintained copy).
--dry-run prints to stdout. Exit code 0 on success.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
DEFAULT_OUT = SKILLS_DIR / "README.md"


# Fields we extract from the frontmatter. Some skill descriptions contain
# unquoted colons (e.g. "/dev-kit:harness-audit [--json]"), which break a
# full YAML parse — line-based extraction sidesteps that without forcing
# every author to learn YAML quoting rules.
_FIELDS = ("name", "category", "alpha", "description", "user-invocable", "user_invocable")


def _is_invocable(raw: object) -> bool:
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in ("false", "0", "no")


def _parse_frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        raise ValueError("no YAML frontmatter found")
    body = m.group(1)
    out: dict = {}
    for line in body.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        for field in _FIELDS:
            prefix = f"{field}:"
            if line.startswith(prefix) and (line[len(prefix)] in (" ", "\t", "")):
                value = line[len(prefix):].strip()
                # Strip surrounding quotes if present.
                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]
                out[field.replace("-", "_")] = value
                break
    return out


def _gather() -> list[dict]:
    rows: list[dict] = []
    for skill_md in sorted(SKILLS_DIR.rglob("SKILL.md")):
        if skill_md.parent.parent != SKILLS_DIR:
            continue  # skip anything nested deeper than skills/<name>/SKILL.md
        text = skill_md.read_text()
        fm = _parse_frontmatter(text)
        rows.append(
            {
                "name": fm.get("name", skill_md.parent.name),
                "dir": skill_md.parent.name,
                "category": fm.get("category", "uncategorized"),
                "alpha": fm.get("alpha", "analysis"),
                "user_invocable": _is_invocable(fm.get("user-invocable", fm.get("user_invocable", "true"))),
                "description": (fm.get("description") or "").strip(),
            }
        )
    rows.sort(key=lambda r: r["name"])
    return rows


def _short_description(desc: str, limit: int = 220) -> str:
    desc = re.sub(r"\s+", " ", desc).strip()
    if len(desc) <= limit:
        return desc
    return desc[: limit - 1].rstrip() + "…"


def _render(rows: list[dict]) -> str:
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda r: r["name"])

    total = len(rows)
    cats = sorted(by_cat.keys())
    human = sum(1 for r in rows if r["user_invocable"])
    model = total - human

    out: list[str] = []
    out.append("# Skills index")
    out.append("")
    out.append(
        "This index lists every skill shipped by the `dev-kit` plugin. Click into any skill to read its full `SKILL.md`; every `SKILL.md` has a back-link at the top to return here."
    )
    out.append("")
    out.append(
        f"**{total} skills** across {len(cats)} categories ({human} human-invocable, {model} model-invoked). The full path of each entry is `skills/<dir>/SKILL.md`. Use `find skills -mindepth 2 -maxdepth 2 -name SKILL.md | wc -l` to confirm."
    )
    out.append("")
    out.append("## By category")
    out.append("")

    for cat in cats:
        items = by_cat[cat]
        out.append(f"### `{cat}` ({len(items)})")
        out.append("")
        out.append("| Skill | α | Description |")
        out.append("|---|---|---|")
        for r in items:
            desc = _short_description(r["description"])
            invocable_marker = " 🔒" if not r["user_invocable"] else ""
            out.append(
                f"| [`{r['name']}`]({r['dir']}/SKILL.md){invocable_marker} | `{r['alpha']}` | {desc} |"
            )
        out.append("")

    out.append("## Alphabetical")
    out.append("")
    out.append("| # | Skill | Category | α | Invocable |")
    out.append("|---|---|---|---|---|")
    for idx, r in enumerate(rows, 1):
        invocable = "human" if r["user_invocable"] else "model"
        out.append(
            f"| {idx} | [`{r['name']}`]({r['dir']}/SKILL.md) | `{r['category']}` | `{r['alpha']}` | {invocable} |"
        )
    out.append("")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Regenerate skills/README.md")
    parser.add_argument("--dry-run", action="store_true", help="print to stdout")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output path")
    args = parser.parse_args(argv)

    rows = _gather()
    rendered = _render(rows)

    if args.dry_run:
        sys.stdout.write(rendered)
        return 0

    Path(args.out).write_text(rendered)
    print(f"wrote {args.out} ({len(rendered)} bytes, {len(rows)} skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
