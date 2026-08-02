#!/usr/bin/env python3
"""Regression tests for the optional public Linear skill contract."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "linear" / "SKILL.md"


def _frontmatter(text: str) -> str:
    match = re.match(r"^---\s*\n(.+?)\n---", text, re.DOTALL)
    if not match:
        raise AssertionError("linear skill frontmatter is missing")
    return match.group(1)


class TestLinearSkill(unittest.TestCase):
    def test_public_skill_metadata_is_valid(self):
        text = SKILL.read_text(encoding="utf-8")
        frontmatter = _frontmatter(text)
        self.assertIn("name: linear", frontmatter)
        self.assertIn("category: config", frontmatter)
        self.assertIn("alpha: state", frontmatter)
        self.assertIn("user-invocable: true", frontmatter)

    def test_explicit_and_implicit_paths_are_documented(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("/dev-kit:linear", text)
        self.assertIn("LINEAR_SKIP", text)
        self.assertIn("LINEAR_ERROR", text)
        self.assertIn("never runs on every prompt", text)

    def test_stale_handoff_does_not_force_issue_reuse(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("existing handoff as context", text)
        self.assertIn("old, closed, or unrelated handoff", text)
        self.assertIn("scope and intended outcome match", text)

    def test_workflow_callers_use_single_optional_preflight(self):
        for name in ("plan", "build", "build-debug", "build-refactor", "refactor"):
            text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("Optional Linear preflight", text, name)
            self.assertIn("LINEAR_SKIP", text, name)
            self.assertIn("once", text, name)

    def test_configuration_describes_non_blocking_modes(self):
        text = (ROOT / "skills" / "config" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("off", text)
        self.assertIn("auto", text)
        self.assertIn("without blocking", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
