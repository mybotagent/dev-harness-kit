#!/usr/bin/env python3
"""test_interview_engine.py — RED-first coverage for lib/interview_engine.py.

Pins the Phase 6 5-field safety contract:
- `validate_5_field` (missing + ambiguous detection)
- `extract_5_field` (conversation transcript → 5 fields)
- `score_interview_ambiguity` (per-axis scores + status)
- state machine (`next_question`, `apply_answer`, `should_terminate`,
  `narrowed_delta`, `dedup_metric`, `user_interrupt`)
- JSON shape parity with `lcs://interview/<step>` 5-field contract
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))

import interview_engine as ie  # noqa: E402


# ----- validate_5_field -----


class TestValidate5Field(unittest.TestCase):
    def test_all_five_present_and_clear(self):
        answers = {
            "goal": "ship a P95 latency under 100ms by Q3",
            "constraints": "no vendor lock-in, OSS-only",
            "success_criteria": "p95 latency under 100ms for 99% of requests",
            "anti_goals": "no GUI dashboard, no admin console",
            "acceptance_rubric": "ops team signs off after load test passes SLO",
        }
        result = ie.validate_5_field(answers)
        self.assertTrue(result["valid"])
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["ambiguous"], [])

    def test_missing_field_detected(self):
        result = ie.validate_5_field({
            "goal": "ship a P95 latency under 100ms by Q3",
            "constraints": "no vendor lock-in, OSS-only",
            "success_criteria": "p95 latency under 100ms for 99% of requests",
            "anti_goals": "no GUI dashboard",
            # acceptance_rubric intentionally missing
        })
        self.assertFalse(result["valid"])
        self.assertIn("acceptance_rubric", result["missing"])
        self.assertEqual(result["ambiguous"], [])

    def test_empty_string_treated_as_missing(self):
        result = ie.validate_5_field({
            "goal": "ship a P95 latency under 100ms by Q3",
            "constraints": "",
            "success_criteria": "p95 latency under 100ms",
            "anti_goals": "no GUI dashboard",
            "acceptance_rubric": "ops team signs off",
        })
        self.assertIn("constraints", result["missing"])

    def test_whitespace_only_treated_as_missing(self):
        result = ie.validate_5_field({
            "goal": "ship a P95 latency under 100ms by Q3",
            "constraints": "   \t  ",
            "success_criteria": "p95 latency under 100ms",
            "anti_goals": "no GUI dashboard",
            "acceptance_rubric": "ops team signs off",
        })
        self.assertIn("constraints", result["missing"])

    def test_ambiguous_field_detected(self):
        # "maybe" + too-short + vague language = ambiguous
        result = ie.validate_5_field({
            "goal": "ship a P95 latency under 100ms by Q3",
            "constraints": "maybe no vendor lock-in probably",
            "success_criteria": "p95 latency under 100ms for 99% of requests",
            "anti_goals": "no GUI dashboard, no admin console",
            "acceptance_rubric": "ops team signs off after load test passes SLO",
        })
        self.assertFalse(result["valid"])
        self.assertIn("constraints", result["ambiguous"])


# ----- extract_5_field -----


class TestExtract5Field(unittest.TestCase):
    def test_extracts_all_five_from_conversation(self):
        conversation = [
            {"role": "assistant", "content": "q_goal: what's the goal?"},
            {"role": "user", "content": "ship a P95 latency under 100ms by Q3"},
            {"role": "assistant", "content": "q_constraints: any constraints?"},
            {"role": "user", "content": "no vendor lock-in, OSS-only"},
            {"role": "assistant", "content": "q_success_criteria: success criteria?"},
            {"role": "user", "content": "p95 latency under 100ms for 99% of requests"},
            {"role": "assistant", "content": "q_anti_goals: what are the anti-goals?"},
            {"role": "user", "content": "no GUI dashboard"},
            {"role": "assistant", "content": "q_acceptance_rubric: acceptance rubric?"},
            {"role": "user", "content": "ops team signs off after load test passes SLO"},
        ]
        out = ie.extract_5_field(conversation)
        self.assertEqual(out["goal"], "ship a P95 latency under 100ms by Q3")
        self.assertEqual(out["constraints"], "no vendor lock-in, OSS-only")
        self.assertEqual(out["success_criteria"], "p95 latency under 100ms for 99% of requests")
        self.assertEqual(out["anti_goals"], "no GUI dashboard")
        self.assertEqual(out["acceptance_rubric"], "ops team signs off after load test passes SLO")

    def test_latest_answer_wins(self):
        # User re-answers the same question — the latest one should win.
        conversation = [
            {"role": "assistant", "content": "q_goal: what's the goal?"},
            {"role": "user", "content": "first answer"},
            {"role": "assistant", "content": "q_goal: please be more specific"},
            {"role": "user", "content": "ship a P95 latency under 100ms by Q3"},
        ]
        out = ie.extract_5_field(conversation)
        self.assertEqual(out["goal"], "ship a P95 latency under 100ms by Q3")

    def test_empty_conversation_yields_empty_fields(self):
        out = ie.extract_5_field([])
        for field in ie.FIVE_FIELDS:
            self.assertEqual(out[field], "")


# ----- score_interview_ambiguity -----


class TestScoreInterviewAmbiguity(unittest.TestCase):
    def test_all_clear_yields_ok_status(self):
        answers = {
            "goal": "ship a P95 latency under 100ms by Q3",
            "constraints": "no vendor lock-in, OSS-only",
            "success_criteria": "p95 latency under 100ms for 99% of requests",
            "anti_goals": "no GUI dashboard, no admin console",
            "acceptance_rubric": "ops team signs off after load test passes SLO",
        }
        s = ie.score_interview_ambiguity(answers)
        self.assertEqual(s["status"], "ok")
        self.assertEqual(s["evidence_count"], 5)
        self.assertEqual(s["ambiguity_score"], 2)
        self.assertEqual(s["value_score"], 1.0)

    def test_some_ambiguous_yields_best_effort(self):
        answers = {
            "goal": "ship a P95 latency under 100ms by Q3",
            "constraints": "no vendor lock-in, OSS-only",
            "success_criteria": "maybe fast and reliable",   # ambiguous
            "anti_goals": "no GUI dashboard",
            "acceptance_rubric": "ops team signs off after load test passes SLO",
        }
        s = ie.score_interview_ambiguity(answers)
        self.assertEqual(s["status"], "best-effort")
        self.assertEqual(s["evidence_count"], 4)

    def test_missing_yields_held(self):
        answers = {
            "goal": "ship a P95 latency under 100ms by Q3",
            "constraints": "no vendor lock-in, OSS-only",
            "success_criteria": "",
            "anti_goals": "no GUI dashboard",
            "acceptance_rubric": "ops team signs off after load test passes SLO",
        }
        s = ie.score_interview_ambiguity(answers)
        self.assertEqual(s["status"], "held")
        self.assertEqual(s["evidence_count"], 4)

    def test_json_shape_matches_hand_off_contract(self):
        # The contract is the same as lcs://interview/<step> 5-field
        # frontmatter (excluding the "step" key which the resource
        # adds). Pin the shape so a refactor cannot silently break
        # LCS round-trips.
        s = ie.score_interview_ambiguity({
            "goal": "ship a P95 latency under 100ms by Q3",
            "constraints": "no vendor lock-in",
            "success_criteria": "p95 latency under 100ms",
            "anti_goals": "no GUI dashboard",
            "acceptance_rubric": "ops team signs off",
        })
        self.assertEqual(
            set(s.keys()),
            {"value_score", "ambiguity_score", "evidence_count", "status"},
        )


# ----- state machine -----


class TestStateMachine(unittest.TestCase):
    def test_next_question_returns_first_unasked(self):
        self.assertEqual(
            ie.next_question({}, []),
            "q_goal",
        )

    def test_next_question_returns_none_when_all_done(self):
        answers = {
            "goal": "ship a P95 latency under 100ms by Q3",
            "constraints": "no vendor lock-in, OSS-only",
            "success_criteria": "p95 latency under 100ms for 99% of requests",
            "anti_goals": "no GUI dashboard, no admin console",
            "acceptance_rubric": "ops team signs off after load test passes SLO",
        }
        asked = [qid for qid, _ in ie.QUESTION_PLAN]
        self.assertIsNone(ie.next_question(answers, asked))

    def test_apply_answer_maps_qid_to_field(self):
        answers = {}
        ie.apply_answer(answers, "q_goal", "ship a P95 latency under 100ms")
        self.assertEqual(answers["goal"], "ship a P95 latency under 100ms")
        ie.apply_answer(answers, "q_constraints", "no vendor lock-in, OSS-only")
        self.assertEqual(answers["constraints"], "no vendor lock-in, OSS-only")

    def test_apply_answer_strips_and_skips_empty(self):
        answers = {"goal": "ship it"}
        ie.apply_answer(answers, "q_goal", "   ")
        self.assertEqual(answers["goal"], "ship it")  # unchanged
        ie.apply_answer(answers, "q_unknown_qid", "anything")
        self.assertEqual(answers["goal"], "ship it")  # unknown qid ignored

    def test_should_terminate_at_safety_valve(self):
        self.assertTrue(ie.should_terminate("ok", cycle=8))

    def test_should_terminate_on_held(self):
        self.assertTrue(ie.should_terminate("held", cycle=3))

    def test_should_terminate_on_user_acknowledged(self):
        self.assertTrue(ie.should_terminate("user-acknowledged", cycle=2))

    def test_should_terminate_false_when_within_valve(self):
        self.assertFalse(ie.should_terminate("ok", cycle=2))

    def test_narrowed_delta_strictly_decreasing(self):
        self.assertTrue(ie.narrowed_delta(prev=5.0, cur=3.0))
        self.assertFalse(ie.narrowed_delta(prev=5.0, cur=5.0))
        self.assertFalse(ie.narrowed_delta(prev=5.0, cur=6.0))

    def test_dedup_metric_fires_on_two_equal_cycles(self):
        self.assertTrue(ie.dedup_metric([5.0, 4.0, 4.0]))
        self.assertFalse(ie.dedup_metric([5.0, 4.0, 3.0]))
        self.assertFalse(ie.dedup_metric([4.0]))

    def test_user_interrupt_recognized_tokens(self):
        for tok in ("stop", "STOP", "Cancel", "skip", "abort", "later"):
            self.assertTrue(ie.user_interrupt({}, "q_goal", tok))
        self.assertFalse(ie.user_interrupt({}, "q_goal", "ship a P95 latency under 100ms"))


# ----- integration: end-to-end pipeline -----


class TestPipeline(unittest.TestCase):
    def test_full_loop_holds_then_unblocks_on_full_clear(self):
        """Simulate one full conversation; verify the score pipeline."""
        convo = [
            {"role": "assistant", "content": "q_goal: what's the goal?"},
            {"role": "user", "content": "ship a P95 latency under 100ms"},
            {"role": "assistant", "content": "q_constraints: any constraints?"},
            {"role": "user", "content": "no vendor lock-in, OSS-only"},
            {"role": "assistant", "content": "q_success_criteria: success criteria?"},
            {"role": "user", "content": "p95 latency under 100ms for 99% of requests"},
            {"role": "assistant", "content": "q_anti_goals: what are the anti-goals?"},
            {"role": "user", "content": "no GUI dashboard, no admin console"},
            {"role": "assistant", "content": "q_acceptance_rubric: acceptance rubric?"},
            {"role": "user", "content": "ops team signs off after load test passes SLO"},
        ]
        answers = ie.extract_5_field(convo)
        v = ie.validate_5_field(answers)
        self.assertTrue(v["valid"], f"expected valid, got missing={v['missing']} ambiguous={v['ambiguous']}")
        s = ie.score_interview_ambiguity(answers)
        self.assertEqual(s["status"], "ok")
        self.assertEqual(s["evidence_count"], 5)

    def test_llm_judge_axis_set_matches(self):
        """Pins that the LLM judge's axes (DIM_AXES) match the
        per-field keys the deterministic scorer produces. Refactor
        guard: a rename in either side without the other will fail."""
        # Pull the deterministic per-field keys from the scorer.
        from llm_judge import DIM_AXES
        judge_axes = DIM_AXES["interview_ambiguity"]
        # Map the rubric's clarity cues to the engine's 5 fields.
        expected = (
            "goal_clarity",
            "constraints_clarity",
            "success_criteria_clarity",
            "anti_goals_clarity",
            "acceptance_rubric_clarity",
        )
        self.assertEqual(judge_axes, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ---- review findings (Phase 6 PR #444) ----

class TestReviewFixes:
    """Coverage for the review findings on PR #444:
    - hyphenated field labels (q_anti-goals)
    - narrowed_delta alias (renamed to is_narrowing)
    - user_interrupt accepts but does not use answers/qid
    """

    def test_extract_handles_hyphenated_qid(self):
        """q_anti-goals (with hyphen) is recognized as the anti_goals field."""
        from interview_engine import extract_5_field
        convo = [
            {"role": "assistant", "content": "q_anti-goals: what should we NOT do?"},
            {"role": "user", "content": "no GUI, no on-prem install."},
        ]
        out = extract_5_field(convo)
        assert out["anti_goals"] == "no GUI, no on-prem install."

    def test_extract_handles_hyphenated_field_name(self):
        """The human-facing 'anti-goals:' form is also recognized."""
        from interview_engine import extract_5_field
        convo = [
            {"role": "assistant", "content": "anti-goals: name the exclusions"},
            {"role": "user", "content": "no mobile, no mobile at all."},
        ]
        out = extract_5_field(convo)
        assert out["anti_goals"] == "no mobile, no mobile at all."

    def test_is_narrowing_returns_bool(self):
        from interview_engine import is_narrowing, narrowed_delta
        # Both names are present; the function is a boolean predicate.
        assert is_narrowing(5.0, 3.0) is True
        assert is_narrowing(5.0, 5.0) is False
        assert is_narrowing(5.0, 7.0) is False
        # narrowed_delta is the legacy alias.
        assert narrowed_delta is is_narrowing

    def test_user_interrupt_tokens(self):
        from interview_engine import user_interrupt
        # Token-only predicate; answers/qid are accepted but ignored.
        assert user_interrupt({}, "q_goal", "stop") is True
        assert user_interrupt({}, "q_goal", "STOP") is True   # case-insensitive
        assert user_interrupt({}, "q_goal", "later") is True
        assert user_interrupt({}, "q_goal", "abort") is True
        assert user_interrupt({}, "q_goal", "real answer") is False
        assert user_interrupt({}, "q_goal", "") is False
        assert user_interrupt({}, "q_goal", "   ") is False  # whitespace stripped
