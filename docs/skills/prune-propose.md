> [← Skills index](README.md) · [Project README](../../README.md)

# `prune-propose`

**Category:** `audit` · **Alpha:** `state` · **Invocation:** `/dev-kit:prune-propose` (human-invoked)

`prune-propose` is a usage-driven prune proposal for the skill inventory itself. It reads `tools/skill_usage.py` telemetry, filters to skills with zero invocations and zero turns in the last 30 days, prints the candidate list as a chat-rendered table, and asks the user to confirm each deletion one at a time via `AskUserQuestion`. It is `alpha: state` because it drives the deletion-proposal state machine (no-usage → proposed → user-approved → deleted): the 0/0-in-30-days window is the deterministic gate, user approval is the second gate, and deletion itself is the terminal state (delegated elsewhere).

## When to use it

- The user types `/dev-kit:prune-propose`.
- The user wants to consolidate skills that have seen no recent usage.

## How it works

The skill runs a strict 3-step workflow:

```
[1/3] DUMP     -> tools/skill_usage.py --days 30 --propose-delete
       quoted: candidate count + skill list
[2/3] PROPOSE  -> scripts/dump_usage.py renders AskUserQuestion per skill
       quoted: per-skill y/n decision (one user click each)
[3/3] REPORT   -> final report with approved-for-deletion set
       quoted: approved count + deleted count
```

**Step 1 — dump.** `python3 tools/skill_usage.py --days 30 --propose-delete --dry-run` filters to skills with **0 turns AND 0 invocations** within the window and pipes the surviving skill list to `scripts/dump_usage.py`. With `--dry-run`, the proposal step is suppressed and only the candidate table prints — use this first to sanity-check the filter.

**Step 2 — propose.** `scripts/dump_usage.py` reads the candidate list, prints a chat-rendered table, then loops one `AskUserQuestion` per candidate. The user picks **Delete** or **Keep** for each — there is no batch approval; each deletion requires an explicit user click. The skill never deletes on its own; it emits the approved set to stdout for downstream automation (`/dev-kit:feat-remove`).

**Step 3 — report.** The final report lists the approved-for-deletion set, the kept set, and the no-decision set, with aggregate counts and the window used quoted so the user has a reproducible record.

## Usage

```bash
/dev-kit:prune-propose [--dry-run]
```

`--dry-run` skips the `AskUserQuestion` loop and only emits the candidate table from Step 1.

## Output

A three-part terminal report: the Step 1 candidate table (skill list with 0 usage in the window), the Step 2 per-skill delete/keep decisions, and the Step 3 summary (approved count, kept count, no-decision count, and the 30-day window used).

## Iron Laws

- MUST-L1: no deletion without the candidate table (Step 1) **and** a per-skill user click (Step 2) — both gates must precede any delete.
- MUST-L3: each phase ends with a quoted exit code + count.
- MUST-L4: no auto-delete, no batch approve, no `--yes` flag.
- L6: this skill is `state` because it owns the prune-proposal state machine; the deletion itself is delegated to `/dev-kit:feat-remove <skill>`.

## Related

- `/dev-kit:feat-remove <skill-name>` — the actual deletion step for each user-approved skill.
- `/dev-kit:prune` — for a whole-codebase slop/dead-code prune instead of a skill-inventory prune.
- `tools/skill_usage.py`, `scripts/dump_usage.py` — telemetry dump and per-skill AskUserQuestion driver.

---
*Source: [`skills/prune-propose/SKILL.md`](../../skills/prune-propose/SKILL.md)*
