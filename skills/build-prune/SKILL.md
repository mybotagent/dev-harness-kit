---
name: build-prune
category: build
description: 3-pass deletion sweep (orphan-code → dead-feature → slop-pattern). No deletion without reproducible signal + regression test.
when_to_use: |
  - Internal sub-skill of /dev-kit:prune
  - Dispatched when the project has accumulated AI slop / dead features
allowed-tools: Read Write Bash Glob Grep
disallowed-tools: WebFetch Agent
model: sonnet
user-invocable: false
---

# build-prune — 3-Pass Deletion Sweep

> Sibling of `build-refactor`. `build-refactor` rewrites/extracts/renames;
> `build-prune` *deletes*. Both are internal model-use sub-skills.

## Iron Law
**No deletion without reproducible signal + regression test.** Each pass must produce a quoted grep/dependency report AND a quoted post-delete test run.

## 3 Passes (separate calls)

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

## Rules

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

## Hook integration

Build stage active. During deletion emit, `tdd-guard` passes if test
deletions accompany (deleting orphan tests is expected). `bash-guard`
blocks any actual `rm` invocation the skill attempts; the skill must
surface commands for the user to run instead.

## Red Flags

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

## Hand-off

Previous (read first): `/dev-kit:inspect` — produces the report that
prioritizes which passes to run.

After 3 passes, `state_codec.append_hand_off(root, "build", "review", "...")`. Next: `/dev-kit:review`.

If a candidate turns out to be a refactor (rename, extract) rather than
a deletion, hand off to `build-refactor` for that single item.
