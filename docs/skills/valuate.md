> [← Skills index](README.md) · [Project README](../../README.md)

# `valuate`

**Category:** `design` · **Alpha:** `enforcement` · **Invocation:** `/dev-kit:valuate <plan-file>` (human-invoked)

`valuate` scores a plan on 6 axes via the LLM judge and returns `proceed` / `revise` / `hold` / `kill`. The verdict envelope persists to `.dev-kit/valuations/<plan-id>.json`. A `kill` or unresolved `hold` is the operator's signal not to start `build`. (The Phase 4 auto-gate that hard-blocked `build` on a non-PROCEED verdict was tied to the LCS substrate and was removed in #463; `build` no longer reads the verdict automatically.) Source: [`skills/valuate/SKILL.md`](../../skills/valuate/SKILL.md).

## When to use it

- The user types `/dev-kit:valuate <plan-file>`.
- The `plan` stage finishes and the user wants an automatic no-go verdict.
- A reviewer wants to know whether the `build` stage will refuse this plan.
- The user wants the decision + per-axis rationale surfaced as one report.

## Invocation

```bash
/dev-kit:valuate phases/<name>/index.json
```

`safety_valve: 1`, `convergence: decision != "hold"`, `dedup_metric: identical-decision-cycle=2`, `user_interrupt: true`. Per-axis rationale is the primary output; the decision field is the build gate's input.
