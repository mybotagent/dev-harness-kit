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

## Lazy-loading index (default)

CLAUDE.md §3 is a pure reference (no inline tree/manifest/deps). The agent reads
canonical source files on demand. `--full-claude-md` writes the full map to
`docs/CODEBASE-MAP.md` instead of inlining.

## 4-Section composition (only when `--full-claude-md`)

`lib/write_project_md.py:render_codebase_map_doc` writes `docs/CODEBASE-MAP.md`:

| Section | Source | Tool |
|---|---|---|
| **Tree** | recursive os.walk (depth 4, exclude `node_modules` `.git` `dist` `__pycache__`) | `os.walk` + path sort |
| **Manifest** | `package.json` / `pyproject.toml` / `go.mod` / `Cargo.toml` (whichever exists) | `Bash: jq` / `Read` |
| **Deps** | lockfile (`pnpm-lock.yaml` / `package-lock.json` / `requirements.txt` / `Pipfile.lock`) top 10 | `Bash: head -10` |
| **Conventions** | `.editorconfig` / `.eslintrc` / `.prettierrc` / `pyproject.toml [tool.*]` | `Read` |

## Modes

| Mode | Output | Tokens |
|---|---|---|
| default | §3 = lazy-loading index in CLAUDE.md | ~100 tokens |
| `--full-claude-md` (opt-in) | `docs/CODEBASE-MAP.md` written (4 sections) | 500~5000 tokens |

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