> [← Skills index](README.md) · [Project README](../../README.md)

# `babysit-pr-local`

**Category:** `ship` · **Alpha:** `state` · **Invocation:** `/dev-kit:babysit-pr-local` (human-invoked)

`babysit-pr-local` is the **local-mode sibling** of `/dev-kit:babysit-pr`. Where `babysit-pr` drives iteration through GH-Actions (poll `gh pr checks`, fetch failed-run logs, push fixes and repeat), `babysit-pr-local` replaces the CI judge with a **local LLM judge** (`bin/review-local.sh`) and always runs a **pre-push pytest gate**. It keeps the same shared plumbing — `lib/babysit_pr_cli` helpers, the lock protocol, the worktree-detect logic — so the two skills never drift on reliability contracts. It never auto-merges: `gh pr merge` stays a human-only action.

## When to use it

- The user types `/dev-kit:babysit-pr-local`.
- GH-Actions minutes are exhausted on the active PR (CI can't run or you want to stop paying for it).
- The operator wants to iterate on review verdicts locally before pushing.

## How it works

### Inputs (resolved at runtime, NOT user args)

`PR_NUMBER`, `PR_STATE`, `REVIEW_VERDICT`, `CHECKS`, and `BRANCH` are read via `gh pr view` / `gh pr checks` / `git rev-parse`, same as `babysit-pr`. The differences:

- **`REVIEW_VERDICT`** comes from the local judge — `bin/review-local.sh` exit code + the `<!-- dev-kit-verdict-audit -->` line of its audit comment, **not** from GitHub review state.
- **`CHECKS`** covers only the deterministic CI checks (`branch-policy`, `secret-scan`, `validate`) — the LLM review/security jobs are replaced locally.
- **`LOCAL_TEST_CMD`** defaults to `pytest -q` (the pre-push pytest gate; MUST-L3 enforces quoting the tail line).
- `MAX_ITERS` defaults to `1000` (the 3-consecutive-no-progress guard fires earlier).

If `PR_NUMBER` is empty (no current-branch PR), print a one-line message and exit 1. If `PR_STATE != OPEN`, print a one-line message and exit 1. Never create a PR implicitly.

### Hidden flags (never appear in slash description)

The slash command is **0-arg** — operators run `/dev-kit:babysit-pr-local` with no arguments. Three flags exist for tests + rare power-user overrides, all suppressed from `--help` / `argument-hint`:

| Flag | Effect | Why hidden |
|---|---|---|
| `--pr N` | Override current-branch PR discovery with explicit PR number | Tests + the rare case where the PR was opened from another worktree |
| `--local-test-cmd CMD` | Override the pre-push pytest gate default (`pytest -q`) | Non-pytest projects (Make, tox) need a real gate; defaulting to `pytest -q` would let a non-pytest project silently pass on `exit 0` with no pytest-tail line |
| `--local-mode` | Internal routing flag — already implied by the slash, kept so the parser doesn't double-route | Routes argv without double-parsing |

These are read by `lib/babysit_pr_cli.parse_babysit_args` (hidden via `argparse.SUPPRESS`) and surfaced on the resulting Namespace as `ns.pr`, `ns.local_test_cmd`, `ns.local_mode`. The pre-scan reader is `lib/babysit_pr_cli.is_local_mode(argv)` for callers that need to route before invoking the full parser.

### Worktree-aware execution

Identical to `babysit-pr`: the babysitter must run inside the worktree owning the PR's branch (`worktree-guard` denies edits from the main checkout). It sources `hooks/lib/worktree-detect.sh` and calls `worktree_detect()`, which sets `$WORKTREE_DETECT` to one of `worktree` / `main` / `outside`. `outside` → exit 0. In the main checkout, it resolves (or creates, verifying the resulting HEAD) the owning worktree via `git worktree list --porcelain`, then `cd`s into it once. A sub-agent is spawned via the `Agent` tool with the resolved worktree path as inherited cwd.

### Lock file protocol

Same as `babysit-pr`: `.dev-kit/babysit.lock` inside the resolved worktree, staleness via `lib/babysit_pr_reliability.py:is_stale_lock()` (TTL default 1800s / 30 min, or `pid=` no longer exists). Live lock → "already running", exit 1.

### Algorithm (5-step local difference)

The loop differs from `babysit-pr`'s 14-step GH-Actions flow in **five steps**:

1. **SNAPSHOT** — `gh pr view` fetches `PR_NUMBER`, `PR_STATE`, `CHECKS`, then diffs against the prior iteration's cached check-state (`.dev-kit/babysit-checks.json`) via `diff_check_states()`.
2. **TERMINATE** — if the local judge verdict is `APPROVED` (from `bin/review-local.sh`) and every deterministic check's conclusion is in `{success, skipped, neutral}`, print "PR approved" and exit 0.
3. **LOCAL JUDGE** — run `bin/review-local.sh` instead of waiting for GH-Actions review; bucket blockers from its audit comment + verdict line. The local judge replaces CI's `review` / `security` / `maintenance` jobs.
4. **VERIFY LOCAL** (hard gate) — run the failing command locally; quote the result as `local:  <command> → <result> (exit <code>)`. The **pre-push pytest gate is always on** — no commit/push until `pytest -q` passes and the tail line is quoted. On failure, do NOT commit/push — loop back to DIAGNOSE within the same iteration.
5. **COMMIT / PUSH / LOG / SLEEP / SAVE / INCREMENT** — same as `babysit-pr` steps 9–14: `git add <specific paths>` (never `git add -p`), `push origin HEAD`, one append-only line to `.dev-kit/babysit.log`, a 20s sleep, overwrite `.dev-kit/babysit-checks.json`, `iter += 1` with the cap-fallback (print blocker list, exit 1 — never silently retries past the cap).

**Termination conditions**: local verdict = `Approve` + deterministic checks green → exit 0; 3 consecutive iterations with no progress → exit 1 with the blocker list.

## Usage

```bash
/dev-kit:babysit-pr-local
```

| Flag | Effect |
|---|---|
| *(no flag)* | Default: runs the local judge + pre-push pytest gate loop on the current branch's PR. |
| `--pr N` | Babysit explicit PR `N`, overriding current-branch PR discovery (tests / cross-worktree case). |
| `--local-test-cmd CMD` | Override the pytest gate default for non-pytest projects. |

## Output

- **stdout**, per iteration: the evidence template — `[babysit] iter=<n>/<max> check=<name> verdict=<result> branch=<branch>`, then `log:`, `fix:`, `local:`, `push:`, `review:`, `remaining:` lines. A "fixed" claim without the `local:` line violates MUST-L3.
- **`.dev-kit/babysit.log`** — one append-only line per iteration.
- **`.dev-kit/babysit.lock`** — removed on exit via `trap`.

## Safety valves (forbidden, no exceptions)

- No `push --force`/`push -f` to `main`/`master` (`push --force-with-lease` is allowed only on your own unmerged branch).
- No auto-merge, ever — `gh pr merge` is always forbidden; `gh pr merge` is a human action even in the single-operator path.
- No secret auto-removal — abort and exit 1 with file:line on any credential detection.
- No destructive git operations: no `reset --hard`, no `clean -fd`, no branch `-D`.
- No skipping a failing test (`pytest.skip`, `@unittest.skip`, removing a test, commenting out an assertion) to force the local gate green.
- No marking a required check optional or `continue-on-error: true`.
- No workarounds that mask a root cause: `|| true`, `|| echo skipped`, raised exit thresholds, widened regexes, disabled hooks.
- One PR at a time — refuses to run if `.dev-kit/babysit.lock` is already held by a live process.

## Hook alignment

Same hooks as `babysit-pr`: `stop-verify` ON, `secret-scan` ON, `slop-detector` ON, `bash-guard` ON, `git-guard` ON (hard-blocks `gh pr merge` in any form — merging into main is always a human action). `tdd-guard` is OFF — the skill babysits an existing PR, it doesn't author new tests.

All stdout/stderr output is English only.

## Related

- [babysit-pr](babysit-pr.md) — the GH-Actions-driven sibling; both share `lib/babysit_pr_cli` and the lock/worktree plumbing.
- [review-local](../../commands/review-local.md) — the local judge this skill drives.
- [local-ci](../../docs/local-ci.md) — full local-CI playbook.
- `hooks/lib/worktree-detect.sh` — the shared worktree discriminator.
- `lib/babysit_pr_cli.py` — `parse_babysit_args`, `is_local_mode()`, the pure helper backing the loop.
- `lib/babysit_pr_reliability.py` — `is_stale_lock()` and `classify_check()`.
- `tests/test_babysit_pr_cli.py`, `tests/test_babysit_pr_reliability.py` — pin the CLI and reliability contracts.

---
*Source: [`skills/babysit-pr-local/SKILL.md`](../../skills/babysit-pr-local/SKILL.md)*
