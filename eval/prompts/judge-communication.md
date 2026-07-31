# judge-communication — D5 LLM judge prompt

Phase 1 placeholder. The actual prompt lands when LLM judge wiring ships
(see proposal §03 Phase 1). The shape below is the contract Phase 1 will
honor: the judge receives the hand-off notes + PR description and must
return a JSON object with the 5 axes below, each rated 1-5.

## Inputs

```
hand_off_notes:
{hand_off}

pr_description:
{pr_description}

commit_messages:
{commit_messages}
```

## Output contract

```json
{
  "axes": {
    "clarity": 1-5,
    "completeness": 1-5,
    "actionability": 1-5,
    "verifiability": 1-5,
    "conciseness": 1-5
  },
  "evidence": "one sentence per axis explaining the rating"
}
```

## Axis definitions

1. **clarity** — Is the intent clear to the next reader? Score 5 when
   the next agent can paraphrase the goal in one sentence.
2. **completeness** — What/why/next-step are all present? Score 5 when
   nothing is missing.
3. **actionability** — Does the next agent know exactly what to do?
   Score 5 when the next step is a single concrete command or file edit.
4. **verifiability** — Can the next agent verify success? Score 5 when
   a test or check is named.
5. **conciseness** — No fluff / padding. Score 5 when every sentence
   carries information.

## Mean → dim value

`value = round(mean(axes))` clamped to 1..5. This becomes the D5 value.
