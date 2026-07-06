#!/usr/bin/env bash
# session-start-check.sh — SessionStart hook.
#
# Gentle reminder layer for the "every task = new worktree" rule.
#
# Fires once at session start. If the session cwd is the MAIN repo
# checkout (not a worktree), emit an additionalContext reminder so
# Claude remembers the rule from the very first turn. Claude can then
# either nudge the user to cut a worktree, or — if the session is
# legitimately a read-only investigation in the main checkout — proceed
# carefully knowing that worktree-guard.sh will block any Edit/Write.
#
# This hook never blocks. The hard block is worktree-guard.sh.
#
# Discriminator: --git-dir == --git-common-dir ⇒ main checkout.

set -uo pipefail
INPUT="$(cat)"

# Need jq to read the (optional) cwd field.
if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

# Prefer the cwd from the hook payload (more authoritative than $PWD),
# fall back to PWD if missing.
HOOK_CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // ""' 2>/dev/null)"
if [ -n "$HOOK_CWD" ] && [ -d "$HOOK_CWD" ]; then
  cd "$HOOK_CWD" || exit 0
fi

# Inside a git working tree? Always run rev-parse from the repo toplevel
# so --git-dir and --git-common-dir are relative to a consistent base
# (avoids absolute/relative mismatch in subdirectories or with symlinked
# /tmp on macOS).
TOPLEVEL="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
GIT_DIR="$(cd "$TOPLEVEL" && git rev-parse --git-dir 2>/dev/null)" || exit 0
GIT_COMMON_DIR="$(cd "$TOPLEVEL" && git rev-parse --git-common-dir 2>/dev/null)" || exit 0

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

# In a worktree → no reminder.
if [ "$GIT_DIR" != "$GIT_COMMON_DIR" ]; then
  exit 0
fi

# In main checkout → emit nudge.
BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || echo detached)"
NUDGE="GIT-WORKFLOW REMINDER (.claude/rules/git-workflow.md): this session started in the main repo checkout (branch='$BRANCH'). For any new implementation task, the rule requires a new worktree + new session + new branch. The hard edit-block is hooks/worktree-guard.sh (PreToolUse). If the user is just investigating or asking questions, proceed; before any Edit/Write, suggest the worktree cut: git fetch origin main && git worktree add -b <type>/<slug> .claude/worktrees/<slug> origin/main."

jq -nc --arg ctx "$NUDGE" \
  '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$ctx}}'
exit 0