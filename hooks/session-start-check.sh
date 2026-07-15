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
#
# Fails open (with stderr warning) when `jq` is missing — the rule is
# advisory in this hook. worktree-guard.sh is the hard-block layer.

set -uo pipefail
INPUT="$(cat)"

# Source the shared worktree-detection helper.
# shellcheck source=lib/worktree-detect.sh
source "$(dirname "$0")/lib/worktree-detect.sh"

# Warn (not fail) if jq is missing.
if ! command -v jq >/dev/null 2>&1; then
  worktree_detect_jq_missing_warn "session-start-check.sh"
  exit 0
fi

# Prefer the cwd from the hook payload (more authoritative than $PWD),
# fall back to PWD if missing.
HOOK_CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // ""' 2>/dev/null)"
if [ -n "$HOOK_CWD" ] && [ -d "$HOOK_CWD" ]; then
  cd "$HOOK_CWD" || exit 0
fi

# Detect whether we are in the main checkout or a worktree.
worktree_detect
case "$WORKTREE_DETECT" in
  worktree|outside|"") exit 0 ;;
  main) ;;
  *) exit 0 ;;
esac

# In main checkout → emit nudge.
BRANCH="$(git symbolic-ref --short HEAD 2>/dev/null || echo detached)"
NUDGE="GIT-WORKFLOW REMINDER (rules/git-workflow.md): this session started in the main repo checkout (branch='$BRANCH'). For any new implementation task, the rule requires a new worktree + client handoff + new branch. The hard edit-block is hooks/worktree-guard.sh (PreToolUse). If the user is just investigating or asking questions, proceed; before any Edit/Write, cut a worktree with: git fetch origin main && git worktree add -b <type>/<slug> .worktrees/<slug> origin/main. Claude Code then opens a new session in that path; Codex spawns/hand-offs a subagent with that path as its working directory."

jq -nc --arg ctx "$NUDGE" \
  '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$ctx}}'
exit 0
