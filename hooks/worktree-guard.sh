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
#   Edits from inside ANY git worktree (main checkout or nested). The
#   discriminator is "git_dir == git_common_dir" which is robust to the
#   worktree living anywhere on disk (not just `.claude/worktrees/`).
#   Edits in non-git directories — this hook is project-scoped.
#
# Why --git-dir vs --git-common-dir:
#   From the main checkout both return the same path (`.git` or its
#   absolute form). From any worktree, --git-dir returns
#   `<common>/worktrees/<name>` while --git-common-dir returns `<common>`.
#   The inequality is a clean, side-effect-free test for "am I in a
#   worktree right now?".
#
# See .claude/rules/git-workflow.md for the full protocol and rationale.

set -uo pipefail
INPUT="$(cat)"

# Fail CLOSED if jq is missing. Without jq we cannot parse the PreToolUse
# payload — silent fail-open would disable this rule entirely.
if ! command -v jq >/dev/null 2>&1; then
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"WORKTREE GUARD: jq is required by worktree-guard.sh but not installed. Install jq (apt/brew/apk) — without it, the worktree rule cannot be enforced."}}\n' >&2
  exit 2
fi

# Confirm we are inside a git working tree. If not, this hook does not
# apply (the rule is scoped to projects with a git-workflow.md contract).
# Always run the rev-parse from the repo toplevel so --git-dir and
# --git-common-dir are relative to a consistent base — otherwise git
# returns absolute for one and relative for the other when the session
# cwd is a subdirectory of the repo (or when /tmp is a symlink like
# /private/tmp on macOS), making equality checks unreliable.
TOPLEVEL="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
GIT_DIR="$(cd "$TOPLEVEL" && git rev-parse --git-dir 2>/dev/null)" || exit 0
GIT_COMMON_DIR="$(cd "$TOPLEVEL" && git rev-parse --git-common-dir 2>/dev/null)" || exit 0

# Canonicalize both to absolute via realpath (falls back to identity if
# realpath is unavailable — macOS ships it by default since 10.12).
abspath() {
  local p="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$p" 2>/dev/null || printf '%s' "$p"
  else
    case "$p" in
      /*) printf '%s' "$p" ;;
      *) printf '%s/%s' "$PWD" "$p" ;;
    esac
  fi
}
GIT_DIR="$(abspath "$GIT_DIR")"
GIT_COMMON_DIR="$(abspath "$GIT_COMMON_DIR")"
GIT_DIR="${GIT_DIR%/}"
GIT_COMMON_DIR="${GIT_COMMON_DIR%/}"

# In a worktree → allow.
if [ "$GIT_DIR" != "$GIT_COMMON_DIR" ]; then
  exit 0
fi

# In main checkout → deny with actionable reason.
BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || echo detached)"
MSG="WORKTREE GUARD: editing in the main checkout (branch='$BRANCH') is forbidden. Per .claude/rules/git-workflow.md: every task = new worktree + new session + new branch. Run: git fetch origin main && git worktree add -b <type>/<slug> .claude/worktrees/<slug> origin/main — then open a new Claude Code session inside that worktree path."

# Build JSON via jq so embedded quotes / backslashes are escaped safely.
jq -nc --arg reason "$MSG" \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}' \
  >&2
exit 2