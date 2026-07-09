---
name: feat-add
category: build
description: Add a new feature under TDD. Reads plan artifacts, writes a failing test first, drives the minimum green implementation, then refactors.
when_to_use: |
  - User types /dev-kit:feat-add <feature>
  - After /dev-kit:plan defines the feature boundary
  - User wants TDD greenfield for one isolated feature
allowed-tools: Read Write Bash Glob Grep Agent
disallowed-tools: WebFetch
model: opus
disable-model-invocation: false
user-invocable: true
---

## What it does

Adds one new feature to the codebase via the Red-Green-Refactor cycle. Resolves the feature name into plan artifacts (`PRD.md` + `phases/<name>/`), writes a failing test first (MUST-L1), implements the minimum code to make it pass, refactors, and leaves the full suite green with a quoted test count. One feature per invocation — boundaries that pull in a second feature are routed back to `/dev-kit:plan`.

## Pre-flight

- `phases/<name>/index.json` MUST exist; if missing, refuse and tell the user to run `/dev-kit:plan` first.
- `<feature>` arg must resolve to a phase name. Reject empty or unresolvable names.
- Methodology gate: `lib/methodology.json:active` must be `tdd` (the default per MUST-48). Non-TDD methodologies are out of scope here.

## Behavior

1. `Read` `phases/<name>/step{next}.md` to load the AC and the feature boundary.
2. Write the failing test in the project's test layout. Match the surrounding test style (xUnit, pytest, vitest, etc.) — do not introduce a new test framework.
3. Run the test once. Assert `exit_code != 0` and capture the failure output. This is the quoted "red" run.
4. Implement the minimum code in the project's source layout. No speculative features (L4: no `we'll extend later`).
5. Run the test again. Assert `exit_code == 0` and capture the count. This is the quoted "green" run.
6. Refactor only if the new code duplicates or obscures an existing pattern. Re-run the full suite.
7. Append a hand-off entry to `.dev-kit/hand-off/feat-add→build.md` quoting both runs and the final full-suite result.

## Rules (no exceptions)

- MUST-L1: a failing test exists before any production line lands.
- MUST-L3: "done" requires a quoted green test count and exit code.
- MUST-L4: no stubs, no `TODO: implement later`, no placeholder returns.
- MUST-L5: one feature per invocation. If two features want to share code, stop and call `/dev-kit:plan` to revise the phase.

## Hook integration

| Hook | Mode |
|---|---|
| tdd-guard | ON — refuses prod code without a prior failing test |
| bash-guard | ON |
| secret-scan | ON (PostToolUse) |
| slop-detector | ON |
| stop-verify | ON — "done" requires quoted test count |

## Output

- Failing test file in the project test layout.
- Implementation file in the project source layout.
- Updated `phases/<name>/index.json` with the step marked `completed` and `started_at` / `completed_at` timestamps.
- `.dev-kit/hand-off/feat-add→build.md` quoting the red run, the green run, and the final full-suite result.

## Test evidence

Quote all three runs verbatim:

```bash
# Red — must fail
python -m pytest tests/<feature>_test.py -v 2>&1 | tail -5
# Green — must pass
python -m pytest tests/<feature>_test.py -v 2>&1 | tail -5
# Full suite — must stay green
python -m pytest tests/ 2>&1 | tail -3
```

Substitute the project's actual test runner (`npm test`, `go test ./...`, `cargo test`, etc.) when the project is not Python.

## Red flags

| Thought | Reality |
|---|---|
| "I'll add a few related features while I'm here" | One feature per invocation. Plan first. |
| "Test is obvious, skip it" | MUST-L1 violation. Write it. |
| "I'll add a stub for the next feature" | MUST-L4 violation. No stubs. |
| "It works on my machine" | Quote exit code or it didn't happen. |

## Next step

Hand off to `/dev-kit:build` if more phases remain, or `/dev-kit:review` for the new feature diff.
