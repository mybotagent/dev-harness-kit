# ADR-0021 — Eval-Repair Loop with Human Review

**Status**: Accepted

## Decision
Detect asset drift → automatic repair loop. Final step = user 1× approve on the diff.

## 8 steps
```
[1] golden_set
[2] LLM as Judge (4 axes: semantic_drift / completeness / correctness / consistency)
[3] Score failures + root cause
[4] Specialized Fixer (9 category experts)
[5] Fix candidate → re-evaluate (loop max 3)
[6] A/B validation regression (golden must not change)
[7] Auto-write diff draft
[8] Human Review ← sync STOP, user approve|reject|defer
```

## Forbidden
- Auto-commit diff ❌ (MUST-NOT-31).
- Auto-reject ❌ (user decides).

## Specialized Fixers
9 (bootstrap / plan / build / review / security / audit / iron_law / hooks / a2a). Each knows the category's 5-field frontmatter, hooks, and scripts and self-fixes.
