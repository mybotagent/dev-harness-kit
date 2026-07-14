#!/usr/bin/env bash
# cost-gate.sh — PreToolUse / PostToolUse / SessionStart hook.
#
# Three-event single hook for the cost-gate subsystem. Validates JSON via
# `jq`, delegates state + cost work to tools/cost_gate_status.py, and
# exits 2 with a deny JSON on hard kill (PreToolUse only).
#
# Fail-closed (deny JSON + exit 2) when `jq` or `python3` is missing.
#
# Timeouts (set by the harness in hooks/hooks.json):
#   SessionStart    5s
#   PostToolUse     5s
#   PreToolUse      3s
#
# State lives at <cwd>/.dev-kit/.cost-gate/state.json (cwd comes from the
# hook payload). Override path via DEV_KIT_COST_GATE_STATE.

set -uo pipefail
INPUT="$(cat)"

# Fail CLOSED if jq is missing. Without jq we cannot parse the hook
# payload; silent fail-open would disable the rule. Always emit the deny
# JSON regardless of event type — for PreToolUse this blocks the call;
# for SessionStart/PostToolUse the harness surfaces a hook error (loud
# failure, not silent bypass).
if ! command -v jq >/dev/null 2>&1; then
  REASON="cost-gate: jq is required by cost-gate.sh but not installed. Install jq (apt/brew/apk) — without it, the cost-gate rule cannot be enforced."
  printf '%s' "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"$REASON\"}}" >&2
  printf '\n' >&2
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  REASON="cost-gate: python3 is required by cost-gate.sh but not installed."
  printf '%s' "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"$REASON\"}}" >&2
  printf '\n' >&2
  exit 2
fi

# Resolve plugin root once (used to locate tools/cost_gate_status.py).
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
DRIVER="$PLUGIN_ROOT/tools/cost_gate_status.py"

if [ ! -f "$DRIVER" ]; then
  printf 'cost-gate: driver missing at %s\n' "$DRIVER" >&2
  exit 0
fi

EVENT="$(printf '%s' "$INPUT" | jq -r '.hook_event_name // ""' 2>/dev/null)"

case "$EVENT" in
  SessionStart)
    printf '%s' "$INPUT" | python3 "$DRIVER" --hook-session-start
    ;;
  PostToolUse)
    printf '%s' "$INPUT" | python3 "$DRIVER" --hook-post-tool-use
    ;;
  PreToolUse)
    printf '%s' "$INPUT" | python3 "$DRIVER" --hook-pre-tool-use
    ;;
  *)
    printf 'cost-gate: unknown event %q\n' "$EVENT" >&2
    exit 0
    ;;
esac
