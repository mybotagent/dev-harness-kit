---
name: bootstrap-full
category: bootstrap
description: One-shot setup for new projects. Runs /dev-kit:bootstrap + /dev-kit:ci-setup in a single call — writes CLAUDE.md + AGENTS.md + active-hooks.json, then installs the 15 CI templates + pre-push hook + marker.
alpha: state
when_to_use:
  - User types `/dev-kit:bootstrap-full` on a brand-new project and wants CLAUDE.md + CI in one shot
  - User does not want to chain `/dev-kit:bootstrap` then `/dev-kit:ci-setup` manually
  - User wants the canonical "new repo" entry point instead of memorizing two skills
allowed-tools: Read Write Glob Bash AskUserQuestion
disallowed-tools: Agent WebFetch
model: opus
disable-model-invocation: false
user-invocable: true
---
> [← Skills index](../../README.md)

# /dev-kit:bootstrap-full — One-Shot Setup (CLAUDE.md + CI)

## What it does

Runs the full new-project pipeline in a single invocation: the three deterministic sub-stages now inlined into `bootstrap` (sanity → codebase-map → hook-matrix) + `lib/write_project_md.py` (writes `CLAUDE.md` as a slim pointer doc, `AGENTS.md` symlink, `.dev-kit/.active-hooks.json`, plus `iron-laws/index.md` + `guidelines/index.md` + `hooks/index.md` + `rules/index.md` for the lazy-loaded content), then immediately hands off to the same `lib/ci_setup.py:install_ci_config()` path used by `/dev-kit:ci-setup` (installs the 15 CI templates + pre-push hook + writes `.dev-kit/ci-config.json` marker + runs Phase 1.5 pre-flight probe + Phase 1.7 lint + Phase 3 verify). End state on disk is identical to running `/dev-kit:bootstrap` followed by `/dev-kit:ci-setup --force`, with no intermediate user prompts.

`/dev-kit:bootstrap` and `/dev-kit:ci-setup` remain standalone for granular cases (refreshing just one half, or onboarding an existing project that already has CLAUDE.md but no CI).

## Iron Law

**0-arg default OK. Hidden flags only:** `--target DIR` (install into a sibling project instead of `$PWD`), `--skip-ci` (stop after Phase 1 — useful when CI is added in a separate later session), `--force` (overwrite existing CI templates during Phase 2 — passed through to `install_ci_config(force=True)`), `--skip-verify` (skip Phase 3 verify), `--full-claude-md` (CLAUDE.md mode — passed through to `write_project_md.py`; overwrites the stub at `docs/CODEBASE-MAP.md` with the full 4-section codebase map), `--skip-sanity`, `--skip-map`, `--strict`, `--persist-audit`.

No visible flags. No option prompts (MUST-NOT-13).

## 4-Phase Orchestration (3 auto + 1 exit)

```
[1] bootstrap       (delegates to bootstrap sub-stages + write_project_md.py)
       ├── sanity                     → stdout only
       ├── codebase-map               → §3 lazy-loading index (consumed only by --full-claude-md)
       ├── hook-matrix                → .dev-kit/.active-hooks.json (SSOT)
       └── write_project_md.py [--full-claude-md] → CLAUDE.md + AGENTS.md + 4 index.md files + docs/CODEBASE-MAP.md stub (atomic; CLAUDE.md is a slim pointer)
       ↓ (auto; --skip-ci short-circuits here)
[2] ci-setup        (delegates to lib/ci_setup.py)
       ├── 1.5 pre-flight probe       → OK/WARN/INFO/SKIP per gh dep (non-blocking)
       ├── install_ci_config()        → 15 EXPECTED_PATHS + .dev-kit/ci-config.json marker
       ├── 1.7 lint pass              → warnings printed as rows; non-fatal
       └── 4 post-install checklist   → ALWAYS printed on success (issue #212-D2)
       ↓ (auto; --skip-verify short-circuits here)
[3] verify          (delegates to ci-setup Phase 3)
       ├── bash -n on every .sh
       ├── ast.parse on every .py
       ├── scripts/validate.py        → expect "OK: CI installation valid"
       └── scripts/ci-local.sh        → expect exit 0
       ↓
[4] exit → pointer to /dev-kit:plan, then /dev-kit:build (plan → build is the canonical sequence; ci-config.json marker satisfies build's pre-flight gate)
         AND pointer to /dev-kit:ci-doctor for post-install verification (issue #212-D1).
```

## Hook integration (stage=bootstrap)

| Hook | Mode |
|---|---|
| tdd-guard | OFF |
| bash-guard | OFF |
| secret-scan | read-only |
| slop-detector | OFF |
| stop-verify | OFF |

Same matrix as `/dev-kit:bootstrap`. `active-hooks.json` SSOT auto-initialized (MUST-13). With `--strict` all hooks `exit 2`.

## Rules

- **0-arg UX (MUST-21)**: zero args. Branching via `when_to_use` auto-match.
- **Single hand-off**: no intermediate prompt between Phase 1 and Phase 2.
- **Idempotent CI**: Phase 2 is marker-driven (same as standalone `ci-setup`). Without `--force`, re-runs are no-op on already-installed files.
- **Never modifies dev-kit's own repo**: writes only into the target (default `$PWD`, or `--target DIR`).
- **Minimal file footprint**: default run touches `CLAUDE.md`, `AGENTS.md`, `.dev-kit/.active-hooks.json`, `iron-laws/index.md`, `guidelines/index.md`, `hooks/index.md` (+ `rules/index.md` if `rules/` exists), `.dev-kit/ci-config.json`, and the 15 CI template paths listed in `skills/ci-setup/SKILL.md`. CLAUDE.md is a slim pointer; detailed content lives in the linked index files. Use `--skip-ci` to land only the bootstrap set.

## Combined summary (printed on success)

```
[bootstrap]  created: CLAUDE.md (slim pointer), AGENTS.md, .dev-kit/.active-hooks.json, iron-laws/index.md, guidelines/index.md, hooks/index.md (+ rules/index.md if rules/ exists)
[ci-setup]   created: 15 files (see ci-setup/SKILL.md)
             marker:   .dev-kit/ci-config.json
             verify:   OK (validate.py + ci-local.sh)
             warnings: 0
```

## Files installed (CI half — see `skills/ci-setup/SKILL.md` for the full 15-row table)

`.github/workflows/{ci,auto-fix-pr,review}.yml`, `.githooks/pre-push`, `scripts/{validate.py,test.sh,branch-policy.sh,ci-local.sh}`, `hooks/{worktree-guard.sh,session-start-check.sh,lib/worktree-detect.sh,hooks.json}`, `.claude/rules/git-workflow.md`, `tests/test_worktree_guard.py`.

## Next step

After `/dev-kit:bootstrap-full`, follow this sequence:

1. The post-install checklist (`POST_INSTALL_CHECKLIST` in `lib/ci_setup.py`) prints automatically at the end of Phase 2 with concrete `gh secret set` commands, branch-protection notes, and the bootstrap-PR caveat. Do these in order.
2. Run `/dev-kit:ci-doctor` (issue #212-D1) for a one-shot PASS/FAIL audit. Re-run after each remediation until `ci-doctor verdict: PASS`.
3. Run `/dev-kit:plan` to synthesize `PRD.md` + `phases/` from the user's idea, then `/dev-kit:build` (the `.dev-kit/ci-config.json` marker satisfies `skills/build/SKILL.md`'s pre-flight gate). This plan → build order is the canonical sequence; `/dev-kit:plan` is required when idea → PRD artifacts are not yet on disk.

For incremental refresh, run `/dev-kit:ci-setup --force` (CI half) or `/dev-kit:bootstrap` (CLAUDE.md half) independently — both remain invocable.
