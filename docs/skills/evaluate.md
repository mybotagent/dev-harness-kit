> [← Skills index](README.md) · [Project README](../../README.md)

# `evaluate`

**Category:** `eval` · **Alpha:** `enforcement` · **Invocation:** `/dev-kit:evaluate` (human-invoked)

`evaluate` is the harness-quality + os-quality extension of `/dev-kit:eval`. It replays recorded transcripts and judges them against the registered rubrics in `eval/rubrics/` (notably `harness-quality.yaml` and `os-quality.yaml`), so a Phase 3 batch (or any harness change) is gated on `harness-quality` and an env / secret / CI cost change is gated on `os-quality`. Source: [`skills/evaluate/SKILL.md`](../../skills/evaluate/SKILL.md).

## When to use it

- The user types `/dev-kit:evaluate [--harness-quality] [--os-quality] [--case <id>] [--dry-run]`.
- A Phase 3 batch (or any harness change) is about to land and needs the `harness-quality` rubric gate.
- An env-var, secret, or CI cost change needs the `os-quality` rubric gate.
- A nightly cron auto-call rotates through the registered dimensions.

## Invocation

```bash
/dev-kit:evaluate
/dev-kit:evaluate --harness-quality
/dev-kit:evaluate --os-quality
/dev-kit:evaluate --case <id> --dry-run
```

`--dry-run` skips LLM calls (mocks each case at the per-dim threshold) — useful in CI without an API key. See `skills/evaluate/SKILL.md` for the full per-axis rubric, the `convergence: per-case axis mean >= 8.0` contract, and the `safety_valve: 1` / `dedup_metric: identical-case-score=2` frontmatter.
