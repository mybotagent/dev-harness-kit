---
name: research
category: design
description: 0-arg research gate. Run Phase 0-3 escalation (cache / direct / multi / human) + verify() + enforce_citations(). /dev-kit:research <claim> [--max-phase N].
alpha: enforcement
when_to_use:
  - User types /dev-kit:research <claim>
  - Plan or review step needs cited evidence before claiming a fact
  - Operator wants a deterministic "every claim cites a source" pass over a draft
  - Code review surfaces an uncited claim that must be backed or removed
allowed-tools: Read Grep Glob Bash
disallowed-tools: Write Edit
model: sonnet
disable-model-invocation: false
user-invocable: true
safety:
  safety_valve: 4
  convergence: enforce_citations returns 0 uncited sentences
  dedup_metric: same-query-escalate=2
  user_interrupt: true
---
> [← Skills index](../../README.md)

# /dev-kit:research — Phase 0-3 research escalation + verification gate

Research with **enforceable citations**: every claim must cite a URL +
fetch timestamp + source type, or be flagged `[UNCITED]`. The skill wraps
`lib/research_engine.py` (escalate / verify / enforce_citations) and
`lib/llm_judge.py`'s new `research_source` + `research_claim` axes.

## What it does

Given a claim, the skill:

1. Escalates through `escalate(query, max_phase=N)`:
   - **Phase 0** — cache hit on `.dev-kit/research_cache.jsonl` (< 30 day old).
   - **Phase 1** — direct HTTP GET + OGP / JSON-LD extract on the first
     candidate URL.
   - **Phase 2** — fan-out across N candidate URLs, dedupe by URL.
   - **Phase 3** — human handoff. Returns a structured `NEEDS_HUMAN`
     payload. Never fabricates a result.
2. Runs `verify(claim, sources)`:
   - Requires `url` + `fetched_at` + `source_type` per source.
   - HEAD-checks every URL; broken URLs become gaps.
   - Boosts confidence when `>= 3` sources agree.
3. Runs `enforce_citations(text)` over the resulting prose:
   - Sentences with a `[src:URL;ts:DATE;type:primary]` block pass through.
   - Other sentences are prefixed `[UNCITED]` so a reviewer can fix them.

The `max_phase` flag defaults to 4 (engine caps at 3, the human handoff).
Pass `--max-phase 0` to force a cache-only run; pass `--max-phase 1` to
forbid Phase 2 multi-source fan-out.

## Usage

```bash
# Full Phase 0-3 escalation with citation gate.
python3 lib/research_engine.py --query "Why does X fail in CI?"

# From the skill surface (this file's invocation):
/dev-kit:research "Why does X fail in CI?" --max-phase 2

# Force a cache-only run (no network):
/dev-kit:research "Why does X fail in CI?" --max-phase 0

# Force citation enforcement on a draft prose file:
python3 -c "from lib.research_engine import enforce_citations; print(enforce_citations(open('draft.md').read()))"
```

## Eval hooks

The skill is judged on two new `DIM_AXES` tuples (each 5 axes, mirror the
`review` shape):

| Axis | What it scores |
|---|---|
| `research_source` | authority / recency / primary-vs-secondary / url validity / citation completeness |
| `research_claim` | citation-required / n-source agreement / primary present / timestamp present / rubric match |

Prompts: `eval/prompts/judge-research-source.md` + `judge-research-claim.md`.
No live eval is auto-triggered — wire via `/dev-kit:eval --dim research_source`
or `--dim research_claim` once a case fixture exists.

## Iron Laws

- **L1**: every claim emitted by `verify()` must include `url` + `fetched_at`
  + `source_type`. Gaps list breaks this contract.
- **L4**: no `TODO` placeholders in source records — empty `title` is fine,
  but missing `fetched_at` is a gap, not a "we'll fill it in later".
- **L5**: one deterministic flow (Phase 0 → 3), not a menu of search engines.

## Failure modes

- Network failure in Phase 1 → escalate to Phase 2 if `max_phase >= 2` and
  at least 2 candidate URLs were given; else Phase 3 `NEEDS_HUMAN`.
- Empty candidate URLs and `max_phase >= 2` → Phase 3 (we do not invent URLs).
- `verify()` with zero sources → `verified=False`, `gaps=[<reason>]`.
- HEAD request fails → URL is dropped from `citations` and listed in `gaps`.

## Next step

- For plan-mode claims: hand off to `/dev-kit:plan` with the citation-enforced prose.
- For review findings: hand off to `/dev-kit:review` after `enforce_citations()`.
- For release-blocking verification: hand off to `/dev-kit:ship` once
  `verify()` returns `verified=True` with `confidence >= 0.7`.
