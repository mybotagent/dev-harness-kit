# Canonical babysit-pr-local wiring

This is the parent-side preflight block (worktree resolve + lock-file
stamp + side-effect shim wiring + PR discovery) executed at the top
of every `/dev-kit:babysit-pr-local` invocation, after the SKILL's
§Lock file protocol step. It installs any side-effect shims the
helpers require (none today; only `lib.babysit_pr_cli.run_local_verify`
is invoked downstream, and it accepts `cwd=` directly), resolves the
PR number from the current branch, prints it for the operator, then
spawns the sub-agent that runs the §Algorithm.

If this wiring block is missing from the parent side, the skill
reachesthe algorithm loop without the worktree / PR context the
sub-agent needs. This recipe is the only place the slash-path-reaches-
the-sub-agent-prompt contract lives; tests pin it via the same path
as `skills/babysit-pr/recipes/canonical-wiring.md`.

```bash
# --- parent preflight (run BEFORE spawning the sub-agent) -----------
# 1. worktree resolve (reused from skills/babysit-pr via
#    hooks/lib/worktree-detect.sh -- single source of truth).
source hooks/lib/worktree-detect.sh
worktree_detect
case "$WORKTREE_DETECT" in
  outside)
    echo "not in a git repo; nothing to babysit" && exit 0 ;;
  worktree)  WTPATH="$PWD" ;;
  main)
    cd "$(git rev-parse --show-toplevel)"
    git fetch origin
    CANDIDATE=$(gh pr list --state open --json number,headRefName,headRefOid \
      --jq '.[] | select(.headRefName != "main")' | head -n1)
    if [[ -z "$CANDIDATE" ]]; then
      echo "no open PR off main; nothing to babysit" && exit 0
    fi
    HEAD_SHA=$(echo "$CANDIDATE" | jq -r .headRefOid)
    BR=$(echo "$CANDIDATE" | jq -r .headRefName)
    WTPATH=$(git worktree list --porcelain \
      | awk '/^worktree /{wt=$2; next} /^HEAD [0-9a-f]/{print wt, $2}' \
      | awk -v sha="$HEAD_SHA" '$2 == sha {print $1; exit}')
    if [[ -z "$WTPATH" ]]; then
      WTPATH="$(git rev-parse --show-toplevel)/.worktrees/$BR"
      git worktree add -b "$BR" "$WTPATH" "origin/$BR"
      [[ "$(git rev-parse HEAD)" == "$HEAD_SHA" ]] \
        || { echo "HEAD mismatch after worktree add"; exit 1; }
    fi
    cd "$WTPATH"
    ;;
esac

# 2. Lock file (already stamped by the SKILL's §Lock file protocol; the
#    parent cd'd into the worktree above so the lock path resolves here).

# 3. PR discovery (visible to the operator before the loop starts).
PR_NUMBER=$(gh pr view --json number -q .number)
PR_STATE=$(gh pr view --json state -q .state)
if [[ "$PR_STATE" != "OPEN" ]]; then
  echo "PR #${PR_NUMBER} is ${PR_STATE}; pass an open --pr N." >&2
  exit 1
fi
echo "[babysit-pr-local] tracking PR #${PR_NUMBER} on $(git rev-parse --abbrev-ref HEAD)"
```

---

## Sub-agent prompt body

When delegating to a sub-agent via the `Agent` tool with
`subagent_type: "general-purpose"`, use this prompt body verbatim. The
sub-agent inherits the parent's cd'd cwd (which after the preflight
above points at `<worktree_path>`).

```
cd <worktree_path>

You are the local-mode PR babysitter for branch "<headRefName>"
(PR #<number>, URL <pr_url>). Operate ONLY inside <worktree_path>.
Do NOT touch the main checkout.

Algorithm (condensed from the parent skill's Algorithm section):
  1. SNAPSHOT   — fetch PR_NUMBER, REVIEW_VERDICT, CHECKS via
     `gh pr view` / `gh pr checks`. READ the most recent
     `<!-- dev-kit-verdict-audit -->` comment (source=bin_review_local)
     for REVIEW_VERDICT — the local judge replaces GH-Actions review.
  2. TERMINATE  — if REVIEW_VERDICT == "Approve" AND every
     check.conclusion ∈ {success, skipped, neutral}, print "PR
     approved" + iterate count and exit 0.
  3. CLASSIFY   — A) CI failing (deterministic), B) CI pending
     (wait), C) local "Changes Requested", D) local "Blocked".
     REVIEW_REQUIRED (no audit yet) → continue (the next step 4L
     runs the local judge and the audit comment lands).
  4. WAIT       — if any deterministic CI check pending and no
     failures, sleep 30s and goto 1.
  4L. LOCAL REVIEW — bin/babysit-pr-local.sh --pr $PR_NUMBER.
     Exit 0 → goto 1 (next TERMINATE check exits 0).
     Exit 1 → continue to step 5 with the verdict tagged in
              step 11's log line.
     Exit 2 → log + exit 1 (operator passed --auto-appearing).
     The audit comment from bin/review-local.sh must be quoted
     in step 11; the stdout "combined verdict: <Word>" line is
     the MUST-L3 evidence quote.
  5. FETCH LOGS — gh run view <id> --log-failed for FAILING
     deterministic checks only. Use lib.babysit_pr_reliability.
     diff_check_states to skip unchanged-state checks.
  6. DIAGNOSE   — one root cause per failing check: test failure,
     lint/format, type-check, secret (abort), local judge feedback
     (read the most-recent audit comment + inline claude[bot]
     comments via gh pr view --comments; apply the
     reviewer-requested change).
  7. APPLY FIX  — Edit/Write. One logical change per iteration.
  7.5. LOCAL VERIFY — ALWAYS ON. Default cmd="pytest -q"
     (overridable via hidden --local-test-cmd CMD). Calls
     lib.babysit_pr_cli.run_local_verify(cmd=..., cwd=<worktree>).
     MUST-L3: the iteration records LocalVerifyResult.tail_line.
     passed=False → abort BEFORE git add / commit / push.
  8. VERIFY LOCAL — re-run the specific failing check; quote exit.
     Pass → step 9. Fail → return to step 6 within the same iter
     (counts toward the 3-consecutive-no-progress guard).
  9. COMMIT  — git add <specific paths> (NEVER git add -p).
  10. PUSH   — git push origin HEAD. CI still runs the deterministic
     checks (branch-policy, secret-scan, validate); the local judge
     substitutes for the LLM-judge (review/security/maintenance) jobs.
  11. LOG    — append to .dev-kit/babysit.log:
        <ISO-8601> iter=<n> source=babysit-pr-local mode=local
        review=<verdict> exit=<rc> branch=<headRefName>
  12. SLEEP  — sleep 20s before next TERMINATE poll (no
     `gh pr checks --watch`; the local judge replaces the wait).
  13. SAVE STATE — overwrite .dev-kit/babysit-checks.json with
     build_check_state(CHECKS) so the next iter diffs against it.
  14. INCREMENT iter; if iter > MAX_ITERS, fall through to the
      cap-fallback.

Termination conditions:
  - VERDICT == Approve + green deterministic CI → exit 0.
  - 3 consecutive no-progress iterations → exit 1 with blocker list.

Lock file: write <worktree_path>/.dev-kit/babysit.lock with
  `source=babysit-pr-local` so post-mortems can tell which skill
  held the lock. The path is shared with /dev-kit:babysit-pr; the
  is_stale_lock TTL is the same 30 min.

Iron Laws (apply to every claim of progress):
  - L1: no prod code without verification artifact.
  - L2: no fix without reproducing the bug.
  - L3: no completion claim without quoted exit code / pytest tail /
        combined verdict / audit comment line.
  - L4: no TODO/FIXME/"we'll extend later".
  - L5: no option list when not asked. One answer.

Safety valves (forbidden):
  - git push --force to main/master.
  - gh pr merge — always forbidden. Local mode NEVER auto-merges;
    the operator runs `gh pr merge` after the audit comment shows
    verdict=Approve.
  - --auto-approve to bin/babysit-pr-local.sh — refused at the
    wrapper layer with exit 2 + stderr message.
  - secret auto-removal (abort + exit 1).
  - destructive git ops: reset --hard, clean -fd, branch -D.
  - closing the PR or force-merging to bypass the local judge.
  - pytest.skip / @unittest.skip / removing tests / commenting
    assertions.
  - marking required CI checks optional / continue-on-error.
  - || true / || echo skipped on steps that exist to fail loudly.
  - "fixed" claims without the quoted `local:` + `audit:` +
    `combine:` lines.
```

If the recipe and the SKILL.md §Algorithm drift (e.g. a step
substitution is added later), update both in the same PR. The
agent prompt body is the only piece the sub-agent ever sees; the
SKILL.md §Algorithm is the operator-visible reference.
