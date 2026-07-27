# Eval: Interview Ambiguity Dimension (judge-interview-ambiguity, v1.0.0)

You are judging the user's completed `/dev-kit:interview` answers against
the 5-field safety contract. Score each field's clarity on a 0-10 axis
where **0 = perfectly clear and 10 = maximally ambiguous**.

The 5-field contract is the Phase 6 MUST-15 plan pattern. Every
interview must clear all 5 fields before `status: ok` is emitted.

## Case

- **Case ID**: ${CASE_ID}
- **Dimension**: interview_ambiguity
- **Field list** (the 5 mandated fields, in canonical order):
  1. `goal` — one sentence: what we ship and what changes for the user.
  2. `constraints` — explicit guardrails / non-negotiables.
  3. `success_criteria` — measurable pass conditions.
  4. `anti_goals` — what we will NOT do (negative spec).
  5. `acceptance_rubric` — how a reviewer scores "done".
- **User answers** (the 5 fields the user typed):
```
${INPUT}
```
- **Per-field heuristics** (the local fallback the skill already ran):
```
${RUBRIC}
```

## Axes (0-10 each; lower = clearer)

1. **goal_clarity** — Is the goal stated as a single, concrete,
   user-facing outcome? 0 = crisp one-liner a PM could paste in a
   release note; 10 = "make it better" or absent.
2. **constraints_clarity** — Are the constraints named, verifiable,
   free of soft language (probably / maybe / ideally)? 0 = bullet list
   of hard rules; 10 = platitudes or empty.
3. **success_criteria_clarity** — Are the criteria numeric / boolean
   thresholds an SRE could run on? 0 = "p95 latency < 100ms"; 10 =
   "fast and reliable" with no numbers.
4. **anti_goals_clarity** — Does each anti-goal name a specific
   feature, audience, or surface we are excluding? 0 = "no GUI
   dashboard"; 10 = "no scope creep" generic.
5. **acceptance_rubric_clarity** — Does the rubric name the reviewer,
   the checklist, and the pass threshold? 0 = "ops signs off after
   load test passes SLO"; 10 = "looks good to me".

## Output Format

ONLY a JSON object (no prose). 5 axes, each 0-10 (lower = clearer):

```json
{"goal_clarity":N,"constraints_clarity":N,"success_criteria_clarity":N,"anti_goals_clarity":N,"acceptance_rubric_clarity":N}
```
