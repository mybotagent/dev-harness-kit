#!/usr/bin/env python3
"""test_research_plan_build.py — Pattern 3 (research -> plan -> implement)
binder structure validation.

Each test is independent (no shared mutable state). The binder is the
3-phase skill described in
`docs/proposals/playbook-application/02-reanalysis.yaml` Pattern 3.

Covered:
  - `skills/research-plan-build/SKILL.md` exists and has the required
    frontmatter (name, alpha, user-invocable).
  - `templates/research.md` and `templates/plan.md` parse as markdown
    with the required section headers.
  - `skills/build/SKILL.md` references `research-plan-build` under the
    composition section.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_frontmatter(md: str) -> dict:
    """Minimal YAML-frontmatter parser (string-typed values only)."""
    m = re.match(r"^---\n(.+?)\n---", md, re.DOTALL)
    assert m, f"frontmatter missing in {md[:40]!r}..."
    fm: dict = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


SKILL_PATH = PROJECT_ROOT / "skills" / "research-plan-build" / "SKILL.md"
RESEARCH_TEMPLATE = PROJECT_ROOT / "templates" / "research.md"
PLAN_TEMPLATE = PROJECT_ROOT / "templates" / "plan.md"
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
        self.assertEqual(fm["name"], "research-plan-build")
        # L6 alpha gate — must be one of the 3 allowed values.
        self.assertIn(
            fm["alpha"], {"state", "enforcement", "analysis"},
            f"alpha={fm['alpha']!r} not in allowed set",
        )

    def test_skill_declares_user_invocable(self):
        """Human-use skill — exposed as `/dev-kit:research-plan-build`."""
        fm = _parse_frontmatter(_read_text(SKILL_PATH))
        self.assertEqual(
            fm.get("user-invocable"), "true",
            "research-plan-build is human-invoked; user-invocable must be true",
        )

    def test_body_documents_three_phases(self):
        """The SKILL.md body must describe research, plan, and implement
        phases — Pattern 3 contract."""
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


class TestPlanTemplate(unittest.TestCase):
    """templates/plan.md must parse and contain the required sections:
    Goal, Steps, Commit protocol, Risks."""

    def test_template_exists(self):
        self.assertTrue(
            PLAN_TEMPLATE.exists(),
            f"missing {PLAN_TEMPLATE}",
        )

    def test_required_headers_present(self):
        text = _read_text(PLAN_TEMPLATE)
        for header in (
            "## Goal",
            "## Steps",
            "## Commit protocol",
            "## Risks",
        ):
            self.assertIn(
                header, text,
                f"plan template missing header {header!r}",
            )

    def test_steps_table_requires_owner_acceptance_dependencies(self):
        text = _read_text(PLAN_TEMPLATE)
        # Steps table must enforce Owner, Acceptance, Dependencies columns.
        for column in ("Owner", "Acceptance", "Dependencies"):
            self.assertIn(
                column, text,
                f"Steps table missing column {column!r}",
            )


class TestBuildComposition(unittest.TestCase):
    """skills/build/SKILL.md must wire the research-plan-build trigger."""

    def test_build_skill_exists(self):
        self.assertTrue(
            BUILD_SKILL_PATH.exists(),
            f"missing {BUILD_SKILL_PATH}",
        )

    def test_build_skill_references_research_plan_build(self):
        text = _read_text(BUILD_SKILL_PATH)
        self.assertIn(
            "research-plan-build", text,
            "build/SKILL.md must reference research-plan-build in the "
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




class TestRunnerContractAlignment(unittest.TestCase):
    """The 3-phase binder must NOT contradict the build runner's actual
    contract: `lib/execute.py:_run_sequential` emits the canonical
    2-commit protocol per step. `plan.md` is the human-readable
    companion to `phases/<name>/` artifacts, NOT a parallel planning
    SSOT that overrides the runner.
    """

    def test_skill_references_2commit_protocol(self):
        body = _read_text(SKILL_PATH)
        self.assertIn(
            "2-commit", body,
            "research-plan-build skill must reference the build runner's "
            "canonical 2-commit protocol (lib/execute.py:_run_sequential)",
        )

    def test_skill_states_plan_md_is_companion(self):
        body = _read_text(SKILL_PATH)
        self.assertIn(
            "human-readable companion", body.lower(),
            "skill must explicitly state plan.md is the human-readable "
            "companion to phases/<name>/ artifacts",
        )

    def test_skill_states_runner_consumes_phases_not_plan(self):
        body = _read_text(SKILL_PATH)
        # The skill must say the runner consumes phases/<name>/, not plan.md.
        self.assertIn(
            "phases/<name>/index.json", body,
            "skill must name phases/<name>/index.json as the runner's input",
        )

    def test_template_states_companion_role(self):
        body = _read_text(PLAN_TEMPLATE)
        self.assertIn(
            "human-readable companion", body.lower(),
            "plan.md template must declare its role as human-readable "
            "companion to phases/<name>/ artifacts",
        )

    def test_template_documents_2commit_protocol(self):
        body = _read_text(PLAN_TEMPLATE)
        # Both feat + chore commits must be referenced.
        self.assertIn("feat(<scope>): step N", body)
        self.assertIn("chore(<scope>): step N output", body)

    def test_build_skill_states_runner_consumes_phases(self):
        body = _read_text(BUILD_SKILL_PATH)
        self.assertIn(
            "phases/<name>/index.json", body,
            "build/SKILL.md must clarify the runner reads phases/<name>/ "
            "artifacts, NOT plan.md",
        )


class TestCrossArtifactContract(unittest.TestCase):
    """Cross-check: skill and templates stay coherent."""

    def test_skill_cites_research_and_plan_templates(self):
        text = _read_text(SKILL_PATH)
        self.assertIn("templates/research.md", text)
        self.assertIn("templates/plan.md", text)

    def test_skill_cites_analysis_core_for_research_phase(self):
        text = _read_text(SKILL_PATH)
        # Research phase must cite the existing analysis_core engine.
        self.assertIn(
            "analysis_core", text,
            "skill must cite lib/analysis_core/ as the research engine",
        )

    def test_skill_enforces_non_skippable_phases(self):
        text = _read_text(SKILL_PATH)
        # The "cannot be skipped" contract must be present and explicit.
        self.assertIn(
            "cannot be skipped", text,
            "skill body must declare phases are non-skippable",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
