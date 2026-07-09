# Eval: Review Dimension (judge-review, v2.0.0)

You are judging the agent's `/dev-kit:review` output for one case fixture.

Score 5 axes 0-10 each. The 5th axis (`code_sanity_score`) is a composite
of clean-code + over-engineering + value rubrics — see
`judge-code-sanity.md` for the 20-checkbox checklist.

## Case

- **Case ID**: ${CASE_ID}
- **Dimension**: ${DIM}
- **Category**: ${CATEGORY} (`real-bug` | `trap` | `clean` | `over-engineering` | `clean-violation` | `no-value`)
- **Input code** (the fixture the reviewer was given):
```
${INPUT}
```
- **Agent output** (the reviewer's JSON verdict + findings):
```
${AGENT_OUTPUT}
```
- **Expected behavior** (the ground-truth verdict + finding set):
```
${EXPECTED}
```

## Code-sanity rubric (for `code_sanity_score` axis)

The reviewer was expected to surface code-sanity findings as part of
its review when the fixture contains planted clean-code / over-eng /
value issues. The full 20-checkbox rubric is below — embed the relevant
checklist in your judgment.

```
${RUBRIC}
```

## Axes (0-10)

1. **verdict_consistency** — does the agent's top-line verdict
   (Blocked / Changes Requested / Approve) match the expected verdict
   for this case? 10 = exact match; 0 = inverted (e.g. Approve on a
   critical bug). One tier off (Blocked -> Changes) = 5.
2. **severity_calibration** — for each finding the agent emitted, does
   the severity (`critical` / `major` / `minor` / `nit`) match the
   actual impact? 10 = every finding at correct severity; 0 = every
   finding wildly mis-severity. Calibrate per-finding; average.
3. **precision** — what fraction of the agent's findings are real
   (planted bugs, real clean-code violations, real over-eng)?
   `TP / (TP + FP)`. Trap / clean fixtures that surface findings = low
   precision. 10 = no false positives; 0 = every finding is noise.
4. **recall** — what fraction of the planted issues did the agent
   surface? `TP / (TP + FN)`. Real-bug fixtures that miss the planted
   bug = low recall. 10 = caught every planted issue; 0 = missed all.
5. **code_sanity_score** — for the planted clean-code / over-eng /
   value items in the fixture, did the agent surface them? Compute the
   composite: `0.4 * clean_code_found + 0.4 * over_eng_caught +
   0.2 * value_articulated`, each sub-score 0-10 per the rubric.

## Output Format

ONLY a JSON object (no prose). 5 axes, each 0-10:

```json
{"verdict_consistency":N,"severity_calibration":N,"precision":N,"recall":N,"code_sanity_score":N}
```
