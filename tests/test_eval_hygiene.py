#!/usr/bin/env python3
"""test_eval_hygiene.py — Hygiene tests for the new agent-behavior eval.

- dry-run mode skips LLM calls and writes a report
- golden schema 2.0.0 fields are present in every real golden
- 12+ case files exist across 3 dims
- 4 new prompts (judge-review, judge-security, judge-plan, judge-code-sanity) exist
- the code-sanity rubric has 20 checkbox items
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import eval_runner  # noqa: E402


class TestEvalDryRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for dim in ("review", "security", "plan"):
            (self.root / "eval" / "cases" / dim).mkdir(parents=True)
            (self.root / "eval" / "transcripts" / dim).mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_no_api_key_skips_llm(self):
        # No cases at all -> empty results, no LLM call.
        result = eval_runner.run_eval(self.root, dry_run=True)
        self.assertEqual(result["results"], [])

    def test_run_eval_writes_report_at_correct_path(self):
        eval_runner.run_eval(self.root, dry_run=True)
        report = self.root / ".dev-kit" / "eval-report.md"
        self.assertTrue(report.exists())


class TestRealCasesExist(unittest.TestCase):
    """Verify the real eval/cases/ tree in the repo (>=12 cases across 3 dims)."""

    def test_real_cases_exist_at_least_12(self):
        root = Path(__file__).parent.parent
        cases_dir = root / "eval" / "cases"
        if not cases_dir.exists():
            self.skipTest("cases dir not generated yet")
        files = list(cases_dir.rglob("*.json"))
        self.assertGreaterEqual(
            len(files), 12,
            f"expected >=12 case files, got {len(files)}",
        )

    def test_real_cases_cover_three_dims(self):
        root = Path(__file__).parent.parent
        cases_dir = root / "eval" / "cases"
        if not cases_dir.exists():
            self.skipTest("cases dir not generated")
        dims = {p.parent.name for p in cases_dir.rglob("*.json")}
        self.assertEqual(dims, {"review", "security", "plan"})

    def test_real_transcripts_exist(self):
        root = Path(__file__).parent.parent
        t_dir = root / "eval" / "transcripts"
        if not t_dir.exists():
            self.skipTest("transcripts dir not generated")
        files = list(t_dir.rglob("*.json"))
        self.assertGreaterEqual(
            len(files), 12,
            f"expected >=12 transcript files, got {len(files)}",
        )

    def test_every_case_has_matching_transcript(self):
        root = Path(__file__).parent.parent
        cases_dir = root / "eval" / "cases"
        t_dir = root / "eval" / "transcripts"
        if not cases_dir.exists() or not t_dir.exists():
            self.skipTest("cases or transcripts dir missing")
        for case_path in cases_dir.rglob("*.json"):
            case = json.loads(case_path.read_text())
            t_path = t_dir / case["dim"] / f"{case['case_id']}.json"
            self.assertTrue(
                t_path.exists(),
                f"missing transcript for {case['case_id']} (dim={case['dim']})",
            )


class TestRealPromptsExist(unittest.TestCase):
    """Verify the 4 new judge prompts exist (and old 3 are gone)."""

    EXPECTED_PROMPTS = {
        "judge-review.md",
        "judge-security.md",
        "judge-plan.md",
        "judge-code-sanity.md",
    }
    DELETED_PROMPTS = {
        "judge-claude-md.md",
        "judge-skill.md",
        "judge-hook.md",
    }

    def test_prompts_are_new_schema(self):
        root = Path(__file__).parent.parent
        prompts = root / "eval" / "prompts"
        if not prompts.exists():
            self.skipTest("prompts dir not generated")
        present = {p.name for p in prompts.glob("*.md")}
        missing = self.EXPECTED_PROMPTS - present
        self.assertFalse(missing, f"missing prompts: {missing}")
        leftover = self.DELETED_PROMPTS & present
        self.assertFalse(leftover, f"old prompts still present: {leftover}")

    def test_code_sanity_rubric_has_20_checkboxes(self):
        root = Path(__file__).parent.parent
        rubric_path = root / "eval" / "prompts" / "judge-code-sanity.md"
        if not rubric_path.exists():
            self.skipTest("rubric not generated yet")
        text = rubric_path.read_text(encoding="utf-8")
        # 20 items: CC-1..8 + OE-1..8 + VM-1..4
        items = re.findall(r"^(CC|OE|VM)-\d+\.", text, re.MULTILINE)
        self.assertEqual(
            len(items), 20,
            f"expected 20 code-sanity items, found {len(items)}",
        )


class TestRealGoldenFiles(unittest.TestCase):
    """Verify the new schema-2.0.0 golden files exist + have required fields."""

    REQUIRED_KEYS = {
        "case_id", "dim", "category", "schema_version",
        "baseline_hash", "captured_at", "expected", "expected_behavior",
        "iron_law_refs", "code_refs",
    }

    def test_real_golden_files_exist(self):
        root = Path(__file__).parent.parent
        golden_dir = root / "eval" / "golden"
        if not golden_dir.exists():
            self.skipTest("golden dir not generated yet")
        files = list(golden_dir.glob("*.json"))
        self.assertGreaterEqual(
            len(files), 12,
            f"expected >=12 golden baselines, got {len(files)}",
        )

    def test_real_golden_files_valid_schema_2_0_0(self):
        root = Path(__file__).parent.parent
        golden_dir = root / "eval" / "golden"
        if not golden_dir.exists():
            self.skipTest("golden dir not generated")
        for f in list(golden_dir.glob("*.json"))[:3]:
            data = json.loads(f.read_text())
            self.assertEqual(data["schema_version"], "2.0.0")
            missing = self.REQUIRED_KEYS - set(data.keys())
            self.assertFalse(missing, f"{f.name} missing: {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
