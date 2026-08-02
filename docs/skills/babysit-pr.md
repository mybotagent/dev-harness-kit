> [← Skills index](README.md) · [Project README](../../README.md)

# `babysit-pr`

**Category:** `ship` · **Alpha:** `state` · **Invocation:** `/dev-kit:babysit-pr` (human-invoked)

`babysit-pr` monitors the PR associated with the **current branch** by default; `--pr N` explicitly targets an open PR when the current branch's PR is closed or merged. Every iteration is evidence-driven (MUST-L3): the skill quotes exit codes, log snippets, and review verdicts before claiming a step is done, and it never auto-merges — merging into `main` stays a human-only action even in the single-operator opt-out path.

## When to use it

- The user types `/dev-kit:babysit-pr`.
- A PR is open on the current branch and CI is red, or review requested changes.
- The user wants unattended iteration on a single PR.

## How it works

### Inputs (resolved at runtime, not user args)

`PR_NUMBER`, `PR_STATE`, `REVIEW_VERDICT` (`''`/`APPROVED`/`CHANGES_REQUESTED`/`REVIEW_REQUIRED`), `CHECKS`, and `BRANCH` are all read via `gh pr view` / `gh pr checks` / `git rev-parse`. `MAX_ITERS` defaults to `1000` (configurable via the `BABYSIT_MAX_ITERS` env var — the 3-consecutive-no-progress stuck-loop guard still fires earlier in practice). `OPERATOR_HANDLE` is `gh api /user -q .login`; `CODEOWNERS_PATH` is `.github/CODEOWNERS`; `COLLABORATORS` comes from the GitHub collaborators API. If `PR_NUMBER` is empty (no `--pr N` and no current-branch PR), the skill prints a one-line message and exits 1 explaining that an explicit `--pr N` or current-branch PR is required. If the resolved `PR_STATE != OPEN`, the skill prints a one-line message and exits 1 rather than silently reporting success. It never creates a PR implicitly.

### Worktree-aware execution

The babysitter must run inside the worktree owning the PR's branch, since `worktree-guard` denies edits from the main checkout. It sources `hooks/lib/worktree-detect.sh` and calls `worktree_detect()`, which sets `$WORKTREE_DETECT` to one of `worktree` / `main` / `outside`. `outside` → exit 0. If the cwd is already the worktree (Scenario A), the skill proceeds directly into the Algorithm below. If the cwd is the main checkout (Scenario B), the parent: fetches `origin`; lists open PRs off `main` via `gh pr list`; on zero candidates, exits 0 ("nothing to babysit"); on multiple candidates, prints a numbered list and exits 0 (never auto-picks); on exactly one candidate, resolves (or creates, verifying the resulting HEAD) the owning worktree via `git worktree list --porcelain`, then `cd`s into it once — the parent's Bash cwd persists for the rest of the session.

A sub-agent is then spawned via the `Agent` tool (`subagent_type: "general-purpose"`) with the resolved worktree path as its inherited cwd, carrying a condensed copy of the Algorithm, termination conditions, lock-file path, and Iron Laws L1-L5.

### Lock file protocol

On start: `mkdir -p .dev-kit`; if `.dev-kit/babysit.lock` exists, check staleness via `lib/babysit_pr_reliability.py:is_stale_lock()` — stale means either the lock's mtime exceeds the TTL (default 1800s / 30 min) or the recorded `pid=` no longer exists. A stale lock is removed and the run proceeds; a live lock refuses with "already running" and exits 1. Otherwise the skill writes `<ISO-8601> pid=$$ branch=<branch>` to the lock and traps removal on exit. The lock lives at `<worktree_path>/.dev-kit/babysit.lock` — inside the resolved worktree, not the main checkout, so parent and sub-agent share the same lock path.

### Ghost-workflow classification

`gh pr checks` may report a check whose underlying workflow file was deleted server-side, staying pending indefinitely. `lib/babysit_pr_reliability.py:classify_check(check_dict, now_epoch, ghost_threshold_seconds=300)` classifies a check as a "ghost" when it has no `databaseId` (regardless of state or age), or when it has a `databaseId` but its `startedAt`/`updatedAt` is older than 300s (5 min). A check with a `databaseId` but no `startedAt`/`updatedAt` at all has no elapsed time to measure against the threshold, so it classifies as "pending" instead of "ghost" — this covers a freshly-requested check (age zero) right after a push, which would otherwise be ghosted immediately and trigger unnecessary recovery/retry logic. It still ghosts out once it ages past the threshold, because by then it carries a stale `startedAt`/`updatedAt`. This replaces the plain wait-and-retry with a surfaced "recovery-required" message instead of spinning to `MAX_ITERS`.

### Algorithm (13-step loop, plus a pre-loop opt-out check)

**Step 0 — opt-out check**: if `--operator-is-only-human` was passed, this runs *before* step 1's snapshot (see "Single-operator bypass" below).

1. **SNAPSHOT** — one `gh` call fetches `PR_NUMBER`, `REVIEW_VERDICT`, `CHECKS`.
2. **TERMINATE** — if `REVIEW_VERDICT == APPROVED` and every check's conclusion is in `{success, skipped, neutral}`, print "PR approved" and exit 0.
3. **CLASSIFY** — bucket blockers into (A) CI failing, (B) CI pending → wait, (C) review `CHANGES_REQUESTED`, (D) `REVIEW_REQUIRED`/empty → print "waiting for human review" and exit 0 (the skill cannot self-approve).
4. **WAIT** — if any check is pending with no failures, sleep 30s and continue.
5. **FETCH LOGS** — `gh run view <run-id> --log-failed` per failing check; truncate to the last 200 lines; capture exit code and first error.
6. **DIAGNOSE** — one root cause per failing check: test failure, lint/format, type-check, secret detected (abort — never auto-remove), or review feedback.
7. **APPLY FIX** — Edit/Write, one logical change per iteration.
8. **VERIFY LOCAL** — re-run the failing command; quote the result in the exact format `local:  <command> → <result> (exit <code>)`.
9. **COMMIT** — `git add <specific paths>` of the just-modified file(s); never `git add -p` (interactive, hangs without a TTY).
10. **PUSH** — pushes the branch (`push origin HEAD`).
11. **LOG** — appends one line to `.dev-kit/babysit.log`: `<ISO-8601> iter=<n> check=<name> fix=<one-line> exit=<code>`.
12. **SLEEP** — `gh pr checks --watch` or a 20s sleep.
13. **INCREMENT** — `iter += 1`; on exceeding `MAX_ITERS`, falls through to the cap-fallback (print the unresolved blocker list, exit 1 — never silently retries past the cap).

**Termination conditions**: approved + green → exit 0; `REVIEW_REQUIRED` → exit 0 ("waiting for human review"); `CHANGES_REQUESTED` → apply and iterate; 3 consecutive iterations with no progress → exit 1 with the blocker list (this guard fires before the full 1000-iteration budget is exhausted).

### Single-operator bypass (`--operator-is-only-human`)

The pure helper `lib/babysit_pr_cli.py:run_babysit_once()` backs this flag (no `subprocess`/`gh` calls inside the helper itself, for reproducibility). Flow: (1) parse argv — no flag → print `REVIEW_REQUIRED -> human-gate` and exit 0 (the legacy default); (2) flag set with no `--rationale` → parser error, exit 2; (3) flag set with rationale — read `.github/CODEOWNERS`, resolve `COLLABORATORS` via the GitHub API (best-effort; an API error does not itself grant the bypass), and check for alternate owners. If alternates exist, refuse and exit 1, falling back to the human-gate path. If none exist, post the audit comment `/ownership-confirmed by operator=<handle> at <ISO-8601>; rationale=<text>` and exit 0 — the PR is never merged by this skill; the operator merges manually.

Exit-code contract from the helper: `EXIT_OK` (0) → confirmed, audit comment posted. `EXIT_MULTI_OWNER` (1) → bypass refused (alternate owners found); mapped to `sys.exit(0)` as the human-gate fallback, since it is a successful refusal, not a skill failure. `EXIT_RATIONALE_REQUIRED` (2) → operator must supply `--rationale`; mapped straight through as exit 2. `EXIT_OWNERSHIP_UNKNOWN` (4) → CODEOWNERS unreadable or the collaborators lookup did not confirm success; fail-closed, mapped to exit 0 as a human-gate fallback (an outage can never be interpreted as "no alternate owners").

The skill wires named shims before calling the helper — `_write_stdout`, `_write_stderr`, `_post_pr_comment` — since the helper is pure and has no direct I/O. There is no merge shim; the bypass never calls `` `gh pr merge` ``.

Example invocation:

```bash
/dev-kit:babysit-pr --operator-is-only-human \
  --rationale "trivial README typo in docstring; no behavior change"
```

## Usage

```bash
/dev-kit:babysit-pr [--pr N] [--operator-is-only-human] [--rationale "<text>"]
```

| Flag | Effect |
|---|---|
| *(no flag)* | Default: prints `REVIEW_REQUIRED -> human-gate` and exits 0 — the audit-safe default. |
| `--pr N` | Babysit explicit PR `N`, overriding current-branch PR discovery. The target must be open; use this when the current branch's PR is closed or merged. |
| `--operator-is-only-human` | Opt-out for single-operator repos. Refuses with exit 1 if CODEOWNERS or the collaborators list name anyone other than the operator. Requires `--rationale`. Posts the audit comment and hands off — never merges. |
| `--rationale "<text>"` | Required with the opt-out flag; quoted verbatim into the audit comment. |

## Output

- **stdout**, per iteration (the evidence template): `[babysit] iter=<n>/<max> check=<name> verdict=<result> branch=<branch>`, followed by `log:`, `fix:`, `local:`, `push:`, `review:`, and `remaining:` lines. A "fixed" claim without the `local:` line violates MUST-L3.
- **`.dev-kit/babysit.log`** — one append-only line per iteration.
- **`.dev-kit/babysit.lock`** — the run's lock file, removed on exit via `trap`.

## Safety valves (forbidden, no exceptions)

- No `push --force`/`push -f` to `main`/`master` (`push --force-with-lease` is allowed only on your own unmerged branch).
- No auto-merge, ever — `` `gh pr merge` `` is always forbidden; the bypass above only posts an audit comment, never merges.
- No secret auto-removal — abort and exit 1 with file:line on any credential detection.
- No destructive git operations: no `reset --hard`, no `clean -fd`, no branch `-D`.
- No skipping a failing test (`pytest.skip`, `@unittest.skip`, removing a test, commenting out an assertion) to force CI green.
- No marking a required check optional or `continue-on-error: true`.
- No bypassing the LLM review gate (closing the PR, removing the review trigger, force-merging, marking the review check optional).
- No workarounds that mask a root cause: `|| true`, `|| echo skipped`, raised exit thresholds, widened regexes, disabled hooks.
- One PR at a time — refuses to run if `.dev-kit/babysit.lock` is already held by a live process.

## Hook alignment

`stop-verify` ON (every "done" claim needs a quoted exit code); `secret-scan` ON (hard-aborts on detected credentials); `slop-detector` ON (blocks vacuous commits like "fix ci"/"wip" with no functional change); `bash-guard` ON (guards force-push patterns); `git-guard` ON (hard-blocks `` `gh pr merge` `` in any form — merging into main is always a human action). `tdd-guard` is OFF — the skill babysits an existing PR, it doesn't author new tests.

All stdout/stderr output is English only.

## Related

- [ship](ship.md) — recommended next step once the loop terminates with an approved PR.
- [repair](repair.md) — recommended on an abnormal exit that looks like a golden-asset regression.
- `hooks/lib/worktree-detect.sh` — the shared worktree discriminator this skill sources rather than reimplementing.
- `lib/babysit_pr_cli.py` — the pure helper backing the single-operator bypass.
- `lib/babysit_pr_reliability.py` — `is_stale_lock()` and `classify_check()`.
- `tests/test_babysit_pr_cli.py`, `tests/test_babysit_pr_reliability.py` — pin the bypass and reliability contracts.

---
*Source: [`skills/babysit-pr/SKILL.md`](../../skills/babysit-pr/SKILL.md)*
