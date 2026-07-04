#!/usr/bin/env bash
# bash-guard.sh — PreToolUse hook for Bash. Blocks destructive commands.
# Default advisory (exit 0); hard-block (exit 2) with --strict.

set -eo pipefail
INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)
[ -z "$CMD" ] && exit 0

# Destructive patterns
BLOCKED_PATTERNS=(
  "rm -rf /"
  "rm -rf ~"
  "rm -rf \$HOME"
  "git push --force.* main"
  "git push -f .* main"
  "git reset --hard"
  "git clean -f"
  "DROP TABLE"
  "DROP DATABASE"
  "chmod 777"
  "chown -R /"
  ">/etc/passwd"
  "curl|sh"
  "wget.*\\|.*sh"
  "npm publish"
  "docker system prune"
  "eval \$"
  "DEV_KIT_HOOK_OFF=.bash-guard"
)

for pattern in "${BLOCKED_PATTERNS[@]}"; do
  if echo "$CMD" | grep -qE "$pattern"; then
    if [ "${DEV_KIT_STRICT:-0}" = "1" ]; then
      echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"BASH GUARD (strict): pattern '$pattern' blocked.\"}}" >&2
      exit 2
    fi
    echo "[bash-guard] Pattern '$pattern' in command: ${CMD:0:60}... (advisory). strict mode required to block." >&2
    exit 0
  fi
done
exit 0
