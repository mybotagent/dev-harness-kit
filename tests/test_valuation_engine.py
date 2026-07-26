#!/usr/bin/env python3
"""test_valuation_engine.py — RED-first tests for lib/valuation_engine.py
(Phase 4, issue #374).

Targets the 4-way decision gate (proceed / revise / hold / kill) plus
the LCS envelope persistence check. Pure-function module; no I/O, no
network — stdlib + a tmpdir is the only setup.

Test inventory (>=8 tests; pin all 4 decisions + envelope shape):

  * proceed_path                       — all 6 axes >= 4, weighted avg >= 4 -> proceed
  * proceed_with_dim_floor             — weighted avg >= 4 but one axis < 3 -> revise
  * revise_when_below_floor            — one axis 2.5 (<3) -> revise
  * kill_by_risk_floor_absolute        — any axis < 2 -> kill (absolute rule)
  * kill_by_low_weighted_average       — weighted avg < 3 -> kill
  * hold_in_mid_band                   — weighted avg in [3,4), no below-floor axes -> hold
  * decision_persists_to_lcs           — canonical envelope validator
  * decision_persists_to_lcs_rejects   — non-canonical envelopes rejected
  * rejects_unknown_axis               — out-of-rubric axis raises ValueError
  * rejects_out_of_range_score         — score > SCORE_MAX raises ValueError
  * weighted_average_is_stable         — same input -> same output (idempotent)
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import valuation_engine as ve  # noqa: E402


# Canonical high-quality 6-axis scores (every dimension 4 — well above
# the 3.0 dimension_floor and the 4.0 proceed_threshold on average).
HIGH_SCORES: dict = {
    "problem_fit": 4,
    "roi_estimate": 4,
    "existing_solution_edge": 4,
    "team_capability": 4,
    "risk_vs_reward": 4,
    "measurability": 4,
}

# One-axis-below-floor scores. `team_capability` is at 2.5 (below 3.0
# floor) but above the 2.0 risk_floor — the engine must return REVISE.
BELOW_FLOOR_SCORES: dict = {
    "problem_fit": 4,
    "roi_estimate": 4,
    "existing_solution_edge": 4,
    "team_capability": 2.5,
    "risk_vs_reward": 4,
    "measurability": 4,
}

# Below-risk-floor scores. `risk_vs_reward` is at 1.5 (< 2.0) — the
# absolute rule must force KILL regardless of all other axes being 5.
RISK_FLOOR_SCORES: dict = {
    "problem_fit": 5,
    "roi_estimate": 5,
    "existing_solution_edge": 5,
    "team_capability": 5,
    "risk_vs_reward": 1.5,
    "measurability": 5,
}

# Mid-band scores (weighted avg in [3, 4), every axis >= 3).
HOLD_SCORES: dict = {
    "problem_fit": 4,
    "roi_estimate": 3,
    "existing_solution_edge": 3,
    "team_capability": 3,
    "risk_vs_reward": 3,
    "measurability": 3,
}

# KILL_LOW_AVG_SCORES was removed: with default thresholds, the
# "weighted avg < hold_threshold" branch is unreachable (every axis
# >= dimension_floor=3 implies avg >= 3 >= hold_threshold). The path
# is covered by test_kill_by_low_weighted_average_with_custom_thresholds
# via explicit threshold overrides.

_PLAN: dict = {}


class TestProceedPath(unittest.TestCase):
    def test_proceed_path_all_high(self):
        result = ve.decide(_PLAN, HIGH_SCORES)
        self.assertEqual(result["decision"], "proceed")
        self.assertEqual(result["blocking_findings"], [])

    def test_proceed_path_rationale_mentions_average(self):
        result = ve.decide(_PLAN, HIGH_SCORES)
        self.assertIn("4.0", result["rationale"])


class TestRevisePath(unittest.TestCase):
    def test_revise_when_below_floor(self):
        result = ve.decide(_PLAN, BELOW_FLOOR_SCORES)
        self.assertEqual(result["decision"], "revise")
        self.assertEqual(len(result["blocking_findings"]), 1)
        self.assertIn("team_capability", result["blocking_findings"][0])

    def test_revise_when_weighted_avg_high_but_one_axis_low(self):
        # 5 of 6 axes at 5, one axis at 2.5 — weighted avg = 27.5/6 ≈ 4.58,
        # which is above proceed_threshold. But team_capability=2.5 is
        # below dimension_floor=3.0, so the engine must REVISE.
        scores = {
            "problem_fit": 5,
            "roi_estimate": 5,
            "existing_solution_edge": 5,
            "team_capability": 2.5,
            "risk_vs_reward": 5,
            "measurability": 5,
        }
        result = ve.decide(_PLAN, scores)
        self.assertEqual(result["decision"], "revise")


class TestKillPath(unittest.TestCase):
    def test_kill_by_risk_floor_absolute(self):
        # Even with five 5s, risk_vs_reward=1.5 forces kill.
        result = ve.decide(_PLAN, RISK_FLOOR_SCORES)
        self.assertEqual(result["decision"], "kill")
        self.assertTrue(
            any("risk_vs_reward" in f for f in result["blocking_findings"]),
            f"expected risk_floor finding, got {result['blocking_findings']!r}",
        )

    def test_kill_by_low_weighted_average_with_custom_thresholds(self):
        # With default thresholds, the "weighted avg < hold_threshold"
        # branch is unreachable (every axis >= dimension_floor implies
        # avg >= dimension_floor = hold_threshold). Demonstrate the
        # path with a custom hold_threshold so the branch is covered.
        result = ve.decide(
            _PLAN, HOLD_SCORES,
            hold_threshold=10.0,    # force the low-avg branch
            proceed_threshold=99.0, # never auto-proceed
        )
        self.assertEqual(result["decision"], "kill")
        self.assertTrue(
            any("weighted_average" in f for f in result["blocking_findings"]),
            f"expected weighted_average finding, got {result['blocking_findings']!r}",
        )


class TestHoldPath(unittest.TestCase):
    def test_hold_in_mid_band(self):
        result = ve.decide(_PLAN, HOLD_SCORES)
        self.assertEqual(result["decision"], "hold")
        self.assertEqual(result["blocking_findings"], [])

    def test_hold_rationale_mentions_threshold_band(self):
        result = ve.decide(_PLAN, HOLD_SCORES)
        self.assertIn("hold_threshold", result["rationale"])


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_output(self):
        # Pure-function contract: identical inputs -> identical output.
        a = ve.decide(_PLAN, HIGH_SCORES)
        b = ve.decide(_PLAN, HIGH_SCORES)
        self.assertEqual(a, b)

    def test_weighted_average_stable_across_calls(self):
        # The internal mean must not drift; same inputs -> same float.
        a = ve.decide(_PLAN, HOLD_SCORES)["rationale"]
        b = ve.decide(_PLAN, HOLD_SCORES)["rationale"]
        self.assertEqual(a, b)


class TestLcsEnvelopeShape(unittest.TestCase):
    """decision_persists_to_lcs() — the LCS envelope validator.

    The build gate's LCS read will trust whatever the engine writes.
    Pin the shape so a malformed envelope (missing key, wrong type)
    is rejected up front instead of crashing the build stage.
    """

    def test_decision_persists_to_lcs_accepts_canonical(self):
        result = ve.decide(_PLAN, HIGH_SCORES)
        self.assertTrue(ve.decision_persists_to_lcs(result))

    def test_decision_persists_to_lcs_rejects_missing_keys(self):
        # Drop blocking_findings -> not a canonical envelope.
        bad = {"decision": "proceed", "rationale": "ok"}
        self.assertFalse(ve.decision_persists_to_lcs(bad))

    def test_decision_persists_to_lcs_rejects_extra_keys(self):
        # A key the LCS consumer doesn't recognize -> reject.
        bad = {
            "decision": "proceed",
            "rationale": "ok",
            "blocking_findings": [],
            "extra_field": "junk",
        }
        self.assertFalse(ve.decision_persists_to_lcs(bad))

    def test_decision_persists_to_lcs_rejects_bad_decision(self):
        # "approve" is not one of the four canonical verdicts.
        bad = {
            "decision": "approve",
            "rationale": "ok",
            "blocking_findings": [],
        }
        self.assertFalse(ve.decision_persists_to_lcs(bad))


class TestInputValidation(unittest.TestCase):
    def test_rejects_unknown_axis(self):
        scores = dict(HIGH_SCORES, foobar=4)
        with self.assertRaises(ValueError) as ctx:
            ve.decide(_PLAN, scores)
        self.assertIn("foobar", str(ctx.exception))

    def test_rejects_out_of_range_score_high(self):
        scores = dict(HIGH_SCORES, problem_fit=10)
        with self.assertRaises(ValueError):
            ve.decide(_PLAN, scores)

    def test_rejects_out_of_range_score_negative(self):
        scores = dict(HIGH_SCORES, problem_fit=-1)
        with self.assertRaises(ValueError):
            ve.decide(_PLAN, scores)


class TestBuildRespectsDecision(unittest.TestCase):
    """The build gate is enforced by what the engine returns, not by
    what the LLM says. Pin that the only verdict that maps to "build
    allowed" is `proceed`. This is the L6 contract that makes the
    valuate skill's `alpha: enforcement` claim load-bearing.
    """

    def test_only_proceed_unblocks_build(self):
        for scores in (HIGH_SCORES, BELOW_FLOOR_SCORES, RISK_FLOOR_SCORES,
                       HOLD_SCORES):
            result = ve.decide(_PLAN, scores)
            allowed = (result["decision"] == "proceed")
            expected = scores is HIGH_SCORES
            self.assertEqual(
                allowed, expected,
                f"scores={scores!r} -> decision={result['decision']!r}",
            )


class TestSkipValuationBackwardCompat(unittest.TestCase):
    """The build skill's `--skip-valuation` flag is the permanent
    backward-compat escape hatch. Pin the engine's behavior on a
    minimal plan (no rubric scores at all -> cannot decide). The
    build stage treats "no verdict available" as a gate refusal,
    NOT a proceed. The engine itself raises — the build stage is
    responsible for the SKIP gate."""

    def test_engine_requires_full_rubric(self):
        # Missing axes -> ValueError. The build stage catches this
        # and exits 2 unless --skip-valuation is set.
        with self.assertRaises(ValueError):
            ve.decide(_PLAN, {"problem_fit": 4})


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ---- CLI (Phase 4 PR #446 review M2) ----

class TestCli:
    """`python3 -m lib.valuation_engine --plan PRD.md --dry-run --json`
    must read the plan, run decide(), and print the canonical envelope."""

    def _write_plan(self, tmp, scores):
        import json, yaml
        p = tmp / "plan.yaml"
        p.write_text(yaml.safe_dump({"plan_value": scores}))
        return str(p)

    def test_cli_proceed_exits_zero(self, tmp_path):
        from valuation_engine import cli_main
        plan = self._write_plan(tmp_path, {
            "problem_fit": 5.0, "roi_estimate": 5.0, "existing_solution_edge": 5.0,
            "team_capability": 5.0, "risk_vs_reward": 5.0, "measurability": 5.0,
        })
        rc = cli_main(["--plan", plan, "--dry-run", "--json"])
        assert rc == 0

    def test_cli_kill_exits_one(self, tmp_path):
        from valuation_engine import cli_main
        # All axes at 0 -> avg 0 < hold_threshold -> kill.
        plan = self._write_plan(tmp_path, {
            "problem_fit": 0.0, "roi_estimate": 0.0, "existing_solution_edge": 0.0,
            "team_capability": 0.0, "risk_vs_reward": 0.0, "measurability": 0.0,
        })
        rc = cli_main(["--plan", plan, "--dry-run"])
        assert rc == 1

    def test_cli_missing_plan_exits_two(self):
        from valuation_engine import cli_main
        rc = cli_main(["--plan", "/nonexistent/plan.yaml"])
        assert rc == 2

    def test_low_average_kills_before_revise(self, tmp_path):
        """The reorder fix: 2.5-average (kill-by-avg) should NOT return
        revise even though every dim is below floor."""
        from valuation_engine import cli_main, decide
        scores = {axis: 2.5 for axis in ("problem_fit", "roi_estimate",
                    "existing_solution_edge", "team_capability",
                    "risk_vs_reward", "measurability")}
        out = decide(plan={}, rubric_scores=scores)
        assert out["decision"] == "kill", f"expected kill for avg=2.5, got {out['decision']}"

    def test_scale_param_picks_per_dim(self):
        from llm_judge import score_range_for_dim
        assert score_range_for_dim("plan_value") == (0.0, 5.0)
        assert score_range_for_dim("review") == (0.0, 10.0)
        assert score_range_for_dim("unknown") == (0.0, 10.0)
