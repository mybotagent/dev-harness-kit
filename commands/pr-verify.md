---
description: Run the deterministic PR verifier on the current branch's PR (or --pr N). Fetches fresh gh state, prints 5-gate verdict + blockers, exits 1 if not approved.
argument-hint: '[--pr <number>] [--repo <owner/repo>]'
---

# /dev-kit:pr-verify

Deterministic PR verification — 5 gates, fresh `gh` fetch per gate,
no cache. Resolves the "babysit said all green on stale data" false
positive by reading the actual current state every call.

The body of this command lives in
[`skills/pr-verify/SKILL.md`](../skills/pr-verify/SKILL.md). The command
itself is a thin wrapper that invokes
`python3 -m lib.pr_verify <pr-number>` from the worker's current
worktree.

## Args (rare; positional only)

| Position | Meaning | Default |
|---|---|---|
| `$1` | PR number to verify | The PR for the current branch (via `gh pr view --json number -q .number`) |
| `$2` | `owner/repo` | `sh-ai-x/dev-harness-kit` |

`$ARGUMENTS` is forwarded to `python3 -m lib.pr_verify` as-is; the
helper accepts `--pr N` and `--repo owner/repo` flags equivalently.

## Execution

```bash
# Default: verify the current branch's PR
python3 -m lib.pr_verify

# Explicit PR
python3 -m lib.pr_verify 579

# Different repo
python3 -m lib.pr_verify --pr 584 --repo sh-ai-x/dev-harness-kit
```

The verifier prints a per-gate summary to stdout and exits 0 if all
five gates pass, 1 otherwise. Per-gate `fetched_at` timestamps are
the single piece of state the caller should trust.

Do not parse the human-readable output and claim "all green" without
also checking the exit code. The babysit flow's failure mode was
trusting prose over exit codes — this skill's contract is
exit-code-based, and downstream skills / humans should respect it.

## Related

- `lib/pr_verify.py` — the implementation; 5 gates, structured output.
- `tests/test_pr_verify.py` — 24 hermetic tests.
- `skills/pr-verify/SKILL.md` — the spec.
