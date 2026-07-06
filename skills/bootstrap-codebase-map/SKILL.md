---
name: bootstrap-codebase-map
category: bootstrap
description: deterministic synthesis of codebase tree + manifest + dependencies + conventions → CLAUDE.md §3. Read-only, no LLM call.
when_to_use: |
  - When `/dev-kit:bootstrap` after sanity PASS
  - When user runs `/dev-kit:map` or `--refresh-codebase-map`
allowed-tools: Read Glob Bash
disallowed-tools: Write Edit WebFetch Agent
model: haiku
disable-model-invocation: false
user-invocable: false
---

# bootstrap-codebase-map — Auto Codebase Context

## Iron Law (no exceptions)
**No guessing / padding ❌.** Only output from pre-validated tools (glob/cat/jq). On guess, append `STALE: guess` marker + wait for user input.

## 4-Section composition

`lib/write_claude_md.py` inserts into CLAUDE.md §3:

| §3 Section | Source | Tool |
|---|---|---|
| **Tree** | recursive glob (depth 4, exclude `node_modules` `.git` `dist` `__pycache__`) | `Glob` + path sort |
| **Manifest** | `package.json` / `pyproject.toml` / `go.mod` auto-detect | `Bash: jq` / `Read` |
| **Deps** | lockfile (`pnpm-lock.yaml` / `package-lock.json` / `requirements.txt`) top 10 | `Bash: head -10` |
| **Conventions** | `.editorconfig` / `.eslintrc` / `pyproject.toml [tool.*]` / commit trailer rules | `Read` |

## Lazy mode (MUST-11)

| Mode | Output | Tokens |
|---|---|---|
| `--slim-claude-md` (default) | §3 = 5-line STUB + `+codebase-map:full` marker | ~200 tokens |
| `--full-claude-md` (opt-in) | §3 = full 4 sections inline | 500~5000 tokens |

## Rules (no exceptions)

- **Determinism**: same input → same output. `jq --sort-keys` + path stable sort.
- **No lockfile mutation**: `pnpm-lock.yaml`, `package-lock.json` changes ❌.
- **Secret mask**: deps / config output masks `password|token|key` as `***`.
- **STALE marker**: on guess, auto-attach `<!-- STALE: <reason> -->` + interrupt build/plan.

## Hook integration

Bootstrap stage:
- `slop-detector=OFF`
- `bash-guard=OFF` (safe commands only)
- `secret-scan=read-only` (output secret auto-masking)