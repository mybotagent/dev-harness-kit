# Eval: Plan-Value Dimension (judge-plan-value, v1.0.0)

You are judging whether a plan is worth building. The /dev-kit:valuate
skill feeds your scores into `lib/valuation_engine.py:decide()`, which
returns one of four verdicts — `proceed` / `revise` / `hold` / `kill` —
that the build stage reads from `lcs://valuations/<plan-id>` to enforce a
no-go gate. Your single most consequential job: do not rescue a plan on
`risk_vs_reward` if the downside is catastrophic. The risk-floor rule is
absolute.

## Case

- **Plan ID**: ${PLAN_ID}
- **Plan body** (the full PRD + phases/<name>/ emitted by /dev-kit:plan):
```
${PLAN}
```
- **Interview answers** (the 5-field contract from the plan stage's
  `lcs://interview/plan-build` hand-off — `safety_valve`,
  `ambiguity_score`, `value_score`, `evidence_count`, `status`):
```
${INTERVIEW}
```

## Rubric (6 axes, score 0-5 each)

1. **problem_fit** — does this plan solve a problem the target user
   actually has today? 5 = user is actively asking for this; 1 = pure
   speculation.
2. **roi_estimate** — does the value (LTV * reachable users) plausibly
   justify the cost? Use the plan stage's value_score = LTV * users /
   cost formula: 5 = value_score > 5.0; 1 = value_score < 1.0.
3. **existing_solution_edge** — is this materially better than what
   the user can already use? 5 = no viable alternative; 1 = free /
   paid alternatives solve this better.
4. **team_capability** — can the team actually deliver it? Stack
   familiarity, on-call burden, skill gaps all count. 5 = team has
   shipped similar systems; 1 = team lacks core skills.
5. **risk_vs_reward** — if this fails in production, how bad is the
   downside? Security, data-loss, reputation, regulatory exposure.
   **ABSOLUTE RULE**: any score < 2 on this axis forces `kill`
   regardless of every other axis. 5 = low downside, reversible; 1 =
   catastrophic (data loss / regulatory / safety).
6. **measurability** — will the team know within 2 weeks of launch
   whether this is working? 5 = leading + lagging metrics, A/B-able;
   1 = no metric at all.

## Score the rubric

For each axis, pick the lowest score whose description matches. If two
adjacent scores both partially match, pick the lower one — the gate is
deliberately conservative. Only output 0 (not scored) if the plan body is
empty or unreadable.

## Output Format

ONLY a JSON object (no prose). 6 axes, each 0-5:

```json
{"problem_fit":N,"roi_estimate":N,"existing_solution_edge":N,"team_capability":N,"risk_vs_reward":N,"measurability":N}
```

Do not include any of `proceed` / `revise` / `hold` / `kill` in the
output. The verdict is computed by `lib/valuation_engine.py:decide()`
from these 6 scores, never by you.
