#!/usr/bin/env bash
# sub-agent-handoff.sh — PostToolUse Agent hook. SHO-154.
#
# Advisory check that the sub-agent response shape can support the
# standard handoff template (feedback-subagent-handoff-template):
#
#   1. STATUS marker     — `**Status**:` line + ✅/⚠️/❌ (or
#                          success/partial/failed)
#   2. EVIDENCE block    — at least one `<cmd> -> <result> (exit N)`
#                          quoted line (KO+EN prose accepted)
#   3. NEXT-ACTION line  — `### Next action` heading OR final
#                          imperative sentence.
#
# If any of those three are absent, the hook emits an advisory to
# stderr listing which pieces the orchestrator should add before
# relaying the result to the user. Always exit 0 (advisory). Per
# #539 ("Linear failures are non-blocking for implicit workflow
# calls"), payload parse errors are also non-blocking so unrelated
# sessions cannot hit a soft-bricked hook.
#
# Fail-CLOSED only when jq is missing (exit 2 with deny JSON) —
# without jq, the payload cannot be parsed at all and the rule
# silently lapses, parallel with worktree-guard.sh.
#
# Per-worktree opt-out: write `<repo>/.dev-kit/.sub-agent-handoff-disabled`.
# The hook prints a one-shot notice and exits 0; structurally the
# hook pretends the response is complete so no advisory surfaces.

set -uo pipefail

INPUT="$(cat)"

# ── opt-out (per-worktree) ──────────────────────────────────────────────────
# Look for .dev-kit/.sub-agent-handoff-disabled either at the
# canonical repo CWD (Claude's session cwd when the hook fires) or
# at the worktree rooted at the current directory. The hook is
# read-only — does not create the file.
OPT_OUT=""
probe_path() {
  local p="$1"
  [ -n "$p" ] || return 1
  [ -f "$p/.dev-kit/.sub-agent-handoff-disabled" ] && OPT_OUT="$p/.dev-kit/.sub-agent-handoff-disabled" && return 0
  return 1
}
probe_path "${CLAUDE_PROJECT_DIR:-}" || probe_path "${PWD}" || true
if [ -n "$OPT_OUT" ]; then
  echo "[sub-agent-handoff] disabled via $OPT_OUT" >&2
  exit 0
fi

# ── jq presence (fail-closed) ──────────────────────────────────────────────
if ! command -v jq >/dev/null 2>&1; then
  printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","permissionDecision":"deny","permissionDecisionReason":"SUB-AGENT HANDOFF: jq is required but not installed. Install jq (apt/brew/apk) — without it, this hook cannot enforce the handoff contract."}}\n' >&2
  exit 2
fi

# ── payload validity (non-blocking warn on parse error per #539) ───────────
# If the payload is not valid JSON we log a one-line warn to stderr
# and exit 0 — silently lapping the check here would re-enable the
# bypass for malformed payloads and a single bad frame would
# soft-brick unrelated sessions (parallel: linear-autosync.sh).
if [ -n "$INPUT" ] && ! printf '%s' "$INPUT" | jq -e . >/dev/null 2>&1; then
  echo "[sub-agent-handoff] warn: stdin payload is not valid JSON; skipping (non-blocking parse error)" >&2
  exit 0
fi

# ── tool name filter (matcher already enforces this; body belt-and-suspenders) ──
TOOL_NAME="$(printf '%s' "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null || true)"
if [ "$TOOL_NAME" != "Agent" ]; then
  exit 0
fi

# ── payload extraction + scan (single Python call) ─────────────────────────
# Python is used to (a) tolerate string-vs-object tool_response and
# (b) scan for handoff pieces in one process. Bypasses jq's
# type-discrimination limits and avoids re-forking.
#
# We dump the script to a tempfile and exec it directly so the
# `>&2` on the python invocation is unambiguous (heredoc + `>&2`
# interactions in `python3 - ... >&2 <<PY` race the file-descriptor
# setup and silently swallow print output).
SCRIPT_TMP="$(mktemp -t sub-agent-handoff.XXXXXX)"
trap 'rm -f "$SCRIPT_TMP"' EXIT
cat > "$SCRIPT_TMP" <<'PY'
import json
import os
import re
import sys

raw = os.environ.get("INPUT", "")
try:
    payload = json.loads(raw) if raw.strip() else {}
except (json.JSONDecodeError, ValueError):
    print("[sub-agent-handoff] warn: stdin payload is not valid JSON; skipping (non-blocking)")
    sys.exit(0)

tool_response = payload.get("tool_response", "")
text = ""

if isinstance(tool_response, str):
    text = tool_response
elif isinstance(tool_response, dict):
    content = tool_response.get("content")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("text", None):
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
        text = "\n".join(parts)
    elif isinstance(content, str):
        text = content
elif tool_response is None:
    text = ""

text = text or ""
if not text.strip():
    # Empty/probe payloads produce no advisory; the hook is silent.
    sys.exit(0)

# --- STATUS detection ---
status_present = bool(
    re.search(r"\*\*(?:Status|status)\*\*\s*[:：]?\s*(?:✅|⚠️|❌|success|partial|failed|Success|Partial|Failed)", text)
    or re.search(r"(?m)^Status\s*[:：]\s*(?:✅|⚠️|❌|success|partial|failed|Success|Partial|Failed)", text)
)

# --- EVIDENCE detection ---
# Quoted `<cmd> -> <result> (exit N)` (or `→`). At least one occurrence.
evidence_present = bool(
    re.search(
        r"`.+?`\s*(?:->|→)\s*`.+?`\s*\(exit\s*-?\d+\)",
        text,
    )
)

# --- NEXT-ACTION detection ---
# `### Next action` heading OR a closing imperative sentence.
next_action_present = bool(
    re.search(r"(?im)^#{2,4}\s*next\s+action\b", text)
    or re.search(
        r"(?m)^(?:[-*]\s+)?(?:Next action|Next steps?|후속 작업|다음 작업)\s*[:：]?\s*\S",
        text,
    )
)

missing = []
if not status_present:    missing.append("STATUS")
if not evidence_present:  missing.append("EVIDENCE")
if not next_action_present: missing.append("NEXT-ACTION")

if not missing:
    print("[sub-agent-handoff] STATUS OK -- handoff template pieces all present.")
    sys.exit(0)

print(
    "[sub-agent-handoff] advisory: agent response is missing "
    + ", ".join(m for m in missing)
    + " piece(s) of the standard handoff template "
    + "(feedback-subagent-handoff-template). The orchestrator's "
    + "next relay cannot quote exit codes / status markers / next "
    + "action without these. To suppress this advisory, write "
    + "`<repo>/.dev-kit/.sub-agent-handoff-disabled` or add the "
    + "missing piece to the agent's response."
)
# Emit one line per missing piece so downstream greps / test
# assertions can match `missing STATUS`, `missing EVIDENCE`,
# `missing NEXT-ACTION` independently.
for m in missing:
    print(f"[sub-agent-handoff] missing {m} piece")
PY
INPUT="$INPUT" python3 "$SCRIPT_TMP" >&2 || true
exit 0
