#!/usr/bin/env bash
# block-dangerous-commands.sh — PreToolUse hook for team installs.
# Hard-blocks destructive commands when present in a Bash invocation.
#
# Input (Claude Code hook protocol, JSON via stdin):
#   {"tool_name": "Bash", "tool_input": {"command": "..."}}
#
# Behavior:
#   - Tokenizes the command into args (bash word splitting, quote-aware
#     via jq + read -a on a JSON-array projection)
#   - Hard-blocks (exit 2 + JSON deny) on any match
#   - Disjoint with bash-guard.sh: this covers ONLY destructive Unix/Git
#     commands. bash-guard covers DDL, npm publish, eval, etc.
#
# This script is a TEMPLATE — copy into your project's .claude/hooks/
# and reference from .claude/settings.json (see docs/team-adoption.md).

set -uo pipefail

INPUT="$(cat)"

# Extract command string via jq (NOT inline python3 — project convention)
CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)"
[ -z "$CMD" ] && exit 0

# Tokenize the command into a bash array.
# `read -ra` with default IFS handles unquoted whitespace (which is how
# destructive commands typically appear: `rm -rf /`, `git push --force`).
# We intentionally do NOT expand $vars in the captured command — a
# command like `rm -rf $HOME/.cache` must keep `$HOME` literal so the
# case pattern `\$HOME/*` can match.
read -ra TOKENS <<< "$CMD"

# Helper: find the first occurrence of `$1` in TOKENS and capture
# subsequent tokens. Returns via globals FIRST_CMD, FIRST_FLAGS, FIRST_ARG.
# If not found, returns 1.
find_cmd() {
  # Returns 0 if $1 is present anywhere in TOKENS, sets FIRST_CMD / FIRST_FLAGS /
  # FIRST_ARG for the *last* match. Use find_cmd_at() in a loop to iterate
  # every occurrence (defeats "rm -rf safe.txt && rm -rf /" bypass).
  local cmd_name="$1"
  local i=0
  local last_i=-1
  while [ $i -lt ${#TOKENS[@]} ]; do
    if [ "${TOKENS[$i]}" = "$cmd_name" ]; then
      local j=$i
      while [ $j -gt 0 ] && [[ "${TOKENS[$((j-1))]}" == *=* ]]; do
        j=$((j-1))
      done
      last_i=$j
    fi
    i=$((i+1))
  done
  if [ $last_i -ge 0 ]; then
    FIRST_CMD="$cmd_name"
    FIRST_FLAGS="${TOKENS[$((last_i+1))]:-}"
    FIRST_ARG="${TOKENS[$((last_i+2))]:-}"
    return 0
  fi
  return 1
}

find_cmd_at() {
  # Like find_cmd, but starts searching at index $2. Sets FIRST_NEXT to the
  # index AFTER the match (for chained re-invocation).
  local cmd_name="$1"
  local start="$2"
  local i=$start
  while [ $i -lt ${#TOKENS[@]} ]; do
    if [ "${TOKENS[$i]}" = "$cmd_name" ]; then
      local j=$i
      while [ $j -gt 0 ] && [[ "${TOKENS[$((j-1))]}" == *=* ]]; do
        j=$((j-1))
      done
      FIRST_CMD="$cmd_name"
      FIRST_FLAGS="${TOKENS[$((j+1))]:-}"
      FIRST_ARG="${TOKENS[$((j+2))]:-}"
      FIRST_NEXT=$((j+1))
      return 0
    fi
    i=$((i+1))
  done
  return 1
}

deny() {
  cat <<EOF
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"BLOCKED: ${1}"}}
EOF
  exit 2
}

# === Destructive rm ===
# Iterate EVERY occurrence of `rm` in the tokenized command. The earlier
# version only checked the first `rm`, which let "rm -rf safe.txt && rm -rf /"
# slip through (the safe rm matched and the dangerous one was never seen).
START=0
while find_cmd_at "rm" "$START"; do
  START=$FIRST_NEXT
  TARGET="$FIRST_ARG"
  FLAGS="$FIRST_FLAGS"
  # Helper: does TARGET look "dangerous"? (absolute path, $HOME, ~, or wildcard)
  is_dangerous_target() {
    case "$1" in
      /*|~*|\$HOME/*|*\**) return 0 ;;
      *) return 1 ;;
    esac
  }
  # Recursive + force combo on dangerous target
  if printf '%s' "$FLAGS" | grep -qE '[rR]' && printf '%s' "$FLAGS" | grep -qE '[fF]'; then
    if is_dangerous_target "$TARGET"; then
      deny "rm recursive + force on '$TARGET' — refuses absolute / home / wildcard paths"
    fi
  fi
  # -f (no -r) on absolute path: also dangerous
  if printf '%s' "$FLAGS" | grep -qE '[fF]' && ! printf '%s' "$FLAGS" | grep -qE '[rR]'; then
    if is_dangerous_target "$TARGET"; then
      deny "rm -f on '$TARGET' — refuses absolute / home paths without -r"
    fi
  fi
done

# === git push force ===
if printf '%s' "$CMD" | grep -qE '(^|[[:space:]])git([[:space:]]|$)' \
   && printf '%s' "$CMD" | grep -qE '(^|[[:space:]])push([[:space:]]|$)'; then
  if printf '%s' "$CMD" | grep -qE '[[:space:]]--force([[:space:];&|>]*|$)|[[:space:]]-f([[:space:];&|>]*|$)'; then
    # Exclude --force-with-lease (safer)
    if ! printf '%s' "$CMD" | grep -qE '[[:space:]]--force-with-lease([[:space:];&|>]*|$)'; then
      deny "git push --force / -f — use --force-with-lease"
    fi
  fi
fi

# === git reset --hard ===
if printf '%s' "$CMD" | grep -qE '(^|[[:space:]])git([[:space:]]|$)' \
   && printf '%s' "$CMD" | grep -qE '(^|[[:space:]])reset([[:space:]]|$)' \
   && printf '%s' "$CMD" | grep -qE '[[:space:]]--hard([[:space:];&|>]*|$)'; then
  deny "git reset --hard — discards uncommitted changes; use git stash first"
fi

# === git clean -fd / -fdx ===
if printf '%s' "$CMD" | grep -qE '(^|[[:space:]])git([[:space:]]|$)' \
   && printf '%s' "$CMD" | grep -qE '(^|[[:space:]])clean([[:space:]]|$)'; then
  if printf '%s' "$CMD" | grep -qE '[[:space:];&|>][-]?[a-zA-Z]*[fF][a-zA-Z]*[dDxX][[:space:];&|>]*'; then
    deny "git clean -fd/-fdx — wipes untracked + ignored; dry-run with -n first"
  fi
fi

# === Fork bomb (defense in depth) ===
if printf '%s' "$CMD" | grep -qF ':(){:|:&};:'; then
  deny "fork bomb pattern detected"
fi

# === Curl/wget piped to shell ===
if printf '%s' "$CMD" | grep -qE '(^|[[:space:]])(curl|wget)([[:space:]]|$)'; then
  if printf '%s' "$CMD" | grep -qE '\|[[:space:]]*(sh|bash)([[:space:]]|$)'; then
    deny "remote script piped to shell — download, inspect, then execute"
  fi
fi

exit 0
