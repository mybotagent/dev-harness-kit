---
name: feat-revise
category: build
description: Revise a feature under TDD. Update the test to reflect the new AC, watch it fail, refactor the implementation, keep the full suite green.
when_to_use: |
  - User types /dev-kit:feat-revise <feature>
  - AC has changed for an existing feature
  - User wants to expand, narrow, or redefine behavior without losing old coverage
allowed-tools: Read Write Bash Glob Grep Agent
disallowed-tools: WebFetch
model: opus
disable-model-invocation: false
user-invocable: true
---

## What it does

Revises one named feature by amending its tests against the new AC, refactoring the implementation to satisfy both the new and the surviving old tests, and verifying the full suite stays green. Retired assertions are flagged for explicit user approval — coverage is never silently deleted.

## Pre-flight

- Feature must exist in `phases/<name>/` or be discoverable in the codebase.
- New AC must be stated by the user in the invocation. If absent, refuse and ask before proceeding.

## Behavior

1. `Read` the current test file for `<feature>` and the implementation under test.
2. Diff the new AC against the existing test cases. Classify each old case as:
   - **Survives** — still valid under new AC; keep as-is.
   - **Amend** — same intent, new shape; update the assertion only.
   - **Retire** — contradicts new AC; flag for user approval before deletion.
3. Add a new failing test that captures the changed AC. Run it. Assert `exit_code != 0`.
4. Refactor the implementation in the smallest diff that turns the new test green WITHOUT breaking any surviving test.
5. Run the full suite. Assert `exit_code == 0` and capture the count.
6. Write `.dev-kit/hand-off/feat-revise→build.md` quoting the new test run and the full-suite run.

## Rules (no exceptions)

- MUST-L1: a failing test reflecting the new AC exists before any impl edit.
- MUST-L3: completion requires a quoted new-test run AND a quoted full-suite run.
- Retired test cases need explicit user ack. Do not silently delete coverage.
- One feature per invocation. If new AC pulls in a second feature, stop and call `/dev-kit:plan`.

## Hook integration

| Hook | Mode |
|---|---|
| tdd-guard | ON — the new-AC test must fail before impl edits |
| bash-guard | ON |
| secret-scan | ON (PostToolUse) |
| slop-detector | ON |
| stop-verify | ON — quoted new test + quoted full-suite green |

## Output

- Updated test file (new AC reflected; surviving cases preserved; retired cases only after explicit user ack).
- Updated implementation.
- `.dev-kit/hand-off/feat-revise→build.md` with quoted runs.

## Red flags

| Thought | Reality |
|---|---|
| "Old test contradicts new AC, just delete it" | Retire requires user ack. Surface, do not bury. |
| "I'll just rewrite the whole feature" | Out of scope. Use `/dev-kit:feat-remove` + `/dev-kit:feat-add`. |
| "Suite passes locally, ship it" | L3 violation. Quote the count. |

## Next step

Hand off to `/dev-kit:build` to continue the phase, or `/dev-kit:review` for the amendment diff.
