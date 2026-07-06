#!/usr/bin/env bash
# devkit-refresh.sh — pull the latest dev-kit plugin into the local cache.
#
# Run this after a PR is merged to origin/main to refresh the plugin
# cache that Claude Code actually loads. Equivalent to:
#
#   cd ~/.claude/plugins/marketplaces/dev-kit && git pull origin main --ff-only
#   rsync -a --delete --exclude=.git ... ~/.claude/plugins/marketplaces/dev-kit/ \
#       ~/.claude/plugins/cache/dev-kit/dev-kit/<version>/
#
# Why this script and not `claude plugin install`:
#   - `claude plugin install` works in a regular shell, but throws a
#     Node TypeError when invoked from inside a Claude Code session
#     (cli.js:384 — pre-existing CLI bug, not ours).
#   - This script does the same job with git + rsync, both of which
#     are stable across all environments.
#
# Usage:
#   bin/devkit-refresh.sh                  # refresh dev-kit
#   bin/devkit-refresh.sh --dry-run        # show what would change
#   bin/devkit-refresh.sh --marketplace P  # override marketplace path
#
# Environment overrides:
#   DEV_KIT_MARKETPLACE_DIR  default: $HOME/.claude/plugins/marketplaces/dev-kit
#   DEV_KIT_CACHE_ROOT       default: $HOME/.claude/plugins/cache/dev-kit/dev-kit

set -euo pipefail

MARKETPLACE_DIR="${DEV_KIT_MARKETPLACE_DIR:-$HOME/.claude/plugins/marketplaces/dev-kit}"
CACHE_ROOT="${DEV_KIT_CACHE_ROOT:-$HOME/.claude/plugins/cache/dev-kit/dev-kit}"
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --marketplace) MARKETPLACE_DIR="$2"; shift 2 ;;
    --cache) CACHE_ROOT="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ ! -d "$MARKETPLACE_DIR/.git" ]; then
  echo "error: marketplace clone not found at $MARKETPLACE_DIR" >&2
  exit 1
fi
if [ ! -d "$CACHE_ROOT" ]; then
  echo "error: cache root not found at $CACHE_ROOT" >&2
  exit 1
fi

VERSION="$(grep -m1 '"version"' "$MARKETPLACE_DIR/.claude-plugin/plugin.json" 2>/dev/null \
           | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')"
if [ -z "$VERSION" ]; then
  echo "error: could not parse version from $MARKETPLACE_DIR/.claude-plugin/plugin.json" >&2
  exit 1
fi
CACHE_DIR="$CACHE_ROOT/$VERSION"

echo "marketplace: $MARKETPLACE_DIR (version $VERSION)"
echo "cache:       $CACHE_DIR"

echo
echo "→ git pull origin main"
if [ "$DRY_RUN" = "1" ]; then
  cd "$MARKETPLACE_DIR" && git fetch origin main --quiet
  LOCAL="$(git rev-parse HEAD)"
  REMOTE="$(git rev-parse origin/main)"
  if [ "$LOCAL" = "$REMOTE" ]; then
    echo "  up to date ($LOCAL)"
  else
    echo "  $LOCAL → $REMOTE (would fast-forward)"
  fi
else
  cd "$MARKETPLACE_DIR" && git pull origin main --ff-only
fi

mkdir -p "$CACHE_DIR"

EXCLUDES=(
  --exclude='.git'
  --exclude='.claude/worktrees'
  --exclude='.dev-kit'
  --exclude='.eval-cache'
  --exclude='*.pyc'
  --exclude='__pycache__'
)
RSYNC_FLAGS=(-a --delete "${EXCLUDES[@]}")

echo
if [ "$DRY_RUN" = "1" ]; then
  echo "→ rsync $MARKETPLACE_DIR/ → $CACHE_DIR/  (DRY RUN)"
  rsync --dry-run --itemize-changes "${RSYNC_FLAGS[@]}" \
    "$MARKETPLACE_DIR/" "$CACHE_DIR/" 2>/dev/null \
    | head -30
  echo "  (truncated; first 30 lines)"
else
  echo "→ rsync $MARKETPLACE_DIR/ → $CACHE_DIR/"
  rsync "${RSYNC_FLAGS[@]}" "$MARKETPLACE_DIR/" "$CACHE_DIR/"
  # Keep +x on hook + script files (rsync -a preserves source bits, but
  # ensures correctness on destinations that were created by an earlier
  # install that set mode 0o644).
  find "$CACHE_DIR/hooks" "$CACHE_DIR/templates" -type f -name '*.sh' \
    -exec chmod +x {} + 2>/dev/null || true
  echo "  done."
fi
