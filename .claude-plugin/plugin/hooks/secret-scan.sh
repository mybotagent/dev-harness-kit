#!/usr/bin/env bash
# secret-scan.sh — PostToolUse hook. Detects credential patterns in Write/Edit/MultiEdit.
# Default advisory (exit 0).

set -eo pipefail
INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""' 2>/dev/null)
CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // .tool_input.new_string // ""' 2>/dev/null)
[ -z "$CONTENT" ] && exit 0

# Patterns (regex). NO secret text in output — masked only.
PATTERNS=(
  "AKIA[0-9A-Z]{16}"
  "sk-[a-zA-Z0-9_-]{20,}"
  "sk-ant-[a-zA-Z0-9_-]{20,}"
  "ghp_[a-zA-Z0-9]{36}"
  "gho_[a-zA-Z0-9]{36}"
  "xox[bpoa]-[a-zA-Z0-9-]{20,}"
  "-----BEGIN [A-Z ]*PRIVATE KEY-----"
  "postgres://[^:]+:[^@]+@"
  "mongodb\+srv://[^:]+:[^@]+@"
)

HITS=()
for p in "${PATTERNS[@]}"; do
  MATCHES=$(echo "$CONTENT" | grep -oE "$p" 2>/dev/null | head -3)
  if [ -n "$MATCHES" ]; then
    HITS+=("$p × $(echo "$MATCHES" | wc -l)")
  fi
done

if [ ${#HITS[@]} -gt 0 ]; then
  echo "[secret-scan] $FILE — credential patterns detected (masked):" >&2
  for h in "${HITS[@]}"; do
    echo "  - $h" >&2
  done
  echo "[secret-scan] Remove or replace with env var reference." >&2
fi
exit 0
