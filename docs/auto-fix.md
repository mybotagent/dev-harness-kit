# Auto-fix on review

The **self-healing PR loop**: when a reviewer requests changes, an LLM agent reads the feedback, applies targeted fixes, commits, and pushes back to the same branch. The reviewer re-runs on the new push. Loop continues until approval or human interrupt.

## Loop

```
PR opened
  ↓
[1] Reviewer runs /dev-kit:review + /dev-kit:security
  ↓
[2] Reviewer posts review with "Changes Requested" (inline + body)
  ↓
[3] auto-fix-pr.yml fires (on pull_request_review: submitted, state=changes_requested)
  ↓
[4] Agent reads review body + inline comments
  ↓
[5] Agent applies fixes, commits, pushes
  ↓
[6] Reviewer re-runs on the new commit (PR auto-triggers review.yml)
  ↓
[2] Repeat until "Approve" or 5-iteration cap
```

## Guards (prevent infinite loop)

1. **Self-review skip** — workflow skips if `review.user.login` starts with `github-actions` or `claude[bot]` (the bot reviewing itself).
2. **Iteration cap** — counts auto-fix commits on the branch. After **5** auto-fix commits, the workflow stops and posts "handing off to human review".
3. **Workflow file lock** — the agent is told NOT to modify `.github/workflows/*` (modifying it invalidates the action's self-validation and causes the next run to skip).
4. **No force-push** — uses `git push` (no `--force`).

## Setup

Required secret (already in use by `review.yml`):

- `MINIMAX_API_KEY` — MiniMax Anthropic-compatible API key

The workflow is **enabled by default** in this repo. To disable for a specific PR, add the label `no-auto-fix` to the PR.

## What the agent sees

```
REVIEW BODY (top-level):
  "PR #12 makes a clean, useful refactor... Two 🟠 majors block merge:
   1. skills/plan-ralph/SKILL.md:4 description still has Korean...
   2. .claude/rules/test-files.md:6 path **/tests/** matches Python..."

INLINE COMMENTS (file:line → note):
  "skills/plan-ralph/SKILL.md:4: Korean description contradicts..."
  ".claude/rules/test-files.md:6: **/tests/** path matches Python..."

RULES:
  1. One commit per fix wave
  2. Push (no force)
  3. Do NOT modify .github/workflows/*
  4. Do NOT modify CLAUDE.md or docs/ unless review asks
  5. If unclear, comment on PR (don't guess)
  6. If no fix needed, empty commit
```

## What the agent does NOT do

- ❌ Force-push
- ❌ Modify CI config
- ❌ Approve or merge (Human-on-the-Loop)
- ❌ Loop past 5 iterations
- ❌ Run if reviewer is `claude[bot]` or `github-actions` (prevents self-reply)

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Workflow doesn't fire | Reviewer wasn't `changes_requested` | Re-request review explicitly |
| Agent says "unclear" | Contradictory or vague feedback | Human comments on PR to clarify |
| 5-iteration cap hit | Stuck loop | Human reviews and merges manually |
| Self-validation skipped | Agent modified `.github/workflows/*` | Revert that change, agent will re-engage next time |
| Wrong LLM API call | `MINIMAX_API_KEY` not set | Add secret in repo settings |

## Safety

The agent is **scoped** by `claude_args: --allowedTools` to git, gh, and read/edit/write. It cannot run arbitrary bash, install packages, or push to other repos.

The hard cap (5 iterations) ensures a stuck feedback loop doesn't burn API budget forever.
