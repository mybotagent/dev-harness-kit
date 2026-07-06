---
name: ci-setup
category: bootstrap
description: Install dev-kit's reusable CI workflow templates into a target project. Idempotent + version-gated via `.dev-kit/ci-config.json`. Hand-off to /dev-kit:build.
when_to_use: |
  - User types `/dev-kit:ci-setup` after `/dev-kit:bootstrap`
  - User wants the same CI shape (branch-policy + validate + test + auto-fix) in a new repo
  - User is preparing a repo for /dev-kit:build (ci-setup is a precondition)
  - Re-run to refresh templates (`--force` flag)
allowed-tools: Read Write Glob Bash AskUserQuestion
disallowed-tools: Agent WebFetch
model: opus
disable-model-invocation: false
---

# /dev-kit:ci-setup — Install CI Templates

## Iron Law

**0-arg default OK; `--force` is the only visible flag. Hidden flags: `--target DIR`, `--skip-verify`. Never modifies the dev-kit repo (only writes into target). `dev-kit:build` will refuse to start without the `.dev-kit/ci-config.json` marker this skill writes.**

## 3-Phase Orchestration

### Phase 1 — Detect (deterministic, no LLM call)

1.1. Parse arguments: `--target DIR` defaults to `$PWD`; `--force` overwrites existing files; `--skip-verify` skips Phase 3.
1.2. Check `python3 ≥ 3.10` (dev-kit requirement).
1.3. **Delegate version short-circuit to `lib/ci_setup.py:install_ci_config()`** — it reads the existing marker and returns a no-op `InstallReport` (all paths in `skipped`, no files touched, marker not rewritten) when `ci_setup_version` matches the current plugin's version AND `force=False`. The skill body surfaces this as "already installed; pass `--force` to refresh" and exits 0.
1.4. Probe target prerequisites: `.git/` (warn if absent — CI is git-themed), `.github/` (create if absent).

### Phase 2 — Install (via `lib/ci_setup.py`)

```bash
python3 -c "
from pathlib import Path
import sys
sys.path.insert(0, 'lib')
from ci_setup import install_ci_config
report = install_ci_config(Path('${TARGET_DIR}'), force=${FORCE})
print(f'created={len(report.created)} overwritten={len(report.overwritten)} skipped={len(report.skipped)} errors={len(report.errors)}')
sys.exit(0 if report.ok and not report.errors else 1)
"
```

2.1. `lib/ci_setup.py:install_ci_config()` resolves the plugin's `templates/ci/` tree (relative to its own `__file__`).
2.2. For each of the 8 `EXPECTED_PATHS` (3 workflow .yml + 1 .githooks/pre-push + 4 scripts):
  - Skip if exists and `force=False` (idempotent).
  - Overwrite if exists and `force=True`.
  - `shutil.copy2` (preserves mtime for git diff stability).
2.3. `chmod 0o755` on shell scripts + pre-push + validate.py.
2.4. Write `.dev-kit/ci-config.json` marker via `atomic_write_json` (POSIX-atomic; no partial-write on crash).

### Phase 3 — Verify (deterministic, exit code quoted)

Unless `--skip-verify`:

3.1. `bash -n` on every installed `.sh` and `.githooks/pre-push`.
3.2. `python3 -c "import ast; ast.parse(open(p).read())"` on every installed `.py`.
3.3. `python3 scripts/validate.py` — expect exit 0, stdout contains `OK: CI installation valid`.
3.4. `bash scripts/ci-local.sh` — expect exit 0 (skips test if no `tests/`).
3.5. `act -l 2>/dev/null || echo "act not installed; falling back to scripts/ci-local.sh"` — WARN, not FAIL.

Print summary table (file → outcome: created/overwritten/skipped/error) + pointer to `docs/ci-setup.md`.

## Rules

- **Idempotent by default** — re-running without `--force` writes zero files; the marker is rewritten with a fresh `installed_at`.
- **`--force` overwrites** ONLY files inside `EXPECTED_PATHS`. Never delete user-created files outside that set.
- **Never modifies dev-kit's own repo** — only writes into the target.
- **Refuse to install onto a non-directory** — raise clearly.
- **Failure exit codes**: 1 = arg error, 2 = marker present + no `--force`, 3 = copy failure, 4 = verify failure.

## Hand-off

- On success, `.dev-kit/ci-config.json` is written. This is the **contract** with `/dev-kit:build`.
- `/dev-kit:build` refuses to start if this marker is absent or `ci_setup_version < "0.1.0"` — see `skills/build/SKILL.md` pre-flight gate.
- For full usage docs: see `docs/ci-setup.md`.

## Files Installed (8 expected paths)

| Path | Purpose |
|---|---|
| `.github/workflows/ci.yml` | Branch-policy warn + test + validate jobs |
| `.github/workflows/auto-fix-pr.yml` | Auto-fix loop on `changes_requested` review (5-iter cap) |
| `.github/workflows/review.yml` | `/dev-kit:review` (3-dim) + `/dev-kit:security` (10-dim) PR fan-out + severity gate |
| `.githooks/pre-push` | Client-side block of `git push` to main (activation: `git config core.hooksPath .githooks`) |
| `scripts/validate.py` | Extracted from dev-kit's `ci.yml` 5-step validate job; checks install + marker + bash syntax |
| `scripts/test.sh` | Pytest wrapper (gracefully skips if no `tests/`) |
| `scripts/branch-policy.sh` | Mirror of `pre-push` for CI script context |
| `scripts/ci-local.sh` | Local-runner entrypoint: `validate.py` + `test.sh` + optional `act -l` |

## Iron Law (repeated, for emphasis)

**Idempotent. Marker-driven. Never modifies dev-kit's own repo.**
