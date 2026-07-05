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
  local cmd_name="$1"
  local i=0
  while [ $i -lt ${#TOKENS[@]} ]; do
    if [ "${TOKENS[$i]}" = "$cmd_name" ]; then
      # Check for env-var prefix (FOO=bar rm ...)
      # Simple heuristic: skip FOO=BAR tokens
      while [ $i -gt 0 ] && [[ "${TOKENS[$((i-1))]}" == *=* ]]; do
        i=$((i-1))
      done
      FIRST_CMD="$cmd_name"
      FIRST_FLAGS="${TOKENS[$((i+1))]:-}"
      FIRST_ARG="${TOKENS[$((i+2))]:-}"
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
if find_cmd "rm"; then
  # FIRST_FLAGS like "-rf", "-fr", "-f", etc.
  # FIRST_ARG is the target
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
fi

# === git push force ===
if printf '%s' "$CMD" | grep -qE '(^|[[:space:]])git([[:space:]]|$)' \
   && printf '%s' "$CMD" | grep -qE '(^|[[:space:]])push([[:space:]]|$)'; then
  if printf '%s' "$CMD" | grep -qE '[[:space:]]--force([[:space:]]|$)|[[:space:]]-f([[:space:]]|$)'; then
    # Exclude --force-with-lease (safer)
    if ! printf '%s' "$CMD" | grep -qE '[[:space:]]--force-with-lease([[:space:]]|$)'; then
      deny "git push --force / -f — use --force-with-lease"
    fi
  fi
fi

# === git reset --hard ===
if printf '%s' "$CMD" | grep -qE '(^|[[:space:]])git([[:space:]]|$)' \
   && printf '%s' "$CMD" | grep -qE '(^|[[:space:]])reset([[:space:]]|$)' \
   && printf '%s' "$CMD" | grep -qE '[[:space:]]--hard([[:space:]]|$)'; then
  deny "git reset --hard — discards uncommitted changes; use git stash first"
fi

# === git clean -fd / -fdx ===
if printf '%s' "$CMD" | grep -qE '(^|[[:space:]])git([[:space:]]|$)' \
   && printf '%s' "$CMD" | grep -qE '(^|[[:space:]])clean([[:space:]]|$)'; then
  if printf '%s' "$CMD" | grep -qE '[[:space:]]-[a-zA-Z]*[fF][a-zA-Z]*[dDxX]'; then
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
