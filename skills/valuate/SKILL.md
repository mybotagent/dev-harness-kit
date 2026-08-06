---
name: valuate
category: design
description: Plan-value gate. Scores a plan on 6 axes via LLM judge and returns proceed / revise / hold / kill. Verdict envelope persists to .dev-kit/valuations/<plan-id>.json.
alpha: enforcement
when_to_use:
  - User types /dev-kit:valuate <plan-file>
  - Plan stage finishes and the user wants an automatic no-go verdict
  - Reviewer wants to know whether the build stage will refuse this plan
  - User wants the decision + per-axis rationale surfaced as one report
allowed-tools: Read Write Bash Grep
disallowed-tools: WebFetch Edit
model: opus
disable-model-invocation: true
user-invocable: false
safety:
  safety_valve: 1
  convergence: decision != "hold"
  dedup_metric: identical-decision-cycle=2
  user_interrupt: true
---
> [← Skills index](../../README.md)

# /dev-kit:valuate — Plan-value no-go gate (Phase 4, issues #369-#373)

The plan-value gate. The `/dev-kit:plan` stage reduces ambiguity;
`/dev-kit:valuate` answers the next question: **is this plan worth
building?** The gate is deterministic — the LLM scores six rubric axes,
then `lib/valuation_engine.py:decide()` collapses them to one of four
verdicts. The verdict envelope persists to
`.dev-kit/valuations/<plan-id>.json`.

> The build stage's hard auto-gate (refuse-on-non-PROCEED) was tied to
> the LCS substrate and was removed in #463. Operators now run
> `/dev-kit:valuate` explicitly; the verdict envelope is the operator's
> signal to proceed or halt — `build` no longer reads it automatically.

## What it does

1. Reads the plan file (default: `PRD.md`) and the plan-stage interview
   hand-off at `.dev-kit/hand-off/plan-build.md`.
2. Builds the LLM judge prompt from `eval/prompts/judge-plan-value.md`
   (substitutes `${PLAN}`, `${INTERVIEW}`, `${PLAN_ID}`).
3. Calls the judge via `lib/llm_judge.py:call_judge(axes=("proceed",
   "revise", "hold", "kill"))`. The judge returns a 6-axis JSON object
   (problem_fit / roi_estimate / existing_solution_edge / team_capability /
   risk_vs_reward / measurability) each 0-5.
4. Calls `lib/valuation_engine.py:decide(plan, rubric_scores)` and gets
   back `{decision, rationale, blocking_findings}`.
5. The CLI prints the verdict + per-axis breakdown to stdout; the
   envelope contract is pinned by
   `lib/valuation_engine.py:decision_is_canonical_envelope`.

The decision is **deterministic on identical input**: same plan + same
rubric scores → same verdict. This is the contract that makes the gate
enforceable (L6 — `alpha: enforcement`).

## Verdict semantics

| Verdict | What it means | Operator guidance |
|---|---|---|
| `proceed` | All dimensions >= 3, weighted avg >= 4 | Proceed to `build` |
| `revise` | Some dimension < 3, but no risk-floor violation | Back to `/dev-kit:plan` |
| `hold` | Weighted avg in [3, 4), no below-floor dimensions | Re-evaluate later |
| `kill` | Any dimension < 2 (absolute risk-floor rule) OR weighted avg < 3 | Archive as no-go |

The absolute risk-floor rule is load-bearing: even a 5.0 on every other
dimension cannot rescue a 1.5 on `risk_vs_reward`. The model cannot talk
its way past this — the gate is a pure function, not an LLM judgment.

## Pre-flight gate

Refuses to start if `PRD.md` is missing. Run `/dev-kit:plan` first; the
gate reads the plan body and the interview hand-off. The interview
hand-off is optional (the engine still runs without it), but the judge
prompt strongly prefers a populated `value_score` / `ambiguity_score`.

## CLI

```
python3 -m lib.valuation_engine --plan PRD.md [--interview .dev-kit/hand-off/plan-build.md] [--rubric lib/valuation_rubrics/default.yaml] [--plan-id <id>] [--dry-run]
```

| Flag | Purpose |
|---|---|
| `--plan PATH` | Plan body (default: PRD.md) |
| `--interview PATH` | Plan-stage interview hand-off (default: `.dev-kit/hand-off/plan-build.md`) |
| `--rubric PATH` | Rubric YAML (default: `lib/valuation_rubrics/default.yaml`) |
| `--plan-id ID` | Plan id used for the verdict filename (default: derived from filename or git branch) |
| `--dry-run` | Skip LLM call; mock the 6 axes at 4.0/4.0/4.0/4.0/4.0/4.0 (proceed) |
| `--json` | Emit only the JSON envelope to stdout |

## Output envelope

```json
{
  "plan_id": "<id>",
  "decision": "proceed|revise|hold|kill",
  "rationale": "<one-line>",
  "blocking_findings": ["<axis>=<value> < <floor>", ...],
  "rubric_scores": {
    "problem_fit": 4,
    "roi_estimate": 5,
    "existing_solution_edge": 3,
    "team_capability": 4,
    "risk_vs_reward": 4,
    "measurability": 4
  },
  "tokens_in": 1234,
  "tokens_out": 89
}
```

The envelope's 3-key shape (`decision` / `rationale` /
`blocking_findings`) is the contract consumers must satisfy; it is
pinned by `lib/valuation_engine.py:decision_is_canonical_envelope`.

## Hook integration (Valuate stage)

- `stop-verify=ON`
- `slop-detector=OFF` (the gate output is structured JSON)
- Others OFF

## Next step

- On `proceed` → `/dev-kit:build` runs.
- On `revise` → back to `/dev-kit:plan` to regenerate the PRD.
- On `hold` → archive the verdict; user re-invokes `/dev-kit:valuate`
  after the wait period.
- On `kill` → archive as no-go; `/dev-kit:plan` should not be re-run
  for the same idea without a substantial pivot.

## Related

- `lib/valuation_engine.py` — pure-function gate (the deterministic core)
- `lib/valuation_rubrics/default.yaml` — 6-axis rubric SSOT
- `eval/prompts/judge-plan-value.md` — LLM judge prompt
- `lib/llm_judge.py` — provider-agnostic judge (uses
  `DIM_AXES["plan_value"]` for the verdict sub-scores)
