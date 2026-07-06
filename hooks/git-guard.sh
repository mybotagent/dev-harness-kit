#!/usr/bin/env bash
# git-guard.sh — PreToolUse hook for Bash. Enforces branch strategy.
#
# Blocks (exit 2 with deny JSON):
#   1. `git commit` when current branch is main
#   2. `git push` to main / origin main
#   3. `git checkout main` followed by other write operations in the same
#      command (e.g. `git checkout main && git commit -m "..."`)
#   4. Force-push to shared branches
#
# Allows everything else. See .claude/rules/git-workflow.md for rationale.

set -uo pipefail
INPUT="$(cat)"
CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)"
[ -z "$CMD" ] && exit 0

# Skip non-git commands entirely.
case "$CMD" in
  *"git "*) ;;
  *) exit 0 ;;
esac

# We only care about: commit, push, checkout (combined with writes), branch -D
# Skip read-only git commands (status, log, diff, show, rev-parse, etc.)
write_pattern='(git[[:space:]]+commit|git[[:space:]]+push|git[[:space:]]+checkout|git[[:space:]]+switch|git[[:space:]]+branch[[:space:]]+-D|git[[:space:]]+branch[[:space:]]+-d)'
if ! printf '%s' "$CMD" | grep -qE "$write_pattern"; then
  exit 0
fi

# Helper: emit PreToolUse deny JSON and exit 2.
deny() {
  local reason="$1"
  cat >&2 <<EOF
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"GIT GUARD: $reason"}}
EOF
  exit 2
}

# Helper: current branch (empty if detached HEAD or not a git repo).
current_branch() {
  git symbolic-ref --short HEAD 2>/dev/null || true
}

# 1. Block git commit on main.
if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+commit'; then
  CUR=$(current_branch)
  if [ "$CUR" = "main" ] || [ "$CUR" = "master" ]; then
    deny "direct commit to '$CUR' is forbidden. Cut a branch off origin/main first (see .claude/rules/git-workflow.md)."
  fi
fi

# 2. Block git push to main.
if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+push'; then
  # Heuristic: any push that names main / master on the remote side.
  # Catches: `git push origin main`, `git push origin HEAD:main`, `git push --force origin main`.
  if printf '%s' "$CMD" | grep -qE '(^|[[:space:]])(origin[[:space:]]+)?(HEAD:)?(main|master)([[:space:]]|$)|:main\b|:master\b'; then
    deny "pushing to main is forbidden. Push to your feature branch: \`git push -u origin <type>/<slug>\`."
  fi
  # Block force-push (defense in depth — bash-guard already catches this).
  if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+push[[:space:]]+(-f|--force|--force-with-lease)([[:space:]]|$)'; then
    if printf '%s' "$CMD" | grep -qE -- '--force-with-lease'; then
      # --force-with-lease is allowed on your own unmerged branch; only block
      # if the push target is main (already caught above).
      :
    else
      deny "force-push (-f/--force) is forbidden. Use --force-with-lease only on your own unmerged branch."
    fi
  fi
fi

# 3. Block `git checkout main` (or `git switch main`) — it primes a direct
#    commit to main in the next command. Allow `git checkout -b ...` (new branch).
if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+(checkout|switch)[[:space:]]'; then
  # Allow `git checkout -b`, `git checkout <commit>`, `git checkout <file>`.
  if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+(checkout|switch)[[:space:]]+(-b|-c|-[0-9]+[[:space:]]|[a-f0-9]{7,}[[:space:]]|--)'; then
    :
  elif printf '%s' "$CMD" | grep -qE 'git[[:space:]]+(checkout|switch)[[:space:]]+(main|master)([[:space:]]|$)'; then
    deny "switching to main in this checkout is forbidden. Use a worktree instead: \`git worktree add -b <type>/<slug> .claude/worktrees/<slug> origin/main\`."
  fi
fi

# 4. Block `git branch -D` on main (deleting the protection itself).
if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+branch[[:space:]]+-D'; then
  if printf '%s' "$CMD" | grep -qE 'git[[:space:]]+branch[[:space:]]+-D[[:space:]]+(main|master)([[:space:]]|$)'; then
    deny "deleting main/master with -D is forbidden."
  fi
fi

exit 0
