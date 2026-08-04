# Research: <topic>

> Phase 1 of the research → plan → implement pipeline.
> Source: `templates/research.md`. Consumed by `skills/research-plan-build/SKILL.md`.
> Citations must satisfy `skills/research/SKILL.md` Phase 0-3 escalation.

## Question

What we are trying to learn. One sentence; framed as a falsifiable claim.

```
question: <single sentence>
scope:    <files / modules / behavior in scope>
out_of_scope: <what we deliberately will not investigate>
```

## Evidence

Each claim must cite `url` + `fetched_at` + `source_type` (primary /
secondary). Format mirrors `lib/research_engine.py:verify()` output.

| # | Claim | Source URL | Fetched at (ISO 8601) | Source type | Confidence |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

Add rows as needed. Minimum 3 independent sources for Gate-2 evidence
(see `skills/plan/SKILL.md` Gate 2.1). Independence = different origin
(user interview, market data, analogue product, prior failed attempt,
paying-customer ask).

## Cross-validation

Cross-validation is the second pass over the evidence table. For each
load-bearing claim, state how it agrees (or disagrees) with at least one
other source. If two independent sources disagree, escalate to
`lib/research_engine.py:escalate()` Phase 2 (multi-source fan-out)
before recording the resolution.

```
claim-1: agrees with claim-3 (independent origin) → confidence boosted
claim-2: standalone, no second source → flag for follow-up
claim-4: disagrees with claim-5 → escalated to Phase 2
```

## Conclusion

A short paragraph answering the question, anchored to the strongest
claim(s) above. Every sentence in this paragraph must have a matching
citation block in the body, or be flagged `[UNCITED]` by
`lib/research_engine.py:enforce_citations()`.

- **Verdict**: confirmed / partial / refuted
- **Open questions**: any unresolved gaps the plan phase must absorb
- **Hand-off**: `/dev-kit:research-plan-build` → plan phase

## Next step

Hand off to `templates/plan.md`. Do not start the plan phase until every
sentence in the Conclusion either cites a source or is explicitly
flagged `[UNCITED]`.
