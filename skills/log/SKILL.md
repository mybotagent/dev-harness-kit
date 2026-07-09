---
name: log
category: shortcuts
description: Toggle /log setup|on|off|status — install/remove loghooks from ~/dev/loghooks into the current project's Claude/Codex settings.
version: 0.1.0
when_to_use: |
  - User types /dev-kit:log on
  - User types /dev-kit:log off
  - User types /dev-kit:log setup
  - User types /dev-kit:log status
allowed-tools: Read Bash
disallowed-tools: Write Edit WebFetch Agent
model: haiku
disable-model-invocation: false
---

# /dev-kit:log — Toggle loghooks on/off

Wraps the standalone `~/dev/loghooks` repo (Stop + SessionEnd transcripts)
as a one-command on/off per project. Hooks are tagged with a sentinel
so off is precise — never touches the user's pre-existing hooks.

## Iron Law

**Hooks merge, not replace. Off is sentinel-scoped, not "rm -rf".**
Every entry this skill installs carries `_loghooks_managed=true`; off
removes only those entries. Existing user hooks are always preserved.

## Subcommands

| Subcommand | What it does | Idempotent |
|---|---|---|
| `setup` | Copy `tools/save_log.py` + scaffold `logs/` in target | Yes (refresh by default; `--force` to no-op even when sha matches) |
| `on` | Merge hooks from `~/dev/loghooks` into target's `.claude/settings.json` + `.codex/hooks.json` | Yes (replace-by-command, not duplicate) |
| `off` | Strip only `_loghooks_managed=true` entries from target's settings | Yes |
| `status` | Show installed-entry count + captured transcript count per target | Read-only |

Default subcommand when none given: `status`.

## Resolution

| Knob | Default | Env |
|---|---|---|
| Source repo | `~/dev/loghooks` | `LOGHOOKS_DIR` |
| Target project | `$PWD` | `TARGET_DIR` |

`jq` is required (the worktree rule-hooks already depend on it).

## Behavior (delegated to scripts/)

1. **Detect subcommand** from `$ARGUMENTS`. If empty → `status`.
2. **Source `scripts/lib.sh`** (sentinel + JSON merge/remove/count helpers).
3. **Dispatch** to the matching `scripts/log-<sub>.sh`.
4. Each script does its own arg parsing + jq + atomic write.
5. SKILL.md body is documentation; the scripts are the contract.

## Flags

| Flag | Subcommands | Effect |
|---|---|---|
| `--target DIR` | all | Override target project |
| `--force` | setup | Overwrite `tools/save_log.py` even when local sha matches |
| `--claude-only` | on, off | Touch only `.claude/settings.json` |
| `--codex-only` | on, off | Touch only `.codex/hooks.json` (no-op if source has no codex config) |

## Setup → On → Off → Status flow

```
1. /dev-kit:log setup     # creates tools/save_log.py + logs/{claude-code,codex}/
2. /dev-kit:log on        # merges Stop + SessionEnd hooks into .claude/settings.json
3.  ... run Claude Code ... transcripts appear in logs/claude-code/<sid>.jsonl
4. /dev-kit:log status    # managed=N captured=N
5. /dev-kit:log off       # strips managed entries; scaffold left in place
```

`off` deliberately leaves `tools/save_log.py` + `logs/` in place — they
cost nothing and a future `on` skips the setup step. Remove them
manually if you really want a clean slate.

## Hand-off

No hand-off to another stage. Pure utility.