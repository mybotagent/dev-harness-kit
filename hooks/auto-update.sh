#!/usr/bin/env bash
# auto-update.sh — SessionStart hook.
#
# Self-healing auto-update for the dev-kit plugin. On every session
# start, checks if the local marketplace clone is behind origin/main.
# If so, fast-forward pull + refresh the plugin cache.
#
# Lifecycle:
#   1. Detect the marketplace clone at $HOME/.claude/plugins/marketplaces/dev-kit/.
#      If absent (plugin installed from a non-git source) → silent no-op.
#   2. `git fetch origin main` and compare local HEAD to origin/main.
#      If equal → silent no-op (the common case after a clean session).
#   3. If behind: `git pull --ff-only` + `claude plugin install dev-kit@dev-kit`
#      to refresh the cache. Both steps fail-soft (warn to stderr, never
#      break the session).
#
# Why a SessionStart hook and not a cron / launchd:
#   - No background process to manage.
#   - Runs only when Claude Code is in use (zero idle CPU).
#   - Self-heals within one session of any new push to origin/main.
#   - Latency is bounded by session frequency (acceptable for plugin updates).
#
# This hook is wired alongside session-start-check.sh (the worktree-rule
# nudge) in hooks.json. Both fire on SessionStart; both are silent on
# the common path. The total cost on a no-op session is two `git rev-parse`
# calls + a single `git fetch` (network).

set -uo pipefail
INPUT="$(cat)"

MARKETPLACE_DIR="${DEV_KIT_MARKETPLACE_DIR:-$HOME/.claude/plugins/marketplaces/dev-kit}"

# 1. No marketplace clone → silent no-op (non-maintainer install).
[ -d "$MARKETPLACE_DIR/.git" ] || exit 0

# 2. Fetch + compare. Network failures degrade silently.
cd "$MARKETPLACE_DIR" || exit 0
git fetch origin main --quiet 2>/dev/null || exit 0

LOCAL="$(git rev-parse HEAD 2>/dev/null)"
REMOTE="$(git rev-parse origin/main 2>/dev/null)"
[ -n "$LOCAL" ] && [ -n "$REMOTE" ] || exit 0

# 3. Up to date → silent no-op.
[ "$LOCAL" != "$REMOTE" ] || exit 0

# 4. Behind → fast-forward pull. Fail-soft on non-fast-forward (manual merge needed).
if ! git pull origin main --ff-only --quiet 2>/dev/null; then
  printf '[dev-kit:auto-update] pull failed (not fast-forward?). Resolve manually:\n  cd %s && git pull origin main\n' "$MARKETPLACE_DIR" >&2
  exit 0
fi

# 5. Refresh plugin cache. Try `claude plugin install` first; on failure,
#    warn the user (the session continues with the old cache — graceful).
if command -v claude >/dev/null 2>&1; then
  if timeout 25 claude plugin install dev-kit@dev-kit >/dev/null 2>&1; then
    exit 0
  fi
  printf '[dev-kit:auto-update] plugin cache refresh failed. Run manually:\n  claude plugin install dev-kit@dev-kit\n' >&2
  exit 0
fi

# No `claude` binary on PATH — rare; nothing to do.
exit 0