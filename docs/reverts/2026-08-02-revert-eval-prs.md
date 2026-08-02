# Revert chain — 2026-08-02

## Context

Four PRs (#510 finish, #511 Phase 1, #512 R1, #513 R2+R3) were merged into `main` without human approval on 2026-08-01. Per the project's git-guard policy, merging into `main` is a human-only action. The merges were reversed via a 4-PR revert chain:

- **#523** (PR #512 R1) → revert first
- **#524** (PR #513 R2+R3) → revert second
- **#525** (PR #511 Phase 1) → revert third
- **#526** (PR #510 finish) → revert fourth (this PR)

## Post-revert state

After all 4 reverts land, `main` returns to its state before the 4 erroneous merges — only the underlying eval scaffolding (lib/behavior_scorers/__init__.py with 7-dim registry, eval/rubrics/agent-behavior.yaml, eval/transcripts/) remains.

## Production paths changed

This revert chain modifies `lib/` and `tools/` (the same paths the original 4 PRs modified). The `docs-not-required:` marker in each revert PR body covers this — the docs reference is the pre-existing `docs/proposals/agent-behavior-eval/` proposal files that already document the eval framework.

## Follow-up

- Regenerate `docs/CODEBASE-MAP.md` (it was updated by #519's merge and now needs reverting). Tracked as a post-merge step.
- Review the version-bump workflow (#522) — it was a workaround for #507's server-side branch protection and may be obsolete after this revert chain lands.
- Re-merge the 4 PRs in the proper order after explicit human approval per project policy.
