#!/usr/bin/env python3
"""
test_plan_template.py — Pins the step.md template + marker contract in
skills/plan/SKILL.md (plan ↔ build SSOT).

Background
----------
The build runner (lib/execute.py) parses HTML-comment markers in the
sub-agent's final reply to know whether a step ended in
`completed` / `error` / `blocked`, and to capture the human-meaningful
`summary` / `error_message` / `blocked_reason`. The agent learns the
marker format from the step.md template that the plan skill emits.

To keep that contract stable, this test pins the template in
`skills/plan/SKILL.md`:

  - The `### Step file template (pinned)` section exists.
  - The `## Verification & Status Update` section exists inside the
    template.
  - All four HTML-comment markers are present:
      `<!-- status: completed | error | blocked -->`
      `<!-- summary: ... | error_message: ... | blocked_reason: ... -->`
  - The `### Marker contract (plan ↔ build SSOT)` subsection lists
    all three statuses and all three companion fields.

If the contract changes, both this test and the runner's parser must
be updated together — that is the regression net.
"""
from __future__ import annotations

import re
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

    def test_template_section_present(self):
        """The pinned template section must exist as a top-level subsection of Gate 4."""
        self.assertIn(
            "### Step file template (pinned)",
            self.text,
            "skills/plan/SKILL.md must contain '### Step file template (pinned)' section",
        )

    def test_verification_and_status_update_section_present(self):
        """The 'Verification & Status Update' section is the agent's contract carrier."""
        self.assertIn(
            "## Verification & Status Update",
            self.text,
            "step.md template must contain '## Verification & Status Update' section",
        )

    def test_status_marker_present(self):
        """The status marker line must be in the template."""
        m = re.search(r"<!--\s*status:\s*([^>]+?)\s*-->", self.text)
        self.assertIsNotNone(m, "missing <!-- status: ... --> marker in plan SKILL.md")
        # All three values must be enumerated.
        for value in REQUIRED_STATUS_VALUES:
            self.assertIn(
                value,
                m.group(1),
                f"status marker missing value '{value}' (got: {m.group(1)!r})",
            )

    def test_companion_marker_present(self):
        """The companion marker (summary / error_message / blocked_reason) must be present.

        The template uses two marker lines: a `<!-- status: ... -->` line and a
        `<!-- summary: ... | error_message: ... | blocked_reason: ... -->` line.
        We pin the companion line specifically (not the partial `<!-- summary: ... -->`
        example elsewhere in the template) by requiring it to contain all three
        field names — that signature only appears on the full companion marker.

        Note: `.*?` (not `[^>]*?`) is used because the placeholders inside the
        marker line (e.g. `<one-line outcome>`) contain `>` characters.
        """
        m = re.search(
            r"<!--.*?error_message.*?blocked_reason.*?-->",
            self.text,
            re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            "missing full companion marker line (must list all three fields in one marker)",
        )
        # All three field names must appear on the SAME marker line.
        for field in REQUIRED_COMPANION_FIELDS:
            self.assertIn(
                field,
                m.group(0),
                f"companion marker missing field '{field}' (got: {m.group(0)!r})",
            )

    def test_marker_contract_subsection_present(self):
        """The 'Marker contract' subsection is the human-readable SSOT for the parser."""
        self.assertIn(
            "### Marker contract (plan ↔ build SSOT)",
            self.text,
            "plan SKILL.md must contain '### Marker contract (plan ↔ build SSOT)' subsection",
        )
        # The subsection must enumerate the three statuses + three fields.
        marker_section = self.text.split("### Marker contract (plan ↔ build SSOT)", 1)[1]
        for value in REQUIRED_STATUS_VALUES:
            self.assertIn(
                f"status: {value}",
                marker_section,
                f"Marker contract section missing 'status: {value}' row",
            )
        for field in REQUIRED_COMPANION_FIELDS:
            self.assertIn(
                field,
                marker_section,
                f"Marker contract section missing '{field}' field row",
            )

    def test_template_contains_no_runtime_status_assertions(self):
        """Plan must not instruct the agent to set in_progress/completed/error/blocked directly.

        The agent's job is to (a) update index.json, (b) emit the marker. Plan does
        not write to those states. A regression here would mean the template
        contradicts the state machine documented in § 'Per-step status'."""
        template_section = self.text.split("### Step file template (pinned)", 1)[1].split(
            "### Marker contract", 1
        )[0]
        # The template must say "Status: pending" as the initial value, and
        # must not include phrases like "set status to in_progress" that
        # would push plan into runtime states.
        self.assertIn(
            "**pending**",
            template_section,
            "template must initialize Status: pending (plan owns this transition)",
        )
        bad_phrases = (
            "set status to in_progress",
            "set status to completed",
            "set status to error",
            "set status to blocked",
        )
        for phrase in bad_phrases:
            self.assertNotIn(
                phrase.lower(),
                template_section.lower(),
                f"template must not instruct plan to write runtime state: {phrase!r}",
            )

    def test_marker_is_paired_with_index_json_update(self):
        """The template's Verification section must instruct the agent to update index.json.

        This guarantees the marker is a hint on top of a real index.json write,
        not a replacement for it (the runner trusts index.json if they disagree).
        """
        verification = re.search(
            r"## Verification & Status Update.*?(?=^## )",
            self.text,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(verification, "Verification section not found")
        self.assertIn(
            "index.json",
            verification.group(0),
            "Verification & Status Update must reference phases/<phase>/index.json update",
        )
        for value in REQUIRED_STATUS_VALUES:
            self.assertIn(
                f'"status": "{value}"',
                verification.group(0),
                f"Verification section missing '\"status\": \"{value}\"' index.json write",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
