#!/usr/bin/env python3
"""test_parallel_dispatch.py — RED-first tests for tools/parallel_dispatch.py.

Covers the multi-agent fan-out + dedupe + verifier + synthesize pipeline
(issue #177). All agents share the same read-only evidence corpus; no
worktrees; no overlap risk because no writes.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from parallel_dispatch import (  # noqa: E402
    Finding,
    SynthesisResult,
    dedupe_findings,
    fanout_and_synthesize,
)


class TestDedupe(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(dedupe_findings([]), [])

    def test_unique_findings_pass_through(self):
        findings = [
            Finding(file="a.py", line=1, theme="x"),
            Finding(file="b.py", line=2, theme="y"),
        ]
        out = dedupe_findings(findings)
        self.assertEqual(len(out), 2)

    def test_duplicate_key_collapses(self):
        findings = [
            Finding(file="a.py", line=1, theme="x", detail="first"),
            Finding(file="a.py", line=1, theme="x", detail="second"),
        ]
        out = dedupe_findings(findings)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].detail, "first")  # first occurrence wins


class TestFanoutAndSynthesize(unittest.TestCase):
    def _ev(self) -> list[Path]:
        return [Path("a.py"), Path("b.py")]

    def test_runs_dimension_agent_per_dim(self):
        seen_dims: list[str] = []
        def dim_agent(dim, evidence):
            seen_dims.append(dim)
            return [Finding(file="a.py", line=1, theme=dim)]
        out = fanout_and_synthesize(
            dimensions=["A01", "A02", "A03"],
            evidence=self._ev(),
            synthesize_prompt="",
            dimension_agent=dim_agent,
        )
        self.assertEqual(seen_dims, ["A01", "A02", "A03"])
        self.assertEqual(len(out.findings), 3)

    def test_dedupes_across_dims(self):
        def dim_agent(dim, evidence):
            return [Finding(file="a.py", line=1, theme="shared")]
        out = fanout_and_synthesize(
            dimensions=["A01", "A02"],
            evidence=self._ev(),
            synthesize_prompt="",
            dimension_agent=dim_agent,
        )
        # 2 dims × 1 finding each, dedupe on (file,line,theme) → 1 finding
        self.assertEqual(len(out.findings), 1)

    def test_verifier_runs_on_deduped(self):
        def dim_agent(dim, evidence):
            return [
                Finding(file="a.py", line=1, theme="real"),
                Finding(file="a.py", line=2, theme="fake"),
            ]
        def verifier(findings):
            return [f for f in findings if f.theme == "real"]
        out = fanout_and_synthesize(
            dimensions=["A01"],
            evidence=self._ev(),
            synthesize_prompt="",
            dimension_agent=dim_agent,
            verifier=verifier,
        )
        self.assertEqual(len(out.verified), 1)
        self.assertEqual(len(out.rejected), 1)

    def test_no_verifier_keeps_all(self):
        def dim_agent(dim, evidence):
            return [Finding(file="a.py", line=1, theme="x")]
        out = fanout_and_synthesize(
            dimensions=["A01"],
            evidence=self._ev(),
            synthesize_prompt="",
            dimension_agent=dim_agent,
        )
        self.assertEqual(len(out.verified), 1)
        self.assertEqual(len(out.rejected), 0)

    def test_no_dimension_agent_keeps_deduped_empty(self):
        out = fanout_and_synthesize(
            dimensions=["A01", "A02"],
            evidence=self._ev(),
            synthesize_prompt="",
        )
        self.assertEqual(out.dimensions, ["A01", "A02"])
        self.assertEqual(out.findings, [])

    def test_default_synthesis_is_json(self):
        def dim_agent(dim, evidence):
            return [Finding(file="a.py", line=1, theme="x", severity="HIGH")]
        out = fanout_and_synthesize(
            dimensions=["A01"],
            evidence=self._ev(),
            synthesize_prompt="",
            dimension_agent=dim_agent,
        )
        payload = json.loads(out.synthesis)
        self.assertEqual(payload["dimensions"], ["A01"])
        self.assertEqual(payload["verified_count"], 1)

    def test_custom_synthesize_called(self):
        def dim_agent(dim, evidence):
            return [Finding(file="a.py", line=1, theme="x")]
        def synth(verified, rejected):
            return f"verified={len(verified)} rejected={len(rejected)}"
        out = fanout_and_synthesize(
            dimensions=["A01"],
            evidence=self._ev(),
            synthesize_prompt="ignored",
            dimension_agent=dim_agent,
            synthesize=synth,
        )
        self.assertEqual(out.synthesis, "verified=1 rejected=0")


class TestSynthesisResultShape(unittest.TestCase):
    def test_fields(self):
        out = fanout_and_synthesize(
            dimensions=["A01"],
            evidence=[Path("x.py")],
            synthesize_prompt="",
        )
        self.assertIsInstance(out, SynthesisResult)
        self.assertEqual(out.dimensions, ["A01"])
        self.assertIsInstance(out.findings, list)
        self.assertIsInstance(out.verified, list)
        self.assertIsInstance(out.rejected, list)
        self.assertIsInstance(out.synthesis, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
