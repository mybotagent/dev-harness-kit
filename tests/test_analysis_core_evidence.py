#!/usr/bin/env python3
"""test_analysis_core_evidence.py — Evidence schema + FP filter.

Locks in the typed evidence contract that flows through the engine:

  Evidence — one finding, parsed once, validated once, then routed
  Severity — strict enum (critical > major > minor > nit)
  Verdict  — CONFIRMED / PLAUSIBLE / REJECTED

The schema is the single source of truth for what a per-dim expert
JSON item must look like after parsing.
"""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.analysis_core.evidence import (  # noqa: E402
    Evidence,
    Severity,
    Verdict,
    SEVERITY_ORDER,
    parse_candidate,
    to_dict,
    from_dict,
)
from lib.analysis_core.fp_filter import (  # noqa: E402
    deterministic_filter,
    dedupe,
    apply_verifier,
    threshold_by_mode,
)


def _cand(**over):
    base = {
        "file": "/repo/src/foo.py",
        "line": 10,
        "dim": "correctness",
        "severity": "major",
        "confidence": "high",
        "title": "x is wrong",
        "tldr": "wrong",
        "failure_scenario": "x = 0 returns null",
    }
    base.update(over)
    return base


class TestEvidenceParse(unittest.TestCase):
    def test_parse_minimal_candidate(self):
        e = parse_candidate(_cand())
        self.assertEqual(e.file, "/repo/src/foo.py")
        self.assertEqual(e.line, 10)
        self.assertEqual(e.severity, Severity.MAJOR)
        self.assertEqual(e.confidence, "high")
        self.assertEqual(e.dim, "correctness")

    def test_parse_rejects_unknown_severity(self):
        with self.assertRaises(ValueError):
            parse_candidate(_cand(severity="extreme"))

    def test_parse_optional_fix_hint(self):
        e = parse_candidate(_cand(fix_hint="use guard"))
        self.assertEqual(e.fix_hint, "use guard")
        # absent → None
        e2 = parse_candidate(_cand())
        self.assertIsNone(e2.fix_hint)

    def test_parse_accepts_owasp_dims(self):
        e = parse_candidate(_cand(dim="owasp-a05"))
        self.assertEqual(e.dim, "owasp-a05")

    def test_round_trip_to_from_dict(self):
        e = parse_candidate(_cand(fix_hint="use guard"))
        d = to_dict(e)
        e2 = from_dict(d)
        self.assertEqual(e, e2)


class TestSeverityOrder(unittest.TestCase):
    def test_order_strict(self):
        self.assertEqual(
            SEVERITY_ORDER,
            [Severity.CRITICAL, Severity.MAJOR, Severity.MINOR, Severity.NIT],
        )

    def test_severity_str_round_trip(self):
        for s in SEVERITY_ORDER:
            self.assertEqual(Severity(s.value), s)


class TestDeterministicFilter(unittest.TestCase):
    def test_drops_missing_failure_scenario(self):
        items = [parse_candidate(_cand(failure_scenario=""))]
        self.assertEqual(deterministic_filter(items), [])

    def test_drops_low_confidence_minor(self):
        items = [parse_candidate(_cand(confidence="low", severity="minor"))]
        self.assertEqual(deterministic_filter(items), [])

    def test_keeps_low_confidence_critical(self):
        items = [parse_candidate(_cand(confidence="low", severity="critical"))]
        self.assertEqual(len(deterministic_filter(items)), 1)

    def test_keeps_medium_confidence_minor(self):
        items = [parse_candidate(_cand(confidence="medium", severity="minor"))]
        self.assertEqual(len(deterministic_filter(items)), 1)


class TestDedupe(unittest.TestCase):
    def test_same_file_line_keeps_higher_severity(self):
        items = [
            parse_candidate(_cand(line=10, severity="minor")),
            parse_candidate(_cand(line=10, severity="critical")),
        ]
        out = dedupe(items)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].severity, Severity.CRITICAL)

    def test_different_lines_both_kept(self):
        items = [
            parse_candidate(_cand(line=10)),
            parse_candidate(_cand(line=20)),
        ]
        self.assertEqual(len(dedupe(items)), 2)


class TestApplyVerifier(unittest.TestCase):
    def test_drops_rejected(self):
        items = [
            parse_candidate(_cand(line=10)),
            parse_candidate(_cand(line=20)),
        ]
        verdicts = [
            (0, Verdict.CONFIRMED, "real"),
            (1, Verdict.REJECTED, "spurious"),
        ]
        out = apply_verifier(items, verdicts)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].line, 10)

    def test_keeps_plausible(self):
        items = [parse_candidate(_cand(line=10))]
        verdicts = [(0, Verdict.PLAUSIBLE, "looks real")]
        self.assertEqual(len(apply_verifier(items, verdicts)), 1)

    def test_unknown_id_dropped_silently(self):
        # A verifier verdict for a non-existent finding id is ignored
        # (the engine never crashes on stray IDs).
        items = [parse_candidate(_cand(line=10))]
        verdicts = [(99, Verdict.REJECTED, "n/a")]
        self.assertEqual(len(apply_verifier(items, verdicts)), 1)


class TestThresholdByMode(unittest.TestCase):
    def test_read_only_keeps_all_severities(self):
        items = [
            parse_candidate(_cand(line=1, severity="nit")),
            parse_candidate(_cand(line=2, severity="minor")),
            parse_candidate(_cand(line=3, severity="major")),
            parse_candidate(_cand(line=4, severity="critical")),
        ]
        self.assertEqual(len(threshold_by_mode(items, "read-only")), 4)

    def test_delete_drops_nits(self):
        items = [
            parse_candidate(_cand(line=1, severity="nit")),
            parse_candidate(_cand(line=2, severity="minor")),
            parse_candidate(_cand(line=3, severity="critical")),
        ]
        out = threshold_by_mode(items, "delete")
        self.assertEqual(len(out), 2)
        self.assertNotIn(Severity.NIT, {e.severity for e in out})

    def test_rewrite_drops_nits(self):
        items = [
            parse_candidate(_cand(line=1, severity="nit")),
            parse_candidate(_cand(line=2, severity="major")),
        ]
        out = threshold_by_mode(items, "rewrite")
        self.assertEqual(len(out), 1)


class TestParseCandidateOptionalFields(unittest.TestCase):
    def test_confidence_default_to_medium(self):
        # The engine must never KeyError on missing confidence;
        # missing → "medium" (treated as filterable).
        bad = _cand()
        bad.pop("confidence", None)
        e = parse_candidate(bad)
        self.assertEqual(e.confidence, "medium")

    def test_verifier_enum_accepts_string(self):
        self.assertEqual(Verdict("CONFIRMED"), Verdict.CONFIRMED)
        with self.assertRaises(ValueError):
            Verdict("maybe")


if __name__ == "__main__":
    unittest.main(verbosity=2)
