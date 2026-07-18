#!/usr/bin/env python3
"""test_analysis_core_runner.py — End-to-end on a tiny synthetic repo.

Builds a 3-file synthetic repo, runs the engine with a synthetic
candidate stream, and asserts:

  - the engine resolves the right dimensions for each mode
  - candidate JSON parses into Evidence
  - the FP filter pipeline drops/retains as expected
  - the renderer produces stable markdown with the per-dim summary
  - the diff emitter emits `rm` for delete mode and a `# rewrite:`
    header for rewrite mode
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.analysis_core import (  # noqa: E402
    run_analysis,
    render_markdown,
    emit_suggested_diffs,
    group,
    Severity,
    Evidence,
)


def _build_synth_repo() -> Path:
    """Create a tiny 3-file repo. Returns the tmp dir."""
    tmp = tempfile.mkdtemp(prefix="ac-synth-")
    root = Path(tmp)
    (root / "a.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n",
        encoding="utf-8",
    )
    (root / "b.py").write_text(
        "def add(a, b):  # dup\n"
        "    return a + b\n",
        encoding="utf-8",
    )
    (root / "c.py").write_text(
        "import os\n"
        "x = os.environ.get('X')\n",
        encoding="utf-8",
    )
    return root


class TestRunAnalysis(unittest.TestCase):
    def test_run_analysis_review_keeps_real_finds(self):
        """Review-mode run on a synthetic repo with realistic candidate stream."""
        repo = _build_synth_repo()
        candidates = {
            "correctness": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "missing input validation",
                    "tldr": "add() does not check types",
                    "failure_scenario": "add(1, 'x') raises TypeError",
                    "fix_hint": "guard with isinstance",
                },
            ],
            "security": [
                {
                    "file": str(repo / "c.py"),
                    "line": 2,
                    "severity": "critical",
                    "confidence": "high",
                    "title": "insecure env read",
                    "tldr": "no secret filter",
                    "failure_scenario": "leaks X in logs",
                },
            ],
            "architecture": [],
        }
        result = run_analysis(
            dimensions=group("review"),
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        self.assertEqual(result.kept_count, 2)
        self.assertEqual(result.filtered_count, 0)
        self.assertEqual(len(result.findings), 2)
        severities = [f.severity for f in result.findings]
        self.assertEqual(
            sorted(severities, key=lambda s: s.value),
            sorted([Severity.CRITICAL, Severity.MAJOR], key=lambda s: s.value),
        )

    def test_run_analysis_filters_missing_failure_scenario(self):
        repo = _build_synth_repo()
        candidates = {
            "correctness": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "speculative",
                    "tldr": "maybe",
                    "failure_scenario": "",  # empty → drop
                },
            ],
        }
        result = run_analysis(
            dimensions=["correctness"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        self.assertEqual(result.kept_count, 0)
        self.assertGreaterEqual(result.filtered_count, 1)

    def test_run_analysis_delete_drops_nits(self):
        repo = _build_synth_repo()
        candidates = {
            "dead": [
                {
                    "file": str(repo / "b.py"),
                    "line": 1,
                    "severity": "nit",
                    "confidence": "medium",
                    "title": "unused",
                    "tldr": "trivia",
                    "failure_scenario": "no callers",
                    "fix_hint": "rm b.py",
                },
            ],
        }
        result = run_analysis(
            dimensions=["dead"],
            mode="delete",
            paths=[repo],
            candidates=candidates,
        )
        self.assertEqual(result.kept_count, 0)

    def test_run_analysis_unknown_dimension_raises(self):
        with self.assertRaises(KeyError):
            run_analysis(
                dimensions=["not-a-dim"],
                mode="read-only",
                paths=[],
                candidates={},
            )


class TestRenderMarkdown(unittest.TestCase):
    def test_markdown_contains_per_dim_summary(self):
        repo = _build_synth_repo()
        candidates = {
            "correctness": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "missing guard",
                    "tldr": "no type check",
                    "failure_scenario": "bad input crashes",
                },
            ],
        }
        result = run_analysis(
            dimensions=["correctness"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        md = render_markdown(result)
        self.assertIn("# Analysis Report", md)
        self.assertIn("correctness", md)
        self.assertIn("missing guard", md)
        self.assertIn("Verdict:", md)

    def test_empty_findings_renders_clean(self):
        repo = _build_synth_repo()
        result = run_analysis(
            dimensions=["correctness"],
            mode="read-only",
            paths=[repo],
            candidates={"correctness": []},
        )
        md = render_markdown(result)
        self.assertIn("Verdict:", md)
        self.assertIn("Healthy", md)


class TestEmitSuggestedDiffs(unittest.TestCase):
    def test_delete_mode_emits_rm(self):
        repo = _build_synth_repo()
        candidates = {
            "dead": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "unused file",
                    "tldr": "no importers",
                    "failure_scenario": "no callers",
                    "fix_hint": "rm a.py",
                },
            ],
        }
        result = run_analysis(
            dimensions=["dead"],
            mode="delete",
            paths=[repo],
            candidates=candidates,
        )
        diffs = emit_suggested_diffs(result)
        self.assertEqual(len(diffs), 1)
        self.assertIn("rm ", diffs[0].command)

    def test_rewrite_mode_emits_header(self):
        repo = _build_synth_repo()
        candidates = {
            "smell": [
                {
                    "file": str(repo / "c.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "long method",
                    "tldr": "too big",
                    "failure_scenario": "unmaintainable",
                    "fix_hint": "split into helpers",
                },
            ],
        }
        result = run_analysis(
            dimensions=["smell"],
            mode="rewrite",
            paths=[repo],
            candidates=candidates,
        )
        diffs = emit_suggested_diffs(result)
        self.assertEqual(len(diffs), 1)
        self.assertIn("# rewrite:", diffs[0].command)

    def test_read_only_emits_no_command(self):
        repo = _build_synth_repo()
        candidates = {
            "correctness": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "x",
                    "tldr": "y",
                    "failure_scenario": "z",
                },
            ],
        }
        result = run_analysis(
            dimensions=["correctness"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        self.assertEqual(emit_suggested_diffs(result), [])


class TestDeterministicEndToEnd(unittest.TestCase):
    """Two runs with identical inputs MUST produce identical outputs."""

    def test_repeatable_output(self):
        repo = _build_synth_repo()
        candidates = {
            "correctness": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "x",
                    "tldr": "y",
                    "failure_scenario": "z",
                },
            ],
        }
        r1 = run_analysis(
            dimensions=["correctness"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        r2 = run_analysis(
            dimensions=["correctness"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        self.assertEqual(render_markdown(r1), render_markdown(r2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
