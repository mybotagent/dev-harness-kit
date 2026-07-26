---
name: build
category: build
description: 0-arg. Per-step sub-agent delegation + self-fix loop (MUST-36~38). Uses harness-runner engine. TDD + verify + debug integrated.
alpha: state
when_to_use: |
  - User types /dev-kit:build
  - After plan+design (PRD.md + phases/<name>/ exist)
  - After /dev-kit:ci-setup has written .dev-kit/ci-config.json (REQUIRED — refuse if marker missing)
allowed-tools: Read Write Bash Glob Grep Agent
disallowed-tools: WebFetch
model: opus
disable-model-invocation: false
---
> [← Skills index](../../README.md)

## What it does

Executes `phases/<name>/step{1..N}.md` end-to-end by spawning one `claude -p` sub-agent per step inside an isolated per-step git worktree, persisting real `step<N>-output.json` (subprocess exit code, stdout, stderr, measured duration), and emitting the 2-commit protocol on the per-step branch. Honors MUST-36 (one sub-agent per step), MUST-37 (3-cycle self-fix guard), MUST-38 (per-step worktree isolation).

## Pre-flight gate

Refuses to start if `.dev-kit/ci-config.json` is absent. Run `/dev-kit:ci-setup` (or `/dev-kit:ci-setup --force` to refresh stale templates) first. No version comparison — presence of the marker is the only precondition; dev-kit does not gate consumer builds on a plugin-version floor.

## Pre-flight valuation gate (Phase 4, issue #373)

Before launching any per-step sub-agent, build reads the latest verdict
for the current plan from `lcs://valuations/<plan-id>` via
`bin/dev-kit-lcs.py --get`. The verdict comes from
`/dev-kit:valuate` (`lib/valuation_engine.py:decide()`).

| Verdict | Reaction |
|---|---|
| `proceed` | Build proceeds normally |
| `revise` | Build refused; print `blocking_findings`; exit 2 |
| `hold` | Build refused; "re-evaluate later" message; exit 2 |
| `kill` | Build refused; archive as no-go; exit 2 |

The gate is fail-closed: a missing or unreadable
`lcs://valuations/<plan-id>` is treated as "no verdict" and the build is
refused with exit 2 unless `--skip-valuation` is passed. The flag is the
permanent backward-compat escape hatch and is not deprecated — use it
when the user explicitly waives the gate (e.g. legacy plans without a
valuation record).

```bash
# Default (gate enforced):
python3 bin/dev-kit-lcs.py --get lcs://valuations/<plan-id>

# Bypass (legacy plans):
/dev-kit:build --skip-valuation
```

The gate is deterministic on identical input — the engine is a pure
function over the 6-axis rubric scores, so the build stage reads the
verdict exactly as `/dev-kit:valuate` wrote it. This is the L6 contract:
the model cannot talk its way past `kill` or `hold`.

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
   - `subprocess.run(["claude", "-p", "--workdir", str(wt), full_prompt], capture_output=True, text=True)` (MUST-36).
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
