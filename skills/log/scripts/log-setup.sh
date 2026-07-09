#!/usr/bin/env bash
# log-setup.sh — copy tools/save_log.py + create logs/ scaffold in target project.
#
# Run once per project before /log on so that the installed hook command
# (`python3 ${CLAUDE_PROJECT_DIR}/tools/save_log.py`) has its script to call.
#
# Idempotent: re-running updates save_log.py to the current source version
# (use --force to overwrite an existing copy if the SHA differs) and creates
# the logs/ tree if missing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--target DIR] [--force]

Creates the target project's logging scaffold:
  <target>/tools/save_log.py     — copied from \$LOGHOOKS_DIR (or ~/dev/loghooks)
  <target>/logs/.gitkeep         — keeps the logs/ tree in version control
  <target>/logs/claude-code/     — Claude Code transcripts land here
  <target>/logs/codex/           — Codex transcripts land here

Idempotent: re-running refreshes save_log.py to the current source version.
--force overwrites even if the local copy SHA matches.

Env:
  LOGHOOKS_DIR   source repo (default: \$HOME/dev/loghooks)
  TARGET_DIR     target project (default: \$PWD)
EOF
}

FORCE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) TARGET_DIR="$2"; shift 2 ;;
        --force)  FORCE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown arg: $1" >&2; usage; exit 1 ;;
    esac
done

require_jq
LOGHOOKS_DIR="$(resolve_loghooks_dir)"
TARGET_DIR="$(resolve_target_dir)"

if [[ ! -d "$TARGET_DIR" ]]; then
    echo "ERROR: target dir does not exist: $TARGET_DIR" >&2
    exit 4
fi

SRC_PY="$LOGHOOKS_DIR/tools/save_log.py"
DST_PY="$TARGET_DIR/tools/save_log.py"

if [[ ! -f "$SRC_PY" ]]; then
    echo "ERROR: source script missing: $SRC_PY" >&2
    exit 2
fi

mkdir -p "$TARGET_DIR/tools"

# Portable SHA-256: prefer coreutils sha256sum, fall back to BSD shasum.
# Alpine / distroless / many debian-slim images ship only sha256sum;
# macOS / FreeBSD ship only shasum.
sha256_cmd() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum
    elif command -v shasum >/dev/null 2>&1; then shasum -a 256
    else echo "ERROR: no sha256 tool installed (need sha256sum or shasum)" >&2; return 1
    fi
}

LOCAL_SHA=""
if [[ -f "$DST_PY" ]]; then
    LOCAL_SHA="$(sha256_cmd < "$DST_PY" | awk '{print $1}')"
fi
SRC_SHA="$(sha256_cmd < "$SRC_PY" | awk '{print $1}')"

if [[ -n "$LOCAL_SHA" && "$LOCAL_SHA" == "$SRC_SHA" && "$FORCE" -eq 0 ]]; then
    echo "OK: $DST_PY already up to date (sha matches)"
else
    if [[ -n "$LOCAL_SHA" ]]; then
        echo "Updating $DST_PY (sha: ${LOCAL_SHA:0:8} -> ${SRC_SHA:0:8})"
    else
        echo "Creating $DST_PY"
    fi
    cp -p "$SRC_PY" "$DST_PY"
    chmod 0755 "$DST_PY"
fi

# Scaffold logs/ tree.
mkdir -p "$TARGET_DIR/logs/claude-code" "$TARGET_DIR/logs/codex"

# Write a .gitkeep so the empty subdirs survive `git status`.
GITKEEP="$TARGET_DIR/logs/.gitkeep"
if [[ ! -f "$GITKEEP" ]]; then
    printf '# conversation transcripts land here. .jsonl files are gitignored.\n' >"$GITKEEP"
fi

# Add a logs/.gitignore that ignores the captured transcripts but keeps
# the directory. Idempotent: skipped if a logs/.gitignore already exists.
LOG_GITIGNORE="$TARGET_DIR/logs/.gitignore"
if [[ ! -f "$LOG_GITIGNORE" ]]; then
    cat >"$LOG_GITIGNORE" <<'GI'
# ignore captured transcripts
*.jsonl

# keep these subdirs present
!.gitkeep
!claude-code/
!codex/
GI
fi

echo
echo "Setup complete for: $TARGET_DIR"
echo "  scripts: tools/save_log.py"
echo "  logs:    logs/{claude-code,codex}/"
echo
echo "Next: run /dev-kit:log on   to enable the hooks."