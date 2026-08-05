#!/usr/bin/env python3
"""skills/learn/scripts/validate_skill.py — gate runner for candidate SKILL.md.

Implements G1-G4 of the /dev-kit:learn validation gates. Exits 0 on success,
1 on any failure with a per-gate violation list on stdout. G5 (L6 governance)
is delegated to tests/test_skill_governance.py and not run from here.

Usage:
    python3 skills/learn/scripts/validate_skill.py <path/to/SKILL.md>
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ALLOWED_CATEGORIES = {
    "audit", "bootstrap", "build", "config", "design", "eval",
    "plan", "review", "security", "ship", "shortcuts", "status",
}
ALLOWED_ALPHA = {"state", "enforcement", "analysis"}
CANONICAL_SECTIONS = (
    "Workflow",
    "Step 1",
    "Step 2",
    "Step 3",
    "Validation gates",
    "Iron Laws",
    "Next step",
)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
SECTION_RE = re.compile(r"^## (.+?)$", re.MULTILINE)


def extract_frontmatter(text: str) -> dict[str, str] | None:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def g1_description_length(fm: dict[str, str]) -> list[str]:
    """description (sans trailing period) must be <=60 chars."""
    desc = fm.get("description", "")
    stripped = desc.rstrip(".").rstrip()
    if len(stripped) > 60:
        return [f"G1 description {len(stripped)} chars > 60 limit: {desc!r}"]
    return []


def g2_frontmatter_schema(fm: dict[str, str] | None, skill_md: Path) -> list[str]:
    if fm is None:
        return ["G2 frontmatter missing or malformed (need '---' wrapper)"]

    violations: list[str] = []

    # name: required, kebab-case, matches directory
    name = fm.get("name", "")
    if not name or not re.match(r"^[a-z][a-z0-9-]*$", name):
        violations.append(f"G2 name not kebab-case: {name!r}")
    elif skill_md.parent.name != name:
        violations.append(
            f"G2 name {name!r} does not match directory {skill_md.parent.name!r}"
        )

    # alpha: required, in allowed set
    alpha = fm.get("alpha", "")
    if not alpha:
        violations.append("G2 alpha missing")
    elif alpha not in ALLOWED_ALPHA:
        violations.append(f"G2 alpha {alpha!r} not in {sorted(ALLOWED_ALPHA)}")

    # category: required, in allowed set
    category = fm.get("category", "")
    if not category:
        violations.append("G2 category missing")
    elif category not in ALLOWED_CATEGORIES:
        violations.append(
            f"G2 category {category!r} not in {sorted(ALLOWED_CATEGORIES)}"
        )

    # when_to_use: required (presence only — content shape enforced elsewhere)
    if "when_to_use" not in fm:
        violations.append("G2 when_to_use missing")

    return violations


def g3_section_order(text: str) -> list[str]:
    sections = [m.group(1) for m in SECTION_RE.finditer(text)]
    canonical_present = [
        s for s in sections if any(s.startswith(c) for c in CANONICAL_SECTIONS)
    ]
    prefixes: list[str] = []
    for s in canonical_present:
        for c in CANONICAL_SECTIONS:
            if s.startswith(c):
                prefixes.append(c)
                break
    indices = [CANONICAL_SECTIONS.index(p) for p in prefixes]
    if indices != sorted(indices):
        return [
            "G3 section order mismatch: "
            f"expected canonical prefix order, got {prefixes}"
        ]
    return []


def g4_name_collision(skill_md: Path) -> list[str]:
    """name must not collide with another skill directory (excluding self)."""
    name = skill_md.parent.name
    skills_root = skill_md.parent.parent
    if not skills_root.is_dir():
        return []  # Not running from the repo; skip collision check.
    for entry in skills_root.iterdir():
        if entry.is_dir() and entry.name == name and entry != skill_md.parent:
            return [f"G4 name collides with skills/{name}/"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a SKILL.md against /dev-kit:learn gates G1-G4."
    )
    parser.add_argument("skill_md", type=Path, help="path to SKILL.md")
    args = parser.parse_args()

    path = args.skill_md.resolve()
    if not path.is_file():
        print(f"validate_skill: file not found: {path}", file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8")
    fm = extract_frontmatter(text)

    violations: list[str] = []
    violations.extend(g2_frontmatter_schema(fm, path))
    if fm is not None:
        violations.extend(g1_description_length(fm))
    violations.extend(g3_section_order(text))
    violations.extend(g4_name_collision(path))

    if violations:
        print("FAIL:", file=sys.stdout)
        for v in violations:
            print(f"  {v}")
        return 1

    print(f"PASS: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
