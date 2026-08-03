#!/usr/bin/env bash
# hooks/linear-autosync.sh — PreToolUse Edit|Write|MultiEdit hook.
#
# Calls tools/linear_sync.py so that every Claude Code edit is
# reflected in the user's Linear workspace without a manual
# `/dev-kit:linear` invocation. The Python script is the
# authoritative gate (config + non-blocking). This wrapper exists
# to:
#   1. Pull CLAUDE_PROJECT_DIR from the hook payload.
#   2. Skip when Linear is not configured (no LINEAR_API_KEY, no
#      `.dev-kit/.enabled.json: mcp.linear`).
#   3. Always exit 0 (per #539: "Linear failures are non-blocking
#      for implicit workflow calls.").
#
# The script self-throttles by checking `.dev-kit/hand-off/linear.json`
# — repeated edits within the same task produce a single updated
# issue, not a flood of new issues. A new task (branch change,
# fresh prompt) replaces the handoff first, so auto-sync only ever
# creates or updates one issue per scope.

set -uo pipefail

INPUT=$(cat)
PROJECT_DIR=$(printf '%s' "$INPUT" | sed -n 's/.*"cwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)
if [ -z "${PROJECT_DIR:-}" ]; then
  PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
fi

cd "$PROJECT_DIR" 2>/dev/null || exit 0

# Fast-path: bail before forking Python if the gate is clearly off.
if [ -z "${LINEAR_API_KEY:-}" ] && [ ! -f "$PROJECT_DIR/.dev-kit/.enabled.json" ]; then
  exit 0
fi

# Disable-model-invocation users have no `python3` alias guaranteed.
for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1; then
    "$py" "$PROJECT_DIR/tools/linear_sync.py"
    exit $?
  fi
done

exit 0
