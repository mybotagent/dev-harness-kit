---
name: build
category: build
description: 0-arg. Per-step sub-agent delegation + self-fix loop (MUST-36~38). Uses harness-runner engine. TDD + verify + debug integrated.
alpha: state
when_to_use: |
  - User types /dev-kit:build
  - After plan+design (PRD.md + phases/<name>/ exist)
  - After /dev-kit:ci-setup has written .dev-kit/ci-config.json (REQUIRED — refuse if marker missing)
allowed-tools: Read Write Bash Glob Grep Agent Skill
disallowed-tools: WebFetch
model: opus
disable-model-invocation: false
---
> [← Skills index](../../README.md)

## What it does

Executes `phases/<name>/step{1..N}.md` end-to-end by spawning one non-interactive agent per step inside an isolated per-step git worktree, persisting real `step<N>-output.json` (subprocess exit code, stdout, stderr, measured duration), and emitting the 2-commit protocol on the per-step branch. Claude is the default; set `DEV_KIT_BUILD_AGENT=codex` to use `codex exec`. Every step has a bounded timeout from `DEV_KIT_AGENT_TIMEOUT_SECONDS` (default 1 hour, max 24 hours). Honors MUST-36 (one sub-agent per step), MUST-37 (3-cycle self-fix guard), MUST-38 (per-step worktree isolation).

## Optional Linear preflight

At the start of a new build task, invoke `/dev-kit:linear` once when Linear is
enabled or available. Continue normally on `LINEAR_SKIP` or an implicit
`LINEAR_ERROR`; do not invoke it per step, retry, or sub-agent. See
`skills/linear/SKILL.md` for the reconciliation contract.

## Pre-flight gate

Refuses to start if `.dev-kit/ci-config.json` is absent. Run `/dev-kit:ci-setup` (or `/dev-kit:ci-setup --force` to refresh stale templates) first. No version comparison — presence of the marker is the only precondition; dev-kit does not gate consumer builds on a plugin-version floor.

## Pre-flight valuation gate (Phase 4, issue #373)

> **Removed in #463.** The build stage's hard auto-gate that read the
> valuation verdict and refused non-PROCEED verdicts was tied to the LCS
> substrate that backed the URI. The LCS substrate is gone; the
> auto-gate went with it. Operators run `/dev-kit:valuate` explicitly
> before invoking `/dev-kit:build`; a non-PROCEED verdict is the
> operator's signal to halt, not a hard block.

The verdict envelope (when it exists) is at
`.dev-kit/valuations/<plan-id>.json`. If `/dev-kit:valuate` was run,
the build proceeds and the verdict is operator context; if the verdict
is `kill` or unresolved `hold`, the operator should not have invoked
`build`. There is no auto-gate, no `--skip-valuation` flag, and no exit
code based on the verdict.

## Composition with /dev-kit:research-plan-build

`/dev-kit:research-plan-build` is the 3-phase binder that wraps research
+ plan + implement into one non-skippable pipeline. The trigger fires
when ANY of:

- Task spans more than 1 session (multi-day work).
- Task touches more than 3 files in its blast radius.
- User explicitly typed `/dev-kit:research-plan-build <idea>`.

When the trigger fires, hand off to `Skill("research-plan-build", <idea>)`
BEFORE running `/dev-kit:plan`. The binder writes `research.md` + `plan.md`
in `.dev-kit/hand-off/<session>/`, then `/dev-kit:plan` emits the
canonical `phases/<name>/index.json` + `step<N>.md` artifacts. The
build runner reads the phases artifacts (NOT `plan.md`); `plan.md` is
the reviewer-facing companion the binder produced.

For single-session work (<=3 files), `/dev-kit:build` runs the direct
`plan -> build` path - no binder. The threshold lives here so a user who
calls `/dev-kit:build` for a multi-file task still gets the 3-phase
pipeline.

See `skills/research-plan-build/SKILL.md` for the per-phase contract.

## Behavior

1. `lib/execute.py:main` parses args; branches on `--parallel N`:
   - `--parallel 0` → `_run_sequential` (default).
   - `--parallel 1` → `_run_parallel` with 1 slot (effectively sequential).
   - `--parallel N > 1` → refuses (exit 2) unless `--allow-parallel-build` is set.
     Two concurrent `claude -p` steps WILL collide on shared files; the collision
     is invisible during the run and surfaces only at merge time. The override
     flag is an escape hatch for the rare case where declared `writes:` are
     disjoint AND no step consumes another's output.
2. Read `phases/<name>/index.json` (must contain `worktree: "<branch-base>"`; emitted by `/dev-kit:plan` as `<prefix>-<phase>`, e.g. `plan/plugin-harness-v3-0-mvp`); derive per-step branch = `<branch-base>-step<N>` and worktree path = `<root>/.worktrees/<phase>-step<N>`. Falls back to `feat/<phase>` when the field is absent (defense-in-depth, not the contract).
3. Skip entries where `status` ∈ `SKIPPABLE_STATUSES` (`completed`, `unimplemented`).
4. Bail with exit 2 if any step has `status == "blocked"` (no implicit resume).
   Override: `--skip-blocked` lets the runner continue past `blocked` steps, running only `pending | error | in_progress`. Skipped blocked steps are listed in `.dev-kit/hand-off/build→review.md` after the run.
5. For each RESUMABLE step:
   - `git worktree add -B <branch> <wt> origin/main` (MUST-38).
   - Read `step<N>.md` as preamble; append AC guard + `3-cycle self-fix max`.
   - `update_step_status(... status="in_progress")` (stamps `started_at`).
   - Spawn the selected agent command (`claude -p` or `codex exec`) with a bounded timeout (MUST-36).
   - Write `phases/<name>/step<N>-output.json` with REAL `exit_code`, `stdout`, `stderr`, `duration_seconds` (no fake `0.01` or `stub completed`).
   - On non-zero exit: `status="error"`, stash `error_message`, return non-zero — no commits.
   - On success: 2 commits on the per-step branch — `feat({phase}): step {N}[ — <name>]` then `chore({phase}): step {N} output`. Push the per-step branch to `origin` if `--push`.

## Status state machine (lib/execute.py)

SSOT: `lib/execute.py:VALID_STATUSES` (+ `SKIPPABLE_STATUSES`, `RESUMABLE_STATUSES`,
`--skip-blocked` override). The plan/build contract: plan emits `pending`,
build drives `in_progress`/`completed`/`error`/`blocked` per the source
constants.

## Hook integration (Stage B)

| Hook | Mode |
|---|---|
| tdd-guard | ON (when methodology=tdd) |
| bash-guard | ON |
| secret-scan | ON (PostToolUse) |
| slop-detector | ON |
| stop-verify | ON |

## Output

- `phases/<name>/step<N>-output.json` per step with `{exit_code, stdout, stderr, duration_seconds, timestamp}` — real subprocess output.
- `.dev-kit/hand-off/build→review.md` auto.
- 2-commit protocol on per-step branch: `feat({phase}): step {N} — {name}` + `chore({phase}): step {N} output`.

## Test evidence

29 tests in `tests/test_execute.py` covering runner behavior: skippable status skips runner, blocked returns 2, pending step creates worktree + invokes claude with preamble+AC, 2-commit protocol per step, no commits on failure, push gated on `--push`. Plus 10 state-machine tests for `update_step_status` (in_progress idempotency, duration rounding, reset semantics).

## Next step

`/dev-kit:review` (3-dim) + `/dev-kit:security` (10-dim) then `/dev-kit:ship`.
