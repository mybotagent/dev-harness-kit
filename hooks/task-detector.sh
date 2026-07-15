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
#
# Word-boundary regex is used on the leading verb to avoid false
# positives on sentences that happen to start with a verb-as-noun
# ("make sure...", "write a brief summary", "addendum:", "fixing
# typos"). Major 1 of PR #22 review.
#
# Fails open (with stderr warning) when `jq` is missing — the rule is
# advisory in this hook. worktree-guard.sh is the hard-block layer.

set -uo pipefail
INPUT="$(cat)"

# Source the shared worktree-detection helper.
# shellcheck source=lib/worktree-detect.sh
source "$(dirname "$0")/lib/worktree-detect.sh"

# Warn (not fail) if jq is missing. See worktree-detect.sh for the
# helper that emits the warning and the rationale.
if ! command -v jq >/dev/null 2>&1; then
  worktree_detect_jq_missing_warn "task-detector.sh"
  exit 0
fi

PROMPT="$(printf '%s' "$INPUT" | jq -r '.prompt // ""' 2>/dev/null)"
[ -z "$PROMPT" ] && exit 0

# Prefer cwd from the hook payload (consistent with
# session-start-check.sh). Fall back to PWD for older hook callers.
HOOK_CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // ""' 2>/dev/null)"
if [ -n "$HOOK_CWD" ] && [ -d "$HOOK_CWD" ]; then
  cd "$HOOK_CWD" || exit 0
fi

# Detect task intent (case-insensitive). Word-boundary regex on the
# leading verb avoids matching "make sure", "write a brief", etc.
LOWER="$(printf '%s' "$PROMPT" | tr '[:upper:]' '[:lower:]')"

task_intent=0
# 1. Slash-invocation: starts with `/`. Strongest signal of a task.
case "$LOWER" in
  /*) task_intent=1 ;;
esac
# 2. Verb-leading start, with a word boundary immediately after the
#    verb so we don't match "addendum:", "fixing...", etc. "make" is
#    intentionally NOT in the list — "make sure", "make a note",
#    "make a decision" are common non-task uses that produce too many
#    false positives. Use "add"/"create"/"build" instead.
if [ "$task_intent" = "0" ] && printf '%s' "$LOWER" | grep -qE '^(implement|add|build|create|fix|refactor|develop|introduce|write|design)([[:space:]]|$|:)'; then
  task_intent=1
fi
# 3. Polite-prefix form: "let's X", "I want to X", etc.
if [ "$task_intent" = "0" ] && printf '%s' "$LOWER" | grep -qE "(let'?s|i want to|please|can you|could you|help me)[[:space:]]+(implement|add|build|create|fix|refactor|develop|introduce|write|design)"; then
  task_intent=1
fi
# 4. Intent-implying noun phrase.
if [ "$task_intent" = "0" ] && printf '%s' "$LOWER" | grep -qE "(new (feature|task|endpoint|function|module|hook|skill)|feature request|bug report)"; then
  task_intent=1
fi

[ "$task_intent" = "1" ] || exit 0

# Task intent detected — check whether we are inside a worktree.
worktree_detect
case "$WORKTREE_DETECT" in
  worktree|outside|"") exit 0 ;;  # already in worktree, or rule doesn't apply
  main) ;;                        # nudge
  *) exit 0 ;;
esac

# In main checkout + new-task intent → emit additionalContext nudge.
BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || echo detached)"
NUDGE="GIT-WORKFLOW REMINDER (rules/git-workflow.md): the user prompt looks like a new task and the session cwd is the main checkout (branch='$BRANCH'). Per the rule, every task = new worktree + client handoff + new branch. Before editing: (1) git fetch origin main && git pull --ff-only origin main; (2) git worktree add -b <type>/<slug> .worktrees/<slug> origin/main; (3) Claude Code opens a new session in that path; Codex spawns/hand-offs a subagent with that path as cwd and passes the task prompt explicitly. If the user explicitly says 'do it now without a worktree', confirm the override before editing — worktree-guard.sh will block edits in the main checkout otherwise."

jq -nc --arg ctx "$NUDGE" \
  '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$ctx}}'
exit 0
