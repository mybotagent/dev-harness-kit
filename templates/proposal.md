# Proposal: <topic>

> Phase 2 of the research → proposal → plan pipeline.
> Source: `templates/proposal.md`. Consumed by
> `skills/research-proposal-plan/SKILL.md`.
> Predecessor: `templates/research.md`. Successor: plan hand-off
> (`.dev-kit/hand-off/rpp→plan.md`).
> Rendered to HTML by `/dev-kit:proposal <main>/<sub>`.

## Authoring contract

Write `docs/proposals/<main>/<sub>.yaml` matching
`skills/proposal/SKILL.md` "Authoring a proposal" verbatim. This
template is a binder-side checklist, NOT a parallel schema. The
canonical shape lives in the proposal skill; do not redefine it
here.

```yaml
title: <one-line title>
status: ready-for-review     # the binder's Phase 2 always writes this
issue: <issue number, optional>
date: YYYY-MM-DD             # today, KST
tags: [<phase-name>]

before:
  summary: |
    Markdown-lite description of the code's CURRENT state.
  evidence:
    - 'file:line, log excerpt, or commit hash supporting the claim'
after:
  summary: |
    Markdown-lite description of the code's PROPOSED state.
  files:
    - path: <repo-relative file path>
      change: |
        Markdown-lite description of what this file becomes.
pros:
  - 'Strength 1 with citation'
  - 'Strength 2'
cons:
  - 'Weakness the proposal knowingly accepts + mitigation'
limitations:
  - 'What the design CANNOT do (out-of-scope-by-design)'

sections:
  - title: Goal
    body: |
      From plan Gate 1/5 (frame): one-sentence goal + target user
      + situation. Copy verbatim from research.md when the
      question-verdict is the goal.
  - title: Evidence
    body: |
      From plan Gate 2/5 (validate): ≥3 independent signals, the
      value_score formula result, and the ambiguity loop's final
      score. Each signal cites the same source as the research.md
      Evidence table.
  - title: Non-goals
    body: |
      From plan Gate 3/5: ≥3 non-goals with rationale + breach
      response each. The breach response is the same as plan's.
  - title: Risks
    body: |
      Free-form list. Mirrors the Risks table in the old
      templates/plan.md but at the proposal granularity — known
      risk + trigger + mitigation, one row each.
  - title: Hand-off
    body: |
      Acceptance: when this proposal is approved, the next step
      is `/dev-kit:plan <phase>`. The plan skill refuses to
      overwrite this YAML when it already exists; the
      collision is the signal that the binder already rendered.
```

## Slug derivation

The proposal topic is `<main>/<sub>`:

- `<main>` = umbrella. The binder resolves it from the same source
  the plan skill uses (per-PR topic at the time of writing).
- `<sub>` = the phase directory name the operator will hand to
  `/dev-kit:plan` at Phase 3. Same name as the worktree branch
  base's `<phase>` segment.

If the slug violates `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}/[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`,
the proposal skill rejects the render and Phase 2 surfaces the slug
error in the binder's stderr.

## Gate to advance

Phase 2 → Phase 3 gate is the proposal HTML's existence:

```text
exists docs/proposals/<main>/<sub>.html
  AND exists docs/proposals/<main>/<sub>.yaml
  AND yaml.status ∈ {ready-for-review, accepted}
```

When the YAML was authored by the binder, `status:` is always
`ready-for-review`. The human reviewer is the only entity that may
flip it to `accepted`; the binder never sets that status on its own.

## Hand-off chain

1. `research-proposal-plan` (this binder) —
   `research.md` + `docs/proposals/<main>/<sub>.{yaml,html}`
2. Human approval gate — `status: ready-for-review → accepted` in the
   YAML, or iterate by re-invoking the binder
3. `plan` (user-invoked next) — `PRD.md` + `phases/<name>/`
4. `build` (user-invoked next) — implementation

The plan skill's existing Gate 5/5 auto-render collision is the
signal that this binder already produced the HTML; the operator
flipping `status: accepted` and re-running `/dev-kit:plan` is the
intended next step, not a re-render request.

## Next step

Open the HTML in a browser. If accepted, set
`status: accepted` in the YAML and invoke `/dev-kit:plan <phase>`.
If rejected, edit the YAML (status + rationale), then re-invoke
`/dev-kit:research-proposal-plan` to re-render.
