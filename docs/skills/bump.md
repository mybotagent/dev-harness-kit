> [← Skills index](README.md) · [Project README](../../README.md)

# `bump`

**Category:** `ship` · **Alpha:** `state` · **Invocation:** `/dev-kit:bump [major|minor|patch]` (human-invoked)

`bump` performs an explicit, user-triggered version bump of `.claude-plugin/plugin.json`, cutting a `chore/bump-vX.Y.Z` branch from `origin/main` and opening a PR whose squash-merge re-fires `.github/workflows/version-bump.yml`. It mirrors the auto-bump the workflow already performs, but exists as its own skill for race recovery — redoing an orphaned bump locally after the workflow leaves a tip without a PR — and for cutting an explicit pre-PR release candidate.

## When to use it

- The user types `/dev-kit:bump [major|minor|patch]`.
- The user wants an explicit local bump before opening a PR (e.g. cutting a release candidate).
- Race recovery: the version-bump workflow left an orphan tip with no PR, and the bump needs to be redone locally.

## How it works

Pre-flight (all read-only checks, fail loud on any violation): confirm `gh auth status`, confirm the current branch is not `main`/`master`, read `CURRENT_VERSION` from `.claude-plugin/plugin.json` via `jq`, and read `HEAD_MSG` via `git log -1 --format=%s`. The skill then refuses to proceed if `HEAD_MSG` already matches the same idempotency regex used at `version-bump.yml:98` (prevents double-bump loops), refuses if `.claude-plugin/plugin.json` has an uncommitted diff against `HEAD`, and refuses if `version-bump.yml` has any in-flight run (`gh run list --workflow=version-bump.yml --status=in_progress`).

Behavior: parse the bump type argument (default `patch`; `minor`/`major` reset trailing components to 0 per semver §11), fetch `origin/main` and re-verify the current version matches (a TOCTOU guard against `origin/main` advancing mid-run), check out `chore/bump-v${NEW_VERSION}` from `origin/main`, bump the version field with `jq`, commit as `chore(release): bump dev-kit to v${NEW_VERSION}` (no `[skip ci]` — a global skip would suppress the tag-emitting workflow too), push, and open a PR via `gh pr create`. It then writes `.dev-kit/hand-off/bump→ship.md` with the PR number, new version, and source branch, pointing to `/dev-kit:ship` as the next step.

Rules: one bump = one branch = one PR (never amend an existing bump branch — cut a new one); no local tagging (the workflow tags post-merge at `version-bump.yml:231-263`); no `--no-verify`; no `git push --force` to `main` (`--force-with-lease` is allowed only on the bump branch); pure bash + `jq`, no dedicated `lib/bump.py`.

## Usage

```bash
/dev-kit:bump [major|minor|patch]
```

| Argument | Effect |
|---|---|
| *(none)* | Defaults to `patch`. |
| `patch` | Increments the patch component. |
| `minor` | Increments minor, resets patch to 0. |
| `major` | Increments major, resets minor and patch to 0. |

## Output

- **stdout**: the pre-flight probe table (gh auth / branch / version / head_msg), the computed `NEW_VERSION`, the `gh pr create` URL, and the hand-off file path.
- **`.dev-kit/hand-off/bump→ship.md`**: PR number, `NEW_VERSION`, source branch, and `Next step: /dev-kit:ship`.

Failure exit codes surface as errors from the pre-flight checks (bad gh auth, on `main`, idempotent no-op, uncommitted diff, in-flight workflow run, or an invalid bump-type argument).

## Related

- [ship](ship.md) — the release gate this skill hands off to once the bump PR is merged and tagged.
- [babysit-pr](babysit-pr.md) — useful for babysitting the bump PR itself during review.
- `.github/workflows/version-bump.yml` — the automated counterpart this skill mirrors and recovers.
- `tests/test_bump_workflow.py` — pins the idempotency regex and the no-`[skip ci]` invariant.

---
*Source: [`skills/bump/SKILL.md`](../../skills/bump/SKILL.md)*
