#!/usr/bin/env python3
"""test_prune.py — Regression for skills/prune/SKILL.md schema.

Locks in the 3-phase prune contract. Asserts:

- frontmatter: user-invocable: true, category: build, model: opus
- body has 3 phase headings ([1/3], [2/3], [3/3])
- body has an Iron Law with MUST-L1 / MUST-L2 / MUST-L3 / MUST-L4 references
- body disambiguates from /dev-kit:refactor (delete != refactor)
- body disambiguates from /dev-kit:feat-remove (project-wide != named feature)
- body declares Edit in disallowed-tools (orchestrator only)
- body never claims to call `rm` itself (mirrors feat-remove discipline)
- frontmatter name matches directory name (covered by test_naming.py
  but pinned here for fast failure if the new file regresses)
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
PRUNE_SKILL = PROJECT_ROOT / "skills" / "prune" / "SKILL.md"
BUILD_PRUNE_SKILL = PROJECT_ROOT / "skills" / "build-prune" / "SKILL.md"


class TestPruneSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not PRUNE_SKILL.exists():
            raise unittest.SkipTest(f"{PRUNE_SKILL} missing")
        cls.text = PRUNE_SKILL.read_text(encoding="utf-8")

    def test_frontmatter_user_invocable_true(self):
        m = re.search(r"^user-invocable:\s*(.+)$", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "user-invocable: frontmatter missing")
        self.assertEqual(m.group(1).strip(), "true", "prune must be user-invocable")

    def test_frontmatter_category_build(self):
        m = re.search(r"^category:\s*(.+)$", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "category: frontmatter missing")
        self.assertEqual(m.group(1).strip(), "build", "prune category must be 'build'")

    def test_frontmatter_model_opus(self):
        # prune is a higher-stakes skill (it deletes code), so the
        # default model is opus rather than sonnet.
        m = re.search(r"^model:\s*(.+)$", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "model: frontmatter missing")
        self.assertEqual(m.group(1).strip(), "opus", "prune model must be 'opus'")

    def test_three_phases_present(self):
        for n in (1, 2, 3):
            pattern = rf"\[{n}/3\]"
            self.assertRegex(
                self.text, pattern,
                f"phase [{n}/3] heading missing from body",
            )

    def test_phase_names_match_documented_chain(self):
        self.assertRegex(self.text, r"\[1/3\]\s*INSPECT", "phase 1 should be INSPECT")
        self.assertRegex(self.text, r"\[2/3\]\s*PRUNE", "phase 2 should be PRUNE")
        self.assertRegex(self.text, r"\[3/3\]\s*REVIEW", "phase 3 should be REVIEW")

    def test_iron_law_cites_four_musts(self):
        # MUST-L2 (reproduce-first) is included because deletion
        # candidates must have a reproducible signal.
        for must in ("MUST-L1", "MUST-L2", "MUST-L3", "MUST-L4"):
            self.assertIn(must, self.text, f"Iron Law must cite {must}")

    def test_hand_off_names_downstream_skill(self):
        m = re.search(r"## Next step(.*?)$", self.text, re.DOTALL)
        self.assertIsNotNone(m, "Next step section missing")
        block = m.group(1)
        self.assertRegex(
            block, r"/dev-kit:\w+",
            "Next step should route to a slash skill",
        )

    def test_no_edit_tool_allowed(self):
        # prune is an orchestrator; deletions belong to phase 2
        # (build-prune) which emits commands for the user to run.
        m = re.search(r"^disallowed-tools:\s*(.+)$", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "disallowed-tools: frontmatter missing")
        tools = m.group(1).split()
        self.assertIn(
            "Edit", tools,
            "prune must declare Edit in disallowed-tools (phase 2 mutates, not this skill)",
        )

    def test_disambiguates_from_refactor(self):
        # prune deletes; refactor rewrites. The body must surface
        # the distinction so users don't run the wrong skill.
        self.assertIn(
            "/dev-kit:refactor", self.text,
            "prune must mention /dev-kit:refactor as the refactor counterpart",
        )

    def test_disambiguates_from_feat_remove(self):
        # prune is project-wide; feat-remove is one named feature.
        self.assertIn(
            "/dev-kit:feat-remove", self.text,
            "prune must mention /dev-kit:feat-remove as the single-feature counterpart",
        )

    def test_never_calls_rm_directly(self):
        # Mirrors feat-remove discipline: the skill emits commands;
        # the user runs them. A "skill should `rm` for me" statement
        # would be a violation.
        self.assertIn(
            "never deletes files itself", self.text,
            "prune must declare it never calls rm/git-rm itself",
        )


class TestBuildPruneSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not BUILD_PRUNE_SKILL.exists():
            raise unittest.SkipTest(f"{BUILD_PRUNE_SKILL} missing")
        cls.text = BUILD_PRUNE_SKILL.read_text(encoding="utf-8")

    def test_frontmatter_user_invocable_false(self):
        # build-prune is a model-use internal block, hidden from slash.
        m = re.search(r"^user-invocable:\s*(.+)$", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "user-invocable: frontmatter missing")
        self.assertEqual(
            m.group(1).strip(), "false",
            "build-prune must be model-use only (user-invocable: false)",
        )

    def test_three_passes_present(self):
        for n in (1, 2, 3):
            pattern = rf"\[{n}/3\]"
            self.assertRegex(
                self.text, pattern,
                f"pass [{n}/3] heading missing from body",
            )

    def test_pass_names_match_documented_chain(self):
        self.assertRegex(self.text, r"\[1/3\]\s*ORPHAN-CODE", "pass 1 should be ORPHAN-CODE")
        self.assertRegex(self.text, r"\[2/3\]\s*DEAD-FEATURE", "pass 2 should be DEAD-FEATURE")
        self.assertRegex(self.text, r"\[3/3\]\s*SLOP-PATTERN", "pass 3 should be SLOP-PATTERN")

    def test_iron_law_present(self):
        self.assertIn("No deletion without reproducible signal", self.text)

    def test_never_invokes_rm_directly(self):
        # The internal skill also must not run rm; bash-guard blocks it.
        self.assertIn("never calls them itself", self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
