#!/usr/bin/env bash
# stop-verify.sh — Stop event hook. Runs AC checks before letting session end.
# Default fail-open (exit 0); emit summary to stderr.

set -eo pipefail
INPUT=$(cat)
LAST_MSG=$(echo "$INPUT" | jq -r '.last_assistant_message // ""' 2>/dev/null)
[ -z "$LAST_MSG" ] && exit 0

# Detect completion-claim patterns (KO + EN)
CLAIM_RE='(완료|통과|작동|fixed|done|passes|should work|should be working|it works)'
EVIDENCE_RE='(exit code|passed [0-9]+|failed [0-9]+|tests:|Traceback|AssertionError|OK \(|FAIL|test_)'

if echo "$LAST_MSG" | grep -qE "$CLAIM_RE" && ! echo "$LAST_MSG" | grep -qE "$EVIDENCE_RE"; then
  echo "[stop-verify] You claimed completion but cited no exit code / test count / build output." >&2
  echo "[stop-verify] Run the verify command and quote the output. (Iron Law #3)" >&2
fi
exit 0
