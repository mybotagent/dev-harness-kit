#!/usr/bin/env bash
# worktree-auto-cut.sh — UserPromptSubmit hook.
#
# Auto-prepares a new worktree when the user starts a new task in the
# main checkout. Companion to task-detector.sh: that hook only nudges;
# this one (a) derives a slug from the prompt, (b) cuts the worktree
# (with all preconditions checked first), and (c) bootstraps the
# log-on scaffold inside the new worktree so the user's first session
# in it is already captured by /dev-kit:token-analyzer.
#
# The hook never blocks. On any failure (network, dirty main, slug
# derivation, etc.) it falls back to a manual-cut nudge so the user
# is never stuck. On success it returns an additionalContext telling
# the assistant to suggest opening a new session in the new path.
#
# Discriminator: WORKTREE_DETECT = "main" + task-intent prompt.
# Silent in worktrees, outside git, on non-task prompts, and when jq
# is missing. Fails open with a stderr warning on missing jq.
#
# Slug policy: `<type>/<verb>-<word1>-<short-hash>` (Q1(a) — descriptive
# + collision-proof). Type defaults to "fix" — the hook does NOT infer
# feat/refactor from the verb because the user can rename before commit.
# Hash = first 6 chars of `git hash-object` on a deterministic seed
# derived from the prompt, so two users with the same prompt get the
# same hash.
#
# Preconditions (any failure → fall back to manual nudge):
#   1. `git status --porcelain` is empty (main is clean)
#   2. The derived branch does not already exist
#   3. `git fetch <remote> <main-ref>` succeeds (or, if no remote,
#      `git rev-parse --verify <main-ref>` succeeds — local fallback)
#   4. `git worktree add` succeeds
#   5. `log-on.sh` runs to completion inside the new worktree
#
# Hook timeout: 30s (the cost is dominated by `git fetch`).

set -uo pipefail
INPUT="$(cat)"

# Source the shared worktree-detection helper.
# shellcheck source=lib/worktree-detect.sh
source "$(dirname "$0")/lib/worktree-detect.sh"

# Fail open with a stderr warning if jq is missing — this hook is
# advisory; worktree-guard.sh is the hard block.
if ! command -v jq >/dev/null 2>&1; then
  worktree_detect_jq_missing_warn "worktree-auto-cut.sh"
  exit 0
fi

PROMPT="$(printf '%s' "$INPUT" | jq -r '.prompt // ""' 2>/dev/null)"
[ -z "$PROMPT" ] && exit 0

# Prefer cwd from the hook payload; fall back to PWD.
HOOK_CWD="$(printf '%s' "$INPUT" | jq -r '.cwd // ""' 2>/dev/null)"
if [ -n "$HOOK_CWD" ] && [ -d "$HOOK_CWD" ]; then
  cd "$HOOK_CWD" || exit 0
fi

# Discriminator: only fire in the main checkout. Worktree sessions
# already follow the rule; outside-git is out of scope.
worktree_detect
case "$WORKTREE_DETECT" in
  worktree|outside|"") exit 0 ;;
  main) ;;
  *) exit 0 ;;
esac

# Detect task intent (same verb regex as task-detector.sh — keep the
# two hooks' classification identical so users see consistent behavior).
LOWER="$(printf '%s' "$PROMPT" | tr '[:upper:]' '[:lower:]')"
task_intent=0
case "$LOWER" in
  /*) task_intent=1 ;;
esac
if [ "$task_intent" = "0" ] && printf '%s' "$LOWER" | grep -qE '^(implement|add|build|create|fix|refactor|develop|introduce|write|design)([[:space:]]|$|:)'; then
  task_intent=1
fi
if [ "$task_intent" = "0" ] && printf '%s' "$LOWER" | grep -qE "(let'?s|i want to|please|can you|could you|help me)[[:space:]]+(implement|add|build|create|fix|refactor|develop|introduce|write|design)"; then
  task_intent=1
fi
if [ "$task_intent" = "0" ] && printf '%s' "$LOWER" | grep -qE "(new (feature|task|endpoint|function|module|hook|skill)|feature request|bug report)"; then
  task_intent=1
fi
# Require a code-edit verb to be present anywhere in the prompt
# (Q2: safer than the leading-verb check alone). This filters out
# "investigate this error", "explain X", "what does Y do?".
if [ "$task_intent" = "1" ] && ! printf '%s' "$LOWER" | grep -qE '(implement|add|build|create|fix|refactor|rename|delete|remove|update|change|introduce)[[:space:]]+(file|function|method|class|module|hook|skill|test|feature|column|field|variable|api|endpoint|route|handler|component|import|export|line|lines)'; then
  task_intent=0
fi
[ "$task_intent" = "1" ] || exit 0

# Precondition 1: main is clean.
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  exit 0   # dirty main → fall back to manual nudge (task-detector.sh)
fi

# Derive slug from the prompt. Strategy:
#   - Take the first strong verb + the first 1-2 content words
#   - Lowercase, strip non-alphanumeric (keep kebab-case)
#   - Truncate to <= 30 chars (room for type + hash)
#   - Append 6-char hash = first 6 of `git hash-object /dev/null` on a
#     seed derived from the prompt itself (deterministic per prompt).
# If the regex doesn't match (very rare for task prompts), fall back
# to a date-based slug.
derive_slug() {
  local prompt_lc="$1"
  local verb noun slug hash seed type
  # Extract first verb (whichever is at the start of the prompt).
  verb="$(printf '%s' "$prompt_lc" | grep -oE '^(implement|add|build|create|fix|refactor|develop|introduce|write|design)' | head -1)"
  [ -z "$verb" ] && verb="fix"
  # First 1-2 content words AFTER the verb. Strip punctuation, drop
  # common stop words. Cap at 20 chars total.
  noun="$(printf '%s' "$prompt_lc" | sed -E "s/^${verb}//; s/[[:punct:]]//g; s/[[:space:]]+/\n/g" \
        | grep -vE '^(a|an|the|to|for|of|in|on|at|by|with|that|this|it|its|be|is|are|was|were|i|me|my|we|our|you|your)$|^$' \
        | head -2 \
        | tr '\n' '-' \
        | sed 's/-$//')"
  # Compose: verb-noun- (or just verb- if noun empty).
  if [ -n "$noun" ]; then
    slug="${verb}-${noun}"
  else
    slug="${verb}"
  fi
  # Truncate slug body to 24 chars (leaves 6 for hash, plus type prefix).
  slug="${slug:0:24}"
  # Strip trailing dash from the truncation.
  slug="${slug%-}"
  # Type prefix — default to "fix" because the user can rename before
  # commit; the verb mapping is intentionally not used.
  type="fix"
  # Hash from the full prompt — deterministic, so two sessions with the
  # same prompt at different times don't collide.
  seed="auto-cut:${prompt_lc}"
  hash="$(printf '%s' "$seed" | git hash-object --stdin 2>/dev/null | head -c 6 || true)"
  [ -z "$hash" ] && hash="$(date +%s | tail -c 7)"
  printf '%s/%s-%s\n' "$type" "$slug" "$hash"
}

# Check if the branch already exists; if so, append a numeric suffix.
unique_branch_name() {
  local base="$1"
  local candidate="$base"
  local n=1
  while git show-ref --verify --quiet "refs/heads/${candidate}" 2>/dev/null; do
    candidate="${base}-${n}"
    n=$((n + 1))
    [ "$n" -gt 99 ] && return 1
  done
  printf '%s\n' "$candidate"
}

SLUG="$(derive_slug "$LOWER")"
# Slug must match the project branch-naming regex (kebab-case, length
# 2-40, type prefix, no forbidden words). Reject and fall back if not.
if ! printf '%s' "$SLUG" | grep -qE '^(fix|feat|refactor|docs|test|chore|perf|hotfix)/[a-z0-9-]{2,40}$'; then
  exit 0
fi
# Reject forbidden slugs (per .claude/rules/git-workflow.md).
case "$SLUG" in
  */wip|*/tmp|*/foo|*/bar|*/asdf|*/test|*/scratch|*/untitled) exit 0 ;;
esac

BRANCH="$(unique_branch_name "$SLUG" 2>/dev/null)" || exit 0
DIRNAME="${BRANCH#*/}"  # strip type prefix for the worktree dir name.

# Resolve which main ref to branch from. Prefer origin/main (just-
# fetched); fall back to local main (no-remote case, e.g. tests).
MAIN_REF=""
if git remote get-url origin >/dev/null 2>&1; then
  if git fetch origin main >/dev/null 2>&1; then
    MAIN_REF="origin/main"
  fi
fi
if [ -z "$MAIN_REF" ] && git rev-parse --verify main >/dev/null 2>&1; then
  MAIN_REF="main"
fi
[ -n "$MAIN_REF" ] || exit 0

WT_PARENT="$PWD/.claude/worktrees"
mkdir -p "$WT_PARENT"
WT_PATH="$WT_PARENT/$DIRNAME"

# Precondition 4: worktree doesn't already exist on disk.
if [ -d "$WT_PATH" ]; then
  exit 0
fi

# Auto-cut. The hook-level timeout (30s in hooks.json) bounds the
# whole operation. `git worktree add` is normally <2s; if it spikes
# (e.g. huge repos) the hook just gets killed by the harness. Note:
# no `timeout(1)` wrapper because macOS does not ship coreutils
# `timeout` by default — the wrapper would rc=127 on every Mac.
if ! git worktree add -b "$BRANCH" "$WT_PATH" "$MAIN_REF" >/dev/null 2>&1; then
  # Clean up partial state on failure.
  git worktree remove --force "$WT_PATH" 2>/dev/null || true
  git branch -D "$BRANCH" 2>/dev/null || true
  exit 0
fi

# Bootstrap: run /dev-kit:log setup + /dev-kit:log on inside the new
# worktree so the user's first session there is captured. Falls
# through silently if either script is missing (e.g. dev-kit plugin
# not yet installed in the consumer project).
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
LOG_SETUP="$PLUGIN_ROOT/skills/log/scripts/log-setup.sh"
LOG_ON="$PLUGIN_ROOT/skills/log/scripts/log-on.sh"

if [ -f "$LOG_SETUP" ]; then
  (cd "$WT_PATH" && TARGET_DIR="$WT_PATH" bash "$LOG_SETUP" >/dev/null 2>&1) || true
fi
if [ -f "$LOG_ON" ]; then
  (cd "$WT_PATH" && TARGET_DIR="$WT_PATH" bash "$LOG_ON" >/dev/null 2>&1) || true
fi

# Build additionalContext — the assistant will see this and tell the
# user to open a new session in the new path.
CTX="worktree auto-cut ready
  branch:  $BRANCH
  path:    $WT_PATH
  next:    open a new Claude Code session in $WT_PATH
  fallback: if any of the above fails, run:
            git fetch origin main && git worktree add -b $BRANCH $WT_PATH $MAIN_REF"
jq -nc --arg ctx "$CTX" \
  '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$ctx}}'
exit 0
