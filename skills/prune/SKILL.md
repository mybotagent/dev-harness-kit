---
name: prune
category: build
description: 0-arg slop-removal chain. One slash wraps inspect → 3-pass delete sweep → review. Gated phases for deleting AI slop and dead features (not refactoring).
when_to_use: |
  - User types /dev-kit:prune
  - User types "remove AI slop" / "delete dead code" / "sweep the codebase for cruft"
  - Whole-pipeline *deletion* after a refactor PR — for *refactoring* use `/dev-kit:refactor`
  - For removing one named feature end-to-end, use `/dev-kit:feat-remove <feature>` instead
allowed-tools: Read Write Bash Glob Grep
disallowed-tools: Edit WebFetch
model: opus
user-invocable: true
---

## What it does

Whole-pipeline *deletion* sweep: dispatches `/dev-kit:inspect` for a
read-only baseline, then runs a 3-pass deletion sweep
(orphan-code → dead-feature → slop-pattern), then `/dev-kit:review` for
the per-diff verification. The three phases are **separate calls, not
one big cycle** (MUST-NO-LOOP) -- each phase gates the next on a quoted
exit code and test count. No deletion lands without a passing test
suite; no phase starts without the previous phase's green evidence.

**`/dev-kit:prune` vs. `/dev-kit:refactor` vs. `/dev-kit:feat-remove`:**

| Skill | Arg | Discovers | Action |
|---|---|---|---|
| `/dev-kit:refactor` | none | n/a (called by user) | refactor (rewrite/extract/rename) |
| `/dev-kit:prune` (this) | none | automatic: scan for slop | delete (rm) |
| `/dev-kit:feat-remove` | `<feature>` required | manual: user names it | delete (rm) — single feature |

`prune` is the project-wide counterpart to `feat-remove` — no `<feature>` arg, automatic discovery of dead/orphan/slop candidates.

## Pre-flight

- 0-arg: whole project directory. Optional `<path>` narrows scope to a
  subtree (passed through to each phase).
- No version-gated preconditions. The dev-harness-kit repo itself is
  the provider of `/dev-kit:ci-setup`, so requiring a consumer-side
  `ci-config.json` here is self-referential. The phase-1 inspect
  baseline + phase-2 per-pass green tests (MUST-L1, MUST-L3) already
  enforce a runnable, fast test suite.
- The test suite must be discoverable and runnable in < 10 minutes.
  If the existing suite is heavier, run `/dev-kit:feat-revise` for
  the affected feature first to keep per-pass gates fast.
- Optional `--phase N` (1|2|3) re-runs only that phase. Default: all
  three in order.
- Optional `--dry-run` (default: ON for first pass). The skill never
  calls `rm` or `git rm` itself — it emits commands and waits for the
  user to run them, mirroring `feat-remove` discipline.

## 3 phases (separate calls)

```
[1/3] INSPECT   -> /dev-kit:inspect
       (read-only baseline; .dev-kit/inspect-report.md with 8-dim findings)
       ↓ quoted: report path + verdict + finding count
[2/3] PRUNE     -> 3 passes in sequence (see below)
       (orphan-code -> dead-feature -> slop-pattern;
        each pass ends with quoted regression-test green;
        skill emits rm/git-rm commands for the user to run)
       ↓ quoted: 3 × (pass name + test count + exit 0)
[3/3] REVIEW    -> /dev-kit:review
       (3-dim per-diff: correctness + security + architecture)
       ↓ quoted: per-dim finding count + overall verdict
```

## Phase 2 — 3-pass deletion sweep

> Sibling of `build-refactor`. `build-refactor` rewrites/extracts/renames;
> phase-2 of `prune` *deletes*. Both are model-use operations.

### Iron Law
**No deletion without reproducible signal + regression test.** Each pass must produce a quoted grep/dependency report AND a quoted post-delete test run.

### The 3 passes

```
[1/3] ORPHAN-CODE  → exports with no callers, files with no importers,
                     branches with no path to them
       (Grep + glob for all references; must return 0 matches after delete)
       ↓ regression test green
[2/3] DEAD-FEATURE → entire capabilities with no live users
                     (unused env vars, deprecated paths, unreachable entry points)
       (Dependency graph check; user must ack any cascade)
       ↓ regression test green
[3/3] SLOP-PATTERN → AI-tell patterns: defensive over-engineering, boilerplate,
                     comment-as-narration, try/except pass blocks, dead options
                     (Matches audit-slop heuristics but mutates rather than reports)
       ↓ full test suite green
```

### Pass rules

- Do not bundle 3 passes into one cycle (MUST-NO-LOOP).
- One pass = one kind. Confirm regression test pass after each.
- The skill **emits** `rm` / `git rm` commands to a report file. It
  never calls them itself. The user runs them. Mirrors `feat-remove`
  discipline.
- ❌ guess. Measure first (e.g., `vulture src/`, `pydeps --show-cycles`,
  custom grep for AI-tell patterns).
- Dependents block by default. If a deletion candidate has any
  importer/caller/test/doc reference, surface the list and refuse to
  proceed without user ack.

### Red flags

| Thought | Reality |
|---|---|
| "Do all 3 passes at once" | Can't tell which pass caused regression |
| "Just `rm -rf` the suspicious dir" | L4 violation + `feat-remove` discipline breach |
| "Comment out to disable" | L4 violation |
| "Verify later" | L3 violation |
| "The user said the feature is dead" | Still surface the dependents list. The user might be wrong. |
| "This is a small file, skip the orphan check" | No. MUST-L2 — every deletion needs a reproducible signal. |
| "I'll just rename to `.bak` instead of deleting" | L4 violation. Renamed-to-bak is the same as commented-out. |
| "This is refactor, not prune" | Stop. Hand off to `build-refactor` instead. |

### Hand-off

- Previous (read first): `/dev-kit:inspect` — produces the report that
  prioritizes which passes to run.
- After 3 passes green, `state_codec.append_hand_off(root, "build", "review", "...")`.
  Next: `/dev-kit:review`.
- If a candidate turns out to be a refactor (rename, extract) rather than
  a deletion, hand off to `build-refactor` for that single item.

## Phase rules (no exceptions)

- MUST-L1: no phase 2 (prune) without a phase-1 (inspect) report.
- MUST-L2: every deletion must have a reproducible signal (orphan grep,
  dead-feature dependency check, or slop-pattern match). No "I think
  this is unused."
- MUST-L3: each phase ends with a quoted exit code + test count
  (or per-dim finding count for inspect/review) before the next phase
  starts. No "trust me" hand-offs.
- MUST-L4: no commented-out code, no `pass`-as-stub, no "kept for
  reference" leftovers. Every deletion lands clean — actually removed
  from disk and git, not commented out.
- MUST-NO-LOOP: phases are sequential gates, not a single retried
  cycle. Phase 2's 3 passes are themselves separate calls; do not
  collapse them here.
- If any phase is RED, stop. Surface the failing phase's quoted output
  to the user. Do not run subsequent phases on a red baseline.
- The skill never deletes files itself. Phase 2 emits the commands;
  the user runs them. This mirrors `feat-remove` discipline.
- Dependents block by default. If a deletion candidate has any
  importer/caller/test/doc reference, the skill refuses to proceed
  until the user acks the cascade (same as `feat-remove` MUST).

## Hook integration

| Hook | Mode |
|---|---|
| tdd-guard | ON (phase 2 mutates; tdd-guard passes if test deletions accompany) |
| bash-guard | ON (blocks destructive `rm -rf` etc.; the skill still surfaces commands for the user) |
| secret-scan | ON (PostToolUse) |
| slop-detector | ON (the deletion itself reduces slop; the report prose is checked) |
| stop-verify | ON -- quoted full-suite green required before declaring done |

## Output

- `.dev-kit/inspect-report.md` (phase 1 artifact)
- `.dev-kit/hand-off/prune-report.md` (this skill's own log:
  per-phase start/end timestamps, quoted exit codes, per-phase finding
  counts, the hand-off chain to `/dev-kit:ship`)
- For each deletion candidate: path + reason + dependents list +
  exact `rm` / `git rm` command for the user to run. No silent cascade.
- Per-phase emitted hand-off JSON via `state_codec.append_hand_off`
  (`build -> review -> ship` once all three phases are green)
- After all 3 phases green: a single quoted full-suite run
  (test count + exit code + duration) in the final report.

## Next step

- All 3 phases green + user has run the deletion commands ->
  `/dev-kit:ship` (release tag emit) or `/dev-kit:status` (HOTL
  visualization of the whole sweep).
- Any phase RED -> the failing phase is the deliverable. Fix the
  blocker (usually: re-run the failing pass after the regression is fixed,
  or `/dev-kit:plan` to scope a structured fix for HIGH findings).
- For one named feature end-to-end, use `/dev-kit:feat-remove <feature>`.
- For pure refactoring (no deletion), use `/dev-kit:refactor`.