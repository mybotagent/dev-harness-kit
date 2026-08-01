> [← Skills index](README.md) · [Project README](../../README.md)

# `ci-triage`

**Category:** `audit` · **Alpha:** `enforcement` · **Invocation:** `/dev-kit:ci-triage` (human-invoked)

`ci-triage` triages failing GitHub Actions runs across recent commits, dedupes them against a persisted case store, and judges new failures against a model/context/harness taxonomy where every case must carry a re-runnable repro plus an executable regression test (or an explicit `N/A: <reason>` when one isn't feasible). The store schema is shaped for reproduction and regression-prevention — a write-up that can't be re-run or re-checked later doesn't count as a judgment.

## When to use it

- The user types `/dev-kit:ci-triage`.
- The user asks "why does CI keep failing on main" or wants recent CI failures classified.
- After noticing a recurring red check and wanting a root-cause writeup instead of re-diagnosing it by hand each time.
- Before proposing a new hook to prevent a CI failure from recurring.

## How it works

The skill first asks the user for scope — either a count of recent commits on the current branch, or an explicit list of commits/SHAs. It never hardcodes a window size. With scope resolved, it runs `python3 lib/ci_triage.py scan --count N` (or `--commits <sha...>`):

1. Each commit is resolved to its full 40-char SHA (`gh run list --commit` silently returns nothing on a short SHA — see `runs_for_commit` in `lib/ci_triage.py`).
2. Linked workflow runs are fetched; for every non-passing run, the failing job/step's log is pulled via `gh run view --log-failed`, or — when GitHub scheduled zero jobs at all (e.g. a stale trigger registration) — the one-line `gh run view` diagnostic instead.
3. Each failure is hashed to a signature and checked against `.dev-kit/ci-triage-log.json`. The scan output separates `unjudged` (new signatures, each carrying the raw failure detail for the model to read), `already_known` (signatures already judged; the occurrence count is bumped, nothing else happens), and `commits[].note` (commits with no direct run, most commonly bot-authored commits pushed with `GITHUB_TOKEN`).

The skill then **judges** each `unjudged` entry. Every case must declare:

- `primary_cause` / `secondary_cause` — validated against `lib/ci_triage.py:CAUSE_TAXONOMY`. Three primary buckets: `model` (the agent had the right info/tools and still judged wrong), `context` (the agent acted reasonably on wrong/missing/stale/conflicting information), or `harness` (the control system around the agent broke — CI, tool schemas, retries, permissions, eval env).
- `evidence` — the specific log line or API field that proves the cause. A citation, not a narrative.
- `repro` — a concrete, re-runnable recipe that reproduces the failure right now.
- `regression_test` — required. `path::test_name` of an executable test that fails before the fix and passes after, or the explicit `N/A: <reason>` escape hatch. A failure that isn't captured as a test doesn't stop recurring, it just stops getting noticed.
- `proposal` — the concrete fix.
- `hook_proposal` (optional) — when the fix is something a hook could enforce so the failure structurally can't recur.

Judgments are recorded via `python3 lib/ci_triage.py record --from-json <path>`, which validates the cause pair and rejects an empty `repro` / `regression_test` before flipping the case to `status: open`.

Once a case is judged, `python3 lib/ci_triage.py process [--auto-fix] [--verify-window N]` closes the loop. The engine walks every `open` case, applies known-pattern fixes when the case's own `proposal` names the exact commands to run (currently `gh api -X PUT .../actions/workflows/<id>/disable` + `enable` for stale trigger registrations), re-scans the workflow's recent runs, and flips the case to `status: processed` once no new failures have appeared after `resolution.fix_applied_at`. The full forensic trail — `commands_run`, `verify_pre`/`verify_post`, `commit` + linked `pr` for code-fix resolutions, and a `post_fix_scan` summary — is persisted in the same store, so a reader can jump from "what failed" to "what fixed it" without leaving `.dev-kit/ci-triage-log.json`. Already-processed cases are skipped (idempotent).

## Why it's shaped this way

- **Reproduction-shaped, not analysis-shaped.** A case is not "done" because it has a good write-up. `repro` and `regression_test` are both required so a reader can re-run the failure later to confirm the fix actually closed it.
- **Dedup by signature, not by commit.** The store's unit of record is a failure signature; commits/runs are occurrences under it. Never write a fresh case for a signature that's already `open` or `processed`.
- **No fabricated root cause.** `evidence` must cite the specific log line, API field, or timestamp comparison that supports the classification. If the evidence is inconclusive, say so — don't guess a cause to fill the field.
- **Full SHA only.** Any code path that calls `gh run list --commit` must resolve to the full 40-char SHA first. A short SHA does not error — it silently returns an empty run list, which looks identical to "no CI ran for this commit."
- **Idempotent re-runs.** `process()` preserves a prior `case["resolution"]` if present rather than unconditionally re-applying the fix. The verify scan uses the recorded `fix_applied_at` as its cutoff, so a failure that appears *after* the original fix is correctly classified as fresh and the case stays `open` with a `last_process_attempt` note. Re-running `process()` on a partially-processed case does not silently flip it to `processed` just because the wall clock advanced.

## Files

| Path | Purpose |
|---|---|
| `skills/ci-triage/SKILL.md` | The skill definition |
| `lib/ci_triage.py` | Deterministic engine — commit resolution, full-SHA run matching, failure-detail fetch, signature dedup, `CAUSE_TAXONOMY` validation, store I/O |
| `tests/test_ci_triage.py` | Signature stability, store round-trip, taxonomy/repro/regression-test validation, short-SHA guard, multi-job failure signals, `##[error]` annotation preference, and mocked end-to-end scan |
