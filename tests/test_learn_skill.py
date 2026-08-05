"""tests/test_learn_skill.py — gates for /dev-kit:learn.

Validates:
- G1: SKILL.md description ≤60 chars (after stripping trailing period)
- G2: SKILL.md frontmatter schema (name/alpha/category/when_to_use)
- G3: SKILL.md section order AND presence of all 7 canonical sections
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


def _make_full_skill_skeleton(
    *, name="badskill", description="x", alpha="state", category="audit",
    when_to_use=("a", "b"), sections=CANONICAL_SECTIONS,
) -> str:
    """Build a SKILL.md skeleton with the canonical 7 sections by default."""
    bullets = "\n".join(f"  - {item}" for item in when_to_use)
    section_lines = "\n\n".join(f"## {s}\n\nbody" for s in sections)
    return (
        "---\n"
        f"name: {name}\n"
        f"alpha: {alpha}\n"
        f"category: {category}\n"
        f"description: {description}\n"
        "when_to_use:\n"
        f"{bullets}\n"
        "---\n"
        f"{section_lines}\n"
    )


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
        """G3 ordering: ## headers appear in canonical prefix order."""
        sections = [m.group(1) for m in SECTION_RE.finditer(self.text)]
        canonical_present = [
            s for s in sections if any(s.startswith(c) for c in CANONICAL_SECTIONS)
        ]
        prefixes = []
        for s in canonical_present:
            for c in CANONICAL_SECTIONS:
                if s.startswith(c):
                    prefixes.append(c)
                    break
        indices = [CANONICAL_SECTIONS.index(p) for p in prefixes]
        self.assertEqual(
            indices, sorted(indices),
            f"sections out of canonical order: {prefixes}",
        )

    def test_all_seven_canonical_sections_present(self):
        """G3 presence: all 7 canonical sections must appear (not just a subset).

        /dev-kit:learn is a generator; a candidate missing `Iron Laws`
        (the section most likely to be elided under token pressure)
        must not silently pass all gates.
        """
        sections = [m.group(1) for m in SECTION_RE.finditer(self.text)]
        present = [
            c for c in CANONICAL_SECTIONS
            if any(s.startswith(c) for s in sections)
        ]
        self.assertEqual(
            sorted(present), sorted(CANONICAL_SECTIONS),
            f"missing canonical sections: "
            f"{sorted(set(CANONICAL_SECTIONS) - set(present))}",
        )


class TestLearnSkillNameCollision(unittest.TestCase):
    """G4: skill name must not collide with any other skill directory."""

    def test_no_self_exclusion_tautology(self):
        """Sanity: the test must not remove the candidate name from the
        existing set before asserting non-membership (a tautology that
        passes under any state)."""
        skills_root = PROJECT_ROOT / "skills"
        existing = {p.name for p in skills_root.iterdir() if p.is_dir()}
        # Verify the candidate 'learn' is in the existing set, so the
        # collision check below has a meaningful target to compare against.
        self.assertIn(
            "learn", existing,
            "test setup invariant: skills/learn/ must exist on disk",
        )

    def test_real_collision_detected(self):
        """G4 positive: a SKILL.md whose name collides with an existing
        skill directory must fail G4 when validated against that tree.

        This test creates a fake skill directory inside skills/ claiming
        the name of an existing skill, then runs the validator's g4 check
        directly. The validator must report a collision.
        """
        sys.path.insert(0, str(SKILL_DIR / "scripts"))
        try:
            from validate_skill import g4_name_collision
        except ImportError as exc:
            self.fail(f"could not import validate_skill: {exc}")

        # Build a fake SKILL.md claiming name 'ci-triage' (a real skill).
        # Place it in a sibling directory inside skills/ so the g4 check
        # iterates the right tree.
        candidate_dir = PROJECT_ROOT / "skills" / "_test_collision_fixture"
        candidate = candidate_dir / "SKILL.md"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        candidate.write_text(
            _make_full_skill_skeleton(name="ci-triage"),
            encoding="utf-8",
        )
        try:
            from validate_skill import extract_frontmatter
            fm = extract_frontmatter(candidate.read_text(encoding="utf-8"))
            violations = g4_name_collision(candidate, fm)
            self.assertTrue(
                any("G4" in v and "collides" in v for v in violations),
                f"G4 should detect the collision; got: {violations}",
            )
        finally:
            candidate.unlink(missing_ok=True)
            candidate_dir.rmdir()


class TestValidateSkillScript(unittest.TestCase):
    """The validate_skill.py CLI must exist and run."""

    def test_script_exists(self):
        self.assertTrue(
            VALIDATE_SCRIPT.is_file(),
            f"missing: {VALIDATE_SCRIPT}",
        )

    def test_script_has_py_extension(self):
        """The validator's filename must end in .py (so python3 <path> works).

        Note: we deliberately do NOT assert the executable bit — the
        script is invoked as `python3 <path>`, which doesn't need +x.
        Asserting only the suffix keeps the test honest about what it
        actually checks.
        """
        if not VALIDATE_SCRIPT.exists():
            self.skipTest("script not yet written")
        self.assertEqual(VALIDATE_SCRIPT.suffix, ".py")

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
        """Negative G1: description >60 chars must fail."""
        if not VALIDATE_SCRIPT.exists():
            self.skipTest("script not yet written")
        bad_skill = _make_full_skill_skeleton(
            name="badskill",
            description="This description is way too long to be a valid "
                        "description under the sixty character limit.",
        )
        self._assert_nonzero(bad_skill, "G1 description")

    def test_script_exits_nonzero_on_missing_alpha(self):
        """Negative G2: missing `alpha:` must fail the schema gate."""
        if not VALIDATE_SCRIPT.exists():
            self.skipTest("script not yet written")
        bad = (
            "---\n"
            "name: badskill\n"
            "category: audit\n"
            "description: x\n"
            "when_to_use:\n  - a\n  - b\n"
            "---\n" + "\n\n".join(f"## {s}\n\nbody" for s in CANONICAL_SECTIONS) + "\n"
        )
        self._assert_nonzero(bad, "G2 alpha")

    def test_script_exits_nonzero_on_invalid_category(self):
        """Negative G2: category not in the 12-value allow-list must fail."""
        if not VALIDATE_SCRIPT.exists():
            self.skipTest("script not yet written")
        bad = _make_full_skill_skeleton(name="badskill", category="bogus")
        self._assert_nonzero(bad, "G2 category")

    def test_script_exits_nonzero_on_non_kebab_name(self):
        """Negative G2: name with uppercase or underscore must fail."""
        if not VALIDATE_SCRIPT.exists():
            self.skipTest("script not yet written")
        bad = _make_full_skill_skeleton(name="BadSkill_Name")
        self._assert_nonzero(bad, "G2 name")

    def test_script_exits_nonzero_on_missing_section(self):
        """Negative G3: a candidate missing `Iron Laws` must fail presence."""
        if not VALIDATE_SCRIPT.exists():
            self.skipTest("script not yet written")
        # Drop 'Iron Laws' from the canonical section list
        missing_one = tuple(c for c in CANONICAL_SECTIONS if c != "Iron Laws")
        bad = _make_full_skill_skeleton(name="badskill", sections=missing_one)
        self._assert_nonzero(bad, "G3 missing Iron Laws")

    def test_script_exits_nonzero_on_reordered_sections(self):
        """Negative G3: swapping the order of two canonical sections must fail."""
        if not VALIDATE_SCRIPT.exists():
            self.skipTest("script not yet written")
        reordered = list(CANONICAL_SECTIONS)
        reordered[0], reordered[1] = reordered[1], reordered[0]
        bad = _make_full_skill_skeleton(name="badskill", sections=tuple(reordered))
        self._assert_nonzero(bad, "G3 section order")

    def test_script_exits_nonzero_on_real_collision(self):
        """Negative G4: a SKILL.md claiming an existing skill's name must fail.

        The fixture is placed inside skills/ (not tests/_fixtures/) so
        the validator's g4 check iterates the correct tree root.
        """
        if not VALIDATE_SCRIPT.exists():
            self.skipTest("script not yet written")
        bad = _make_full_skill_skeleton(name="ci-triage")
        collide_dir = PROJECT_ROOT / "skills" / "_collision_e2e_fixture"
        collide_path = collide_dir / "SKILL.md"
        collide_dir.mkdir(parents=True, exist_ok=True)
        collide_path.write_text(bad, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, str(VALIDATE_SCRIPT), str(collide_path)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(
                result.returncode, 0,
                "validate_skill.py should fail on name collision",
            )
            self.assertIn("G4", result.stdout + result.stderr)
        finally:
            collide_path.unlink(missing_ok=True)
            collide_dir.rmdir()

    def _assert_nonzero(self, skill_text: str, expected_gate_token: str) -> None:
        """Helper: write skill_text to a fixture file, run validator, assert fail."""
        bad_path = PROJECT_ROOT / "tests" / "_fixtures" / "negative_skill.md"
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text(skill_text, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, str(VALIDATE_SCRIPT), str(bad_path)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(
                result.returncode, 0,
                f"validate_skill.py should fail when {expected_gate_token} is violated",
            )
            self.assertIn(
                expected_gate_token.split()[0],  # "G1", "G2", "G3"
                result.stdout + result.stderr,
            )
        finally:
            bad_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
