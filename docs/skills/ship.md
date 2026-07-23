> [← Skills index](README.md) · [Project README](../../README.md)

# `ship`

**Category:** `ship` · **Alpha:** `state` · **Invocation:** `/dev-kit:ship` (human-invoked)

`ship` is the release gate: a 0-arg check that confirms the pre-push main-block passed, the review verdict is Approve, and the CHANGELOG is current, then cuts and pushes the release tag. It exists as its own skill because tagging a release is a distinct, deliberate human action separate from merging a PR — the gate only fires once, at the moment the maintainer decides to cut a release.

## When to use it

- The user types `/dev-kit:ship`.
- At release cutoff, once a PR has an Approve verdict and CI is green.

## How it works

`ship` runs four steps in order: (1) verify the pre-push main-block passed (the gh-autoswitch check), (2) check that the Review verdict is Approve — a separate security scan pass is also acceptable, (3) auto-generate the CHANGELOG entry, and (4) create and push the git tag. The skill is read-only over the repo other than the tag push itself: its `allowed-tools` are `Read Bash` only, with `Write Edit WebFetch` disallowed, and it runs on `haiku` since the logic is a deterministic gate check, not authored content.

Iron Law for this skill: no direct push to `main` (PRs only), no `--no-verify` abuse, and no auto-merge — the user has already reviewed before `ship` runs.

## Usage

```bash
/dev-kit:ship
```

No flags — 0-arg only.

## Output

A git tag pushed to the remote, plus a CHANGELOG entry reflecting the release. `stop-verify` is ON for this stage, so the skill's completion claim must include the quoted evidence for the main-block validation.

## Related

- [bump](bump.md) — the explicit version-bump skill that typically precedes `ship`; its hand-off file `.dev-kit/hand-off/bump→ship.md` points here.
- [babysit-pr](babysit-pr.md) — recommended when the loop terminates with an approved PR, to hand off toward `ship`.
- [review](review.md), [security](security.md) — sources of the Approve verdict this gate requires.

---
*Source: [`skills/ship/SKILL.md`](../../skills/ship/SKILL.md)*
