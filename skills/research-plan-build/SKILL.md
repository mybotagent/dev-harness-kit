---
name: research-plan-build
category: build
description: 3-phase binder (research → plan → implement). Enforces non-skippable phases; cites lib/analysis_core/ for the research half; emits templates/research.md and templates/plan.md.
alpha: state
when_to_use: |
  - User types /dev-kit:research-plan-build <idea>
  - /dev-kit:plan gates on research evidence and the user asked to inline the 3-phase pipeline
  - Task spans >1 session OR touches >3 files (composed trigger from /dev-kit:build)
allowed-tools: Read Write Glob Grep
disallowed-tools: Edit WebFetch NotebookEdit Bash
model: opus
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
phases. No phase may be skipped; the safety_valve gate refuses to
proceed when the predecessor artifact is missing.

## What it does

1. **Research phase** → writes `.dev-kit/hand-off/<session>/research.md`
   from `templates/research.md`. The research engine is `lib/research_engine.py`
   (Phase 0-3 escalation + `verify()` + `enforce_citations()`); the
   rendering contract is `lib/analysis_core/runner.py:render_markdown`.
   Not code. No source edits, no test edits.
2. **Plan phase** → writes `plan.md` from `templates/plan.md` AS THE
   HUMAN-READABLE COMPANION to `phases/<name>/index.json` +
   `step<N>.md`. The plan skill (`/dev-kit:plan`) is what emits the
   `phases/<name>/` artifacts the build runner consumes; this binder
   emits `plan.md` next to them so a reviewer can read the plan in one
   place. Each row in the Steps table has Owner, Acceptance,
   Dependencies. Reviewable before any code is written.
3. **Implement phase** → hands off to `/dev-kit:build` (or
   `/dev-kit:build-tdd` when methodology=tdd). The build runner reads
   `phases/<name>/index.json` (NOT `plan.md`); `plan.md` is the
   reviewer artifact. The build runner enforces the 2-commit protocol
   per step (`lib/execute.py:_run_sequential`): one `feat(...)`
   commit + one `chore(...)` commit per successful step. Commit
   subjects are `feat({phase}): step {N}[ — <name>]` and
   `chore({phase}): step {N} output`. The runner does NOT inject a commit
   body. Step numbering lives in the subject.

## Why this skill exists

- Plan is reviewable before code is written (Gate-5 emit vs Gate-4 decompose).
- Each phase writes to disk so the next phase can read the artifact
  cold, instead of carrying the prior turn's context window into the
  next phase.
- Composes with the existing research half
  (`lib/research_engine.py` + `lib/analysis_core/`) which is already in
  production; this skill is the binder that ties research and plan
  phases to the build runner.

## Phases (cannot be skipped)

The three phases are mandatory and sequential. The skill refuses to
advance when the prior phase's artifact is missing or incomplete.

### Phase 1 — Research

- **Input**: 1-line idea + scope.
- **Action**: read `lib/research_engine.py` + `lib/analysis_core/runner.py`,
  then write `.dev-kit/hand-off/<session>/research.md` from
  `templates/research.md`.
- **Output contract**: every claim in the Conclusion cites
  `url` + `fetched_at` + `source_type`, OR is flagged `[UNCITED]` by
  `enforce_citations()`.
- **Gate to advance**: `annotated = enforce_citations(conclusion)` and
  `[UNCITED] not in annotated`. `enforce_citations()` returns annotated
  text, not a count; the absence of the marker in the returned
  Conclusion is the executable gate.
- **Refuse**: writing any source file under `src/`, `lib/`, `tests/`,
  `hooks/`, `skills/<other>/`, `commands/`, `tools/` during this phase.

### Phase 2 — Plan

- **Input**: research.md from Phase 1.
- **Action**: read `templates/plan.md`, write `plan.md` at the
  plan-emit location (`docs/proposals/<main>/<sub>/plan.md` or the
  phase-local path consumed by `/dev-kit:build`).
- **Output contract**: Steps table has ≥3 rows; each row has Owner,
  Acceptance, Dependencies; each `### Step detail` block has the
  `verification:` field.
- **Gate to advance**: at least 3 step rows AND every detail block has
  `verification:` filled in.
- **Refuse**: writing any source file or running the build runner.

### Phase 3 — Implement

- **Input**: plan.md from Phase 2.
- **Action**: hand off to `/dev-kit:build` (or `/dev-kit:build-tdd`).
  The build runner walks each plan step, spawning one sub-agent per
  step inside an isolated per-step worktree, with the 2-commit
  protocol per step.
- **Output contract**: ONE PLAN STEP per build run. The build runner
  emits the canonical 2-commit protocol per step (`feat(...)` then
  `chore(...)`) — see `lib/execute.py:_run_sequential`. The step
  number lives in the commit subject; the runner does NOT inject a commit
  body (no Acceptance/Verification/Files bullet block). The cross-walk
  anchor between commit subject and `plan.md` is the step number, not a
  body. Multiple plan steps in one commit bundle is the runner's
  contract violation, not the binder's.
- **Refuse**: bundling multiple plan steps into a single build run.

## Composition with /dev-kit:build

`/dev-kit:build` invokes this binder when ANY of:

- Task spans more than 1 session (multi-day work).
- Task touches more than 3 files in its blast radius.
- User explicitly typed `/dev-kit:research-plan-build`.

Otherwise `/dev-kit:build` runs the plan-only path (`/dev-kit:plan` →
build). This is the "composed trigger" — both skills wire the same
threshold so the binder fires consistently regardless of entry point.

## Hook integration

| Hook | Mode | Why |
|---|---|---|
| tdd-guard | ON (when methodology=tdd) | blocks production code without a failing test |
| bash-guard | ON | keeps the binder on `Read`/`Write` only |
| secret-scan | ON (PostToolUse) | research URLs may embed credentials |
| slop-detector | ON | enforces the citation contract |
| stop-verify | ON | refuses to stop before all 3 phases are emitted |

## Output

- `.dev-kit/hand-off/<session>/research.md` (Phase 1)
- `plan.md` at the plan-emit location (Phase 2)
- Per-step branches + 2-commit protocol per row of the Steps table
  (Phase 3, delegated to `/dev-kit:build`)

## Test evidence

`tests/test_research_plan_build.py` validates:

- `skills/research-plan-build/SKILL.md` exists and declares `alpha: state`.
- `templates/research.md` and `templates/plan.md` parse as markdown with
  the required section headers (Question, Evidence, Cross-validation,
  Conclusion for research; Goal, Steps, Commit protocol, Risks for plan).
- `skills/build/SKILL.md` references `research-plan-build` under the
  composition section.

Run: `python3 -m pytest tests/test_research_plan_build.py -v`.

## Next step

`/dev-kit:build` (or `/dev-kit:build-tdd`) for the implement phase. The
binder's job is done once the build runner emits the per-step commits
and the plan.md Steps table is fully ticked off.
