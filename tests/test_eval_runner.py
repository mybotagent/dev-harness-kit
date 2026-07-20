#!/usr/bin/env python3
"""test_eval_runner.py — RED-first tests for lib/eval_runner.py (schema 2.0.0).

Targets the new agent-behavior eval: case-based discovery, transcript
replay, per-dim judge dispatch, per-dim report. Mocks the LLM judge so
the tests are deterministic.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import eval_runner  # noqa: E402
import llm_judge  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed_case(root: Path, dim: str, case_id: str, category: str, expected: dict) -> Path:
    case_dir = root / "eval" / "cases" / dim
    case_dir.mkdir(parents=True, exist_ok=True)
    case_path = case_dir / f"{case_id}.json"
    case_path.write_text(
        json.dumps(
            {
                "case_id": case_id,
                "dim": dim,
                "category": category,
                "expected": expected,
                "schema_version": "2.0.0",
            }
        ),
        encoding="utf-8",
    )
    return case_path


def _seed_transcript(root: Path, dim: str, case_id: str, agent_output: dict) -> Path:
    t_dir = root / "eval" / "transcripts" / dim
    t_dir.mkdir(parents=True, exist_ok=True)
    t_path = t_dir / f"{case_id}.json"
    t_path.write_text(
        json.dumps(
            {
                "case_id": case_id,
                "dim": dim,
                "agent_output": agent_output,
                "captured_at": "2026-07-09T19:00:00+09:00",
                "captured_by": "test",
            }
        ),
        encoding="utf-8",
    )
    return t_path


class TestDiscoverCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for dim in ("review", "security", "plan"):
            (self.root / "eval" / "cases" / dim).mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_discovers_one_case_per_dim(self):
        for dim in ("review", "security", "plan"):
            _seed_case(self.root, dim, f"{dim}-01-test", "real-bug", {"verdict": "Blocked"})
        cases = eval_runner.discover_cases(self.root)
        kinds = sorted(c["dim"] for c in cases)
        self.assertEqual(kinds, ["plan", "review", "security"])
        self.assertEqual(len(cases), 3)

    def test_skips_case_with_wrong_dim_field(self):
        _write(
            self.root / "eval" / "cases" / "review" / "bad.json",
            json.dumps({"case_id": "bad", "dim": "security", "schema_version": "2.0.0"}),
        )
        cases = eval_runner.discover_cases(self.root)
        self.assertEqual(cases, [])

    def test_skips_unknown_dim_dir(self):
        (self.root / "eval" / "cases" / "weird-dim").mkdir()
        _write(
            self.root / "eval" / "cases" / "weird-dim" / "x.json",
            json.dumps({"case_id": "x", "dim": "weird-dim"}),
        )
        cases = eval_runner.discover_cases(self.root)
        self.assertEqual(cases, [])

    def test_no_cases_dir_returns_empty(self):
        cases = eval_runner.discover_cases(self.root)
        self.assertEqual(cases, [])

    def test_each_case_has_required_fields(self):
        _seed_case(self.root, "review", "review-01-test", "real-bug", {"verdict": "Blocked"})
        cases = eval_runner.discover_cases(self.root)
        for c in cases:
            for key in ("case_id", "dim", "expected", "schema_version", "raw_path"):
                self.assertIn(key, c, f"missing {key}")


class TestTranscriptIO(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_transcript_returns_none_when_missing(self):
        self.assertIsNone(eval_runner.load_transcript(self.root, "review", "nope"))

    def test_load_transcript_roundtrip(self):
        _seed_transcript(
            self.root, "review", "review-01", {"verdict": "Blocked", "findings": []}
        )
        t = eval_runner.load_transcript(self.root, "review", "review-01")
        self.assertIsNotNone(t)
        self.assertEqual(t["agent_output"]["verdict"], "Blocked")

    def test_save_transcript_atomic(self):
        p = eval_runner.save_transcript(
            self.root, "review", "review-01", {"agent_output": {"verdict": "Approve"}}
        )
        self.assertTrue(p.exists())
        self.assertIn("Approve", p.read_text())


class TestJudgeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for dim in ("review", "security", "plan"):
            (self.root / "eval" / "cases" / dim).mkdir(parents=True)
            (self.root / "eval" / "transcripts" / dim).mkdir(parents=True)
        # Seed a review case + transcript.
        _seed_case(
            self.root, "review", "review-01-sql", "real-bug",
            {"verdict": "Blocked", "min_severity": "major"},
        )
        _seed_transcript(
            self.root, "review", "review-01-sql",
            {"verdict": "Blocked", "findings": [{"dim": "security", "severity": "critical"}]},
        )
        # A prompt template is required for _judge_case to render.
        _write(
            self.root / "eval" / "prompts" / "judge-review.md",
            "# judge-review\n${INPUT}\n${AGENT_OUTPUT}\n${EXPECTED}\n${RUBRIC}\n"
            "${CASE_ID} ${DIM} ${CATEGORY}\n",
        )
        _write(
            self.root / "eval" / "prompts" / "judge-code-sanity.md",
            "# code-sanity rubric (placeholder for tests)",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_judge_case_returns_5_axes_for_review(self):
        with patch.object(llm_judge, "call_judge", return_value={
            "scores": {ax: 9.0 for ax in llm_judge.DIM_AXES["review"]},
            "tokens_in": 1, "tokens_out": 1, "raw": "{}",
        }):
            case = eval_runner.discover_cases(self.root)[0]
            result = eval_runner.judge_case(self.root, case)
        self.assertEqual(set(result["scores"]), set(llm_judge.DIM_AXES["review"]))
        self.assertEqual(len(result["scores"]), 5)
        self.assertEqual(result["verdict"], "OK")
        self.assertEqual(result["score"], 9.0)

    def test_judge_case_missing_transcript_returns_skipped(self):
        # Case without a transcript.
        _seed_case(
            self.root, "plan", "plan-01-no-tx", "clear-spec", {"verdict": "Approve"}
        )
        case = eval_runner.discover_cases(self.root)
        plan_case = [c for c in case if c["case_id"] == "plan-01-no-tx"][0]
        with patch.object(llm_judge, "call_judge") as mock_judge:
            result = eval_runner.judge_case(self.root, plan_case)
        mock_judge.assert_not_called()  # no LLM call for missing transcript
        self.assertEqual(result["verdict"], "SKIPPED")


class TestRunEval(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for dim in ("review", "security", "plan"):
            (self.root / "eval" / "cases" / dim).mkdir(parents=True)
            (self.root / "eval" / "transcripts" / dim).mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_no_api_key_returns_mocks(self):
        for dim in llm_judge.DIM_AXES:
            _seed_case(self.root, dim, f"{dim}-01", "x", {"verdict": "OK"})
            _seed_transcript(
                self.root, dim, f"{dim}-01", {"verdict": "Approve", "findings": []}
            )
        report = eval_runner.run_eval(self.root, dry_run=True)
        self.assertEqual(report["summary"]["OK"], 0)
        self.assertEqual(report["summary"]["DRIFT_WARNING"], 3)
        self.assertEqual(report["summary"]["ROT"], 0)
        self.assertEqual(report["summary"]["SKIPPED"], 0)
        self.assertEqual(len(report["results"]), 3)

    def test_run_eval_writes_report(self):
        # Seed at least one case per dim so the per-dim table has content.
        for dim in llm_judge.DIM_AXES:
            _seed_case(self.root, dim, f"{dim}-01", "x", {"verdict": "OK"})
            _seed_transcript(
                self.root, dim, f"{dim}-01", {"verdict": "Approve", "findings": []}
            )
        report = eval_runner.run_eval(self.root, dry_run=True)
        out = self.root / ".dev-kit" / "eval-report.md"
        self.assertTrue(out.exists())
        body = out.read_text()
        self.assertIn("Per-Dimension Scores", body)
        self.assertIn("review", body)
        self.assertIn("security", body)
        self.assertIn("plan", body)

    def test_dim_filter(self):
        _seed_case(self.root, "review", "review-01", "x", {"verdict": "OK"})
        _seed_transcript(
            self.root, "review", "review-01", {"verdict": "Approve", "findings": []}
        )
        _seed_case(self.root, "plan", "plan-01", "x", {"verdict": "OK"})
        _seed_transcript(self.root, "plan", "plan-01", {"verdict": "Approve"})
        report = eval_runner.run_eval(self.root, dry_run=True, dim="plan")
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["dim"], "plan")

    def test_case_filter(self):
        _seed_case(self.root, "review", "review-01-a", "x", {"verdict": "OK"})
        _seed_transcript(self.root, "review", "review-01-a", {"verdict": "Approve"})
        _seed_case(self.root, "review", "review-02-b", "x", {"verdict": "OK"})
        _seed_transcript(self.root, "review", "review-02-b", {"verdict": "Approve"})
        report = eval_runner.run_eval(
            self.root, dry_run=True, case="review-02-b"
        )
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["case_id"], "review-02-b")

    def test_invalid_dim_raises(self):
        with self.assertRaises(ValueError):
            eval_runner.run_eval(self.root, dry_run=True, dim="bogus")

    def test_missing_transcript_marked_skipped(self):
        _seed_case(self.root, "review", "review-01", "x", {"verdict": "OK"})
        # No transcript seeded.
        report = eval_runner.run_eval(self.root, dry_run=True)
        self.assertEqual(report["summary"]["SKIPPED"], 1)

    def test_judge_api_error_marks_rot_continues(self):
        _seed_case(self.root, "review", "review-01", "x", {"verdict": "OK"})
        _seed_transcript(self.root, "review", "review-01", {"verdict": "Approve"})
        _write(
            self.root / "eval" / "prompts" / "judge-review.md",
            "# judge-review stub\n${CASE_ID} ${DIM} ${CATEGORY}\n${INPUT}\n${AGENT_OUTPUT}\n${EXPECTED}\n${RUBRIC}\n",
        )
        _write(
            self.root / "eval" / "prompts" / "judge-code-sanity.md",
            "# rubric stub",
        )
        with patch.object(
            llm_judge, "call_judge", side_effect=RuntimeError("api down")
        ), patch.object(
            llm_judge, "load_config",
            return_value={"provider": "minimax", "model": "x",
                          "api_key": "fake", "base_url": "x"},
        ):
            report = eval_runner.run_eval(self.root, dry_run=False)
        self.assertEqual(report["summary"]["ROT"], 1)
        self.assertIn("api down", report["results"][0].get("error", ""))


# --- per-helper tests (issue #93) ---------------------------------------

class TestRenderSummary(unittest.TestCase):
    def test_block_includes_verdict_counts(self):
        results = [
            {"verdict": "OK"}, {"verdict": "OK"},
            {"verdict": "DRIFT_WARNING"}, {"verdict": "ROT"},
            {"verdict": "SKIPPED"},
        ]
        out = eval_runner._render_summary(results)
        self.assertIn("## Summary", out)
        self.assertIn("- Total cases: 5", out)
        self.assertIn("- OK: 2", out)
        self.assertIn("- DRIFT_WARNING: 1", out)
        self.assertIn("- ROT: 1", out)
        self.assertIn("- SKIPPED: 1", out)

    def test_block_handles_empty_results(self):
        out = eval_runner._render_summary([])
        self.assertIn("## Summary", out)
        self.assertIn("- Total cases: 0", out)


class TestRenderPerDimTable(unittest.TestCase):
    def test_block_includes_axes(self):
        results = [
            {"dim": "review", "verdict": "OK", "scores": {"precision": 9.0, "recall": 8.0}},
            {"dim": "review", "verdict": "DRIFT_WARNING", "scores": {"precision": 7.0, "recall": 7.0}},
        ]
        out = eval_runner._render_per_dim_table(results)
        self.assertIn("## Per-Dimension Scores", out)
        self.assertIn("### review", out)
        self.assertIn("| Axis | Mean |", out)
        self.assertIn("`precision`", out)
        self.assertIn("`recall`", out)


class TestRenderPerCase(unittest.TestCase):
    def test_block_includes_case_id_and_axes(self):
        results = [
            {"verdict": "OK", "case_id": "case-1", "dim": "review",
             "score": 9.0, "scores": {"precision": 9.0, "recall": 8.0}},
        ]
        out = eval_runner._render_per_case(results)
        self.assertIn("## Per-Case Results", out)
        self.assertIn("`case-1`", out)
        self.assertIn("dim=review", out)
        self.assertIn("precision=9.0", out)


class TestWriteReportDispatcher(unittest.TestCase):
    def test_body_thin(self):
        import inspect
        source = inspect.getsource(eval_runner.write_report)
        logic_lines = [
            l for l in source.splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
        self.assertLess(
            len(logic_lines), 50,
            f"write_report too long: {len(logic_lines)} lines",
        )


class TestRunEvalDispatcher(unittest.TestCase):
    def test_body_thin(self):
        import inspect
        source = inspect.getsource(eval_runner.run_eval)
        logic_lines = [
            l for l in source.splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
        self.assertLess(
            len(logic_lines), 50,
            f"run_eval too long: {len(logic_lines)} lines",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
