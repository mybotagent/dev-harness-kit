---
paths:
  - ".claude/**"
  - "hooks/**"
  - "docs/adr/ADR-00**-*.md"
  - "tests/test_git_workflow.py"
  - "tests/test_worktree_guard.py"
---

# Git workflow rules (dev-harness-kit)

These rules apply to every code change — feature, fix, refactor, docs, test, chore.
Violation = rejected by `git-guard` hook at commit/push time.

## Iron Laws (read first)

1. **`main` is sacred.** Never commit directly to `main`. Never push to `main`. Never fast-forward a feature branch into `main` locally.
2. **Every task = new worktree + new session + new branch.** No edits on the previous task's branch. No edits in the main checkout.
3. **Always branch from latest `main`.** Cut from `origin/main` (just-fetched), not from a stale local ref or another feature branch.

## Branch naming (mandatory)

Format: **`<type>/<slug>`**

| Type | When | Examples |
|---|---|---|
| `fix/` | bug fix from review or reported defect | `fix/review-findings`, `fix/cli-nameerror` |
| `feat/` | new user-facing feature or skill | `feat/pm-prd-tracking`, `feat/eval-repair-v2` |
| `refactor/` | no behavior change, internal cleanup | `refactor/dedup-state-codec` |
| `docs/` | documentation only | `docs/adr-0021-branch-strategy` |
| `test/` | tests only, no source change | `test/team-hooks-coverage` |
| `chore/` | deps, build, CI, tooling | `chore/bump-pytest-9` |
| `perf/` | performance, no behavior change | `perf/index-json-parse` |
| `hotfix/` | emergency revert of a merged main commit | `hotfix/revert-abc123` |

### Slug rules

- **kebab-case**, lowercase, English only (no Korean, no spaces, no underscores).
- **Action-first**: describe what the branch does, not what file it touches.
  - ✅ `fix/cli-nameerror`, `feat/eval-repair-v2`
  - ❌ `fix/state_codec`, `feature_eval` (wrong type), `MyFeature` (not kebab)
- **Length**: 2–40 chars. Single-char slugs (e.g. `fix/a`) are too vague.
- No author names, no issue numbers (issue #N goes in the PR body, not the branch name).
- No personal/scratch names: `wip`, `tmp`, `foo`, `bar`, `asdf`, `test`, `scratch`, `untitled` → rejected by `tests/test_git_workflow.py::FORBIDDEN_RE`.

## Worktree + session protocol (mandatory for every new task)

```
# 1. Update local main to match origin
git fetch origin main
git checkout main
git pull --ff-only origin main

# 2. Cut a fresh worktree for the new task (auto-creates branch from origin/main)
git worktree add -b fix/<slug> .claude/worktrees/fix-<slug> origin/main

# 3. Open a new Claude Code session IN THAT WORKTREE
#    (the session cwd is the worktree path, not the main checkout)

# 4. Do all edits, tests, commits, push — all from inside the worktree
git push -u origin fix/<slug>
gh pr create --base main --head fix/<slug> --title "..." --body "Closes #N"

# 5. After PR is merged (or abandoned), remove the worktree
git worktree remove .claude/worktrees/fix-<slug>
git branch -d fix/<slug>        # local branch gone
```

**Why a new session?** Each task = fresh context. Don't carry over findings/decisions from the previous branch — they belong in the PR body and the commit message, not in the next branch's working memory.

**Why a new worktree?** Multiple branches in one checkout collide on `phases/`, `.dev-kit/`, the running test process, and uncommitted edits. A worktree is a free, isolated copy.

## PR conventions (mandatory)

- **Base branch**: `main` (always).
- **Title**: `<type>(<scope>): <subject>` (Conventional Commits)
  - Examples: `fix(review): address 10 blockers`, `feat(execute): add started_at field`
- **Body** must include:
  - Summary (2-5 bullets)
  - Test plan with quoted exit codes / test counts
  - `Closes #N` (or `Refs #N` if not auto-closing)
- **One commit per task** unless the task explicitly requires a WIP series.
- **No force-push** to shared branches (use `git push --force-with-lease` only on your own unmerged branch, never after review has started).
- **No merge commits in the PR** — rebase or squash before merge.

## Enforcement

1. **`hooks/git-guard.sh`** (PreToolUse, Bash matcher) — blocks:
   - `git commit` when current branch is `main` (deny with reason)
   - `git push` to `main` or `origin main` (deny with reason)
   - `git checkout main` followed by `git commit` in the same command
   - `git push --force` and `git push -f` (already blocked by `bash-guard.sh` — kept for redundancy)
2. **`hooks/worktree-guard.sh`** (PreToolUse, Write|Edit|MultiEdit matcher) — HARD BLOCK on edits in the main checkout. Discriminator: `git rev-parse --git-dir == --git-common-dir` evaluated from the repo toplevel (canonicalized via `realpath`). Any Edit/Write/MultiEdit attempted while the session cwd is the main checkout is denied with an actionable message naming the worktree command. **Fails closed** (deny) when `jq` is missing.
3. **`hooks/task-detector.sh`** (UserPromptSubmit) — EARLY WARNING. Detects new-task intent in user prompts (slash-invocations; verb-leading start with word boundary; polite-prefix forms like "let's add"; intent-implying noun phrases). When intent matches AND the session is in the main checkout, emits an `additionalContext` nudge so Claude remembers the rule before doing any work. Silent in worktrees and on clarifying questions. **Fails open with a stderr warning** when `jq` is missing (advisory hook; the hard block is worktree-guard.sh).
4. **`hooks/session-start-check.sh`** (SessionStart) — GENTLE NUDGE at session start. If the session begins in the main checkout (not a worktree), emits an `additionalContext` reminder. Never blocks. **Fails open with a stderr warning** when `jq` is missing.
5. **`hooks/lib/worktree-detect.sh`** — shared `worktree_detect()` helper. All three rule-hooks source this so the `--git-dir`/`--git-common-dir` discriminator doesn't drift across files.
6. **`tests/test_worktree_guard.py`** + **`tests/test_git_workflow.py`** (regression) — on every CI run, asserts:
   - All non-main branches match `<type>/<slug>` format
   - No `TODO` / `wip` / `tmp` slugs in the last 30 commits' branch names
   - Recent merged PR titles follow Conventional Commits
   - `worktree-guard.sh` denies Edit/Write in the main checkout, allows in worktrees, fails closed when `jq` is missing, exits 0 on empty payload, and exits 0 outside any git repo
   - `task-detector.sh` nudges on task-intent prompts in the main checkout, stays silent in worktrees and on non-task prompts (including false-positive guard: "make sure", "write a brief", "addendum:", "fixing typos"), stays silent on empty prompt
   - `session-start-check.sh` nudges when started in the main checkout, stays silent in worktrees, stays silent on missing `cwd`
   - `hooks.json` wires all three hooks into the correct event matchers
7. **PreToolUse `stop-verify`** (existing) — at session end, runs the regression test to catch any rule violations before allowing the session to stop.

## Out of scope (intentionally not enforced)

- Branch deletion hygiene (handled by `git worktree remove` discipline).
- Merge queue / protected-branch GitHub settings (operational concern, lives in repo Settings — see ADR-0021 if added later).
- Issue template enforcement (handled by `.github/ISSUE_TEMPLATE/`).

## Exceptions

- **`hotfix/*`**: only used to revert a merged main commit. PR is auto-mergeable. Still requires a worktree (the revert is a real change). Still requires CI green.
- **Documentation-only fixes to README/CHANGELOG** that the user explicitly requests as "just fix it now" with no PR review: maintainer judgment, but **never** on `main` directly — branch + PR is the only path.

## Related

- `docs/adr/ADR-0022-branch-strategy.md` (rationale, alternatives considered)
- `tests/test_git_workflow.py` (branch-naming + `git-guard` regression)
- `tests/test_worktree_guard.py` (`worktree-guard` + `task-detector` + `session-start-check` regression)
- `hooks/lib/worktree-detect.sh` (shared discriminator — single source of truth)
- `hooks/git-guard.sh` (PreToolUse Bash block)
- `hooks/worktree-guard.sh` (PreToolUse Edit/Write block, fails closed)
- `hooks/task-detector.sh` (UserPromptSubmit nudge, fails open with warning)
- `hooks/session-start-check.sh` (SessionStart nudge, fails open with warning)
- `hooks/hooks.json` (wires all hooks into Claude Code)
