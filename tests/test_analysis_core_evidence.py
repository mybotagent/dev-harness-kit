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

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.analysis_core import (  # noqa: E402
    emit_suggested_diffs,
    run_analysis,
)
from lib.analysis_core.evidence import (  # noqa: E402
    SEVERITY_ORDER,
    Severity,
    Verdict,
    from_dict,
    parse_candidate,
    to_dict,
)
from lib.analysis_core.fp_filter import (  # noqa: E402
    Verifier,
    apply_verifier,
    dedupe,
    deterministic_filter,
    threshold_by_mode,
)


def _build_synth_repo() -> Path:
    """Tiny 3-file repo for runner-driven tests."""
    import tempfile
    tmp = tempfile.mkdtemp(prefix="ac-evi-")
    root = Path(tmp)
    (root / "a.py").write_text("x = 0\n", encoding="utf-8")
    (root / "b.py").write_text("y = 1\n", encoding="utf-8")
    (root / "c.py").write_text("z = 2\n", encoding="utf-8")
    return root


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


class TestDeletionProofStrictBooleans(unittest.TestCase):
    """`deletion_proof` is the safety gate for whole-file deletion. The
    parser must reject non-boolean values so a malformed proof can never
    silently enable a `git rm`. Required keys are `no_importers`,
    `no_callers`, `no_references`, `no_runtime_calls`; missing keys or
    non-bool values are dropped from the stored proof.
    """

    def test_proof_non_bool_value_dropped(self):
        # "yes" is truthy in Python but not a real bool; the parser must
        # drop it so the engine's proof check fails closed.
        e = parse_candidate(_cand(
            deletion_scope="whole-file",
            deletion_proof={"no_importers": True, "no_callers": "yes"},
        ))
        self.assertIsNotNone(e.deletion_proof)
        self.assertIn("no_importers", e.deletion_proof)
        self.assertNotIn("no_callers", e.deletion_proof)
        self.assertIs(e.deletion_proof["no_importers"], True)

    def test_proof_dict_coerced_to_bool(self):
        # Coerce other truthy values (1, "true") to True, falsy (0, "") to False.
        e = parse_candidate(_cand(
            deletion_scope="whole-file",
            deletion_proof={"no_importers": 1, "no_callers": 0},
        ))
        self.assertEqual(e.deletion_proof["no_importers"], True)
        self.assertEqual(e.deletion_proof["no_callers"], False)

    def test_proof_keys_normalized_to_str(self):
        e = parse_candidate(_cand(
            deletion_scope="whole-file",
            deletion_proof={"no_importers": True, "no_callers": True,
                            "no_references": True, "no_runtime_calls": True},
        ))
        # All four safety keys present and bool.
        for k in ("no_importers", "no_callers", "no_references", "no_runtime_calls"):
            self.assertIn(k, e.deletion_proof)
            self.assertIsInstance(e.deletion_proof[k], bool)


class TestDeleteModeRejectsPartialProof(unittest.TestCase):
    """The whole-file deletion gate requires ALL FOUR safety booleans:
    `no_importers AND no_callers AND no_references AND no_runtime_calls`.
    A missing key means the proof is incomplete and the engine must
    emit a `# delete-blocked:` diff instead of `git rm`.
    """

    def test_missing_no_references_blocks_git_rm(self):
        repo = _build_synth_repo()
        result = run_analysis(["dead"], "delete", [repo], candidates={"dead": [{
            "file": str(repo / "a.py"), "line": 0, "severity": "major",
            "confidence": "high", "title": "x", "tldr": "t",
            "failure_scenario": "orphan module",
            "deletion_scope": "whole-file",
            "deletion_root_cause": "orphan module",
            "deletion_proof": {
                "no_importers": True, "no_callers": True,
                # no_references: MISSING -> whole-file proof incomplete
                "no_runtime_calls": True,
            },
        }]})
        diffs = emit_suggested_diffs(result)
        self.assertEqual(len(diffs), 1)
        self.assertNotIn("git rm", diffs[0].command)
        self.assertIn("delete-blocked", diffs[0].command)

    def test_full_four_key_proof_emits_git_rm(self):
        repo = _build_synth_repo()
        result = run_analysis(["dead"], "delete", [repo], candidates={"dead": [{
            "file": str(repo / "a.py"), "line": 0, "severity": "major",
            "confidence": "high", "title": "x", "tldr": "t",
            "failure_scenario": "orphan module",
            "deletion_scope": "whole-file",
            "deletion_root_cause": "orphan module",
            "deletion_proof": {
                "no_importers": True, "no_callers": True,
                "no_references": True, "no_runtime_calls": True,
            },
        }]})
        diffs = emit_suggested_diffs(result)
        self.assertEqual(len(diffs), 1)
        self.assertIn("git rm", diffs[0].command)


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


class TestDimFallback(unittest.TestCase):
    """When expert JSON contracts omit `dim`, the outer loop's dim name
    must be inherited so findings render with correct attribution and
    do not collide during dedupe.
    """

    def test_missing_dim_inherits_fallback(self):
        bad = _cand()
        bad.pop("dim", None)
        e = parse_candidate(bad, dim_fallback="dead")
        self.assertEqual(e.dim, "dead")

    def test_present_dim_overrides_fallback(self):
        # Caller-provided dim wins over fallback so per-item dim is honored.
        e = parse_candidate(_cand(dim="smell"), dim_fallback="dead")
        self.assertEqual(e.dim, "smell")

    def test_empty_dim_falls_back(self):
        bad = _cand()
        bad["dim"] = ""
        e = parse_candidate(bad, dim_fallback="dead")
        self.assertEqual(e.dim, "dead")


class TestCrossDimDedupePreservesStronger(unittest.TestCase):
    """Cross-dim dedupe MUST keep the stronger finding regardless of
    arrival order — never silently drop a CRITICAL behind a MINOR.
    """

    def test_minor_then_critical_keeps_critical(self):
        items = [
            parse_candidate(_cand(line=1, dim="smell", severity="minor")),
            parse_candidate(_cand(line=1, dim="dead", severity="critical")),
        ]
        out = dedupe(items)
        sevs = [e.severity for e in out]
        self.assertIn(Severity.CRITICAL, sevs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].dim, "dead")

    def test_critical_then_minor_keeps_critical(self):
        items = [
            parse_candidate(_cand(line=2, dim="dead", severity="critical")),
            parse_candidate(_cand(line=2, dim="smell", severity="minor")),
        ]
        out = dedupe(items)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].severity, Severity.CRITICAL)

    def test_same_severity_keeps_first(self):
        # Deterministic tie-break: arrival order wins.
        items = [
            parse_candidate(_cand(line=3, dim="smell", severity="major")),
            parse_candidate(_cand(line=3, dim="dead", severity="major")),
        ]
        out = dedupe(items)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].dim, "smell")



class TestVerdictIdentityStable(unittest.TestCase):
    """Verifier.new_id is the SSOT for verdict identity — the same
    (verifier, evidence_id, voter) triple always hashes to the same ID.
    Different triples give different IDs. This lets downstream logs
    dedupe by ID instead of by positional list index (which is fragile
    under reorderings and filter changes).
    """

    def test_verdict_ids_are_stable(self):
        a1 = Verifier.new_id("llm-judge", "ev-1", "voter-A")
        a2 = Verifier.new_id("llm-judge", "ev-1", "voter-A")
        self.assertEqual(a1, a2, "same input triple must hash to same ID")
        # Different verifier → different ID.
        b = Verifier.new_id("static-rules", "ev-1", "voter-A")
        self.assertNotEqual(a1, b, "different verifier must give different ID")
        # Different evidence → different ID.
        c = Verifier.new_id("llm-judge", "ev-2", "voter-A")
        self.assertNotEqual(a1, c, "different evidence must give different ID")
        # Different voter → different ID.
        d = Verifier.new_id("llm-judge", "ev-1", "voter-B")
        self.assertNotEqual(a1, d, "different voter must give different ID")
        # Format: 16-char hex.
        self.assertEqual(len(a1), 16)
        self.assertTrue(all(ch in "0123456789abcdef" for ch in a1))



class TestFixVsFixHintSchemaSeparation(unittest.TestCase):
    """The schema boundary MUST keep `fix` (verbatim code/patch) and
    `fix_hint` (human-readable suggestion) independent. Setting one
    never pollutes the other; `fix_hint` never enters the diff stream.
    """

    def test_fix_vs_fix_hint_separation(self):
        # Both fields exist independently.
        e = parse_candidate(_cand(
            fix="def foo():\n    return 42\n",  # verbatim patch
            fix_hint="add a foo() helper that returns 42",  # prose hint
        ))
        self.assertEqual(e.fix, "def foo():\n    return 42\n")
        self.assertEqual(
            e.fix_hint,
            "add a foo() helper that returns 42",
            "fix_hint must hold human-readable prose, separate from fix",
        )
        # Either can be set without the other.
        e_only_fix = parse_candidate(_cand(fix="x = 1"))
        self.assertEqual(e_only_fix.fix, "x = 1")
        self.assertIsNone(e_only_fix.fix_hint)
        e_only_hint = parse_candidate(_cand(fix_hint="explain"))
        self.assertIsNone(e_only_hint.fix)
        self.assertEqual(e_only_hint.fix_hint, "explain")

    def test_diff_stream_does_not_pollute_with_fix_hint(self):
        # When the evidence carries BOTH `fix` and a non-empty
        # `fix_hint`, the rewrite-mode diff must contain `fix` only —
        # never the human-readable `fix_hint` prose.
        import tempfile

        from lib.analysis_core import (
            emit_suggested_diffs,
            run_analysis,
        )
        tmp = tempfile.mkdtemp(prefix="ac-fix-hint-")
        root = Path(tmp)
        (root / "m.py").write_text("x = 0\n", encoding="utf-8")
        candidates = {
            "smell": [
                {
                    "file": str(root / "m.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "long method",
                    "tldr": "too big",
                    "failure_scenario": "unmaintainable",
                    "fix": "def helper():\n    pass\n",
                    "fix_hint": "consider extracting the body into helper() for readability",
                },
            ],
        }
        result = run_analysis(
            dimensions=["smell"],
            mode="rewrite",
            paths=[root],
            candidates=candidates,
        )
        diffs = emit_suggested_diffs(result)
        self.assertEqual(len(diffs), 1)
        # Diff contains the verbatim fix code …
        self.assertIn("def helper()", diffs[0].command)
        # … but NOT the fix_hint prose.
        self.assertNotIn(
            "consider extracting", diffs[0].command,
            "fix_hint prose must never enter the diff stream",
        )
        self.assertNotIn(
            "readability", diffs[0].command,
            "fix_hint prose must never enter the diff stream",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
