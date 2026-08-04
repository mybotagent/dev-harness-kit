> [← Skills index](README.md) · [Project README](../../README.md)

# `research-plan-build`

**Category:** `build` · **Alpha:** `state` · **Invocation:** `/dev-kit:research-plan-build <idea>` (human-invoked)

`research-plan-build` is the self-contained 3-phase binder (research → plan → implement). It exists because `/dev-kit:plan` gates on research evidence but the user asked to inline the full pipeline in one slash, and `/dev-kit:build` runs the implementation phase after the plan is written. No phase may be skipped; the safety_valve gate refuses to advance when the prior phase's artifact is missing or incomplete.

## When to use it

- The user types `/dev-kit:research-plan-build <idea>`.
- `/dev-kit:plan` gates on research evidence AND the user asked to inline the 3-phase pipeline.
- The task spans more than 1 session (multi-day work) OR touches more than 3 files in its blast radius (composed trigger wired into `/dev-kit:build`).
- The user explicitly wants the non-skippable 3-phase pipeline (research → plan → implement) bound to one slash.

## How it works

The binder runs three mandatory phases, each phase a separate gate:

1. **Phase 1 — Research.** Reads `lib/research_engine.py` + `lib/analysis_core/runner.py`, then writes `.dev-kit/hand-off/<session>/research.md` from `templates/research.md`. The research engine runs the Phase 0-3 escalation (cache / direct / multi / human) and `enforce_citations()`. Every claim in the Conclusion section must cite `url` + `fetched_at` + `source_type`, OR be flagged `[UNCITED]`. The gate to advance is `annotated = enforce_citations(conclusion)` and `[UNCITED] not in annotated` (the function returns annotated text, not a count). The phase refuses to write any source file under `src/`, `lib/`, `tests/`, `hooks/`, `skills/<other>/`, `commands/`, `tools/`.
2. **Phase 2 — Plan.** Reads `templates/plan.md`, writes `plan.md` at the plan-emit location (`docs/proposals/<main>/<sub>/plan.md` or the phase-local path consumed by `/dev-kit:build`). The Steps table has ≥3 rows; each row has Owner, Acceptance, Dependencies; each `### Step detail` block has the `verification:` field filled in. Gate to advance: at least 3 step rows AND every detail block has `verification:`.
3. **Phase 3 — Implement.** Hands off to `/dev-kit:build` (or `/dev-kit:build-tdd` when methodology=tdd). The build runner reads `phases/<name>/index.json` (NOT `plan.md`); `plan.md` is the reviewer-facing companion the binder produced. ONE PLAN STEP per build run; the runner emits the canonical 2-commit protocol per step (`feat(...)` then `chore(...)`) — see `lib/execute.py:_run_sequential`. Bundling multiple plan steps into a single build run is the runner's contract violation.

### Composition with `/dev-kit:build`

`/dev-kit:build` invokes this binder when ANY of:

- Task spans more than 1 session (multi-day work).
- Task touches more than 3 files in its blast radius.
- User explicitly typed `/dev-kit:research-plan-build`.

Otherwise `/dev-kit:build` runs the plan-only path (`/dev-kit:plan` → build). This is the "composed trigger" — both skills wire the same threshold so the binder fires consistently regardless of entry point. See `skills/build/SKILL.md` §"Composition with /dev-kit:research-plan-build" for the trigger wiring.

## Usage

```bash
/dev-kit:research-plan-build <idea> [--scope "<scope>"]
```

| Argument | Effect |
|---|---|
| `<idea>` | 1-line task description (required). |
| `--scope "<scope>"` | Optional scope qualifier; passed verbatim to the research engine. |

There are no version-gated preconditions — the binder is self-referential.

## Output

- **Phase 1**: `.dev-kit/hand-off/<session>/research.md` (with cited Conclusion).
- **Phase 2**: `plan.md` at the plan-emit location (with Steps table + Step detail blocks).
- **Phase 3**: per-step branches + 2-commit protocol per row of the Steps table (delegated to `/dev-kit:build`); the step number is embedded in the commit subject (`feat({phase}): step {N}[ — <name>]` then `chore({phase}): step {N} output`). The runner does NOT inject commit bodies — it runs `git commit -m <subject>` only (`lib/execute.py:_commit_step`).

Failure exit codes surface as errors from any phase that fails its gate (`[UNCITED]` present in annotated Conclusion, fewer than 3 step rows, missing `verification:` fields, or a build-runner contract violation). Note that `phases/<name>/step<N>-output.json` is written into the per-step worktree BEFORE the first `feat(...)` commit, so the feat commit typically captures both the implementation files and the output JSON; the `chore(...)` commit is a no-op when there is nothing new to stage (`lib/execute.py:_commit_step`).

## Hook integration

| Hook | Mode | Why |
|---|---|---|
| `tdd-guard` | ON (when methodology=tdd) | blocks production code without a failing test |
| `bash-guard` | ON | keeps the binder on `Read`/`Write` only |
| `secret-scan` | ON (PostToolUse) | research URLs may embed credentials |
| `slop-detector` | ON | enforces the citation contract |
| `stop-verify` | ON | refuses to stop before all 3 phases are emitted |

## Test evidence

`tests/test_research_plan_build.py` validates:

- `skills/research-plan-build/SKILL.md` exists and declares `alpha: state`.
- `templates/research.md` and `templates/plan.md` parse as markdown with the required section headers (Question, Evidence, Cross-validation, Conclusion for research; Goal, Steps, Commit protocol, Risks for plan).
- `skills/build/SKILL.md` references `research-plan-build` under the composition section AND declares `Skill` in its `allowed-tools` (so `Skill("research-plan-build", <idea>)` is permitted).
- The research-plan-build skill body uses the executable citation gate (`"[UNCITED]" not in enforce_citations(conclusion)`), not a numeric threshold.
- Neither the skill nor `templates/plan.md` claims a commit body is emitted (runner uses `git commit -m <subject>` only).

Run: `python3 -m pytest tests/test_research_plan_build.py -v`.

## Related

- [build](build.md) — the implement-phase runner the binder hands off to.
- [plan](plan.md) — emits `phases/<name>/index.json` + `step<N>.md` that the build runner consumes.
- [research](research.md) — Phase 0-3 escalation engine shared with the research phase.
- `lib/research_engine.py` — research engine (Phase 0-3 + `verify()` + `enforce_citations()`).
- `lib/analysis_core/runner.py:render_markdown` — research rendering contract.
- `lib/execute.py:_run_sequential` — 2-commit protocol per step.
- `lib/execute.py:_commit_step` — `git add -A` + conditional `git commit -m <subject>` (no body, no `--allow-empty`).
- `lib/execute.py:_step_post_collect` — writes `step<N>-output.json` to the per-step worktree BEFORE the first commit.

---
*Source: [`skills/research-plan-build/SKILL.md`](../../skills/research-plan-build/SKILL.md)*
