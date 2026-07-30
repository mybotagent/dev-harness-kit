---
name: bootstrap
category: bootstrap
description: 0-arg orchestrator. Writes minimal CLAUDE.md + AGENTS.md + active-hooks.json on a fresh repo. No noise files by default.
alpha: state
when_to_use: |
  - User types `/dev-kit:bootstrap` 1st time on a new project
  - User wants to refresh CLAUDE.md / active-hooks.json
allowed-tools: Read Write Glob Bash AskUserQuestion
disallowed-tools: Agent WebFetch
model: opus
disable-model-invocation: false
---
> [← Skills index](../../README.md)

# /dev-kit:bootstrap — Minimal First-Run Setup

## What it does

Runs three deterministic sub-stages (sanity → codebase-map → hook-matrix) and then writes the project SSOT. On a fresh repo, exactly these files land on disk: `CLAUDE.md`, `AGENTS.md`, `.dev-kit/.active-hooks.json`, `iron-laws/index.md`, `guidelines/index.md`, `hooks/index.md`, plus `rules/index.md` if `rules/` exists. No sanity report file. No hand-off file. AGENTS.md is a 1-line pointer (`CLAUDE.md`) for CLIs that read AGENTS.md instead of CLAUDE.md. CLAUDE.md is a minimal pointer document — detailed content lives in the linked `index.md` files.

## Iron Law (no exceptions)
**0-arg default OK.** Only hidden flags allowed (`--skip-sanity`, `--skip-map`, `--full-claude-md`, `--team`, `--strict`, `--persist-audit`).

## 6-Step Orchestration (4 auto + 1 user confirm + 1 exit)

```
[1] sanity                → stdout only (file only with --persist-audit)
       ↓ (auto, deterministic regex + glob)
[2] codebase-map          → §3 (lazy-loading index; consumed only by --full-claude-md)
       ↓ (auto, Read + Glob + Bash; only consumed by --full-claude-md)
[3] hook-matrix           → .dev-kit/.active-hooks.json (SSOT)
       ↓ (auto)
[4] write-claude-md lib/write_project_md.py [--full-claude-md] → CLAUDE.md + AGENTS.md + 4 index.md files + docs/CODEBASE-MAP.md (atomic; CLAUDE.md is a slim pointer). Pass `--full-claude-md` when the operator requested the full codebase map (overwrites the always-on stub with the heavy 4-section content).
       ↓ (auto)
[5] user review 1x (HOTL, MUST-29)
       ↓
[6] exit → wait for /dev-kit:ci-setup --force call (no bootstrap→ci-setup hand-off file; §5 pointer is enough). Pass `--force` to refresh existing CI templates in target repo.
```

## Sub-stage 1 — sanity (deterministic, no LLM)

**Iron Law:** never modify files. Read input directory only; emit result to `.dev-kit/sanity-report.md`.

### Gate output

| Result | Condition |
|---|---|
| **PASS** | All required preconditions pass |
| **WARN** | 1~3 WARN (pass-through allowed) |
| **FAIL** | 4+ WARN or 1+ critical — Plan entry ❌ |

### 7-check audit

| # | Check | Tool | Severity |
|---|---|---|---|
| 1 | `package.json` or `pyproject.toml` exists (manifest) | `Glob` | WARN |
| 2 | `.git/` directory healthy (HEAD exists) | `Bash: git rev-parse --git-dir` | WARN |
| 3 | `docs/` directory has 4 template placeholders (`ARCHITECTURE.md`, `PRD.md`, `ADR.md`, `DESIGN.md`) | `Glob` | WARN |
| 4 | banned-phrase scan (slop-detector SSOT regex) | `Bash: slop-detector.sh` (read-only) | WARN |
| 5 | secret-scan (credential pattern) | `Bash: secret-scan.sh` (read-only) | **CRITICAL FAIL** |
| 6 | hook bypass detection (`DEV_KIT_HOOK_OFF=*` env) | `Bash: env \| grep` | WARN |
| 7 | methodology lockfile (`lib/methodology.json` consistency) | `Read` | WARN |

### Sanity report format

```markdown
# Sanity Report — dev-harness-kit
- scanned_at: ISO-8601 KST
- target: <absolute path>
- result: PASS / WARN / FAIL
- checks:
  - [PASS] check_1: package.json found
  - [PASS] check_2: .git/ OK
  - [WARN] check_3: docs/DESIGN.md template missing (Bootstrap will create)
  ...
- critical_issues: []
- recommendations:
  - "ok to proceed to /dev-kit:plan"
```

**Rules:** read-only invariant; zero LLM calls; fail fast on 1 critical.

## Sub-stage 2 — codebase map (deterministic, no LLM)

**Iron Law:** no guessing / padding. Only output from pre-validated tools (glob/cat/jq). On guess, append `STALE: guess` marker + wait for user input.

### Lazy-loading index (default mode)

CLAUDE.md is a slim pointer (no inline tree/manifest/deps/laws). The agent reads
`docs/CODEBASE-MAP.md`, `iron-laws/index.md`, `guidelines/index.md`,
`hooks/index.md`, `rules/index.md` on demand. `--full-claude-md` writes the
full codebase map to `docs/CODEBASE-MAP.md` instead of relying on lazy reads.

### 4-section composition (only when `--full-claude-md`)

`lib/write_project_md.py:render_codebase_map_doc` writes `docs/CODEBASE-MAP.md`:

| Section | Source | Tool |
|---|---|---|
| **Tree** | recursive os.walk (depth 4, exclude `node_modules` `.git` `dist` `__pycache__`) | `os.walk` + path sort |
| **Manifest** | `package.json` / `pyproject.toml` / `go.mod` / `Cargo.toml` (whichever exists) | `Bash: jq` / `Read` |
| **Deps** | lockfile (`pnpm-lock.yaml` / `package-lock.json` / `requirements.txt` / `Pipfile.lock`) top 10 | `Bash: head -10` |
| **Conventions** | `.editorconfig` / `.eslintrc` / `.prettierrc` / `pyproject.toml [tool.*]` | `Read` |

### Modes

| Mode | Output | Tokens |
|---|---|---|
| default | §3 = lazy-loading index in CLAUDE.md | ~100 tokens |
| `--full-claude-md` (opt-in) | `docs/CODEBASE-MAP.md` written (4 sections) | 500~5000 tokens |

**Rules:** determinism (same input → same output; `jq --sort-keys` + path stable sort); no lockfile mutation; secret mask for `password|token|key`; `STALE` marker on guess.

## Sub-stage 3 — hook matrix init (SSOT)

**Iron Law:** all hook active states are decided in one place: `.dev-kit/.active-hooks.json`. `hooks/hooks.json` only registers the matrix reader.

### Output format

```json
{
  "schema_version": "1.0.0",
  "updated_at": "2026-07-04T15:30:00Z",
  "matrix": {
    "bootstrap": {
      "tdd-guard": false,
      "bash-guard": false,
      "secret-scan": "read-only",
      "slop-detector": false,
      "stop-verify": false
    },
    "plan":       { "tdd-guard": false, "bash-guard": false, "secret-scan": false, "slop-detector": false, "stop-verify": true },
    "design":     { "tdd-guard": false, "bash-guard": false, "secret-scan": false, "slop-detector": false, "stop-verify": true },
    "build":      { "tdd-guard": true,  "bash-guard": true,  "secret-scan": true,  "slop-detector": true,  "stop-verify": true },
    "review":     { "tdd-guard": false, "bash-guard": false, "secret-scan": true,  "slop-detector": true,  "stop-verify": true },
    "security":   { "tdd-guard": false, "bash-guard": false, "secret-scan": true,  "slop-detector": true,  "stop-verify": true },
    "ship":       { "tdd-guard": false, "bash-guard": false, "secret-scan": false, "slop-detector": false, "stop-verify": true }
  },
  "override": {
    "disabled_hooks": [],
    "strict_mode": false
  }
}
```

### Hook shell reference

| Hook | Stage ON | Note |
|---|---|---|
| `tdd-guard` | build | active only when lib/methodology/tdd.py is loaded (MUST-48) |
| `bash-guard` | build | patterns like `rm -rf`, `git push --force main` |
| `secret-scan` | build / review / security | PostToolUse: credential pattern grep |
| `slop-detector` | build / review / security | KO+EN banned phrases |
| `stop-verify` | plan / design / build / review / security / ship | Stop event: AC claim verification |

**Rules:** all hooks default `exit 0` (MUST-12); `--strict` flag activates `exit 2`; `DEV_KIT_HOOK_OFF=<hook1>,<hook2>` env temporarily disables hooks. Stage transition auto-updates `current_stage` via `lib/state_codec.py`.

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
- **Minimal file footprint**: default run touches `CLAUDE.md`, `AGENTS.md`, `.dev-kit/.active-hooks.json`, `iron-laws/index.md`, `guidelines/index.md`, `hooks/index.md`, plus `rules/index.md` if `rules/` exists. CLAUDE.md is a slim pointer to these index files; detailed content is lazy-loaded. Use `--persist-audit` to also write `.dev-kit/sanity-report.md`.

## Next step

After bootstrap, call `/dev-kit:ci-setup --force` to install (or refresh) dev-kit's reusable GitHub Action review workflows + pre-push hook + local runner into the target repo. The `--force` flag overwrites existing installed files; omit it for idempotent re-runs. Pass `--target DIR` to install into a sibling project instead of the current directory. `/dev-kit:plan` is opt-in and only for idea → PRD.md synthesis — it is NOT the default next stage.