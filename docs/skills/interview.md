> [← Skills index](README.md) · [Project README](../../README.md)

# `interview`

**Category:** `design` · **Alpha:** `enforcement` · **Invocation:** `/dev-kit:interview <plan-file>` (human-invoked)

`interview` runs the 5-field safety-contract interview that gates plan emission. It drives `lib.interview_engine` through a single Ralph loop with `safety_valve=8`, `narrowed_delta=true`, `dedup_metric: identical-ambiguity-cycle=2`, and `user_interrupt: true`. Convergence is `composite (ambiguity_score <= 3 AND all_5_fields_clear)`. Source: [`skills/interview/SKILL.md`](../../skills/interview/SKILL.md).

## When to use it

- The user types `/dev-kit:interview <plan-file>`.
- The `plan` skill reads `.dev-kit/hand-off/<step>.md` before emitting a PRD.
- The user wants to back-fill the 5 fields for an in-flight phase.
- A reviewer wants the audit trail (`decision-log.md` + `loop-log.json`) for the interview loop.

## Output

- `decision-log.md` — the 5 fields × iterations matrix
- `loop-log.json` — per-turn safety / convergence / dedup metrics
- An updated `.dev-kit/hand-off/<step>.md` the `plan` stage reads from
