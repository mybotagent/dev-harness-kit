#!/usr/bin/env python3
"""test_research_proposal_plan.py — Pattern 3 (research -> proposal -> plan)
binder structure validation.

Each test is independent (no shared mutable state). The binder is the
3-phase skill described in
`docs/proposals/playbook-application/02-reanalysis.yaml` Pattern 3,
replaced from the prior research-plan-build binder: build is OUT of
scope, the human approval gate sits BEFORE plan decomposition.

Covered:
  - `skills/research-proposal-plan/SKILL.md` exists and has the
    required frontmatter (name, alpha, user-invocable).
  - `templates/research.md` and `templates/proposal.md` parse as
    markdown with the required section headers.
  - `skills/build/SKILL.md` references `research-proposal-plan` under
    the composition section.
  - The plan-skill `disable-model-invocation: true` invariant is
    documented in the binder body (the binder knows it cannot
    Skill-invoke plan).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_frontmatter(md: str) -> dict:
    """Parse the YAML frontmatter block via PyYAML."""
    import yaml  # already a project dependency (tests/test_smoke.py)
    m = re.match(r"^---\n(.+?)\n---", md, re.DOTALL)
    assert m, f"frontmatter missing in {md[:40]!r}..."
    return yaml.safe_load(m.group(1)) or {}


SKILL_PATH = PROJECT_ROOT / "skills" / "research-proposal-plan" / "SKILL.md"
RESEARCH_TEMPLATE = PROJECT_ROOT / "templates" / "research.md"
PROPOSAL_TEMPLATE = PROJECT_ROOT / "templates" / "proposal.md"
PLAN_SKILL_PATH = PROJECT_ROOT / "skills" / "plan" / "SKILL.md"
BUILD_SKILL_PATH = PROJECT_ROOT / "skills" / "build" / "SKILL.md"


class TestBinderSkillExists(unittest.TestCase):
    """The binder SKILL.md must exist and declare the L6 alpha field."""

    def test_skill_file_exists(self):
        self.assertTrue(
            SKILL_PATH.exists(),
            f"missing {SKILL_PATH}",
        )

    def test_frontmatter_has_required_fields(self):
        text = _read_text(SKILL_PATH)
        fm = _parse_frontmatter(text)
        for field in ("name", "alpha", "category", "description"):
            self.assertIn(
                field, fm,
                f"frontmatter missing required field {field!r}: {fm}",
            )
        self.assertEqual(fm["name"], "research-proposal-plan")
        # L6 alpha gate — must be one of the 3 allowed values.
        self.assertIn(
            fm["alpha"], {"state", "enforcement", "analysis"},
            f"alpha={fm['alpha']!r} not in allowed set",
        )

    def test_skill_declares_user_invocable(self):
        """Human-use skill — exposed as `/dev-kit:research-proposal-plan`."""
        fm = _parse_frontmatter(_read_text(SKILL_PATH))
        # PyYAML parses unquoted `true` as the bool True.
        self.assertEqual(
            fm.get("user-invocable"), True,
            "research-proposal-plan is human-invoked; user-invocable must be true",
        )

    def test_body_documents_three_phases(self):
        """The SKILL.md body must describe research, proposal, and plan
        hand-off phases — Pattern 3 contract."""
        text = _read_text(SKILL_PATH)
        for header in (
            "### Phase 1",
            "### Phase 2",
            "### Phase 3",
        ):
            self.assertIn(
                header, text,
                f"missing phase header {header!r} in body",
            )


class TestResearchTemplate(unittest.TestCase):
    """templates/research.md must parse and contain the 4 required
    sections: Question, Evidence, Cross-validation, Conclusion."""

    def test_template_exists(self):
        self.assertTrue(
            RESEARCH_TEMPLATE.exists(),
            f"missing {RESEARCH_TEMPLATE}",
        )

    def test_required_headers_present(self):
        text = _read_text(RESEARCH_TEMPLATE)
        for header in (
            "## Question",
            "## Evidence",
            "## Cross-validation",
            "## Conclusion",
        ):
            self.assertIn(
                header, text,
                f"research template missing header {header!r}",
            )

    def test_evidence_table_has_required_columns(self):
        text = _read_text(RESEARCH_TEMPLATE)
        # The Evidence section must enforce the citation contract:
        # url, fetched_at, source_type.
        for column in ("Source URL", "Fetched at", "Source type", "Confidence"):
            self.assertIn(
                column, text,
                f"Evidence table missing column {column!r}",
            )


class TestProposalTemplate(unittest.TestCase):
    """templates/proposal.md must parse and contain the required
    sections: Authoring contract, Slug derivation, Gate, Hand-off."""

    def test_template_exists(self):
        self.assertTrue(
            PROPOSAL_TEMPLATE.exists(),
            f"missing {PROPOSAL_TEMPLATE}",
        )

    def test_required_headers_present(self):
        text = _read_text(PROPOSAL_TEMPLATE)
        for header in (
            "## Authoring contract",
            "## Slug derivation",
            "## Gate to advance",
            "## Hand-off chain",
        ):
            self.assertIn(
                header, text,
                f"proposal template missing header {header!r}",
            )

    def test_template_points_to_proposal_skill_schema(self):
        text = _read_text(PROPOSAL_TEMPLATE)
        # The binder-side template must defer to the proposal skill's
        # canonical schema — do not duplicate the YAML shape here.
        self.assertIn(
            "skills/proposal/SKILL.md",
            text,
            "proposal.md must defer to skills/proposal/SKILL.md for the "
            "canonical YAML shape, not duplicate it",
        )

    def test_template_documents_status_field(self):
        text = _read_text(PROPOSAL_TEMPLATE)
        # The status field is the approval gate; the template must
        # document `ready-for-review` as the binder's authored value.
        self.assertIn(
            "ready-for-review", text,
            "proposal.md must document status: ready-for-review as the "
            "binder's authored YAML value",
        )


class TestBuildComposition(unittest.TestCase):
    """skills/build/SKILL.md must wire the research-proposal-plan trigger."""

    def test_build_skill_exists(self):
        self.assertTrue(
            BUILD_SKILL_PATH.exists(),
            f"missing {BUILD_SKILL_PATH}",
        )

    def test_build_skill_references_research_proposal_plan(self):
        text = _read_text(BUILD_SKILL_PATH)
        self.assertIn(
            "research-proposal-plan", text,
            "build/SKILL.md must reference research-proposal-plan in the "
            "composition section",
        )
        # Must mention the trigger condition explicitly.
        self.assertIn(
            "1 session", text,
            "build/SKILL.md must document the >1 session trigger",
        )
        self.assertIn(
            "3 files", text,
            "build/SKILL.md must document the >3 files trigger",
        )

    def test_build_skill_has_compose_section(self):
        """The composition section heading must be present."""
        text = _read_text(BUILD_SKILL_PATH)
        self.assertIn(
            "## Composition", text,
            "build/SKILL.md must have a ## Composition section",
        )

    def test_build_skill_drops_old_binder_reference(self):
        text = _read_text(BUILD_SKILL_PATH)
        self.assertNotIn(
            "research-plan-build", text,
            "build/SKILL.md must NOT reference the old research-plan-build "
            "binder; it was replaced by research-proposal-plan",
        )


class TestCitationGateExecutableContract(unittest.TestCase):
    """The Phase 1 -> Phase 2 gate must match `enforce_citations()`'s
    string return type, NOT a numeric count. The function returns
    annotated text (`lib/research_engine.py:607`), not a count of
    uncited sentences.
    """

    def test_skill_gate_uses_marker_absence_not_count(self):
        body = _read_text(SKILL_PATH)
        # Must describe absence-of-marker semantics, not a number.
        self.assertIn(
            "[UNCITED] not in annotated", body,
            "research-proposal-plan skill must describe the gate as "
            '"[UNCITED] not in annotated" (enforce_citations returns '
            "annotated text, not a count)",
        )
        self.assertNotIn(
            "zero uncited sentences",
            body,
            "skill must NOT describe the gate as a numeric count; "
            "enforce_citations returns annotated text, not a count",
        )

    def test_research_template_gate_uses_marker_absence(self):
        body = _read_text(RESEARCH_TEMPLATE)
        self.assertIn(
            "[UNCITED]", body,
            "research.md must surface the [UNCITED] marker as the gate signal",
        )
        self.assertIn(
            "returns annotated text, not a count",
            body,
            "research.md must clarify enforce_citations() return type so "
            "the executable gate is unambiguous",
        )


class TestPlanHandOffInvariant(unittest.TestCase):
    """The plan skill is `disable-model-invocation: true`. The binder
    must NOT try to Skill-invoke it; the human re-invocation is the
    approval gate.
    """

    def test_plan_skill_disables_model_invocation(self):
        """Sanity: the invariant the binder depends on still holds."""
        fm = _parse_frontmatter(_read_text(PLAN_SKILL_PATH))
        self.assertEqual(
            fm.get("disable-model-invocation"), True,
            "plan/SKILL.md must keep disable-model-invocation: true; the "
            "binder's hand-off contract depends on it",
        )

    def test_skill_documents_plan_disable_invariant(self):
        body = _read_text(SKILL_PATH)
        self.assertIn(
            "disable-model-invocation", body,
            "binder body must cite the plan skill's disable-model-invocation "
            "flag — that is the human gate, not a workaround",
        )

    def test_skill_writes_hand_off_file(self):
        body = _read_text(SKILL_PATH)
        self.assertIn(
            "rpp→plan.md", body,
            "binder must name the .dev-kit/hand-off/rpp->plan.md hand-off "
            "file as Phase 3's artifact",
        )


class TestCrossArtifactContract(unittest.TestCase):
    """Cross-check: skill and templates stay coherent."""

    def test_skill_cites_research_and_proposal_templates(self):
        text = _read_text(SKILL_PATH)
        self.assertIn("templates/research.md", text)
        self.assertIn("templates/proposal.md", text)

    def test_skill_enforces_non_skippable_phases(self):
        text = _read_text(SKILL_PATH)
        # The "cannot be skipped" contract must be present and explicit.
        self.assertIn(
            "cannot be skipped", text,
            "skill body must declare phases are non-skippable",
        )

    def test_skill_categorizes_as_plan(self):
        fm = _parse_frontmatter(_read_text(SKILL_PATH))
        self.assertEqual(
            fm.get("category"), "plan",
            "binder category must be 'plan' — the chain culminates in "
            "plan emission, not build (build is OUT of scope)",
        )

    def test_skill_excludes_build_from_phases(self):
        body = _read_text(SKILL_PATH)
        # Build is OUT — the binder must say so explicitly so a future
        # reader doesn't try to re-add it.
        self.assertIn(
            "Build is OUT", body,
            "skill body must explicitly state build is OUT of the binder",
        )


class TestBuildSkillGateAlignment(unittest.TestCase):
    """Contract tests for the build skill -> binder composition gate.

    The composition instruction in `skills/build/SKILL.md` is
    `Skill("research-proposal-plan", <idea>)`. For that call to be
    permitted, `Skill` must appear in `allowed-tools`. Mirrors the
    convention established at `skills/plan/SKILL.md:10`.
    """

    def test_build_skill_allows_skill_tool(self):
        fm = _parse_frontmatter(_read_text(BUILD_SKILL_PATH))
        allowed = fm.get("allowed-tools", "").split()
        self.assertIn(
            "Skill", allowed,
            "build/SKILL.md allowed-tools must include 'Skill' so the "
            "documented Skill('research-proposal-plan', <idea>) handoff is "
            "permitted. Mirror skills/plan/SKILL.md:10.",
        )

    def test_build_skill_does_not_disallow_skill_tool(self):
        fm = _parse_frontmatter(_read_text(BUILD_SKILL_PATH))
        disallowed = fm.get("disallowed-tools", "").split()
        self.assertNotIn(
            "Skill", disallowed,
            "build/SKILL.md disallowed-tools must NOT include 'Skill'.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
