---
name: prune
category: build
description: 0-arg slop-removal chain. One slash wraps inspect → 3-pass delete sweep → review. Gated phases for deleting AI slop and dead features (not refactoring).
alpha: analysis
when_to_use:
  - User types /dev-kit:prune
  - User types "remove AI slop" / "delete dead code" / "sweep the codebase for cruft"
  - Whole-pipeline deletion after a refactor PR — for refactoring use `/dev-kit:refactor`
  - For removing one named feature end-to-end, use `/dev-kit:feat-remove <feature>`
allowed-tools: Read Write Bash Glob Grep
disallowed-tools: Edit WebFetch
model: opus
user-invocable: true
---

Whole-pipeline **deletion** sweep. `/dev-kit:inspect` baseline → 3-pass delete
via `lib.analysis_core.run_analysis(..., mode="delete", ...)` → `/dev-kit:review`.
Phases are **separate calls**, each gating the next on a quoted exit code +
test count. `prune` is project-wide; `/dev-kit:feat-remove <feature>` deletes
one named feature. `prune` deletes; `/dev-kit:refactor` rewrites.

## 3 phases (separate calls)

0-arg: whole project. `<path>` narrows. No version-gated preconditions
(self-referential). Suite must run < 10 min. `--phase N` re-runs one phase.
`--dry-run` defaults ON for first pass.

```
[1/3] INSPECT   -> /dev-kit:inspect  (.dev-kit/inspect-report.md)
       ↓ quoted: report path + verdict + finding count
[2/3] PRUNE     -> orphan-code -> dead-feature -> slop-pattern
       ↓ quoted: 3 × (pass name + test count + exit 0)
[3/3] REVIEW    -> /dev-kit:review  (correctness + security + architecture)
       ↓ quoted: per-dim finding count + verdict
```

## Phase 2 — 3-pass deletion sweep

Sibling of `build-refactor` (rewrites). `prune` *deletes*. **Iron Law.** No
deletion without reproducible signal + regression test.

```
[1/3] ORPHAN-CODE  -> exports with no callers, files with no importers, unreachable branches
[2/3] DEAD-FEATURE -> entire capabilities with no live users (unused env vars, deprecated paths)
[3/3] SLOP-PATTERN -> AI-tell patterns: defensive over-engineering, comment-as-narration, try/except pass blocks
```

One pass = one kind. Confirm regression test pass after each. The skill
**emits** `rm` / `git rm` commands to a report file. It never deletes files itself — mirrors `feat-remove` discipline. Dependents block by default.

## Phase rules

MUST-L1: no phase 2 without a phase-1 report. MUST-L2: every deletion needs a reproducible signal. MUST-L3: each phase ends with quoted exit code + test count. MUST-L4: no commented-out code, no `pass`-as-stub. MUST-NO-LOOP: phases are sequential gates, not a retried cycle.

## Next step

All 3 phases green + user has run deletion commands -> `/dev-kit:ship` or `/dev-kit:status`. Any phase RED -> fix the blocker. For one named feature, `/dev-kit:feat-remove <feature>`. For pure refactoring, `/dev-kit:refactor`.
