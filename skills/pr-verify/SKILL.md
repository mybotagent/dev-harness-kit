---
name: pr-verify
category: ship
description: Deterministic PR verification — fresh `gh pr view` + check + comment fetches on every call. Catches the "stale CI / LLM-judge still in progress" false positive the babysit flow had.
alpha: enforcement
when_to_use:
  - User types /dev-kit:pr-verify [<pr-number>]
  - Before any claim that a PR is "ready to merge" / "all green" / "approved"
  - At the START of every babysit iteration, before reporting status
  - Whenever a previous babysit message said "all green" but the user suspects the data was stale
allowed-tools: Read Write Bash Glob
disallowed-tools: Agent Edit
model: sonnet
disable-model-invocation: false
user-invocable: true
---

> [← Skills index](../../README.md)

# /dev-kit:pr-verify — deterministic PR verification

## What it does

Runs **five gates** against a single PR, fetching state from GitHub
freshly on every invocation. No cache, no in-process memoization,
no filesystem state. The report's `checked_at` is the single
timestamp the caller should trust.

The skill was created because the previous babysit flow trusted
whatever `gh pr checks` and the PR-comment stream happened to
contain at the moment of the call. On multi-commit PRs the latest
LLM-judge verdict on a *new* run would post a NEW comment alongside
the old one, but the babysit skill's pass condition read *any*
`Approve` text without checking that the **newest** run also
approved. Operators were told the PR was "all green" while the
most recent job was still failing.

This skill is the deterministic answer:

  1. **EVERY call fetches state fresh from GitHub** (no in-process
     cache, no filesystem cache, no module-level memoization).
  2. **EVERY gate is reported with the timestamp of the fetch**
     that produced it, so a stale or skipped gate is visible to
     the caller.
  3. **The pass condition is the AND of all gates**; any
     pending/failed gate yields a non-pass result with a one-line
     "BLOCKER" per gate.
  4. **The output is structured** (a printable summary table) so
     the caller — human or babysit loop — can verify the verdict
     instead of trusting prose.

## Gates

  **G1. PR state is `OPEN`.** Closed / merged / draft = fail.

  **G2. Every CI check is in a terminal success state.**
     `pass` and `skipping` buckets are terminal-pass; `pending` is
     "still running" (NOT a pass); `fail` is fail. The verifier
     reads `gh pr checks --json bucket` directly so a still-running
     review never claims "approved".

  **G3. The most recent LLM-judge verdict (parsed from the most
     recent `claude[bot]` comment) is `Approve`.** The parser
     picks the comment with the latest `updated_at` that contains
     a `**Verdict:**` line. If the most recent run is still in
     progress (no verdict yet), the gate reports `MISSING` and
     fails.

  **G4. No `<!-- dev-kit-verdict-audit -->` comment records a
     workflow-run whose `status=failure` was paired with
     `verdict=Approve`.** This is the false positive the babysit
     skill had: the audit line said `verdict=Approve` but the
     workflow's exit code was `failure` (e.g. the LLM API errored
     or the workflow self-validated). G4 reads the audit comments
     directly and flags the discrepancy.

  **G5. The merge state is `CLEAN` or `BEHIND`.** BEHIND is a
     soft pass (the branch can merge after a rebase);
     BLOCKED / DIRTY / UNKNOWN are hard fails.

## Usage

```bash
# From the PR's branch worktree, or pass --pr explicitly:
/dev-kit:pr-verify               # auto-detects PR for current branch
/dev-kit:pr-verify 579           # explicit PR number
/dev-kit:pr-verify --pr 584 --repo sh-ai-x/dev-harness-kit
```

Output is a single-page summary:

```
PR #579 (sh-ai-x/dev-harness-kit) — checked at 2026-08-06T01:07:08+00:00
  Verdict: NOT APPROVED
  [G1] PASS PR state is OPEN: state=OPEN, isDraft=False, mergeStateStatus=BEHIND
  [G2] FAIL every CI check is in a terminal success state: FAILED: severity gate (review + security)
  [G3] FAIL most recent LLM-judge verdict is Approve: latest verdict: Changes Requested
  [G4] PASS no audit comment with status=failure + verdict=Approve: no false-positive pairs
  [G5] PASS mergeStateStatus is CLEAN or BEHIND: mergeStateStatus=BEHIND, mergeable=MERGEABLE
  Blockers:
    - [G2] every CI check is in a terminal success state: FAILED: severity gate (review + security)
    - [G3] most recent LLM-judge verdict is Approve: latest verdict: Changes Requested
```

Exit code 0 if all five gates pass; 1 otherwise. The summary is
emitted to stdout regardless; the blockers are emitted to stderr
so they can be filtered separately.

## Iron Law (L3 evidence)

The verifier's own claim "all five gates green" must be backed by
the per-gate evidence in the output. The `checked_at` timestamp
is the single piece of state the caller trusts; per-gate
`fetched_at` values are derived from the same call.

## Hand-off

The verifier's output is a drop-in for the babysit skill's
"REVIEW_REQUIRED -> human-gate" hand-off: if the verifier reports
NOT APPROVED, the caller surfaces the blockers; if APPROVED, the
caller can safely claim ready-to-merge.

## Implementation

The verifier is a pure-Python module (`lib/pr_verify.py`) called
via `python3 -m lib.pr_verify <pr-number>`. All `gh` calls are
isolated behind a single `_run_gh` helper that does the
subprocess.run with capture and check=True. The module is fully
unit-tested (24 tests) with all `gh` calls mocked.

## Related

- `lib/pr_verify.py` — the implementation; 5 gates, structured
  output, no cache.
- `tests/test_pr_verify.py` — 24 hermetic tests covering each gate
  + the parser + the integration path.
- `lib/babysit_pr_cli.py` — the babysit skill; should call
  `lib.pr_verify.verify_pr` instead of inlining the freshness
  check. Tracked as a follow-up.
- `docs/hooks/hook-coverage-gaps.md` — Gap #13 candidate
  ("babysit-pr can claim 'all green' on stale data") is closed
  by this skill.
