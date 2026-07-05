---
name: bootstrap
category: bootstrap
description: 0-arg orchestrator. Runs sanity + codebase-map + active-hooks initialization. Writes CLAUDE.md SSOT.
when_to_use: |
  - User types `/dev-kit:bootstrap` 1st time on a new project
  - User wants to refresh CLAUDE.md / active-hooks.json
allowed-tools: Read Write Glob Bash AskUserQuestion
disallowed-tools: Agent WebFetch
model: opus
disable-model-invocation: false
---

# /dev-kit:bootstrap — First-Run Orchestrator

## Iron Law (no exceptions)
**0-arg default OK.** Only hidden flags allowed (`--skip-sanity`, `--skip-map`, `--slim|--full`, `--team`, `--strict`).

## 4-Step Orchestration (3 autonomous + 1 user confirm)

```
[1] sanity bootstrap-sanity              → .dev-kit/sanity-report.md
       ↓ (auto, deterministic regex + glob)
[2] codebase-map bootstrap-codebase-map  → §3 (5-line STUB default)
       ↓ (auto, Read + Glob + Bash)
[3] active-hooks bootstrap-active-hooks  → .dev-kit/.active-hooks.json (SSOT)
       ↓ (auto)
[4] write-claude-md lib/write_claude_md.py → CLAUDE.md (§1~§5 atomic)
       ↓ (auto)
[5] user review 1x (HOTL, MUST-29)
       ↓
[6] exit / hand-off → wait for /dev-kit:plan call
```

## Hook integration (stage=bootstrap)

| Hook | Mode |
|---|---|
| tdd-guard | OFF |
| bash-guard | OFF |
| secret-scan | read-only |
| slop-detector | OFF |
| stop-verify | OFF |

`active-hooks.json` SSOT auto-initialized (MUST-13). With `--strict` all hooks `exit 2`.

## Rules (no exceptions)

- **0-arg UX (MUST-21)**: zero args. Branching via `when_to_use` auto-match.
- **HOTL (MUST-29)**: steps 1~4 auto. §5 hand-off pointer auto-updated.
- **YAGNI**: no extra option prompts ❌ (MUST-NOT-13). Only hidden flags like `--slim|--full`.
- **No-over-engineering (MUST-25)**: defaults handle 80%. Extra features require ADR.

## Hand-off result

On success, `.dev-kit/hand-off/bootstrap→plan.md` auto-written (state_codec.py). Next `/dev-kit:plan` call auto-injects preamble.

## Hot failure (on FAIL)

- sanity FAIL → Plan entry blocked. `/dev-kit:plan` call warns on stderr.
- Hook override (`DEV_KIT_HOOK_OFF=*`) auto-detected → sanity report WARN.
- Missing `eval/golden/*.json` → bootstrap unaffected (Phase 3+ introduces).