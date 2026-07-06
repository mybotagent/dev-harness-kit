#!/usr/bin/env bash
# task-detector.sh — UserPromptSubmit hook.
#
# Early-warning layer for the "every task = new worktree" rule (see
# .claude/rules/git-workflow.md).
#
# When a user prompt looks like a NEW TASK (implement / add / build / etc.)
# AND the session cwd is the MAIN checkout (not a worktree), emit an
# additionalContext nudge that names the protocol. Claude then sees the
# reminder before doing any work and can suggest the worktree cut.
#
# This is advisory — it never blocks the prompt. The hard block is
# worktree-guard.sh (PreToolUse on Edit/Write).
#
# Detection:
#   Strong start-verbs: implement / add / build / create / fix / refactor /
#                       develop / introduce / make / write / design
#   Slash-invocation:   /<skill-name>  (slash commands are task-starters)
#   Polite-prefix forms: "let's X", "I want to X", "please X",
#                        "can you X", "could you X", "help me X"
#   Noun phrases:       "new feature", "new task", "feature request"

set -uo pipefail
INPUT="$(cat)"

# Need jq to read the prompt field safely.
if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

PROMPT="$(printf '%s' "$INPUT" | jq -r '.prompt // ""' 2>/dev/null)"
[ -z "$PROMPT" ] && exit 0

# Detect task intent (case-insensitive).
LOWER="$(printf '%s' "$PROMPT" | tr '[:upper:]' '[:lower:]')"

task_intent=0
case "$LOWER" in
  implement*|add*|build*|create*|fix*|refactor*|develop*|introduce*|make*|write*|design*)
    task_intent=1 ;;
  /*)
    task_intent=1 ;;
esac
if [ "$task_intent" = "0" ]; then
  if printf '%s' "$LOWER" | grep -qE "(let'?s|i want to|please|can you|could you|help me)[[:space:]]+(implement|add|build|create|fix|refactor|develop|introduce|make|write|design)"; then
    task_intent=1
  fi
fi
if [ "$task_intent" = "0" ]; then
  if printf '%s' "$LOWER" | grep -qE "(new (feature|task|endpoint|function|module|hook|skill)|feature request|bug report)"; then
    task_intent=1
  fi
fi

[ "$task_intent" = "1" ] || exit 0

# Task intent detected — now check whether we are inside a worktree.
# Same discriminator as worktree-guard.sh. Always run rev-parse from the
# toplevel so --git-dir / --git-common-dir are relative to a consistent
# base (avoids absolute/relative mismatch when cwd is a subdirectory or
# when /tmp is a symlink to /private/tmp on macOS).
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

# In a worktree → no nudge needed.
if [ "$GIT_DIR" != "$GIT_COMMON_DIR" ]; then
  exit 0
fi

# In main checkout + new-task intent → emit additionalContext nudge.
BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || echo detached)"
NUDGE="GIT-WORKFLOW REMINDER (.claude/rules/git-workflow.md): the user prompt looks like a new task and the session cwd is the main checkout (branch='$BRANCH'). Per the rule, every task = new worktree + new session + new branch. Before editing, the user should: (1) git fetch origin main && git pull --ff-only origin main; (2) git worktree add -b <type>/<slug> .claude/worktrees/<slug> origin/main; (3) open a new Claude Code session inside that worktree path. If the user explicitly says 'do it now without a worktree', confirm the override before editing — worktree-guard.sh will block edits in the main checkout otherwise."

jq -nc --arg ctx "$NUDGE" \
  '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$ctx}}'
exit 0