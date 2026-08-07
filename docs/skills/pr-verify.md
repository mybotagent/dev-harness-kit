> [← Skills index](README.md) · [Project README](../../README.md)

# `pr-verify`

**Category:** `ship` · **Alpha:** `enforcement` · **Invocation:** `/dev-kit:pr-verify` (human-invoked)

`pr-verify` replaces the babysit flow's "trust `gh pr checks` and any `Approve` text in the comment stream" pass condition with a deterministic 5-gate verifier (`lib/pr_verify.py`) that fetches PR state fresh from GitHub on every call. Each gate emits a `fetched_at` timestamp; the pass condition is the AND of all five gates; the output is a structured summary table so the caller — human or babysit loop — can verify the verdict instead of trusting prose.

## When to use it

- The user types `/dev-kit:pr-verify [<pr-number>]`.
- Before any claim that a PR is "ready to merge" / "all green" / "approved".
- At the START of every babysit iteration, before reporting status.
- Whenever a previous babysit message said "all green" but the user suspects the data was stale.

## The five gates

| Gate | Pass condition | Source of false positive it closes |
|---|---|---|
| **G1** | PR state is `OPEN` (not draft / closed / merged). | Merged-but-still-on-board PR being claimed as "approved". |
| **G2** | Every CI check is in a terminal success state. `pending` = "still running" = NOT pass. | A still-running review being reported as "approved". |
| **G3** | Every required LLM-judge job (review + security + maintenance) has its most recent audit comment carrying `verdict=Approve`. A stale audit (created before the PR's most recent push) yields a fail. | An OLD `Approve` from a previous run silently ruling out a NEW `Changes Requested`. |
| **G4** | No `<!-- dev-kit-verdict-audit -->` comment records a workflow-run whose `status=failure` was paired with `verdict=Approve`. | The "audit line says `Approve` but workflow exit was `failure`" false positive. |
| **G5** | Merge state is `CLEAN` or `BEHIND`. `BEHIND` is a soft pass; `BLOCKED` / `DIRTY` / `UNKNOWN` / `UNSTABLE` are hard fails. | `UNSTABLE` (a required check is being recomputed) being collapsed into `PASS`. |

A stale audit (G3) is detected via `pr_pushed_at` (the PR's most recent push timestamp) compared against each audit's `created_at` — the per-job freshness guard the M-2 stale-verdict fix wires up.

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
  [G3] FAIL every required LLM-judge per-job verdict is Approve: non-Approve jobs: {'review': 'Changes'}
  [G4] PASS no audit comment with status=failure + verdict=Approve: no false-positive pairs
  [G5] PASS mergeStateStatus is CLEAN or BEHIND: mergeStateStatus=BEHIND, mergeable=MERGEABLE
  Blockers:
    - [G2] every CI check is in a terminal success state: FAILED: severity gate (review + security)
    - [G3] every required LLM-judge per-job verdict is Approve: non-Approve jobs: {'review': 'Changes'}
```

Exit code `0` if all five gates pass; `1` otherwise. The summary is emitted to stdout. The `--help` banner and the no-PR-found error go to stderr so the verdict summary can be piped cleanly.

## Iron Law (L3 evidence)

The verifier's own claim "all five gates green" must be backed by the per-gate evidence in the output. The `checked_at` timestamp is the single piece of state the caller trusts; per-gate `fetched_at` values are derived from the same call.

## Hand-off

The verifier's output is a drop-in for the babysit skill's "REVIEW_REQUIRED → human-gate" hand-off: if the verifier reports NOT APPROVED, the caller surfaces the blockers; if APPROVED, the caller can safely claim ready-to-merge.

## Implementation

The verifier is a pure-Python module (`lib/pr_verify.py`) called via `python3 -m lib.pr_verify` (or the matching skill invocation). All `gh` calls are isolated behind a single `_run_gh` helper that wraps `subprocess.run(capture_output=True, check=False, timeout=30)` and raises `GhError` on any failure; each gate catches `GhError` and returns a fail-closed `GateResult`. The module is fully unit-tested (54 tests) with all `gh` calls mocked.

## Related

- [babysit-pr](babysit-pr.md) — the orchestration loop that calls `pr-verify` each iteration.
- `lib/pr_verify.py` — the implementation; 5 gates, structured output, no cache.
- `tests/test_pr_verify.py` — 54 hermetic tests covering each gate + the parser + the integration path + CLI forms + edge-case failure paths.
- `lib/babysit_pr_cli.py` — the babysit skill; should call `lib.pr_verify.verify_pr` instead of inlining the freshness check. Tracked as a follow-up.

---
*Source: [`skills/pr-verify/SKILL.md`](../../skills/pr-verify/SKILL.md)*
