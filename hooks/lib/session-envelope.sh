#!/usr/bin/env bash
# session-envelope.sh — shared cwd + branch + emit helpers for the two
# nudge hooks (session-start-check.sh + task-detector.sh). Both hook bodies
# duplicate the same envelope:
#   1. extract HOOK_CWD from stdin payload (more authoritative than $PWD)
#   2. cd into HOOK_CWD if it's a real directory
#   3. resolve the current branch (or "detached" fallback)
#   4. emit the jq additionalContext JSON envelope
# The audit (#15) flagged this 4-step envelope as copy-pasted between the
# two hooks with the only difference being the hookEventName field.

# Bail if executed directly.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  printf 'session-envelope.sh must be sourced, not executed.\n' >&2
  exit 1
fi

# extract_hook_cwd HOOK_NAME — read HOOK_CWD from stdin payload and cd into it.
# Falls back to current $PWD if the payload cwd is missing or not a directory.
# Always returns 0; the caller decides whether to short-circuit.
extract_hook_cwd() {
    HOOK_CWD="$(printf '%s' "${INPUT:-$(cat 2>/dev/null)}" | jq -r '.cwd // ""' 2>/dev/null)"
    if [ -n "$HOOK_CWD" ] && [ -d "$HOOK_CWD" ]; then
        cd "$HOOK_CWD" || return 0
    fi
    return 0
}

# current_branch — echo the current short branch name, or "detached" fallback.
current_branch() {
    git symbolic-ref --short HEAD 2>/dev/null || echo "detached"
}

# emit_worktree_nudge EVENT_NAME NUDGE_TEXT — write the additionalContext
# envelope on stdout. EVENT_NAME is "SessionStart" or "UserPromptSubmit"
# (anything Claude Code accepts as hookEventName). The script then exits 0.
emit_worktree_nudge() {
    local event_name="$1"
    local nudge="$2"
    jq -nc --arg ctx "$nudge" --arg ev "$event_name" \
        '{hookSpecificOutput:{hookEventName:$ev,additionalContext:$ctx}}'
}
