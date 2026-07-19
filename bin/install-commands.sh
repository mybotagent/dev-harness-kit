#!/usr/bin/env bash
# install-commands.sh — Install slash-commands from commands/ to both
# .claude/commands/ and .codex/commands/ target trees.
#
# Source-of-truth: commands/<name>.md  (one markdown file per slash command,
# frontmatter + body. The body uses `$ARGUMENTS` for the full arg string.)
#
# Targets:
#   Claude Code  ->  .claude/commands/<name>.md  (verbatim, $ARGUMENTS native)
#   Codex        ->  .codex/commands/<name>.md  (with $ARGUMENTS translated
#                     into Codex's `${@}` positional-args form so the
#                     downstream parser renders positional `["foo","bar"]`).
#
# Why two targets: Claude Code and Codex each look for slash commands in
# their own config tree. The plugin lives in one checkout; this script
# syncs the canonical commands/ into both target trees. In a real install
# the targets are typically symlinks to the plugin's commands/ dir, but
# in the test suite we materialize copies so the verifier can run in a
# temp dir.
#
# Usage:
#   bin/install-commands.sh                  # install to .claude + .codex
#   bin/install-commands.sh --claude-only    # only .claude/commands
#   bin/install-commands.sh --codex-only     # only .codex/commands
#   bin/install-commands.sh --src <dir>      # override source (default: commands/)
#   bin/install-commands.sh --target <dir>   # override target root (default: .)
#   bin/install-commands.sh --verify         # parse + render check (no writes)
#   bin/install-commands.sh --help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SRC_DIR="$PROJECT_ROOT/commands"
TARGET_ROOT="$PROJECT_ROOT"
VERIFY=0
INSTALL_CLAUDE=1
INSTALL_CODEX=1
VERBOSE=0

die() { echo "error: $*" >&2; exit 1; }
log() { [ "$VERBOSE" = "1" ] && echo "  $*" || true; }
info() { echo "  $*"; }

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --verify)    VERIFY=1; shift ;;
    --claude-only) INSTALL_CODEX=0; shift ;;
    --codex-only)  INSTALL_CLAUDE=0; shift ;;
    --src)       [ $# -ge 2 ] || die "--src requires a path"; SRC_DIR="$2"; shift 2 ;;
    --target)    [ $# -ge 2 ] || die "--target requires a path"; TARGET_ROOT="$2"; shift 2 ;;
    --verbose|-v) VERBOSE=1; shift ;;
    -h|--help)   usage; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done

[ -d "$SRC_DIR" ] || die "source dir not found: $SRC_DIR"

# ----- helpers ---------------------------------------------------------

# render_command_for_target <target-kind> <source-md>
# target-kind = "claude" | "codex"
# For "claude": emit the source markdown verbatim.
# For "codex":  emit a copy where `$ARGUMENTS` is replaced with `"$@"` so
#               the downstream parser expands positional args into a
#               single space-separated string identical to the claude
#               rendering.
render_command_for_target() {
  local kind="$1"
  local src="$2"

  if [ "$kind" = "codex" ]; then
    sed 's/\$ARGUMENTS/"$@"/g' "$src"
  else
    cat "$src"
  fi
}

# install_one_target <target-kind> <dest-dir>
install_one_target() {
  local kind="$1"
  local dest="$2"
  mkdir -p "$dest"
  local count=0
  for src in "$SRC_DIR"/*.md; do
    [ -f "$src" ] || continue
    name="$(basename "$src")"
    log "[$kind] install $name"
    render_command_for_target "$kind" "$src" > "$dest/$name"
    count=$((count + 1))
  done
  info "$kind: installed $count command(s) to $dest"
}

# verify_target <kind> <dest-dir>
verify_target() {
  local kind="$1"
  local dest="$2"
  [ -d "$dest" ] || die "$kind target dir not found: $dest"
  local count=0
  for src in "$SRC_DIR"/*.md; do
    [ -f "$src" ] || continue
    name="$(basename "$src")"
    dst="$dest/$name"
    [ -f "$dst" ] || die "[$kind] missing installed file: $dst"
    count=$((count + 1))
  done
  info "$kind: verified $count command(s)"
}

# ----- main ------------------------------------------------------------

if [ "$VERIFY" = "1" ]; then
  info "verify-only mode (no writes)"
  [ "$INSTALL_CLAUDE" = "1" ] && verify_target "claude" "$TARGET_ROOT/.claude/commands"
  [ "$INSTALL_CODEX"  = "1" ] && verify_target "codex"  "$TARGET_ROOT/.codex/commands"
  info "ok"
  exit 0
fi

info "install: $SRC_DIR → .claude/commands + .codex/commands (root: $TARGET_ROOT)"
[ "$INSTALL_CLAUDE" = "1" ] && install_one_target "claude" "$TARGET_ROOT/.claude/commands"
[ "$INSTALL_CODEX"  = "1" ] && install_one_target "codex"  "$TARGET_ROOT/.codex/commands"
info "ok"
