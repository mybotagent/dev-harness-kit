> [← Skills index](README.md) · [Project README](../../README.md)

# `bootstrap`

**Category:** `bootstrap` · **Alpha:** `state` · **Invocation:** `/dev-kit:bootstrap` (human-invoked)

`bootstrap` is the minimal first-run setup for a fresh repository: it writes exactly three files — `CLAUDE.md`, `AGENTS.md`, and `.dev-kit/.active-hooks.json` — with no noise files by default. It exists as its own skill because every dev-kit project needs one deterministic, LLM-light entry point that establishes the project SSOT (single source of truth) before any planning or building begins.

## When to use it

- The user runs `/dev-kit:bootstrap` for the first time on a new project.
- The user wants to refresh `CLAUDE.md` / `active-hooks.json`.

## How it works

Bootstrap runs three deterministic sub-stages followed by the write step, in a 6-step orchestration (4 auto steps, 1 user confirmation, 1 exit):

1. **Sanity** (deterministic, no LLM) — a 7-check audit: manifest presence (`package.json`/`pyproject.toml`), `.git/` health, `docs/` template placeholders, a banned-phrase scan (slop-detector SSOT regex), a secret-scan (credential pattern — this is the one **CRITICAL FAIL** check, all others are WARN), a hook-bypass detection (`DEV_KIT_HOOK_OFF=*` env), and a methodology lockfile consistency check (`lib/methodology.json`). Result is PASS (all pass), WARN (1-3 warnings, pass-through allowed), or FAIL (4+ warnings or 1+ critical — blocks Plan entry). Output goes to stdout only; a file (`.dev-kit/sanity-report.md`) is written only with `--persist-audit`.
2. **Codebase map** (deterministic, no LLM) — default mode writes a lazy-loading index (~100 tokens) directly into CLAUDE.md §3, deferring to on-demand reads of canonical source files. With `--full-claude-md`, a full 4-section map (Tree via `os.walk` depth 4, Manifest, Deps top-10, Conventions) is written instead to `docs/CODEBASE-MAP.md` via `lib/write_project_md.py:render_codebase_map_doc`.
3. **Hook matrix init** — writes `.dev-kit/.active-hooks.json` as the single source of truth for which hooks (`tdd-guard`, `bash-guard`, `secret-scan`, `slop-detector`, `stop-verify`) are active per stage (bootstrap/plan/design/build/review/security/ship). `hooks/hooks.json` only registers the matrix reader; all activation decisions live in the JSON.
4. **write-claude-md** — `lib/write_project_md.py` writes `CLAUDE.md` and `AGENTS.md` (a 1-line pointer to CLAUDE.md for CLIs that read AGENTS.md) atomically, sections §1-§5.
5. **User review** (HOTL, human-on-the-loop, MUST-29) — one confirmation step.
6. **Exit** — waits for the user to call `/dev-kit:ci-setup --force`; there is no bootstrap→ci-setup hand-off file, since the §5 pointer in CLAUDE.md is sufficient.

Hidden flags (no visible option prompts — MUST-NOT-13): `--skip-sanity`, `--skip-map`, `--slim|--full`, `--team`, `--strict`, `--persist-audit`. With `--strict`, all hooks default to `exit 2` instead of `exit 0`.

## Usage

```bash
/dev-kit:bootstrap [--skip-sanity] [--skip-map] [--slim|--full] [--team] [--strict] [--persist-audit]
```

| Flag | Effect |
|---|---|
| *(0-arg)* | Runs the full sanity → codebase-map → hook-matrix → write pipeline; touches only `CLAUDE.md`, `AGENTS.md`, `.dev-kit/.active-hooks.json`. |
| `--skip-sanity` | Skips the sanity sub-stage. |
| `--skip-map` | Skips the codebase-map sub-stage. |
| `--slim` / `--full` | Controls CLAUDE.md verbosity mode. |
| `--full-claude-md` | Writes the full 4-section codebase map to `docs/CODEBASE-MAP.md` instead of the lazy-loading index. |
| `--team` | Team-mode variant (hidden flag). |
| `--strict` | All hooks default to `exit 2` instead of `exit 0`. |
| `--persist-audit` | Also writes `.dev-kit/sanity-report.md`. |

## Output

Three files on a fresh repo: `CLAUDE.md`, `AGENTS.md`, `.dev-kit/.active-hooks.json`. With `--persist-audit`, also `.dev-kit/sanity-report.md`. With `--full-claude-md`, also `docs/CODEBASE-MAP.md`.

## Related

- [bootstrap-full](bootstrap-full.md) — composes this skill with `/dev-kit:ci-setup` into one call.
- [ci-setup](ci-setup.md) — the canonical next step (`/dev-kit:ci-setup --force`) after bootstrap.
- `/dev-kit:plan` — opt-in idea → PRD.md synthesis; not the default next stage.

---
*Source: [`skills/bootstrap/SKILL.md`](../../skills/bootstrap/SKILL.md)*
