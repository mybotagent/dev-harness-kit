#!/usr/bin/env bash
# worktree-guard.sh — PreToolUse hook for Write|Edit|MultiEdit.
#
# Enforces .claude/rules/git-workflow.md "every task = new worktree" rule.
#
# Denies (exit 2):
#   Edit / Write / MultiEdit when the session cwd is the MAIN repo checkout
#   (the checkout that owns the .git directory at its root). Forces the
#   user to cut a worktree off origin/main before making any edits.
#
# Allows (exit 0):
#   Edits from inside ANY git worktree. The discriminator is
#   `git_dir == git_common_dir` which is robust to the worktree living
#   anywhere on disk (not just `.worktrees/`).
#   Edits in non-git directories — this hook is project-scoped.
#   Empty / probe payloads — nothing to gate.
#
# Fails closed (exit 2 with deny JSON) when `jq` is missing.
#
# The discriminator lives in hooks/lib/worktree-detect.sh so the
# three rule-hooks don't drift. See .claude/rules/git-workflow.md.

# VERSION-SLOT RULE (canonical contract — see PR #270 for the
# implementation and test):
#   slot = origin/main HEAD plugin.json version + (PR merge-order index - 1)
# Sub-agents pushing a PR MUST verify slot, re-pin both plugin.json
# files if mismatched, then push with --force-with-lease.
# Slot examples (assuming origin/main HEAD = 0.3.75):
#   PR #266 -> slot 1 -> 0.3.76
#   PR #267 -> slot 2 -> 0.3.77
#   PR #271 -> slot 6 -> 0.3.81
#
# _compute_version_slot — version-slot helper for parallel-PR pushes.
#
# Computes the plugin.json version slot for a PR given its merge-order
# position. The formula:
#   slot = origin/main HEAD version + (PR_index - 1)
# where PR_index is 1-based (1 = first merged, 2 = second, etc.).
#
# Sub-agents pushing a PR MUST call this to verify their plugin.json
# matches the slot BEFORE pushing. If mismatch: re-pin both files,
# commit, then push with --force-with-lease.
#
# Reference: see the "VERSION-SLOT RULE" block above in the hook
# header comments for the full rationale and slot examples.
_compute_version_slot() {
  local pr_index="${1:-1}"   # 1-based merge-order position
  local main_version
  main_version=$(git show origin/main:.claude-plugin/plugin.json 2>/dev/null \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['version'])" 2>/dev/null)
  if [ -z "$main_version" ]; then
    printf '0.3.75\n'   # fallback (origin unavailable)
    return 0
  fi
  python3 -c "
import sys
v = '${main_version}'
parts = v.split('.')
parts[2] = str(int(parts[2]) + ${pr_index} - 1)
print('.'.join(parts))
"
}

set -uo pipefail
INPUT="$(cat)"

# Source the shared worktree-detection helper.
# shellcheck source=lib/worktree-detect.sh
source "$(dirname "$0")/lib/worktree-detect.sh"
source "${BASH_SOURCE[0]%/*}/lib/payload-parse.sh"

# Fail CLOSED if jq is missing. Without jq we cannot parse the
# PreToolUse payload — silent fail-open would disable this rule.
if ! command -v jq >/dev/null 2>&1; then
  # Hand-built printf here (not the deny() helper from payload-parse.sh)
  # because deny() itself depends on jq. Self-contained fail-closed.
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"WORKTREE GUARD: jq is required by worktree-guard.sh but not installed. Install jq (apt/brew/apk) — without it, the worktree rule cannot be enforced."}}\n' >&2
  exit 2
fi

# Extract the target file path. If the payload is empty or has no
# file_path (e.g. a probe call with empty stdin), exit 0 — there is
# nothing to gate. This must run BEFORE the worktree-detect check so
# a probe call from any cwd (main checkout included) is a no-op.
FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // ""' 2>/dev/null)"
[ -z "$FILE_PATH" ] && exit 0

# Orchestration branches (orch/*) are routing/analysis-only worktrees.
# Edits to protected paths (code, hooks, tests, manifests, plugins,
# and source extensions) are denied here so any code change still
# flows through a non-orchestration worktree
# (fix/|feat/|docs/|chore/|test/|refactor/|perf/|hotfix/). User
# handoff temp notes under .dev-kit/round-*/** remain writable so
# the orchestrator can leave round-N notes for the receiving client.
#
# B — branch detection goes via file_path extraction (NOT the
# parent-session cwd), because sub-agents running inside a nested
# worktree still inherit the parent's `git symbolic-ref --short HEAD`
# output of `main` — see the parent-cwd misfire notes. The previous
# version of this hook therefore always saw `main` and never fired
# the orch branch check; the file_path extraction below closes that
# gap by reading the branch from the worktree the file_path points
# into (the worktree IS a git linkfile, so `git -C <path>` resolves
# the correct branch without cd).
ORCH_BRANCH=""
if [[ "$FILE_PATH" =~ (\.worktrees/)([^/]+) ]]; then
  WT_NAME="${BASH_REMATCH[2]}"
  # Resolve the worktree dir relative to the main checkout, which
  # always owns the `.worktrees/<name>/` sibling directories.
  if [ -d ".worktrees/${WT_NAME}" ]; then
    ORCH_BRANCH="$(git -C ".worktrees/${WT_NAME}" symbolic-ref --short HEAD 2>/dev/null || echo detached)"
  fi
fi
if [[ "$ORCH_BRANCH" == orch/* ]]; then
  # .dev-kit/round-*/** hand-off tmp notes are the ONLY writable paths
  # on an orchestration branch — short-circuit before main-deny so the
  # orchestrator can leave round-N notes even if cwd is main checkout.
  # Matches .dev-kit/round-* at the start OR after any slash segment.
  if [[ "$FILE_PATH" =~ (^|/)\.dev-kit/round- ]]; then
    exit 0
  fi
  case "$FILE_PATH" in
    *lib/*|*lib|*skills/*|*skills|*hooks/*|*hooks|*tests/*|*tests|*templates/*|*templates|*bin/*|*bin|*.codex-plugin*|*.claude-plugin*|*.py|*.sh|*.ts|*.js)
      deny "ORCH ISOLATION" "code edits are forbidden in orch/* worktree. Allowed paths only are .dev-kit/round-*/**. Move the change to a feature worktree."
      ;;
  esac
fi

# Detect whether we are in the main checkout or a worktree. The lib
# function never returns 1 here because we just verified jq exists.
worktree_detect
case "$WORKTREE_DETECT" in
  worktree|outside|"") exit 0 ;;
  main) ;;
  *) exit 0 ;;
esac

# In main checkout → deny with actionable reason. The case statement
# and the deny() call below are byte-identical to the pre-PR-270
# version — only the MSG string content is updated to the
# deterministic env-var checklist + Iron Laws recap.
BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || echo detached)"
MSG="WORKTREE GUARD: editing in main checkout (branch='$BRANCH') is forbidden.

REQUIRED environment setup before retrying:
  git config --global dev-kit.orch.client=claude   # or codex
  git config --global dev-kit.orch.concurrency=single   # or parallel

Without these, abort this edit. Re-running without setting them will be denied.

Routing (after config is set):
  claude  + single   -> git worktree add -b <type>/<slug> .worktrees/<slug> origin/main
                        cd .worktrees/<slug>
                        open a Claude session there
  claude  + parallel -> same worktree, then fan out sub-agents via the Agent tool
  codex   + single   -> git worktree add ..., then spawn one sub-agent with cwd=<worktree>
  codex   + parallel -> spawn N sub-agents each with cwd=<worktree> and explicit task prompt

Hard rules (Iron Laws §1):
  L1: no prod code without verification artifact (test/contract/domain)
  L3: no completion claim without quoted exit codes / test counts
  L4: no TODO/FIXME/later/starting-point
  L5: no option list when not asked
  M push / commit / PR to main: forbidden
  M edit of code files in any worktree: forbidden (Tier 1 = orchestrator)
  Other worktrees are private to their T; entry is allowed ONLY for hand-off docs
   in .dev-kit/round-*/**."

  deny "WORKTREE GUARD" "$MSG"
