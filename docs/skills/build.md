> [← Skills index](README.md) · [Project README](../../README.md)

# `build`

**Category:** `build` · **Alpha:** `state` · **Invocation:** `/dev-kit:build` (human-invoked)

`build` is the execution engine of the harness: it takes the step files a prior `/dev-kit:plan` produced and actually runs them, one isolated sub-agent per step, so that no single sprawling session has to hold the whole phase's state at once. It exists as its own skill because running steps safely requires real process isolation (per-step git worktrees), a hard concurrency policy, and persisted real subprocess evidence — none of which a plain prompt can guarantee on its own.

## When to use it

- The user types `/dev-kit:build`.
- Planning and design are already done — `PRD.md` and `phases/<name>/` exist.
- `/dev-kit:ci-setup` has already written `.dev-kit/ci-config.json` — this is a hard requirement, not a suggestion.

## How it works

`build` refuses to start if `.dev-kit/ci-config.json` is absent, telling the user to run `/dev-kit:ci-setup` (or `--force` to refresh stale templates) first. There is no version comparison gate — only presence of the marker file matters.

Once the pre-flight gate passes, `lib/execute.py:main` parses arguments and branches on `--parallel N`:

- `--parallel 0` (default) runs `_run_sequential`.
- `--parallel 1` runs `_run_parallel` with a single slot, which is effectively sequential.
- `--parallel N > 1` refuses with exit code 2 unless `--allow-parallel-build` is also set, because two concurrent `claude -p` steps can collide on shared files invisibly during the run and the collision only surfaces at merge time. The override exists for the narrow case where the steps' declared `writes:` are disjoint and no step consumes another's output.

`build` reads `phases/<name>/index.json`, which must contain a `worktree: "<branch-base>"` field emitted by `/dev-kit:plan` (e.g. `plan/plugin-harness-v3-0-mvp`). From that it derives the per-step branch (`<branch-base>-step<N>`) and worktree path (`<root>/.worktrees/<phase>-step<N>`); if the field is absent it falls back to `feat/<phase>` as a defense-in-depth measure, not as the intended contract.

Steps whose `status` is in `SKIPPABLE_STATUSES` (`completed`, `unimplemented`) are skipped. The runner bails with exit code 2 if any step has `status == "blocked"` — there is no implicit resume. The `--skip-blocked` override lets the runner continue past blocked steps, running only `pending | error | in_progress` ones; any steps skipped this way are listed in `.dev-kit/hand-off/build→review.md` after the run.

For each resumable step, `build`:

1. Runs `git worktree add -B <branch> <wt> origin/main` (MUST-38 — per-step worktree isolation).
2. Reads `step<N>.md` as the preamble and appends the acceptance-criteria guard plus a "3-cycle self-fix max" instruction (MUST-37).
3. Marks the step `in_progress` via `update_step_status`, which stamps `started_at`.
4. Invokes `subprocess.run(["claude", "-p", "--workdir", str(wt), full_prompt], capture_output=True, text=True)` — exactly one sub-agent per step (MUST-36).
5. Writes `phases/<name>/step<N>-output.json` with the real `exit_code`, `stdout`, `stderr`, and `duration_seconds` — never a stubbed `0.01` or "stub completed" value. This write targets the per-step worktree (`wt`), not the orchestrator's root checkout: the chore commit below runs `git add -A` with `cwd=wt`, so a file written under `root/phases/...` would never be staged there.
6. On non-zero exit: marks the step `error`, stashes the `error_message`, and returns non-zero with no commits made.
7. On success: makes two commits on the per-step branch — `feat({phase}): step {N}[ — <name>]` then `chore({phase}): step {N} output` — and pushes the per-step branch to `origin` if `--push` was set.

The status state machine lives in `lib/execute.py` (`VALID_STATUSES`, `SKIPPABLE_STATUSES`, `RESUMABLE_STATUSES`, and the `--skip-blocked` override) as the single source of truth: `/dev-kit:plan` emits `pending`, and `build` drives the step through `in_progress` / `completed` / `error` / `blocked`.

During the build stage, the hook matrix is: `tdd-guard` ON when `methodology=tdd`, `bash-guard` ON, `secret-scan` ON (PostToolUse), `slop-detector` ON, `stop-verify` ON.

## Usage

```bash
/dev-kit:build [--parallel N] [--allow-parallel-build] [--skip-blocked] [--push]
```

| Flag | Effect |
|---|---|
| `--parallel 0` | Sequential execution (default). |
| `--parallel 1` | Parallel runner with one slot — effectively sequential. |
| `--parallel N > 1` | Refuses with exit 2 unless paired with `--allow-parallel-build`. |
| `--allow-parallel-build` | Escape hatch permitting `--parallel N > 1` when steps' `writes:` are disjoint and none consumes another's output. |
| `--skip-blocked` | Continue past `blocked` steps, running only `pending \| error \| in_progress`; skipped steps are recorded in the hand-off file. |
| `--push` | Push the per-step branch to `origin` after a successful step. |

## Output

- `phases/<name>/step<N>-output.json` per step: `{exit_code, stdout, stderr, duration_seconds, timestamp}`, all real subprocess output.
- `.dev-kit/hand-off/build→review.md`, written automatically.
- A 2-commit protocol per successful step on its per-step branch: `feat({phase}): step {N} — {name}` and `chore({phase}): step {N} output`.

Test evidence: 29 tests in `tests/test_execute.py` cover runner behavior (skippable-status skipping, blocked returning exit 2, pending steps creating a worktree and invoking `claude` with the preamble + acceptance-criteria guard, the 2-commit protocol, no commits on failure, push gated on `--push`), plus 10 state-machine tests for `update_step_status` (in-progress idempotency, duration rounding, reset semantics).

## Long-running session templates

When a build phase is expected to span more than one Claude Code session — typical signal: step count >= 5, or the user explicitly says "this is a multi-day effort" — `build` copies the four-file template bundle from `templates/` into the per-step worktree at `<worktree>/templates/` before the first step starts (idempotent — `cp -u` refreshes only stale files). The bundle is the cold-start fix: without it, every new session spends 30-60 min re-discovering "what did the last session do?".

| Template | Purpose |
|---|---|
| `templates/init.sh` | Bootstrap: verify env, read feature list, pick next failing feature, run baseline test. Idempotent — re-run every session open. |
| `templates/feature_list.json` | JSON array of `{id, description, status, depends_on, test_path}`. Single source of truth for "what's left". |
| `templates/progress.log.md` | Append-only per-session log (Goal / Work done / Tests status / Blockers / Next session should / Commits). |
| `templates/session_handoff.md` | Resume-from-cold-context checklist; read FIRST at session open, before any code change. |

Operational contract: each step's preamble (`step<N>.md`) must include a one-line reminder to append to `progress.log.md` before commit and to re-run `init.sh` at session open. Steps driven by `codex exec` honor the same contract — the runner copies the templates into the worktree before spawning the agent so the templates are part of the agent's working tree.

Failure mode: if `init.sh` exits 3 (`"no failing feature remaining"`) at the start of a step, the build has effectively finished — bail to `/dev-kit:review` instead of forcing another step.

Template behavior is validated by `tests/test_long_running_templates.py` (structure + behavioral execution in a tmpdir covering dry-run / missing-list / all-passing exit codes).

## Related

- [build-tdd](build-tdd.md) — the Red-Green-Refactor sub-skill active during build when `methodology=tdd`.
- [build-debug](build-debug.md) — invoked when a step's sub-agent needs systematic debugging.
- [build-verify](build-verify.md) — enforces evidence before a "done" declaration.
- `/dev-kit:review` and `/dev-kit:security`, then `/dev-kit:ship` — the next stages after `build` completes.
- `lib/execute.py` — the harness-runner engine this skill wraps.
- `tests/test_execute.py` — the 29 + 10 tests referenced above.

---
*Source: [`skills/build/SKILL.md`](../../skills/build/SKILL.md)*
