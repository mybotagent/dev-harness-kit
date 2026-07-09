---
name: build-engine
category: build
description: harness-runner engine per step. atomic write + 2-commit protocol + parallel worktree. No own cycle (each step is a separate cycle, MUST-NO-LOOP).
version: 0.1.0
when_to_use: |
  - Auto-invoked by /dev-kit:build per step
allowed-tools: Read Write Bash
disallowed-tools: Edit WebFetch Agent
model: sonnet
user-invocable: false
---

# build-engine — Phase Step Executor

## Iron Law
**No work outside the step ❌.** Don't create files or features not specified in the step file. If you need extras, register a new step in index.json.

## 2-Commit Protocol

```
[1] feat(scope): step<N> — <name>
    (code changes)
[2] chore(scope): step<N> output
    (step<N>-output.json recorded)
```

Use `git reset HEAD -- <path>` between the two commits.

## Hook integration

All ON during Build stage:
- `tdd-guard` (active per methodology)
- `bash-guard` (blocks destructive commands)
- `secret-scan` (PostToolUse: credential pattern)
- `slop-detector` (KO+EN banned phrases)
- `stop-verify` (Stop event: AC claim)

## Rules

- **MAX_RETRIES=3**: 3 retries per step. After that → `status=error` + report to main.
- **`--parallel N`**: N independent steps run in worktree isolation concurrently. Auto-detect phase dependencies.
- **resume**: pending steps auto-continue. `index.json` status state machine.
- **blocked**: user intervention required (API key / manual setup). `blocked_reason` required (status state machine validate).
- **idempotent**: `step<N>-output.json` atomic-overwritten on re-run.

## Output

- `step<N>-output.json`: `{step, phase, exit_code, stdout, stderr, duration_seconds, timestamp}`

## Sub-agent delegation

Phase 3 (planned): main orchestrator delegates AC execution to sub-agents in isolated worktrees with scoped permissions. Currently sequential-only.