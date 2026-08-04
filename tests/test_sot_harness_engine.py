"""Tests for lib/sot_harness_engine.py — pure synthesizer tests."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

from sot_harness_engine import (
    ROUNDS,
    RoundDecision,
    SOTDecisionSet,
    _rec_for,
    synthesize_sot,
    write_sot_handout,
)


def _full_decision_set() -> SOTDecisionSet:
    """Build a complete decision set: accept the first recommendation of every round."""
    ds = SOTDecisionSet(
        project_name="test-project",
        idea_one_liner="Test idea for SOT.",
        session_id="test-session",
    )
    for round_obj in ROUNDS:
        rec = round_obj.recommendations[0]
        ds.decisions[round_obj.key] = RoundDecision(
            round_key=round_obj.key,
            recommendation_id=rec.id,
            decision="accept",
        )
    ds.open_questions = ["what about X?"]
    return ds


class TestRounds(unittest.TestCase):
    def test_five_rounds(self):
        self.assertEqual(len(ROUNDS), 5)

    def test_keys(self):
        keys = {r.key for r in ROUNDS}
        self.assertEqual(
            keys,
            {"project_context", "verification", "context", "safety", "lifecycle"},
        )

    def test_each_round_has_at_least_two_recommendations(self):
        for r in ROUNDS:
            self.assertGreaterEqual(
                len(r.recommendations), 2, f"round {r.key} has < 2 recs"
            )

    def test_every_recommendation_has_source(self):
        for r in ROUNDS:
            for rec in r.recommendations:
                self.assertTrue(
                    rec.source_url.startswith("https://"),
                    f"{r.key}/{rec.id} missing source URL",
                )
                self.assertTrue(rec.thesis, f"{r.key}/{rec.id} missing thesis")


class TestRecLookup(unittest.TestCase):
    def test_lookup_round_rec(self):
        rec = _rec_for("project_context", "long_running")
        self.assertIsNotNone(rec)
        self.assertIn("initializer", rec.thesis.lower())

    def test_lookup_missing(self):
        self.assertIsNone(_rec_for("project_context", "nonsense"))


class TestValidate(unittest.TestCase):
    def test_complete_set_validates(self):
        ds = _full_decision_set()
        self.assertEqual(ds.validate(), [])

    def test_incomplete_set_fails(self):
        ds = SOTDecisionSet(project_name="x", idea_one_liner="y")
        ds.decisions["project_context"] = RoundDecision(
            round_key="project_context",
            recommendation_id="long_running",
            decision="accept",
        )
        errs = ds.validate()
        self.assertTrue(any("missing decisions" in e for e in errs))

    def test_customize_requires_text(self):
        ds = _full_decision_set()
        ds.decisions["lifecycle"] = RoundDecision(
            round_key="lifecycle",
            recommendation_id="ralph_loop",
            decision="customize",
            customize_text="",  # missing
        )
        errs = ds.validate()
        self.assertTrue(any("customize" in e for e in errs))


class TestSynthesize(unittest.TestCase):
    def test_synthesize_contains_all_dimensions(self):
        ds = _full_decision_set()
        out = synthesize_sot(ds)
        for round_obj in ROUNDS:
            self.assertIn(
                round_obj.key.replace("_", " ").title(), out,
                f"sot doc missing dimension: {round_obj.key}",
            )

    def test_synthesize_contains_sources(self):
        ds = _full_decision_set()
        out = synthesize_sot(ds)
        # Every accepted recommendation's source URL should appear
        for round_obj in ROUNDS:
            rec = round_obj.recommendations[0]
            self.assertIn(rec.source_url, out)

    def test_synthesize_contains_implementation_phases(self):
        ds = _full_decision_set()
        out = synthesize_sot(ds)
        self.assertIn("Phase 1: Lifecycle", out)
        self.assertIn("Phase 2: Verification", out)
        self.assertIn("Phase 3: Context", out)
        self.assertIn("Phase 4: Safety", out)

    def test_synthesize_contains_acceptance_criteria(self):
        ds = _full_decision_set()
        out = synthesize_sot(ds)
        self.assertIn("Acceptance Criteria", out)
        self.assertIn("A1", out)
        self.assertIn("A5", out)

    def test_synthesize_includes_rejected_with_reason(self):
        ds = _full_decision_set()
        # Reject a recommendation with a reason
        ds.decisions["context"] = RoundDecision(
            round_key="context",
            recommendation_id="subagent_firewall",
            decision="reject",
            note="too much complexity for our team",
        )
        out = synthesize_sot(ds)
        self.assertIn("Rejected Patterns", out)
        self.assertIn("too much complexity", out)

    def test_synthesize_incomplete_returns_held(self):
        ds = SOTDecisionSet(project_name="x", idea_one_liner="y")
        out = synthesize_sot(ds)
        self.assertIn("INCOMPLETE", out)
        self.assertIn("held", out)


class TestWrite(unittest.TestCase):
    def test_write_sot_handout_creates_file(self):
        import tempfile
        ds = _full_decision_set()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = write_sot_handout(ds, root)
            self.assertTrue(target.exists())
            self.assertIn("SOT Harness Document", target.read_text())


if __name__ == "__main__":
    unittest.main()
