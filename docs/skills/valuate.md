> [← Skills index](README.md) · [Project README](../../README.md)

# `valuate`

**Category:** `design` · **Alpha:** `enforcement` · **Invocation:** model-invocable only (`user-invocable: false`; the slash `/dev-kit:valuate` was removed from the user menu in PR #589).

`valuate` scores a plan on 6 axes via the LLM judge and returns `proceed` / `revise` / `hold` / `kill`. The verdict envelope persists to `.dev-kit/valuations/<plan-id>.json`. A `kill` or unresolved `hold` is the planning stage's signal not to start `build`. (The Phase 4 auto-gate that hard-blocked `build` on a non-PROCEED verdict was tied to the LCS substrate and was removed in #463; `build` no longer reads the verdict automatically.) Source: [`skills/valuate/SKILL.md`](../../skills/valuate/SKILL.md).

## When to use it

- `/dev-kit:plan` (or another model-invoked planning stage) calls into the rubric during plan emission.
- A reviewer wants to know whether the `build` stage would refuse this plan.
- An agent needs the decision + per-axis rationale surfaced as one report.

## Invocation

`valuate` is invoked by another skill or sub-agent via the standard skill-tool contract; there is no user-facing slash. The caller supplies the plan file path (default `PRD.md`):

```text
invoke_skill("valuate", plan="phases/<name>/index.json")
```

`safety_valve: 1`, `convergence: decision != "hold"`, `dedup_metric: identical-decision-cycle=2`, `user_interrupt: true`. Per-axis rationale is the primary output; the decision field is the build gate's input.
