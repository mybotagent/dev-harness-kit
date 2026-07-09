---
name: eval
category: eval
description: Asset freshness (CLAUDE.md / skill / hook / Iron Law) LLM-as-judge evaluation. /dev-kit:eval dry-run + golden set cross-check.
version: 0.1.0
when_to_use: |
  - User types /dev-kit:eval
  - nightly cron auto-call
allowed-tools: Read Grep Bash Agent
disallowed-tools: Write Edit
model: opus
disable-model-invocation: false
---

# /dev-kit:eval — Asset Freshness Eval (4 axes)

4-axis score (semantic_drift / completeness / correctness / consistency). 0-10 scale. ≥ 8 OK, 5-7 drift warning, < 5 ROT.

## Rules

- DRIFT WARNING → async notify (Slack/Email/PR bot).
- ROT → CI fail. No hard-block — user can interrupt.
- 2-judge cross-check (MUST-NOT-23). Mismatched → quarantine to `.pending.json`.

## Next step

On DRIFT WARNING, `/dev-kit:repair` auto-call (8-step loop).