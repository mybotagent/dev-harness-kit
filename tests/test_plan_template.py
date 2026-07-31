#!/usr/bin/env python3
"""
test_plan_template.py — Pins that skills/plan/SKILL.md delegates the
step-file template + marker contract to lib/execute.py (the actual SSOT).

Background
----------
The build runner (lib/execute.py) parses HTML-comment markers in the
sub-agent's final reply to know whether a step ended in
`completed` / `error` / `blocked`, and to capture the human-meaningful
`summary` / `error_message` / `blocked_reason`. The agent learns the
marker format from the step.md template that the plan skill emits.

The plan SKILL.md no longer inlines the template body or marker grammar —
it points at `lib/execute.py` for both. This test pins that delegation
contract: a regression that re-inlines the template or removes the
pointer would re-introduce the duplication this PR removed.
"""
from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
PLAN_SKILL = PROJECT_ROOT / "skills" / "plan" / "SKILL.md"

REQUIRED_STATUS_VALUES = ("completed", "error", "blocked")
REQUIRED_COMPANION_FIELDS = ("summary", "error_message", "blocked_reason")


class TestPlanStepTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PLAN_SKILL.exists():
            raise unittest.SkipTest(f"plan SKILL.md missing: {PLAN_SKILL}")
        cls.text = PLAN_SKILL.read_text(encoding="utf-8")

    def test_delegates_template_to_lib_execute(self):
        """The pinned template pointer must point at lib/execute.py."""
        self.assertIn(
            "lib/execute.py",
            self.text,
            "skills/plan/SKILL.md must reference lib/execute.py as the SSOT",
        )
        self.assertIn(
            "VALID_STATUSES",
            self.text,
            "skills/plan/SKILL.md must reference VALID_STATUSES from lib/execute.py",
        )
        self.assertIn(
            "parse_status_marker",
            self.text,
            "skills/plan/SKILL.md must reference parse_status_marker from lib/execute.py",
        )

    def test_status_marker_present_in_pointer(self):
        """The pointer section must mention the three status values so the
        reader knows what state machine the runner implements."""
        for value in REQUIRED_STATUS_VALUES:
            self.assertIn(
                value,
                self.text,
                f"plan SKILL.md must mention status value '{value}' (even just via pointer)",
            )

    def test_companion_marker_present_in_pointer(self):
        """The pointer section must mention the three companion field names."""
        for field in REQUIRED_COMPANION_FIELDS:
            self.assertIn(
                field,
                self.text,
                f"plan SKILL.md must mention companion field '{field}' (even just via pointer)",
            )

    def test_template_contains_no_runtime_status_assertions(self):
        """Plan must not instruct the agent to set in_progress/completed/error/blocked directly.

        Now that the template body lives in lib/execute.py, the assertion is
        simpler: the plan SKILL.md itself must not contain phrases that
        would push plan into runtime states."""
        bad_phrases = (
            "set status to in_progress",
            "set status to completed",
            "set status to error",
            "set status to blocked",
        )
        for phrase in bad_phrases:
            self.assertNotIn(
                phrase.lower(),
                self.text.lower(),
                f"plan SKILL.md must not instruct plan to write runtime state: {phrase!r}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
