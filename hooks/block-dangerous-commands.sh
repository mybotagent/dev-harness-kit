#!/usr/bin/env bash
# block-dangerous-commands.sh — PreToolUse hook
# Hard-block destructive commands. Exits 2 with deny JSON on match.
#
# Input (Claude Code hook protocol, JSON via stdin):
#   {"tool_name": "Bash", "tool_input": {"command": "..."}}
#
# Blocked patterns (case-sensitive on the destructive part, case-insensitive flag):
#   - rm -rf / (or any path starting with /, ~, or containing *)
#   - rm -fr, rm -Rf, rm -fR (any -f + -r combination)
#   - git push --force / -f (any branch)
#   - git push --force-with-lease to main/master
#   - git reset --hard (any ref)
#   - git clean -fd / -fdx (untracked + ignored)
#   - chmod -R 777 / 0777
#   - mkfs / dd if= / fdisk
#   - curl/wget piped to sh/bash
#   - :(){:|:&};: (fork bomb)

set -uo pipefail

INPUT="$(cat)"

# Extract bash command
CMD="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('command', '') or '')
except: print('')
" 2>/dev/null)"

[ -z "$CMD" ] && exit 0

deny() {
  local reason="$1"
  cat <<EOF
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"BLOCKED by block-dangerous-commands: ${reason}"}}
EOF
  exit 2
}

# Recursive rm (any -f + -r combo, with absolute or wildcard path)
if echo "$CMD" | grep -E '\brm\b' | grep -E '\s-[a-zA-Z]*[rR][a-zA-Z]*\s|\s-[a-zA-Z]*[fF][a-zA-Z]*\s' | grep -E '/|~|\*' >/dev/null; then
  deny "recursive rm with absolute/wildcard path: $CMD"
fi
# Simpler: rm -rf / or rm -rf /*
if echo "$CMD" | grep -E '\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*[fF][a-zA-Z]*\s+/' >/dev/null; then
  deny "rm -rf on absolute path: $CMD"
fi
if echo "$CMD" | grep -E '\brm\s+-[a-zA-Z]*[fF][a-zA-Z]*[rR][a-zA-Z]*\s+/' >/dev/null; then
  deny "rm -rf on absolute path: $CMD"
fi

# git push force (any branch)
if echo "$CMD" | grep -E '\bgit\s+push\b' | grep -E '\s--force\b|\s-f\b' >/dev/null; then
  deny "git push --force/-f is blocked: $CMD"
fi

# git reset --hard
if echo "$CMD" | grep -E '\bgit\s+reset\s+--hard' >/dev/null; then
  deny "git reset --hard is blocked: $CMD"
fi

# git clean -fdx / -fd (untracked + ignored)
if echo "$CMD" | grep -E '\bgit\s+clean\s+-[a-zA-Z]*[fF][a-zA-Z]*[dDxX]' >/dev/null; then
  deny "git clean with -fd/-fdx is blocked: $CMD"
fi

# chmod -R 777 / 0777
if echo "$CMD" | grep -E '\bchmod\b' | grep -E '\s-[a-zA-Z]*R[a-zA-Z]*\s|0777' >/dev/null; then
  deny "chmod -R with permissive mode: $CMD"
fi

# mkfs / dd if= / fdisk
if echo "$CMD" | grep -E '\bmkfs(\.[a-z0-9]+)?\b|\bdd\s+if=|\bfdisk\b' >/dev/null; then
  deny "disk operation blocked: $CMD"
fi

# curl/wget piped to sh/bash
if echo "$CMD" | grep -E '\b(curl|wget)\b' | grep -E '\|\s*(sh|bash)\b' >/dev/null; then
  deny "remote script piped to shell: $CMD"
fi

# Fork bomb
if echo "$CMD" | grep -F ':(){:|:&};:' >/dev/null; then
  deny "fork bomb pattern: $CMD"
fi

exit 0
