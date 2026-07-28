# Push-Intent Judge (judge-push-intent, v1.0.0)

Used by `.githooks/pre-push` (opt-in via `DEV_KIT_PUSH_INTENT=1`) via
`lib/push_intent_judge.py` to judge whether the commit about to be
pushed has value/intent. Surfaces a single `VERDICT=` line on stdout
(OK / DRIFT_WARNING / ROT) and a one-line `REASON=` for the terminal.

The judge returns ONLY the four value/meaning axes (VM-1..4) from
`judge-code-sanity.md`. Clean-code (CC-1..8) and over-engineering
(OE-1..8) belong to the dedicated CI maintenance gate (see
`judge-maintenance.md` and `.github/workflows/maintenance.yml`). This
split keeps the pre-push hook fast (one small LLM call) and avoids
running the full rubric twice per push.

## Inputs

- `${COMMIT_MESSAGE}` — the full commit body (subject + description) of the
  tip commit being pushed.
- `${DIFF_STAT}` — `git diff --stat` output of the same commit (one line
  per file: `<adds>+ <dels>- <path>`).
- `${DIFF_SAMPLE}` — up to ~2 KB of unified diff hunk content for the
  same commit, to ground the scope-discipline judgment.

## Axes (each 0-10; aggregate = mean, then verdict_from_score)

- `intent_clarity` — Does the commit message state a clear, single
  purpose? Bonus for tying the change to a real user need or a stated
  problem. Penalize vague verbs ("tidy up", "stuff", "various").
  Anchor: VM-1 + VM-4 from `judge-code-sanity.md`.
- `scope_discipline` — Does the diff match the stated purpose? No
  unrelated drive-by edits, no "while I was here" additions, no
  bundling multiple features. Anchor: VM-3 + VM-4.
- `change_necessity` — Is the change necessary, or is it noise
  (whitespace-only, rename churn, import reorder, pure formatting)?
  Anchor: VM-2 + VM-4.
- `value_alignment` — Does the change contribute to a stated goal
  visible in the commit message, PR description, or linked issue?
  Anchor: VM-1 + VM-4.

## Score sub-rubric (when an axis has relevant input)

For each axis, if the axis's relevant pattern is NOT present in the
input, score that axis at 10 (vacuously clean). Otherwise score by
how many of the bullet anchors above were violated.

## Output format

Respond ONLY with a single JSON object:

```json
{
  "intent_clarity": <0-10>,
  "scope_discipline": <0-10>,
  "change_necessity": <0-10>,
  "value_alignment": <0-10>,
  "reason": "<one short sentence naming the worst axis>"
}
```

No prose before or after. The `reason` string is what the pre-push
hook prints to the operator's terminal — keep it under 100 chars.