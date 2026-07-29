---
name: interview
category: design
description: "5-field safety-contract interview that gates plan emission. Drives `lib.interview_engine` through one Ralph loop, enforces `safety_valve=8`, `narrowed_delta`, `dedup_metric` (identical-ambiguity-cycle=2), and `user_interrupt`."
alpha: enforcement
when_to_use:
  - User types /dev-kit:interview <plan-file>
  - Plan skill consumes the interview hand-off before emitting PRD
  - User wants to back-fill the 5 fields for an in-flight phase
  - Reviewer wants the audit trail (decision-log.md + loop-log.json) for the interview loop
allowed-tools: Read Write Glob AskUserQuestion
disallowed-tools: Bash Edit NotebookEdit WebFetch
model: opus
disable-model-invocation: true
user-invocable: true
safety:
  safety_valve: 8
  convergence: composite (ambiguity_score <= 3 AND all_5_fields_clear)
  narrowed_delta: true
  dedup_metric: "identical-ambiguity-cycle=2"
  user_interrupt: true
---
> [← Skills index](../../README.md)

# /dev-kit:interview — 5-field safety contract

Self-contained. Drives `lib.interview_engine` through one conversational
loop until all 5 fields (goal / constraints / success_criteria /
anti_goals / acceptance_rubric) clear the composite convergence test.
The output is the hand-off frontmatter at
`.dev-kit/hand-off/interview-<session>.md`, which the plan skill reads
before emitting PRD.md.

## Iron Laws (Phase 6, MUST-15)

1. **5 fields are mandatory.** Every interview must surface an answer
   for `goal`, `constraints`, `success_criteria`, `anti_goals`, and
   `acceptance_rubric`. Any absent field = `status: held`.
2. **`safety_valve: 8` cycle cap.** At most 8 user turns. Cap reached
   without pass → `status: held`; the plan skill refuses to emit PRD.
3. **`narrowed_delta`.** Each iteration's `ambiguity_score` must
   strictly decrease. Equality does not narrow.
4. **`dedup_metric: identical-ambiguity-cycle=2`.** Two cycles with the
   same `ambiguity_score` in a row breaks the loop and surfaces
   `status: best-effort` (the user keeps the current scores, no PRD
   re-ask).
5. **`user_interrupt`.** Stop / cancel / skip / abort / later (exact
   tokens) freeze the contract at `status: user-acknowledged`. The
   plan skill may proceed with the partial contract; the reviewer sees
   the freeze in the audit log.

## Core goal

Interview artifacts only. No code, no PRD, no build. Take a 1-line
idea + a 5-field intake loop → write the hand-off frontmatter the plan
skill reads from `.dev-kit/hand-off/interview-<session>.md`.

## Inputs / outputs

- **Input**: 1-line idea (from `<plan-file>` if given, else from the
  user prompt) + session id (default = "default").
- **Output**:
  - `.dev-kit/hand-off/interview-<session>.md` — frontmatter carrying
    the 4 contract fields + `status`.
  - `.dev-kit/decision-log.md` — every question + answer, one entry
    per cycle.
  - `.dev-kit/loop-log.json` — narrowing per cycle (MUST-16).

## Conversational loop (5 questions, 1 Ralph)

```
[1/5] goal              — q_goal              maps to goal
       ↓
[2/5] constraints       — q_constraints       maps to constraints
       ↓
[3/5] success_criteria  — q_success_criteria  maps to success_criteria
       ↓
[4/5] anti_goals        — q_anti_goals        maps to anti_goals
       ↓
[5/5] acceptance_rubric — q_acceptance_rubric maps to acceptance_rubric
```

Iteration order is the MUST-15 plan pattern — do not skip around.
Each question asks **exactly one** thing; the user can ask to re-prompt
or skip.

### Composite convergence test

```
PASS  iff  all 5 fields pass `validate_5_field` (present + clear)
        AND  ambiguity_score <= 3
```

On FAIL, loop on the failing field. Cap at `safety_valve=8` cycles.
On cap without pass → write `status: held` to the hand-off file.

### Decision-log entry per cycle

```markdown
# cycle N (q_goal)
- answer: "<user answer verbatim>"
- per-field scores: {goal: 2, constraints: 10, ...}
- ambiguity: 6 -> 4 (narrowed, ok)
- next: re-ask q_constraints (still missing)
```

## LLM judge re-score (per-dim eval)

The deterministic `lib.interview_engine.score_interview_ambiguity`
runs locally. The LLM judge (`eval/prompts/judge-interview-ambiguity.md`,
5 axes: `goal_clarity` / `constraints_clarity` / `success_criteria_clarity`
/ `anti_goals_clarity` / `acceptance_rubric_clarity`) re-scores the
final answer set when the user invokes `/dev-kit:eval --dim interview_ambiguity`.

The judge MUST return the same shape as `score_interview_ambiguity`
(see `lib/llm_judge.py:DIM_AXES["interview_ambiguity"]`) so the
deterministic and LLM paths compose without a custom translator.

## Rules (no exceptions)

- 5-field loop declared (MUST-15): `safety_valve=8`, composite
  convergence, `is_narrowing` (boolean predicate; legacy alias
  `narrowed_delta` still exported for backward compat), `dedup_metric`,
  `user_interrupt`.
- No artifacts other than `.dev-kit/hand-off/interview-<session>.md`,
  `.dev-kit/hand-off/interview→plan.md`,
  `.dev-kit/decision-log.md`, `.dev-kit/loop-log.json`.
- No code, no PRD, no `phases/<name>/` writes (the plan skill owns
  those).
- "Just write the code" before all 5 fields are clear → still no PRD.
- `lib/interview_engine.py` is the only source of the 5-field state
  machine; do not fork the logic.
- After HOLD or user-acknowledged, the plan skill decides whether to
  proceed (it will refuse to emit PRD on `held`).

## Hook alignment

Interview stage:
- `slop-detector=OFF` (interview artifacts tolerate LLM-typical phrasing)
- `stop-verify=ON`
- Others OFF

## Hand-off

On `.dev-kit/hand-off/interview-<session>.md` complete:
- `state_codec.append_hand_off(root, "interview", "plan",
   f"session={session} status={status}")` auto
- Write `.dev-kit/hand-off/interview→plan.md` summarizing the contract
- Wait for `/dev-kit:plan` invocation

## Next step

`/dev-kit:plan <idea>` — reads `.dev-kit/hand-off/interview-<session>.md`
(the hand-off file above) before Gate 1. If `status: held`, refuse to
emit PRD.md and surface the gap to the user.
