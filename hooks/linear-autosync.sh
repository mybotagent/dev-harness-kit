#!/usr/bin/env bash
# hooks/linear-autosync.sh — PreToolUse Edit|Write|MultiEdit hook.
#
# Calls tools/linear_sync.py so that every Claude Code edit is
# reflected in the user's Linear workspace without a manual
# `/dev-kit:linear` invocation. The Python script is the
# authoritative gate (config + non-blocking). This wrapper exists
# to:
#   1. Pull CLAUDE_PROJECT_DIR from the hook payload.
#   2. Skip when Linear is clearly not configured across ANY of
#      the supported sources (env var, .env.linear, per-worktree
#      linear-config.json, legacy .enabled.json).
#   3. Always exit 0 (per #539: "Linear failures are non-blocking
#      for implicit workflow calls.").
#
# The fast-path is a deliberate micro-optimization. It MUST mirror
# every activation source the Python script supports; if the user
# configured Linear only via `.dev-kit/.env.linear` (Option B in
# the skill), the gate is wide open and we still need to fork
# Python to read the key. Failing to check this is the single
# most common way auto-sync silently stops working.

set -uo pipefail

INPUT=$(cat)
PROJECT_DIR=$(printf '%s' "$INPUT" | sed -n 's/.*"cwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)
if [ -z "${PROJECT_DIR:-}" ]; then
  PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
fi

cd "$PROJECT_DIR" 2>/dev/null || exit 0

# Fast-path: bail before forking Python only if NO activation
# source is present. Mirrors `_enabled()` in tools/linear_sync.py.
if [ -z "${LINEAR_API_KEY:-}" ] && \
   [ ! -f "$PROJECT_DIR/.dev-kit/.env.linear" ] && \
   [ ! -f "$PROJECT_DIR/.dev-kit/linear-config.json" ] && \
   [ ! -f "$PROJECT_DIR/.dev-kit/.enabled.json" ]; then
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
