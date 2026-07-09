---
name: repair
category: repair
description: 8-step Eval-Repair loop (golden → judge → root cause → fix → judge → A/B → diff → Human Review). Final step = single user approve.
when_to_use: |
  - User types /dev-kit:repair approve|reject|defer <asset>
allowed-tools: Read Grep Glob Bash Agent
disallowed-tools: Edit Write
model: opus
disable-model-invocation: false
---

# /dev-kit:repair — Eval-Repair Loop (Human Review terminal)

8 automated steps + final step = single user approve. Never auto-commit ❌ (MUST-NOT-31).

## 8 steps

1. Read golden_set
2. LLM as Judge (4-axis score)
3. Score failures + root cause
4. Invoke Specialized Fixer (9 categories)
5. Fix candidate → re-evaluate (loop max 3)
6. A/B Validation Regression (golden invariant)
7. Auto-write draft diff (`.dev-kit/repair/<asset>.diff`)
8. **Human Review** (user `approve|reject|defer <asset>`)

## Commands

- `/dev-kit:repair list` — pending diff list
- `/dev-kit:repair approve <asset>` — git apply
- `/dev-kit:repair reject <asset>` — discard diff + add golden regression pattern
- `/dev-kit:repair defer <asset>` — preserve diff