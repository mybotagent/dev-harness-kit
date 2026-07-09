#!/usr/bin/env bash
# slop-detector.sh — PostToolUse hook. v2.
#
# Flags LLM-tells in Write/Edit results using the SSOT bank under
#   ${CLAUDE_PLUGIN_ROOT}/hooks/references/slop/{phrases,structures}.md
#
# Default advisory (exit 0). Opt-in strict via SLOP_STRICT=1 (exit 2 on HIGH).
#
# Tiers (env SLOP_LEVEL=1|2|3, default 2):
#   T1 PHRASE    phrases.md     — KO + EN n-grams (throat-clearing, jargon, adverbs, meta)
#   T2 STRUCTURE structures.md  — regex shapes (binary contrast, false agency, Wh-starters, lazy extremes, KO structure)
#   T3 RHYTHM    structures.md  — density (em-dash count, three-item lists, dramatic fragmentation)
#
# Severity rules (see hooks/references/slop/README.md for the full ladder):
#   - Any KO phrase/structure match → HIGH immediately.
#   - ≥3 unique T1 OR ≥1 T2 + ≥1 T1 → HIGH
#   - ≥2 unique T1 OR KO structure → MEDIUM
#   - 1 unique T1 OR 1 T2          → LOW
#
# If references/slop/{phrases,structures}.md is missing, falls back to the v1 inline
# bank and prints a one-shot WARN to stderr. No silent failure.

set -eo pipefail

# ── locale ──────────────────────────────────────────────────────────────────
# CI runners often default to POSIX/C locale, which makes `grep -E` reject
# multi-byte (Korean) patterns in references/slop/{phrases,structures}.md with
# "Invalid collation character" and silently emit zero matches. Force a UTF-8
# locale before any grep call so the SSOT loads cleanly.
#
# Detection priority:
#   1. Honour the caller's explicit LC_ALL/LANG if they already point at a UTF-8 locale.
#   2. C.UTF-8 if installed (always present on glibc >= 2.13, which is every modern Linux CI).
#   3. en_US.UTF-8 if installed (default on macOS).
#   4. Fall back to printing a one-shot WARN and skip KO matching in T1/T2.
#
# NB: a previous revision buffered `locale -a` before grep -q to dodge SIGPIPE,
# but the per-locale regex still misfires when the CI emits a slightly different
# locale name (e.g. `C.utf8` lowercase). The C.UTF-8 case-insensitive probe is
# robust enough.
_existing_utf=0
case "${LC_ALL:-}${LANG:-}" in *.[Uu][Tt][Ff]-?8*) _existing_utf=1 ;; esac
if [ "$_existing_utf" = "1" ]; then
  : # caller already set a UTF-8 locale; trust it
elif _LOCALES="$(locale -a 2>/dev/null || true)" \
     && printf '%s\n' "$_LOCALES" | grep -qiE '^C\.[Uu][Tt][Ff]-?8$'; then
  export LC_ALL=C.UTF-8 LANG=C.UTF-8
elif printf '%s\n' "$_LOCALES" | grep -qiE '^en_US\.[Uu][Tt][Ff]-?8$'; then
  export LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
else
  # KO matching will emit grep "Invalid collation character" noise; surface it
  # explicitly so the degradation is visible in CI logs.
  printf '[slop-detector] WARN: no UTF-8 locale found in locale -a; KO pattern matching disabled. Currently: LC_ALL=%s LANG=%s.\n' "${LC_ALL:-unset}" "${LANG:-unset}" >&2
fi
unset _LOCALES _existing_utf 2>/dev/null || true

# ── inputs ──────────────────────────────────────────────────────────────────
INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""' 2>/dev/null)
CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // .tool_input.new_string // ""' 2>/dev/null)
[ -z "$CONTENT" ] && exit 0

# File path scope skip — checks/lockfiles produce noise without value.
case "$FILE" in
  *.lock|*.min.js|*.min.css|*-lock.json|pnpm-lock.yaml|package-lock.json|yarn.lock) exit 0;;
esac

# ── config ──────────────────────────────────────────────────────────────────
SLOP_LEVEL="${SLOP_LEVEL:-2}"        # 1=phrase, 2=+structure, 3=+rhythm
SLOP_QUIET="${SLOP_QUIET:-0}"        # 1=suppress stderr (still exit 0)
SLOP_STRICT="${SLOP_STRICT:-0}"      # 1=exit 2 on HIGH

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PHRASES_BANK="${PLUGIN_ROOT}/hooks/references/slop/phrases.md"
STRUCTURES_BANK="${PLUGIN_ROOT}/hooks/references/slop/structures.md"

# ── helpers ─────────────────────────────────────────────────────────────────
# Filter a bank file: drop `#`-prefixed comments and blank lines.
load_bank() {
  local f="$1"
  [ -r "$f" ] || return 1
  grep -vE '^[[:space:]]*#|^[[:space:]]*$' "$f"
}

# Run a tier through Python `re` to dodge grep's locale-dependent collation
# ("Invalid collation character" with KO patterns under POSIX locale).
# Args: <bank_path> <content_path> -> unique matches (one per line) on stdout.
scan_tier() {
  local bank="$1"
  local content_file="$2"
  local pats
  pats="$(load_bank "$bank" 2>/dev/null)" || return 0
  [ -z "$pats" ] && return 0
  PYTHONIOENCODING=utf-8 python3 - "$bank" "$content_file" <<'PY' 2>/dev/null | sort -u | head -10 || true
import re, sys, pathlib
bank_path, content_path = sys.argv[1], sys.argv[2]
# Drop `#` comments and blank lines; one ERE per remaining line.
pats = [
    line for line in pathlib.Path(bank_path).read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.lstrip().startswith("#")
]
text = pathlib.Path(content_path).read_text(encoding="utf-8")
seen = set()
for p in pats:
    # Normalize POSIX classes for Python `re`: `[[:space:]]*` → `\s*`, etc.
    # Otherwise Python treats `[[:space:]]` as a char class containing literal
    # `[`, `:`, `s`, ..., `]`, which doesn't match whitespace.
    p_norm = re.sub(r"\[\[:space:\]\]", r"\\s", p)
    p_norm = re.sub(r"\[\[:alnum:\]_]\]", r"\\w", p_norm)
    p_norm = re.sub(r"\[\[:digit:\]\]", r"\\d", p_norm)
    try:
        for m in re.finditer(p_norm, text):
            seen.add(m.group(0))
    except re.error:
        # Skip malformed pattern silently (validation lives in tests/test_slop_detector.py).
        continue
# Stable order: matches appear in the order they are first seen.
for m in seen:
    print(m)
PY
}

# KO flag — anything matching the CJK Hangul range within matches.
ko_present() {
  printf '%s' "$1" | python3 -c '
import sys
print("yes" if any(0xAC00 <= ord(c) <= 0xD7A3 for c in sys.stdin.read()) else "no")
'
}

# Count non-empty match lines.
count_lines() {
  printf '%s\n' "$1" | awk 'NF' | wc -l | tr -d ' '
}

CONTENT_FILE="$(mktemp -t slop.XXXXXX)"
printf '%s' "$CONTENT" > "$CONTENT_FILE"
trap 'rm -f "$CONTENT_FILE"' EXIT

# ── inline fallback (v1 SSOT, used only if banks missing) ──────────────────
INLINE_BANK='(Certainly[!.]|I'\''d be happy to|Great question|Let'\''s dive in|delve into|leverage|robust|comprehensive|tapestry|In conclusion|Hope this helps|It'\''s worth noting|Importantly|seamlessly|unleash|empower|game-changer|cutting-edge|state-of-the-art|강력한|종합적인|다양한|꼼꼼하게|꾹꾹|핵심적으로|중요한 점은|주시하겠습니다|살펴보겠습니다)'

t1_matches=""
t2_matches=""

if [ ! -r "$PHRASES_BANK" ]; then
  echo "[slop-detector] WARN: $PHRASES_BANK not readable; using inline v1 fallback (T1 only)." >&2
  t1_matches="$(grep -oE "$INLINE_BANK" "$CONTENT_FILE" 2>/dev/null | sort -u | head -10)"
else
  t1_matches="$(scan_tier "$PHRASES_BANK" "$CONTENT_FILE")"
  if [ "$SLOP_LEVEL" -ge 2 ] && [ -r "$STRUCTURES_BANK" ]; then
    t2_matches="$(scan_tier "$STRUCTURES_BANK" "$CONTENT_FILE")"
  fi
fi

# ── severity ladder ─────────────────────────────────────────────────────────
t1_n=$(count_lines "$t1_matches")
t2_n=$(count_lines "$t2_matches")
ko_t1=$(ko_present "$t1_matches")
ko_t2=$(ko_present "$t2_matches")

severity="OK"
if [ "$ko_t2" = "yes" ]; then
  severity="HIGH"                       # any KO structure → HIGH
elif [ "$ko_t1" = "yes" ] && [ "$t1_n" -ge 3 ]; then
  severity="HIGH"                       # ≥3 KO phrases → HIGH
elif [ "$t1_n" -ge 3 ] || { [ "$t1_n" -ge 1 ] && [ "$t2_n" -ge 1 ]; }; then
  severity="HIGH"                       # ≥3 unique T1 OR ≥1 T1 + ≥1 T2 → HIGH
elif [ "$t1_n" -ge 2 ]; then
  severity="MEDIUM"
elif [ "$ko_t2" = "yes" ]; then
  severity="MEDIUM"
elif [ "$t1_n" -ge 1 ] || [ "$t2_n" -ge 1 ]; then
  severity="LOW"
fi

# ── emit ────────────────────────────────────────────────────────────────────
emit() {
  [ "$SLOP_QUIET" = "1" ] && return 0
  local sev="$1"; shift
  echo "[slop-detector] ${sev} — ${FILE}" >&2
  while IFS= read -r line; do
    [ -n "$line" ] && echo "  ${line}" >&2
  done <<< "$*"
  echo "[slop-detector] If intentional, ignore. Otherwise delete the phrases." >&2
}

body=""
if [ -n "$t1_matches" ]; then
  body="${body}T1 phrase:
$t1_matches
"
fi
if [ -n "$t2_matches" ]; then
  body="${body}T2 structure:
$t2_matches
"
fi

case "$severity" in
  HIGH|MEDIUM|LOW) emit "$severity" "$body" ;;
esac

if [ "$severity" = "HIGH" ] && [ "$SLOP_STRICT" = "1" ]; then
  exit 2
fi

exit 0
