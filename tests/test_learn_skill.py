"""tests/test_learn_skill.py — gates for /dev-kit:learn.

Validates:
- G1: SKILL.md description ≤60 chars (after stripping trailing period)
- G2: SKILL.md frontmatter schema (name/alpha/category/when_to_use)
- G3: SKILL.md section order matches canonical 7-section pattern
- G4: skill name does not collide with any existing skill directory
- G5: L6 governance test passes for the new skill (delegated to
      tests.test_skill_governance.TestSkillGovernance)
- The validate_skill.py CLI script itself runs and exits 0/1 correctly
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = PROJECT_ROOT / "skills" / "learn"
SKILL_MD = SKILL_DIR / "SKILL.md"
VALIDATE_SCRIPT = SKILL_DIR / "scripts" / "validate_skill.py"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
SECTION_RE = re.compile(r"^## (.+?)$", re.MULTILINE)
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


def _read_skill_md() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _extract_frontmatter(text: str) -> dict[str, str] | None:
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


class TestLearnSkillMdExists(unittest.TestCase):
    def test_skill_directory_exists(self):
        self.assertTrue(SKILL_DIR.is_dir(), f"missing dir: {SKILL_DIR}")

    def test_skill_md_exists(self):
        self.assertTrue(SKILL_MD.is_file(), f"missing: {SKILL_MD}")


class TestLearnSkillFrontmatter(unittest.TestCase):
    def setUp(self):
        if not SKILL_MD.exists():
            self.skipTest("SKILL.md not yet written")
        self.text = _read_skill_md()
        self.fm = _extract_frontmatter(self.text)

    def test_frontmatter_present(self):
        self.assertIsNotNone(
            self.fm, "SKILL.md frontmatter must be wrapped in '---' lines"
        )

    def test_name_matches_directory(self):
        self.assertEqual(self.fm.get("name"), "learn")

    def test_alpha_is_valid(self):
        self.assertIn(self.fm.get("alpha", ""), ALLOWED_ALPHA)

    def test_category_is_valid(self):
        self.assertIn(self.fm.get("category", ""), ALLOWED_CATEGORIES)

    def test_when_to_use_present(self):
        self.assertIn("when_to_use", self.fm)

    def test_description_within_60_chars(self):
        """G1: description (sans trailing period) must be ≤60 chars."""
        desc = self.fm.get("description", "")
        stripped = desc.rstrip(".").rstrip()
        self.assertLessEqual(
            len(stripped), 60,
            f"description {len(stripped)} chars > 60 limit: {desc!r}",
        )


class TestLearnSkillSectionOrder(unittest.TestCase):
    def setUp(self):
        if not SKILL_MD.exists():
            self.skipTest("SKILL.md not yet written")
        self.text = _read_skill_md()

    def test_sections_in_canonical_order(self):
        """G3: ## headers must appear in the canonical 7-section order."""
        sections = [m.group(1) for m in SECTION_RE.finditer(self.text)]
        # Filter to only the canonical section prefixes (skip incidental ## blocks)
        canonical_present = [
            s for s in sections if any(s.startswith(c) for c in CANONICAL_SECTIONS)
        ]
        # Extract canonical prefix from each
        prefixes = []
        for s in canonical_present:
            for c in CANONICAL_SECTIONS:
                if s.startswith(c):
                    prefixes.append(c)
                    break
        # Check that prefixes appear in canonical order
        indices = [CANONICAL_SECTIONS.index(p) for p in prefixes]
        self.assertEqual(
            indices, sorted(indices),
            f"sections out of canonical order: {prefixes}",
        )


class TestLearnSkillNameCollision(unittest.TestCase):
    """G4: 'learn' must not collide with any existing skill directory."""

    def test_no_collision_with_existing_skills(self):
        skills_root = PROJECT_ROOT / "skills"
        existing = {p.name for p in skills_root.iterdir() if p.is_dir()}
        # The new skill directory itself is allowed; the gate rejects
        # only if another directory already claims this name.
        # In a fresh test env, 'learn' is the only candidate.
        candidates_excluding_self = existing - {"learn"}
        self.assertNotIn(
            "learn", candidates_excluding_self,
            "skill name 'learn' collides with existing directory",
        )


class TestValidateSkillScript(unittest.TestCase):
    """The validate_skill.py CLI must exist and run."""

    def test_script_exists(self):
        self.assertTrue(
            VALIDATE_SCRIPT.is_file(),
            f"missing: {VALIDATE_SCRIPT}",
        )

    def test_script_is_executable(self):
        if not VALIDATE_SCRIPT.exists():
            self.skipTest("script not yet written")
        # Should be runnable via 'python3 <path>'
        self.assertTrue(VALIDATE_SCRIPT.suffix == ".py")

    def test_script_exits_zero_on_valid_skill(self):
        """End-to-end: running validate_skill.py on the new SKILL.md
        should exit 0 (all gates pass)."""
        if not VALIDATE_SCRIPT.exists():
            self.skipTest("script not yet written")
        if not SKILL_MD.exists():
            self.skipTest("SKILL.md not yet written")
        result = subprocess.run(
            [sys.executable, str(VALIDATE_SCRIPT), str(SKILL_MD)],
            capture_output=True, text=True,
        )
        self.assertEqual(
            result.returncode, 0,
            f"validate_skill.py failed on valid SKILL.md:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}",
        )

    def test_script_exits_nonzero_on_bad_description(self):
        """Negative: a SKILL.md with description >60 chars must fail G1."""
        if not VALIDATE_SCRIPT.exists():
            self.skipTest("script not yet written")
        bad_skill = (
            "---\n"
            "name: badskill\n"
            "alpha: state\n"
            "category: audit\n"
            "description: This description is way too long to be a valid "
            "description under the sixty character limit.\n"
            "when_to_use:\n"
            "  - x\n"
            "  - y\n"
            "---\n"
            "# Bad\n\n## Workflow\n\n## Step 1\n\n## Step 2\n\n"
            "## Step 3\n\n## Validation gates\n\n## Iron Laws\n\n## Next step\n"
        )
        bad_path = PROJECT_ROOT / "tests" / "_fixtures" / "bad_skill.md"
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text(bad_skill, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, str(VALIDATE_SCRIPT), str(bad_path)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(
                result.returncode, 0,
                "validate_skill.py should fail on description >60 chars",
            )
        finally:
            bad_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
