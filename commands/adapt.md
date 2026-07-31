---
name: adapt
category: build
description: Mid-build plan/spec amendment. Pauses the current step, diffs PRD.md + step file against actual output, proposes a minimal patch, writes it on user approval, and resumes the per-step harness runner (lib/execute.py).
when_to_use: |
  - User types /dev-kit:adapt
  - A build step is in_progress and the plan/spec is discovered to be wrong
  - User wants the build to continue with amended artifacts, not restart from scratch
alpha: state
---

## Invocation

Arguments: `$ARGUMENTS` — pass any focused scope (step number, artifact name, or short rationale) so the diff surfaces the right contradiction.

## What it does

Pauses an in-flight per-step harness runner (`lib/execute.py`) step, surfaces the contradiction between the planned artifact (`PRD.md` and/or `phases/<name>/step<N>.md`) and the actual step output (`phases/<name>/step<N>-output.json`), proposes a minimal patch scoped to the discovered gap, writes the patch only on explicit user approval, then resumes the build from the next unblocked step. Designed to be invoked at most once per step; consecutive invokes on the same step are a red flag that the plan itself is unstable.

## Pre-flight

- A `phases/<name>/step<N>-output.json` must exist with `status` ∈ `{in_progress, error}`.
- The skill never edits `step<N>-output.json` itself — the per-step harness runner (`lib/execute.py`) is the sole writer of that file (MUST-36).
- If no build is in flight, refuse and point the user to `/dev-kit:plan` for pre-build revision.

## Cycle

```
[1/4] PAUSE    → mark phases/<name>/index.json step status = "blocked" (reason: adapt)
[2/4] DIFF     → quoted mismatch between plan + actual output
                  (PRD AC vs exit_code; step AC vs stdout; PRD vs step boundary)
       ↓
[3/4] PROPOSE  → minimal patch (one bullet per file, ≤ 3 lines of new content)
                  (must NOT introduce new AC — out-of-scope work is a /dev-kit:plan job)
       ↓
[4/4] APPLY    → on explicit user approval:
                    - write PRD.md and/or step<N>.md
                    - resume /dev-kit:build (the per-step harness runner flips blocked → pending → in_progress)
```

## Rules (no exceptions)

- MUST-L5: one proposed patch per invocation. No "while I'm here" edits. If two gaps exist, the second waits for a second `adapt` call.
- MUST-L3: completion requires the patch written + the next build step started with a quoted exit code.
- The command does NOT modify `step<N>-output.json`. The per-step harness runner (`lib/execute.py`) owns that file.
- The patch is MINIMAL: the smallest change that resolves the surfaced contradiction. No refactors, no opportunistic cleanups, no scope creep.

## Hook integration

| Hook | Mode |
|---|---|
| bash-guard | ON |
| secret-scan | ON (PostToolUse) |
| slop-detector | ON — refuse vague patches ("improve the design", "make it cleaner") |
| stop-verify | ON — quoted next-step exit code required before declaring done |

## Output

- Patched `PRD.md` and/or `phases/<name>/step<N>.md` (one or both, never zero).
- Updated `phases/<name>/index.json` flipping the step from `blocked` back to `pending` (the per-step harness runner picks it up).
- `.dev-kit/hand-off/adapt→build.md` quoting the diff, the patch, and the user approval line.

## Red flags

| Thought | Reality |
|---|---|
| "While I'm here, let me also fix X" | Out of scope. Run another command. |
| "The plan was wrong from the start" | That is a `/dev-kit:plan` revision, not an adapt. |
| "I'll just rewrite the whole step" | L5 violation. Minimal patch only. |
| "Adapt three times in a row" | Stop. The plan is too unstable — back to `/dev-kit:plan`. |

## Next step

Hand off to `/dev-kit:build` (resumes from the next unblocked step). If the same step needs a second adapt, the user should consider `/dev-kit:plan` instead.
