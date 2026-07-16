#!/usr/bin/env bash
# worktree-verify-clean.sh — repair helper for issue #215.
#
# Two ways to invoke the underlying `worktree_verify_clean <path>`
# (defined in lib/worktree-verify-clean.sh):
#
#   1. From any shell, as a one-shot post-cut verify step:
#        bash hooks/worktree-verify-clean.sh <worktree-path>
#      The script sources the lib helper, calls it on the given path,
#      prints the one-line summary on stdout, and exits 0 (always — the
#      repair is best-effort and never fails the caller).
#
#   2. As an optional PostToolUse:Bash hook (matcher `Bash`,
#      command pattern matching `git worktree add`). When wired into
#      hooks.json, every `git worktree add` Claude Code observes is
#      followed by a no-op verify that leaves the worktree cleanly
#      aligned with HEAD's blob. The hook is opt-in — opt-in keeps the
#      protected surface small (no side effect on existing workflows)
#      and lets projects decide whether to wire it via ci-setup.
#
# What it does (see lib/worktree-verify-clean.sh for the contract):
# walks tracked files at HEAD, compares each on-disk SHA to HEAD's
# blob SHA, and `git checkout HEAD -- <path>` restores any that
# disagree. Untracked files, deleted files, and files where the disk
# content already matches HEAD are left alone.
#
# Why PostToolUse (in the opt-in path) and not PreToolUse? The stale-
# file state can only be detected AFTER the worktree exists (we need
# its HEAD blob SHAs) and AFTER git has finished its own bookkeeping.
# PreToolUse runs before the command, which is too early; PostToolUse
# is the correct layer for the safety net.
#
# Never blocks. A failed repair is logged to stderr (advisory) but does
# not fail-stop the calling session — the worktree is still functional,
# just possibly out of sync, and a human can run
# `git checkout HEAD -- <path>` manually.
#
# Mode dispatch:
#   - $1 is a directory → CLI mode (manual verify). Run helper, exit 0.
#   - stdin is non-empty JSON → hook mode (PostToolUse). Parse the
#     bash command, dispatch on `git worktree add`, exit 0.

set -uo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB="$HOOK_DIR/lib/worktree-verify-clean.sh"

# CLI mode: caller passed a directory as $1. Source the lib and run.
if [ $# -ge 1 ] && [ -d "$1" ]; then
  # shellcheck source=lib/worktree-verify-clean.sh
  source "$LIB"
  worktree_verify_clean "$1"
  exit 0
fi
# CLI help mode.
if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  sed -n '2,/^set -uo pipefail/p' "$0" | sed -n '1,/@$/p' || true
  echo "
usage:
  bash $0 <worktree-path>    # one-shot verify a worktree
  (no args; JSON on stdin)   # PostToolUse:Bash hook mode"
  exit 0
fi

# Hook mode.
INPUT="$(cat)"
[ -n "$INPUT" ] || exit 0
command -v jq >/dev/null 2>&1 || exit 0

# Pull the bash command the assistant (or shell) just executed.
CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)"
[ -n "$CMD" ] || exit 0

# Match exactly the shapes we care about. We avoid matching
# `git worktree remove`, `git worktree list`, etc.
case "$CMD" in
  *git*worktree*add*) ;;
  *) exit 0 ;;
esac
# Refine — require the literal `git worktree add` (or `git worktree add -f`,
# etc.) preceded by a command boundary. Avoids `git worktree add lookalikes`
# inside other commands.
if ! printf '%s' "$CMD" | grep -qE '(^|[[:space:]]|;|&&|\|\|)git([[:space:]]+|-)worktree([[:space:]]+|-)add([[:space:]]|$)'; then
  exit 0
fi

[ -f "$LIB" ] || exit 0

# Pick a sensible worktree target to verify. We try, in order:
#   1. The last token of the command (most common — `git worktree add
#      -b branch /path` ends in the path).
#   2. All worktrees registered in the current repo (best-effort:
#      run the helper on each; the helper short-circuits cleanly when
#      there's no drift).
TARGETS=()

# (1) Last positional arg.
last="$(printf '%s' "$CMD" | awk '{print $NF}')"
if [ -n "$last" ] && [ "$last" != "$CMD" ] && [ -d "$last" ]; then
  TARGETS+=("$last")
fi

# (2) All worktrees registered in the current repo.
if REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  if [ -d "$REPO_ROOT/.git" ]; then
    while IFS= read -r wt; do
      [ -n "$wt" ] && [ "$wt" != "$REPO_ROOT" ] && TARGETS+=("$wt")
    done < <(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
             | awk '/^worktree /{print $2}')
  fi
fi

# De-duplicate TARGETS while preserving order.
if [ "${#TARGETS[@]}" -gt 0 ]; then
  unique=()
  for t in "${TARGETS[@]}"; do
    skip=0
    for u in "${unique[@]:-}"; do
      [ "$t" = "$u" ] && { skip=1; break; }
    done
    [ "$skip" = "0" ] && unique+=("$t")
  done
  TARGETS=("${unique[@]}")
fi

# Run the helper on each candidate. We silence stdout (so the JSON
# envelope on the calling hook is unaltered); we forward stderr so a
# real repair surfaces in the user's terminal.
for wt in "${TARGETS[@]:-}"; do
  (
    # shellcheck source=lib/worktree-verify-clean.sh
    source "$LIB"
    worktree_verify_clean "$wt"
  ) 2>&1 >&2 || true
done

exit 0
