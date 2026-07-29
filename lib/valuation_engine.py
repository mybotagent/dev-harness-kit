"""valuation_engine.py — Plan-value decision core (Phase 4, issue #369).

Pure-function gate that maps (plan, rubric_scores) -> {decision, rationale,
blocking_findings}. The decision is one of four verdicts that the build
stage reads from `lcs://valuations/<plan-id>` to enforce a no-go gate:

    proceed → build is allowed
    revise  → build refused; the plan must be rewritten (back to plan stage)
    hold    → build refused; re-evaluate later
    kill    → build refused; the idea is archived as no-go

Threshold logic (matches `lib/valuation_rubrics/default.yaml`):

  * If any rubric dimension scores below `risk_floor` -> decision = "kill"
    regardless of all other dimensions. This is the absolute risk-floor
    rule: even a perfect-scoring plan in other dimensions is killed if any
    one dimension (typically "risk_vs_reward") drops below the floor.
  * If the weighted average of all dimensions >= `proceed_threshold` AND
    every dimension >= `dimension_floor` -> decision = "proceed".
  * If the weighted average < `hold_threshold` -> decision = "kill".
  * If the weighted average is between `hold_threshold` and
    `proceed_threshold`, and at least one dimension is below
    `dimension_floor` (but not below `risk_floor`) -> decision = "revise".
  * Otherwise -> decision = "hold".

The function is deterministic on identical inputs: same plan + same rubric
scores always produces the same decision. This is the contract that makes
the build gate enforceable (L6 — `alpha: enforcement`).

Inputs:
    plan: dict (the raw plan payload — body, phases, etc.). Currently
          unused beyond preserving the API; future versions may inspect
          plan fields to flag structural blockers.
    rubric_scores: dict[str, float]  — 6-dimension rubric with keys
          matching `lib/valuation_rubrics/default.yaml` ("problem_fit",
          "roi_estimate", "existing_solution_edge", "team_capability",
          "risk_vs_reward", "measurability"). Each value 0-5.

Returns:
    dict with three keys:
      decision: "proceed" | "revise" | "hold" | "kill"
      rationale: one-line human explanation
      blocking_findings: list[str] of per-dimension notes that drove the
                         decision (e.g. "risk_vs_reward=1.5 < risk_floor=2").
"""
from __future__ import annotations

import sys
from typing import Dict, List, Optional

# Dimension names — the 6 axes from lib/valuation_rubrics/default.yaml.
# Order matches the rubric file; `decide()` does not depend on the order.
DIMENSIONS: tuple[str, ...] = (
    "problem_fit",
    "roi_estimate",
    "existing_solution_edge",
    "team_capability",
    "risk_vs_reward",
    "measurability",
)

# Default thresholds. Mirrors `lib/valuation_rubrics/default.yaml`.
#   proceed_threshold : weighted average >= this value -> "proceed".
#   hold_threshold    : weighted average <  this value -> "kill" (low-priority).
#   dimension_floor   : any single dimension < this value blocks "proceed".
#   risk_floor        : any single dimension < this value forces "kill".
#                       The risk_floor rule is absolute: even a 5.0 on every
#                       other dimension cannot rescue a 1.5 on risk.
DEFAULT_PROCEED_THRESHOLD: float = 4.0
DEFAULT_HOLD_THRESHOLD: float = 3.0
DEFAULT_DIMENSION_FLOOR: float = 3.0
DEFAULT_RISK_FLOOR: float = 2.0

# Score scale. Rubric scores are 1-5 inclusive; 0 means "not scored".
SCORE_MIN: float = 0.0
SCORE_MAX: float = 5.0


def _weighted_average(scores: Dict[str, float]) -> float:
    """Plain mean across the six dimensions. Round to 2dp for stable output."""
    values = [float(v) for v in scores.values()]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def _validate(scores: Dict[str, float]) -> None:
    """Reject out-of-range scores, unknown axes, and missing axes.

    The build gate relies on this failing loudly — a malformed payload is
    a programming error, not a user choice. We do not silently default
    missing dimensions to 0 because that would make a partial payload
    indistinguishable from a low-scoring payload (and a partial payload
    that happens to average >= proceed_threshold would slip a `proceed`
    through without the missing-axis check).
    """
    unknown = set(scores) - set(DIMENSIONS)
    if unknown:
        raise ValueError(f"unknown rubric dimensions: {sorted(unknown)}")
    missing = set(DIMENSIONS) - set(scores)
    if missing:
        raise ValueError(f"missing rubric dimensions: {sorted(missing)}")
    for axis, value in scores.items():
        if value < SCORE_MIN or value > SCORE_MAX:
            raise ValueError(
                f"rubric score out of range: {axis}={value} "
                f"(must be {SCORE_MIN}..{SCORE_MAX})"
            )


def decide(
    plan: dict,
    rubric_scores: Dict[str, float],
    *,
    proceed_threshold: float = DEFAULT_PROCEED_THRESHOLD,
    hold_threshold: float = DEFAULT_HOLD_THRESHOLD,
    dimension_floor: float = DEFAULT_DIMENSION_FLOOR,
    risk_floor: float = DEFAULT_RISK_FLOOR,
) -> Dict[str, object]:
    """Return {"decision", "rationale", "blocking_findings"}.

    Pure function. Same input always yields same output. The decision is
    one of "proceed" | "revise" | "hold" | "kill". See module docstring
    for the threshold logic and the absolute risk-floor rule.
    """
    _validate(rubric_scores)
    avg = _weighted_average(rubric_scores)
    findings: List[str] = []

    # 1. Absolute risk-floor rule. Any dimension below risk_floor -> kill.
    for axis, value in rubric_scores.items():
        if value < risk_floor:
            findings.append(
                f"{axis}={value} < risk_floor={risk_floor} "
                f"(absolute risk-floor rule)"
            )

    if findings:
        return {
            "decision": "kill",
            "rationale": (
                f"killed by risk-floor rule: "
                f"{'; '.join(findings)}"
            ),
            "blocking_findings": findings,
        }

    # 2. proceed path: weighted average >= proceed_threshold AND every
    #    dimension >= dimension_floor.
    below_floor = [
        (axis, value) for axis, value in rubric_scores.items()
        if value < dimension_floor
    ]
    if avg >= proceed_threshold and not below_floor:
        return {
            "decision": "proceed",
            "rationale": (
                f"all dimensions >= {dimension_floor}, "
                f"weighted average {avg} >= {proceed_threshold}"
            ),
            "blocking_findings": [],
        }

    # 3. low-average kill: documented contract says "weighted average
    #    below hold_threshold -> kill" (low overall priority). Check
    #    this BEFORE the below-floor revise path so an average below
    #    the kill floor always short-circuits to kill, not revise.
    if avg < hold_threshold:
        return {
            "decision": "kill",
            "rationale": (
                f"weighted average {avg} < hold_threshold={hold_threshold} "
                f"(low overall priority)"
            ),
            "blocking_findings": [
                f"weighted_average={avg} < hold_threshold={hold_threshold}"
            ],
        }

    # 4. revise path: at least one dimension is below dimension_floor
    #    (but not below risk_floor — already handled above). avg is
    #    >= hold_threshold here, so this is a "moderate but fixable"
    #    signal, not a kill.
    if below_floor:
        findings = [
            f"{axis}={value} < dimension_floor={dimension_floor}"
            for axis, value in below_floor
        ]
        return {
            "decision": "revise",
            "rationale": (
                f"weighted average {avg} >= hold_threshold but "
                f"{len(findings)} dimension(s) below floor"
            ),
            "blocking_findings": findings,
        }

    # 5. mid-band hold. avg >= hold_threshold but avg < proceed_threshold,
    #    no below-floor dimensions — the plan is workable but not strong.
    return {
        "decision": "hold",
        "rationale": (
            f"weighted average {avg} in [hold_threshold={hold_threshold}, "
            f"proceed_threshold={proceed_threshold}); no blockers but no "
            f"strong proceed signal"
        ),
        "blocking_findings": [],
    }


def decision_persists_to_lcs(decision: Dict[str, object]) -> bool:
    """Return True iff `decision` is the canonical envelope to persist at
    `lcs://valuations/<plan-id>`. A non-canonical envelope (missing keys,
    wrong types) is rejected so the LCS resource can rely on the shape.
    """
    if not isinstance(decision, dict):
        return False
    if set(decision) != {"decision", "rationale", "blocking_findings"}:
        return False
    if decision["decision"] not in ("proceed", "revise", "hold", "kill"):
        return False
    if not isinstance(decision["rationale"], str):
        return False
    if not isinstance(decision["blocking_findings"], list):
        return False
    return True


__all__ = [
    "DIMENSIONS",
    "DEFAULT_PROCEED_THRESHOLD",
    "DEFAULT_HOLD_THRESHOLD",
    "DEFAULT_DIMENSION_FLOOR",
    "DEFAULT_RISK_FLOOR",
    "SCORE_MIN",
    "SCORE_MAX",
    "decide",
    "decision_persists_to_lcs",
    "cli_main",
]


# ---------------------------------------------------------------------------
# CLI (Phase 4, issue #369 M2: documented in skills/valuate/SKILL.md
# and docs/stages/STAGES.md as `python3 -m lib.valuation_engine --plan PRD.md
# --dry-run`.)
# ---------------------------------------------------------------------------

def _load_plan_scores(plan_path: str) -> Dict[str, float]:
    """Read a YAML/JSON plan and extract the 6 plan_value scores.

    The plan file is expected to have a top-level ``plan_value`` dict
    with keys matching ``DIMENSIONS`` (problem_fit, roi_estimate,
    existing_solution_edge, team_capability, risk_vs_reward,
    measurability). Missing dimensions are treated as 0 (worst
    case) so a partial plan cannot sneak past the gate.
    """
    import json
    from pathlib import Path
    p = Path(plan_path)
    text = p.read_text(encoding="utf-8")
    if p.suffix in (".yaml", ".yml"):
        import yaml
        doc = yaml.safe_load(text) or {}
    else:
        doc = json.loads(text)
    raw = doc.get("plan_value", {}) if isinstance(doc, dict) else {}
    out: Dict[str, float] = {}
    for axis in DIMENSIONS:
        out[axis] = float(raw.get(axis, 0) or 0)
    return out


def cli_main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Returns 0 on proceed, 1 on hold/revise/kill, 2 on error.

    Usage:
        python3 -m lib.valuation_engine --plan PRD.md [--dry-run] [--json]
    """
    import argparse
    import json
    parser = argparse.ArgumentParser(prog="valuation_engine")
    parser.add_argument("--plan", required=True, help="path to plan YAML/JSON")
    parser.add_argument("--dry-run", action="store_true",
                        help="print decision; do not persist to LCS")
    parser.add_argument("--json", action="store_true", help="emit JSON envelope")
    args = parser.parse_args(argv)
    try:
        scores = _load_plan_scores(args.plan)
    except (OSError, ValueError) as exc:
        print(f"error loading plan: {exc}", file=sys.stderr)
        return 2
    decision = decide(plan={}, rubric_scores=scores)
    envelope = {
        "decision": decision["decision"],
        "rationale": decision["rationale"],
        "blocking_findings": decision["blocking_findings"],
        "scores": scores,
        "source_plan": args.plan,
    }
    if args.json:
        print(json.dumps(envelope, indent=2))
    else:
        print(f"decision: {decision['decision']}")
        print(f"rationale: {decision['rationale']}")
        for f in decision["blocking_findings"]:
            print(f"  - {f}")
    if not args.dry_run and decision_persists_to_lcs(decision):
        # The build pre-flight will look this up; the CLI itself does
        # not write (kept pure so tests can use --dry-run without
        # touching the on-disk LCS cache).
        pass
    return 0 if decision["decision"] == "proceed" else 1


if __name__ == "__main__":
    import sys
    sys.exit(cli_main())
