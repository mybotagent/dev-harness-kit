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

import yaml

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
    """Parse YAML frontmatter via PyYAML safe_load.

    Returns a dict of stringified values (lists → JSON-ish repr) for
    downstream gate checks. Returns None when the '---' wrapper is
    missing or the YAML fails to parse.
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    raw = m.group(1)
    try:
        loaded = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(loaded, dict):
        return None
    return {str(k): str(v) if not isinstance(v, (list, dict)) else repr(v)
            for k, v in loaded.items()}


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
    """Enforce BOTH presence AND order of all 7 canonical sections.

    The /dev-kit:learn skill is a generator: a candidate missing
    `Iron Laws` (the most load-bearing section under token pressure)
    must not silently pass. G3 therefore requires all 7 sections to
    appear, in the canonical order, not just a subset.
    """
    sections = [m.group(1) for m in SECTION_RE.finditer(text)]
    canonical_present: list[str] = []
    for s in sections:
        for c in CANONICAL_SECTIONS:
            if s.startswith(c):
                canonical_present.append(c)
                break
    indices = [CANONICAL_SECTIONS.index(p) for p in canonical_present]
    violations: list[str] = []
    missing = [c for c in CANONICAL_SECTIONS if c not in canonical_present]
    if missing:
        violations.append(
            "G3 missing canonical sections: "
            f"{missing} (all 7 required)"
        )
    if indices != sorted(indices):
        violations.append(
            "G3 section order mismatch: "
            f"expected canonical prefix order, got {canonical_present}"
        )
    return violations


def g4_name_collision(skill_md: Path, fm: dict[str, str] | None) -> list[str]:
    """name field must not collide with an existing skill directory.

    The validator runs before the candidate is written, so the
    candidate file may live at any path (e.g. tests/_fixtures/x.md).
    We use the frontmatter `name:` field to find the candidate's
    eventual home (`skills/<name>/SKILL.md`) and check whether that
    directory already exists — except when it equals the candidate's
    own parent (which is the normal write target).
    """
    if not fm:
        return []
    name = fm.get("name", "").strip()
    if not name:
        return []
    # Locate the skills/ root by walking up from the candidate file.
    skills_root = None
    ancestor = skill_md.resolve().parent
    while ancestor != ancestor.parent:
        if (ancestor / "skills").is_dir() and (
            ancestor / "skills" / "SKILL.md"
        ).exists() is False or (ancestor / "skills").is_dir():
            # Either a real skills/ tree, or anything named skills/.
            if (ancestor.name == "skills") or (
                (ancestor / "skills").is_dir()
            ):
                pass
        # Simpler heuristic: walk up to find a sibling `skills/`.
        if (ancestor.parent / "skills").is_dir():
            skills_root = ancestor.parent / "skills"
            break
        ancestor = ancestor.parent
    if skills_root is None:
        return []
    target = skills_root / name
    if not target.exists():
        return []
    # Allow the candidate to live inside its own target dir (normal
    # write scenario). Otherwise it's a collision.
    try:
        skill_md.resolve().relative_to(target.resolve())
        return []
    except ValueError:
        return [f"G4 name collides with skills/{name}/"]


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
    violations.extend(g4_name_collision(path, fm))

    if violations:
        print("FAIL:", file=sys.stdout)
        for v in violations:
            print(f"  {v}")
        return 1

    print(f"PASS: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
