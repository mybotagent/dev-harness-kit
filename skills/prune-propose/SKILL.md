---
name: prune-propose
category: audit
alpha: state
description: 0-arg skill — usage telemetry dump + per-skill delete proposal. User approves each deletion explicitly.
when_to_use:
  - User types /dev-kit:prune-propose
  - User wants to consolidate skills with no recent usage
allowed-tools: Read Bash
disallowed-tools: Write Edit
model: sonnet
disable-model-invocation: false
user-invocable: true
---
> [← Skills index](../../README.md)

Usage-driven prune proposal. Reads `tools/skill_usage.py` telemetry,
filters skills with **0 invocations AND 0 turns in the last 30 days**,
prints the candidate list as a chat-rendered table, and asks the user
to confirm each deletion one at a time via `AskUserQuestion`.

`alpha: state` — this skill drives the deletion-proposal state machine
(no-usage -> proposed -> user-approved -> deleted). The 0/0 + 30-day
window is the deterministic gate; user approval is the second gate;
deletion is the terminal state.

## Workflow

```
[1/3] DUMP     -> tools/skill_usage.py --days 30 --propose-delete
       ↓ quoted: candidate count + skill list
[2/3] PROPOSE  -> scripts/dump_usage.py renders AskUserQuestion per skill
       ↓ quoted: per-skill y/n decision (one user click each)
[3/3] REPORT   -> final report with approved-for-deletion set
       ↓ quoted: approved count + deleted count
```

`--dry-run` skips the AskUserQuestion loop and only emits the candidate
table. Use it first to sanity-check the filter.

## Step 1 — dump

```bash
python3 tools/skill_usage.py --days 30 --propose-delete --dry-run
```

The `--propose-delete` flag filters to **0 turns AND 0 invocations**
within the window and pipes the surviving skill list to
`scripts/dump_usage.py`. With `--dry-run` the proposal step is
suppressed and only the candidate table prints.

## Step 2 — propose

`scripts/dump_usage.py` reads the candidate list, prints a chat-rendered
table, then loops one `AskUserQuestion` per candidate. The user picks
**Delete** or **Keep** for each. No batch approval — each deletion
requires an explicit user click. The skill never deletes on its own;
it just emits the approved set to stdout for downstream automation
(`/dev-kit:prune --target <feature>`).

## Step 3 — report

Final report lists the approved-for-deletion set + the kept set + the
no-decision set. Aggregate counts and the window used are quoted so the
user has a reproducible record.

## Iron Laws

- MUST-L1: no deletion without the candidate table (step 1) AND a
  per-skill user click (step 2). Both gates must precede any delete.
- MUST-L3: each phase ends with a quoted exit code + count.
- MUST-L4: no auto-delete, no batch approve, no `--yes` flag.
- L6: this skill is `state` because it owns the prune-proposal state
  machine (dump -> propose -> report). The deletion itself is delegated
  to `/dev-kit:prune --target <skill>` per the existing discipline.

## Next step

After approval: `/dev-kit:prune --target <skill-name>` per approved skill.
For a whole-codebase prune instead of skill inventory, use
`/dev-kit:prune`.
