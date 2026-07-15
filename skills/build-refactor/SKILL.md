---
name: build-refactor
category: build
description: 4-pass cleanup (dead → dup → naming → coverage). No cleanup without regression test (MUST-L1 + L4).
when_to_use: |
  - User types "cleanup" / "refactor" / "simplify"
  - Internal sub-skill of /dev-kit:refactor
allowed-tools: Read Write Bash Glob Grep
disallowed-tools: WebFetch Agent
model: sonnet
user-invocable: false
---

# build-refactor — 4-Pass Cleanup

> Previously named `build-simplify`. Renamed to match the parent
> `/dev-kit:refactor` skill. For actual code deletion (slop, dead
> features, orphan code), see the sibling `/dev-kit:prune` skill — its
> 3-pass deletion sweep (orphan-code → dead-feature → slop-pattern) is
> inlined into `skills/prune/SKILL.md` as "Phase 2".

## Iron Law
**No cleanup without regression test.** Pass 1 = dead code removal — confirm all affected tests pass before next pass.

## 4 Passes (separate calls)

```
[1/4] DEAD CODE   → unused exports / dead branches / commented-out blocks
       (Grep with permission to find all references first)
       ↓ regression test green
[2/4] DUPLICATION → same logic in 2+ places. extract helper / module
       ↓ regression test green
[3/4] NAMING      → variable / function / file / module names clear
       ↓ regression test green
[4/4] COVERAGE    → boost weak tests. hot path + edge cases
       ↓ full test suite green
```

## Rules

- Do not bundle 4 passes into one cycle (MUST-NO-LOOP).
- One pass = one kind. Confirm regression test pass after each.
- ❌ guess. Measure first (e.g., `coverage report --include=src/lib`).
- This skill *refactors* (rewrites / extracts / renames). It does **not**
  delete whole files or features. For deletion, dispatch `/dev-kit:prune`
  (3-pass sweep inlined into its Phase 2 section).

## Hook integration

Build stage active. During cleanup edits, `tdd-guard` passes if test changes accompany (helps rename).

## Red Flags

| Thought | Reality |
|---|---|
| "Do all 4 passes at once" | Can't tell which pass caused regression |
| "Leave tests as-is" | L1 violation |
| "Comment out to disable" | L4 violation |
| "Verify later" | L3 violation |
| "Delete the whole unused module" | Out of scope. Use `/dev-kit:prune` (its Phase 2 3-pass sweep). |

## Hand-off

Previous (read first): `/dev-kit:inspect` — produces the report that
prioritizes which passes to run.

After 4 passes, `state_codec.append_hand_off(root, "build", "review", "...")`. Next: `/dev-kit:review`.

If passes surface whole-file deletion candidates, hand off to
`/dev-kit:prune` for the deletion pass rather than continuing here.
