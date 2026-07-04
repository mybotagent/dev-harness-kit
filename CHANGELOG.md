# Changelog

All notable changes to dev-harness-kit are documented here.

## [0.1.0] - 2026-07-04

### Added
- Plugin skeleton: `.claude-plugin/{marketplace, plugin/{plugin, hooks}}.json`
- 17 skills across 9 categories (bootstrap, plan, design, build, review, security, audit, shortcuts, ship)
- 15 commands (0-arg): `bootstrap / plan / design (alias) / build / review / security / ship / audit / eval / repair / config / status / onboard` + 2 shortcuts
- 5 hook scripts: `tdd-guard, bash-guard, secret-scan, slop-detector, stop-verify` (all `exit 0` advisory by default; `--strict` enables hard-block)
- lib modules: `state_codec, active_hooks_codec, write_claude_md, execute, methodology/{abc,tdd,__init__}, install.sh`
- Iron Laws SSOT in `CLAUDE.md §1` (5 laws)
- `.dev-kit/` state files (state.json, .active-hooks.json, hand-off/*.md)
- Pre-impl gate (`docs/PRE-IMPL-CHECK.md`) + 8-dimension cost analysis (`docs/COST-ANALYSIS.md`)
- 57 pytest tests passing

### Absorbed (5 → 1)
- `pm-prd-fast` → `skills/plan/plan-ralph/`
- `interview-harness-skills` → merged into `plan-ralph`
- `dev-harness` → `lib/execute.py` + `skills/build/build-*`
- `claude-review-plugins` → `skills/review/review-code` + `skills/security/security-scan` + `lib/install.sh`
- `slop-shield` → `hooks/{slop-detector, secret-scan}.sh` + Iron Laws (CLAUDE.md §1)

### Deprecated
- Each of the 5 original repos has `DEPRECATED.md` → directs to this plugin

### Pending (next milestones)
- A2A typed interface (lib/a2a_codec.py + lib/a2a_contracts/*.schema.json v1.0.0)
- Sub-agent runner (lib/sub_agent_runner.py + worktree isolation)
- Eval runner + 9 specialized fixers + golden set
- /dev-kit:eval and /dev-kit:repair runtime
- E2E workflow validation (bootstrap → plan → build → review → ship)
