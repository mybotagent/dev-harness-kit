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
#   anywhere on disk (not just `.claude/worktrees/`).
#   Edits in non-git directories — this hook is project-scoped.
#   Empty / probe payloads — nothing to gate.
#
# Fails closed (exit 2 with deny JSON) when `jq` is missing.
#
# The discriminator lives in hooks/lib/worktree-detect.sh so the
# three rule-hooks don't drift. See .claude/rules/git-workflow.md.

set -uo pipefail
INPUT="$(cat)"

# Source the shared worktree-detection helper.
# shellcheck source=lib/worktree-detect.sh
source "$(dirname "$0")/lib/worktree-detect.sh"

# Fail CLOSED if jq is missing. Without jq we cannot parse the
# PreToolUse payload — silent fail-open would disable this rule.
if ! command -v jq >/dev/null 2>&1; then
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"WORKTREE GUARD: jq is required by worktree-guard.sh but not installed. Install jq (apt/brew/apk) — without it, the worktree rule cannot be enforced."}}\n' >&2
  exit 2
fi

# Extract the target file path. If the payload is empty or has no
# file_path (e.g. a probe call with empty stdin), exit 0 — there is
# nothing to gate. This must run BEFORE the worktree-detect check so
# a probe call from any cwd (main checkout included) is a no-op.
FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // ""' 2>/dev/null)"
[ -z "$FILE_PATH" ] && exit 0

# Detect whether we are in the main checkout or a worktree. The lib
# function never returns 1 here because we just verified jq exists.
worktree_detect
case "$WORKTREE_DETECT" in
  worktree|outside|"") exit 0 ;;
  main) ;;
  *) exit 0 ;;
esac

# In main checkout → deny with actionable reason.
BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || echo detached)"
MSG="WORKTREE GUARD: editing in the main checkout (branch='$BRANCH') is forbidden. Per .claude/rules/git-workflow.md: every task = new worktree + new session + new branch. Run: git fetch origin main && git worktree add -b <type>/<slug> .claude/worktrees/<slug> origin/main — then open a new Claude Code session inside that worktree path."

# Build JSON via jq so embedded quotes / backslashes are escaped safely.
jq -nc --arg reason "$MSG" \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}' \
  >&2
exit 2