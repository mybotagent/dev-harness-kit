---
name: feat-remove
category: build
description: Safely remove a feature. Sweeps the call graph, flags dependents, produces a deletion report, and verifies the full suite stays green after deletion.
alpha: state
when_to_use: |
  - User types /dev-kit:feat-remove <feature>
  - Feature is deprecated, replaced, or out of scope
  - User wants confidence no orphan callers, tests, or docs remain
allowed-tools: Read Write Bash Glob Grep
disallowed-tools: Edit WebFetch
model: opus
disable-model-invocation: false
user-invocable: true
---

## What it does

Removes one named feature end-to-end: discovers every reference (callers, tests, docs, plan artifacts), produces a deletion report, blocks on dependent features that the user has not yet acked, and finally verifies the full suite passes after deletion. The skill never deletes files itself — it emits the commands and waits for the user to run them, mirroring the `build-debug` write-prevention pattern.

## Pre-flight

- `<feature>` arg required. Refuse empty.
- Feature must be locatable in the codebase (impl + at least one test, OR explicit user override).
- If dependents exist, the skill lists them and refuses to proceed until the user acks the cascade.

## 4 phases

```
[1/4] SWEEP       → grep + glob for: impl paths, test paths, doc paths, plan artifacts
       (must return 0 matches after deletion — orphan check)
       ↓
[2/4] DEPENDENTS  → list every other feature that imports / calls / extends <feature>
       (block if any exist; user must ack or reroute to /dev-kit:plan)
       ↓
[3/4] REPORT      → write .dev-kit/hand-off/feat-remove-report.md
       (paths to delete + exact rm / git rm commands for the user to run)
       ↓
[4/4] VERIFY      → after user runs the deletes, run the full suite
       (must stay green; if red, /dev-kit:build-debug the regression)
```

## Rules (no exceptions)

- MUST-L3: completion requires a quoted post-delete full-suite run.
- MUST-L4: no "I'll just leave a stub for the import" — every reference is either deleted or migrated, not stubbed.
- Dependents block by default. No silent cascade.
- The skill never calls `rm` or `git rm` itself. The user runs the commands from the report.

## Hook integration

| Hook | Mode |
|---|---|
| bash-guard | ON — blocks destructive `rm -rf` etc. anyway; the skill still surfaces commands for the user |
| secret-scan | ON (PostToolUse) |
| slop-detector | ON |
| stop-verify | ON — quoted full-suite green required before declaring done |

## Output

- `.dev-kit/hand-off/feat-remove-report.md` listing every path to delete, the exact commands, and the dependents list.
- After the user runs the deletes: a quoted full-suite run (test count + exit code + duration).
- Updated `phases/<name>/index.json` marking the step `unimplemented` (the phase is closed, not deleted — git history is the audit trail).

## Red flags

| Thought | Reality |
|---|---|
| "Just delete the main file, the rest is noise" | Sweep first. Orphan tests fail the build later. |
| "I'll keep it commented out for reference" | L4 violation. Commented-out code is stub. |
| "The dependents can be fixed later" | Block, do not cascade. Surface the list. |
| "Suite still passes after delete" | L3 violation. Quote the count. |

## Next step

Hand off to `/dev-kit:build` to re-verify, or `/dev-kit:review` for the deletion diff.
