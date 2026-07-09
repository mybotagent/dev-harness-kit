---
name: simplify
category: build
description: 0-arg cleanup chain. One slash wraps inspect -> build-simplify -> review. 3 gated phases with quoted exit codes between each.
when_to_use: |
  - User types /dev-kit:simplify
  - User types "clean up the codebase" / "refactor everything" / "simplify the whole project"
  - Whole-pipeline cleanup after a refactor PR
allowed-tools: Read Write Bash Glob Grep
disallowed-tools: Edit WebFetch
model: sonnet
user-invocable: true
---

## What it does

Whole-pipeline cleanup: dispatches `/dev-kit:inspect` for a read-only
baseline report, then `/dev-kit:build-simplify` for the mutating 4-pass
cleanup (dead -> dup -> naming -> coverage), then `/dev-kit:review`
for the per-diff verification. The three phases are **separate calls,
not one big cycle** (MUST-NO-LOOP) -- each phase gates the next on a
quoted exit code and test count. No fix lands without a passing test
suite; no phase starts without the previous phase's green evidence.

## Pre-flight

- 0-arg: whole project directory. Optional `<path>` narrows scope to a
  subtree (passed through to each phase).
- Refuse to start if `.dev-kit/ci-config.json` is absent OR
  `ci_setup_version` < `0.2.0`. Run `/dev-kit:ci-setup` first.
- The test suite must be runnable in < 10 minutes. If the existing
  suite is heavier, run `/dev-kit:feat-revise` for the affected
  feature first to keep per-pass gates fast.
- Optional `--phase N` (1|2|3) re-runs only that phase. Default: all
  three in order.

## 3 phases (separate calls)

```
[1/3] INSPECT    -> /dev-kit:inspect
       (read-only baseline; .dev-kit/inspect-report.md with 8-dim findings)
       ↓ quoted: report path + verdict + finding count
[2/3] SIMPLIFY   -> /dev-kit:build-simplify
       (4 passes internally: dead -> dup -> naming -> coverage;
        each pass ends with quoted regression-test green)
       ↓ quoted: 4 × (pass name + test count + exit 0)
[3/3] REVIEW     -> /dev-kit:review
       (3-dim per-diff: correctness + security + architecture)
       ↓ quoted: per-dim finding count + overall verdict
```

## Rules (no exceptions)

- MUST-L1: no phase 2 (simplify) without a phase-1 (inspect) report.
- MUST-L3: each phase ends with a quoted exit code + test count
  (or per-dim finding count for inspect/review) before the next phase
  starts. No "trust me" hand-offs.
- MUST-L4: no commented-out code, no `pass`-as-stub, no
  "we'll fix this in a follow-up" leftovers. Every cleanup lands clean.
- MUST-NO-LOOP: phases are sequential gates, not a single retried
  cycle. Phase 2's 4 passes are themselves separate calls inside
  `build-simplify`; do not collapse them here.
- If any phase is RED, stop. Surface the failing phase's quoted output
  to the user. Do not run subsequent phases on a red baseline.
- The skill never edits source files itself. Phase 2 does the
  mutations; phases 1 and 3 are read-only.

## Hook integration

| Hook | Mode |
|---|---|
| tdd-guard | ON (phase 2 mutates; tdd-guard passes if test changes accompany) |
| bash-guard | ON |
| secret-scan | ON (PostToolUse) |
| slop-detector | ON (phase 2 mutates prose too) |
| stop-verify | ON -- quoted full-suite green required before declaring done |

## Output

- `.dev-kit/inspect-report.md` (phase 1 artifact)
- `.dev-kit/hand-off/simplify-report.md` (this skill's own log:
  per-phase start/end timestamps, quoted exit codes, per-phase finding
  counts, the hand-off chain to `/dev-kit:ship`)
- Per-phase emitted hand-off JSON via `state_codec.append_hand_off`
  (`build -> review -> ship` once all three phases are green)
- After all 3 phases green: a single quoted full-suite run
  (test count + exit code + duration) in the final report.

## Red flags

| Thought | Reality |
|---|---|
| "Run all 3 phases in one big cycle" | MUST-NO-LOOP violation. Each phase must gate the next on quoted output. |
| "Skip phase 1, I already know the smells" | MUST-L1 violation. The baseline is what makes phase 2's output verifiable. |
| "Phase 2 is enough, review is overhead" | L3 violation. The review catches what the simplify pass missed. |
| "I'll just leave a TODO for the leftover" | L4 violation. Either fix it in this run or surface it as a HIGH finding. |
| "Suite still passes after phase 2" | L3 violation. Quote the count. |
| "Phase 3 found a HIGH, but it's small, let's ship" | Stop. Re-run phase 2 or hand off to `/dev-kit:plan` for a structured fix. |

## Next step

- All 3 phases green -> `/dev-kit:ship` (release tag emit) or
  `/dev-kit:status` (HOTL visualization of the whole cleanup).
- Any phase RED -> the failing phase is the deliverable. Fix the
  blocker (usually: re-run `build-simplify` after the regression is
  fixed, or `/dev-kit:plan` to scope a structured fix for HIGH
  findings).
