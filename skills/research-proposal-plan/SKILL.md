---
name: research-proposal-plan
category: plan
description: 3-phase binder (research → proposal → plan). Runs research + proposal HTML autonomously, then stops at the human approval gate and hands off to /dev-kit:plan. Build is OUT of scope.
alpha: state
when_to_use: |
  - User types /dev-kit:research-proposal-plan <idea>
  - Task spans >1 session OR touches >3 files (composed trigger from /dev-kit:build)
  - Operator wants the approval gate to sit BEFORE phase decomposition, not after
allowed-tools: Read Write Glob Skill
disallowed-tools: Edit WebFetch NotebookEdit Bash
model: sonnet
disable-model-invocation: false
user-invocable: true
safety:
  safety_valve: 3
  convergence: each phase artifact exists at the canonical path with the required sections
  dedup_metric: same-phase-template-missing=1
  user_interrupt: true
---
> [← Skills index](../../README.md)

## Overview

Self-contained binder that walks a single task through three mandatory
phases. The approval gate sits BEFORE phase decomposition, so a
rejection by the human reviewer does not waste the expensive Gate 4/5
decompose-emit work in `/dev-kit:plan`.

## What it does

1. **Research phase** → writes `.dev-kit/hand-off/<session>/research.md`
   from `templates/research.md`. The research engine is
   `lib/research_engine.py` (Phase 0-3 escalation + `verify()` +
   `enforce_citations()`); the rendering contract is
   `lib/analysis_core/runner.py:render_markdown`. No source edits.
2. **Proposal phase** → writes `docs/proposals/<main>/<sub>.yaml` and
   renders `docs/proposals/<main>/<sub>.html` via the
   `/dev-kit:proposal` skill (see `skills/proposal/SKILL.md`). The
   proposal is the human-review artifact. The hand-off shape lives in
   `templates/proposal.md`. Status is set to `ready-for-review`; the
   human is the only entity that may advance it to `accepted`.
3. **Plan phase** → STOPS at the approval gate. The binder writes
   `.dev-kit/hand-off/rpp→plan.md` listing the proposal HTML path and
   instructing the operator to (a) review the HTML, (b) flip the YAML
   `status:` to `accepted`, then (c) invoke `/dev-kit:plan <phase>`.
   The plan skill is **`disable-model-invocation: true`** (see
   `skills/plan/SKILL.md:13`); the binder cannot `Skill("plan", ...)`
   and the human re-invocation is the gate, not a workaround.

The build phase is OUT of this binder. After `/dev-kit:plan` emits
`PRD.md` + `phases/<name>/`, the operator invokes `/dev-kit:build` —
that step is independent of the binder.

## Why this skill exists

- Approval gate before Gate 4/5 decompose. Today's flow
  (`skills/plan/SKILL.md:280-360`) auto-renders the proposal AFTER the
  per-step JSON + step files are already emitted; a rejection throws
  away decomposition. This binder inverts the order.
- Each phase writes to disk so the next phase reads the artifact cold,
  not the prior turn's context window.
- The previous binder (`research-plan-build`) bundled build into the
  same slash, which compressed the approval gate to zero. Build is a
  different tool class (Edit/Bash) and a different review surface (per-
  step PRs); it lives in its own slash.

## Phases (cannot be skipped)

### Phase 1 — Research

- **Input**: 1-line idea + scope.
- **Action**: invoke `Skill("research", "<claim>")` then write
  `.dev-kit/hand-off/<session>/research.md` from `templates/research.md`.
- **Output contract**: every claim in the Conclusion cites
  `url` + `fetched_at` + `source_type`, OR is flagged `[UNCITED]` by
  `enforce_citations()`.
- **Gate to advance**: `annotated = enforce_citations(conclusion)` and
  `[UNCITED] not in annotated`. `enforce_citations()` returns annotated
  text, not a count; the absence of the marker in the returned
  Conclusion is the executable gate.
- **Refuse**: writing any source file under `src/`, `lib/`, `tests/`,
  `hooks/`, `skills/<other>/`, `commands/`, `tools/` during this phase.

### Phase 2 — Proposal

- **Input**: research.md from Phase 1.
- **Action**: author `docs/proposals/<main>/<sub>.yaml` from
  `templates/proposal.md` (sections derived from PRD gates 1-3
  shape: frame / validate / non-goals), then invoke
  `Skill("proposal", topic="<main>/<sub>")` to render the HTML.
- **Output contract**: YAML has `status: ready-for-review` and the
  required `before` / `after` / `pros` / `cons` / `limitations` /
  `sections` blocks (see `skills/proposal/SKILL.md` "Authoring a
  proposal"). HTML opens in any browser; defensive HTML escaping on
  every interpolated value (the proposal skill's contract).
- **Gate to advance**: YAML exists at the canonical path AND
  `<main>/<sub>.html` is on disk AND `status:` ∈ {`ready-for-review`,
  `accepted`}.
- **Refuse**: rendering when Phase 1's research.md is missing or the
  citation gate has not closed. No source-code writes.

### Phase 3 — Plan hand-off (gate)

- **Input**: rendered HTML at `docs/proposals/<main>/<sub>.html`.
- **Action**: WRITE-ONLY phase. Write
  `.dev-kit/hand-off/rpp→plan.md` with the proposal path, the YAML
  status field, and the explicit instruction:

  ```text
  1. Open docs/proposals/<main>/<sub>.html in a browser.
  2. If accepted: set status: accepted in
     docs/proposals/<main>/<sub>.yaml, then run
     /dev-kit:plan <phase>. (Plan will refuse to overwrite the
     existing proposal — that collision is the signal that the binder
     already rendered it.)
  3. If rejected: edit the YAML (status: rejected + rationale),
     iterate Phase 2 by re-invoking /dev-kit:research-proposal-plan.
  ```

- **Refuse**: any code, any build, any `Skill("plan", ...)` invocation.
  The plan skill is `disable-model-invocation: true`; the human
  re-invocation IS the gate.

## Composition with /dev-kit:build

`/dev-kit:build` invokes this binder when ANY of:

- Task spans more than 1 session (multi-day work).
- Task touches more than 3 files in its blast radius.
- User explicitly typed `/dev-kit:research-proposal-plan`.

Otherwise `/dev-kit:build` runs the direct `plan → build` path. This
is the "composed trigger" — both skills wire the same threshold so the
binder fires consistently regardless of entry point.

## Hook integration

| Hook | Mode | Why |
|---|---|---|
| bash-guard | ON | keeps the binder on `Read`/`Write`/`Skill` only |
| secret-scan | ON (PostToolUse) | research URLs may embed credentials |
| slop-detector | ON | enforces the citation contract |
| stop-verify | ON | refuses to stop before all phases are emitted or the gate is reached |

## Output

- `.dev-kit/hand-off/<session>/research.md` (Phase 1)
- `docs/proposals/<main>/<sub>.yaml` + `.html` (Phase 2)
- `.dev-kit/hand-off/rpp→plan.md` (Phase 3 hand-off)

## Test evidence

`tests/test_research_proposal_plan.py` validates:

- `skills/research-proposal-plan/SKILL.md` exists and declares `alpha: state`.
- `templates/research.md` and `templates/proposal.md` parse with the
  required section headers.
- `skills/build/SKILL.md` references `research-proposal-plan` under the
  composition section.
- The plan-skill `disable-model-invocation` invariant is documented in
  the binder body (the binder knows it cannot Skill-invoke plan).

Run: `python3 -m pytest tests/test_research_proposal_plan.py -v`.

## Next step

After the operator accepts the proposal HTML, `/dev-kit:plan <phase>`
runs the Gate 4/5 decompose + PRD emit. After that, `/dev-kit:build`
walks `phases/<name>/step<N>.md` end-to-end. The binder's job is done
once the proposal HTML is rendered and the hand-off is written; the
approval gate is a human gate, not an automated one.
