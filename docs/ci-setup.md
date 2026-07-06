# `/dev-kit:ci-setup` — Install Dev-Kit's CI Templates

The `/dev-kit:ci-setup` skill installs dev-kit's reusable CI workflow templates, Git hooks, and local-runner scripts into any project that has already been bootstrapped via `/dev-kit:bootstrap`. It exists so the same CI shape — branch-policy guards, three-job validate/test/auto-fix, severity-gated review — can be replicated across every repo in your fleet with one command.

## When to use it

Run `/dev-kit:ci-setup` once per project, after `/dev-kit:bootstrap` and before `/dev-kit:build`. The skill is idempotent, so re-running it is safe (use `--force` to refresh templates after dev-kit upgrades its CI shape).

## What gets installed

The skill copies 8 files from the `templates/ci/` source tree into the target project:

| Path | Purpose |
|---|---|
| `.github/workflows/ci.yml` | Branch-policy warn + `pytest` test + `validate.py` validator jobs |
| `.github/workflows/auto-fix-pr.yml` | Auto-fix loop on `changes_requested` review (5-iteration cap, label counter, forbidden-path guard) |
| `.github/workflows/review.yml` | `/dev-kit:review` (3-dim) + `/dev-kit:security` (10-dim) PR fan-out + severity gate |
| `.githooks/pre-push` | Client-side block of `git push` to `main`; activate with `git config core.hooksPath .githooks` |
| `scripts/validate.py` | Extracted from dev-kit's own `ci.yml` 5-step validate job; checks install + marker + bash syntax |
| `scripts/test.sh` | `pytest` wrapper (gracefully skips if no `tests/` directory) |
| `scripts/branch-policy.sh` | Mirror of `pre-push` for CI script context |
| `scripts/ci-local.sh` | Local-runner entrypoint: `validate.py` + `test.sh` + optional `act -l` |

After install, the marker file `.dev-kit/ci-config.json` is written at the project root. The marker is the **contract** with `/dev-kit:build` — without it, build refuses to start.

## How to verify

```bash
bash scripts/ci-local.sh
```

This is the same set of checks GitHub Actions runs in `ci.yml`, but without requiring `nektos/act` or push access. Expected output:

```
=== validate ===
validate.py — repo_root=/path/to/repo
  - installation complete OK (8 files)
  - ci-config marker OK (v0.1.0)
  - bash syntax OK (5 scripts clean)
  - test runner OK (bash -n clean)
OK: CI installation valid

=== test ===
... (pytest output, or "skip" if no tests/)
```

Optional: `act -l` lists the discovered workflows if `nektos/act` is installed; the script warns and falls back gracefully if not.

## Hand-off to build

The skill writes `.dev-kit/ci-config.json` as a marker. `/dev-kit:build` will refuse to start unless this marker exists and `ci_setup_version` is current. If you see the gate message:

```
Pre-flight gate: refuse to start if `.dev-kit/ci-config.json` is absent.
Run `/dev-kit:ci-setup` first.
```

…run `/dev-kit:ci-setup` (or re-run with `--force` if the marker is stale).

## FAQ

**Q: Will it overwrite my existing `.github/workflows/ci.yml`?**
A: No — re-running without `--force` is idempotent and will skip existing files. Use `--force` to refresh after dev-kit's templates evolve.

**Q: Do I need `nektos/act`?**
A: No. `scripts/ci-local.sh` runs the same validators locally on any POSIX host. `act` is optional — install from <https://nektos.act.dev> if you want full GitHub Actions parity (e.g., Docker-based matrix testing).

**Q: How do I uninstall?**
A: Delete `.dev-kit/ci-config.json`, then `git rm` the 8 installed files (or `rm -rf` them if the target repo is freshly built and not yet under version control). The CI templates are intentionally not deeply integrated — they're plain files you own.

**Q: Why is the marker file versioned?**
A: So `/dev-kit:build` can refuse to run on stale templates after a dev-kit upgrade that changes the CI shape. Re-run `/dev-kit:ci-setup --force` after upgrading dev-kit to pick up new validator logic.

**Q: Can I customize a file without losing changes on refresh?**
A: Yes — when `/dev-kit:ci-setup --force` rewrites an `EXPECTED_PATHS` file, it does so verbatim from the template. Customizations live OUTSIDE that set (e.g., extra workflow files in `.github/workflows/`, additional Git hooks beyond `pre-push`). Files outside `EXPECTED_PATHS` are never touched.
