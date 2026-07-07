---
name: bootstrap
category: bootstrap
description: 0-arg orchestrator. Writes minimal CLAUDE.md + AGENTS.md + active-hooks.json on a fresh repo. No noise files by default.
when_to_use: |
  - User types `/dev-kit:bootstrap` 1st time on a new project
  - User wants to refresh CLAUDE.md / active-hooks.json
allowed-tools: Read Write Glob Bash AskUserQuestion
disallowed-tools: Agent WebFetch
model: opus
disable-model-invocation: false
---

# /dev-kit:bootstrap — Minimal First-Run Setup

## What it does

Runs three deterministic sub-skills (`bootstrap-sanity`, `bootstrap-codebase-map`, `bootstrap-active-hooks`) and then writes the project SSOT. On a fresh repo, exactly three files land on disk: `CLAUDE.md`, `AGENTS.md`, and `.dev-kit/.active-hooks.json`. No sanity report file. No hand-off file. AGENTS.md is a 1-line pointer (`CLAUDE.md`) for CLIs that read AGENTS.md instead of CLAUDE.md.

## Iron Law (no exceptions)
**0-arg default OK.** Only hidden flags allowed (`--skip-sanity`, `--skip-map`, `--slim|--full`, `--team`, `--strict`, `--persist-audit`).

## 4-Step Orchestration (3 autonomous + 1 user confirm)

```
[1] sanity bootstrap-sanity              → stdout only (file only with --persist-audit)
       ↓ (auto, deterministic regex + glob)
[2] codebase-map bootstrap-codebase-map  → §3 (lazy-loading index; consumed only by --full-claude-md)
       ↓ (auto, Read + Glob + Bash; only consumed by --full-claude-md)
[3] active-hooks bootstrap-active-hooks  → .dev-kit/.active-hooks.json (SSOT)
       ↓ (auto)
[4] write-claude-md lib/write_project_md.py → CLAUDE.md + AGENTS.md (§1~§5 atomic)
       ↓ (auto)
[5] user review 1x (HOTL, MUST-29)
       ↓
[6] exit → wait for /dev-kit:plan call (no bootstrap→plan hand-off file; §5 pointer is enough)
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
- **YAGNI**: no extra option prompts ❌ (MUST-NOT-13). Only hidden flags like `--slim|--full`, `--persist-audit`.
- **No-over-engineering (MUST-25)**: defaults handle 80%. Extra features require ADR.
- **Minimal file footprint**: default run touches only `CLAUDE.md`, `AGENTS.md`, `.dev-kit/.active-hooks.json`. Use `--persist-audit` to also write `.dev-kit/sanity-report.md`.

## Next step

After bootstrap, call `/dev-kit:plan` to write the planning artifacts (`PRD.md` + `phases/<name>/`). `/dev-kit:ci-setup` is opt-in and only for installing dev-kit's reusable GitHub Action review workflows into a target repo — it is NOT a generic next stage.