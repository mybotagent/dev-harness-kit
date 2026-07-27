> [← Skills index](README.md) · [Project README](../../README.md)

# `research`

**Category:** `design` · **Alpha:** `enforcement` · **Invocation:** `/dev-kit:research <claim>` (human-invoked)

`research` runs the Phase 0 → Phase 3 citation-enforcement gate over any claim that needs backing. It escalates through `cache → direct → multi-source → human-in-the-loop`, then `verify()` and `enforce_citations()` are the no-go gates. Every claim either cites a source or is removed. Source: [`skills/research/SKILL.md`](../../skills/research/SKILL.md).

## When to use it

- The user types `/dev-kit:research <claim>`.
- The `plan` or `review` step needs cited evidence before claiming a fact.
- The operator wants a deterministic "every claim cites a source" pass over a draft.
- Code review surfaces an uncited claim that must be backed or removed.

## Invocation

```bash
/dev-kit:research "any non-trivial factual claim" --max-phase 3
```

`safety_valve: 4`, `convergence: enforce_citations returns 0 uncited sentences`, `dedup_metric: same-query-escalate=2`, `user_interrupt: true`.
