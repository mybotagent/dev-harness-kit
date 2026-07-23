> [← Skills index](README.md) · [Project README](../../README.md)

# `bootstrap-full`

**Category:** `bootstrap` · **Alpha:** `state` · **Invocation:** `/dev-kit:bootstrap-full` (human-invoked)

`bootstrap-full` composes `/dev-kit:bootstrap` and `/dev-kit:ci-setup` into a single one-shot call for brand-new projects. It exists as the canonical "new repo" entry point so the user doesn't have to remember to chain the two skills manually — the end state on disk is identical to running `/dev-kit:bootstrap` followed by `/dev-kit:ci-setup --force`, with no intermediate prompts. `bootstrap` and `ci-setup` remain standalone for granular cases (refreshing just one half, or onboarding a project that already has one half in place).

## When to use it

- The user types `/dev-kit:bootstrap-full` on a brand-new project and wants CLAUDE.md + CI in one shot.
- The user does not want to chain `/dev-kit:bootstrap` then `/dev-kit:ci-setup` manually.
- The user wants the canonical "new repo" entry point instead of memorizing two skills.

## How it works

A 4-phase orchestration (3 auto phases + 1 exit):

1. **Bootstrap** — delegates to the same bootstrap sub-stages (sanity → codebase-map → hook-matrix) plus `lib/write_project_md.py`, producing `CLAUDE.md`, `AGENTS.md`, and `.dev-kit/.active-hooks.json`.
2. **CI-setup** — delegates to `lib/ci_setup.py`: runs the Phase 1.5 pre-flight probe (OK/WARN/INFO/SKIP per `gh` dependency, non-blocking), calls `install_ci_config()` to land the 15 expected CI paths plus the `.dev-kit/ci-config.json` marker, runs the Phase 1.7 lint pass (warnings only, non-fatal), and always prints the Phase 4 post-install checklist on success.
3. **Verify** — delegates to ci-setup's Phase 3: `bash -n` on every `.sh`, `ast.parse` on every `.py`, `scripts/validate.py` (expects `"OK: CI installation valid"`), and `scripts/ci-local.sh` (expects exit 0).
4. **Exit** — points to `/dev-kit:plan` then `/dev-kit:build` as the canonical next sequence, and to `/dev-kit:ci-doctor` for post-install verification.

Hidden flags only (no visible option prompts, MUST-NOT-13): `--target DIR` (install into a sibling project), `--skip-ci` (stop after Phase 1), `--force` (overwrite existing CI templates in Phase 2), `--skip-verify` (skip Phase 3), `--slim|--full` (CLAUDE.md mode, passed through), `--skip-sanity`, `--skip-map`, `--strict`, `--persist-audit`.

The skill never modifies dev-kit's own repo — it writes only into the target (default `$PWD`, or `--target DIR`). CI installation is marker-driven and idempotent: without `--force`, re-runs are a no-op on already-installed files.

## Usage

```bash
/dev-kit:bootstrap-full [--target DIR] [--skip-ci] [--force] [--skip-verify] [--slim|--full]
```

| Flag | Effect |
|---|---|
| *(0-arg)* | Full pipeline against `$PWD`: bootstrap → ci-setup → verify. |
| `--target DIR` | Installs into a sibling project instead of `$PWD`. |
| `--skip-ci` | Stops after Phase 1 (bootstrap only). |
| `--force` | Overwrites existing CI templates during Phase 2. |
| `--skip-verify` | Skips Phase 3 verification. |
| `--slim` / `--full` | CLAUDE.md verbosity mode, passed through to `write_project_md.py`. |

## Output

Default run touches `CLAUDE.md`, `AGENTS.md`, `.dev-kit/.active-hooks.json`, `.dev-kit/ci-config.json`, plus the 15 CI template paths: `.github/workflows/{ci,auto-fix-pr,review}.yml`, `.githooks/pre-push`, `scripts/{validate.py,test.sh,branch-policy.sh,ci-local.sh}`, `hooks/{worktree-guard.sh,session-start-check.sh,lib/worktree-detect.sh,hooks.json}`, `.claude/rules/git-workflow.md`, `tests/test_worktree_guard.py`. A combined summary table is printed on success (created/marker/verify/warnings). `--skip-ci` lands only the first three files.

## Related

- [bootstrap](bootstrap.md) — the CLAUDE.md-writing half this skill composes.
- [ci-setup](ci-setup.md) — the CI-installing half this skill composes; see it for the full 15-row file table.
- `/dev-kit:ci-doctor` — recommended post-install PASS/FAIL audit.
- `/dev-kit:plan`, `/dev-kit:build` — the canonical sequence after `bootstrap-full` completes.

---
*Source: [`skills/bootstrap-full/SKILL.md`](../../skills/bootstrap-full/SKILL.md)*
