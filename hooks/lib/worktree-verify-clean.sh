#!/usr/bin/env bash
# worktree-verify-clean.sh — sourced helper, not directly executable.
#
# Public API:
#   worktree_verify_clean [<wt_path>]
#
# Detects and repairs "stale files" left behind by a `git worktree add`
# against a target path that already contained files (see issue #215).
# When git creates a worktree at a path with pre-existing files, it does
# NOT overwrite them — the worktree's bookkeeping (.git link, HEAD,
# refs) is set up, but each pre-existing file remains on disk and is
# reported by `git status` as `modified:` against the new HEAD. The
# result is a working tree that disagrees with HEAD for those files,
# even though both report the same commit. The most painful consequence
# is `ImportError` against fresh test runs: functions defined in HEAD
# do not exist in the on-disk file, so any test importing them fails.
#
# This helper walks the tracked files at HEAD, compares each on-disk
# SHA (`git hash-object`) to HEAD's blob SHA (`git rev-parse HEAD:<p>`),
# and force-restores the HEAD version with `git checkout HEAD -- <path>`
# whenever they differ. Untracked files are left alone. Files deleted
# from disk but present in HEAD are also left alone (no resurrection).
#
# Output (stdout, one line):
#   checked=<N> repaired=<N>   — normal completion
#   skipped (<reason>)          — path is not a git worktree (no-op)
#
# Exit status: always 0. The repair must never cause the calling hook
# to fail — even if every `git checkout` fails (e.g. read-only FS), the
# worktree is still usable, just out of sync; the user can run
# `git checkout HEAD -- <path>` manually. Non-zero exit from this
# helper would cascade into hard hook failures in
# worktree-auto-cut.sh, which is the wrong blast radius for what is
# essentially a recoverable sync drift.
#
# Wiring:
#   - hooks/worktree-auto-cut.sh sources and calls immediately after
#     `git worktree add` so the handoff context is already clean.
#   - hooks/worktree-verify-clean.sh (PostToolUse:Bash) sources and
#     calls whenever the user invokes `git worktree add` directly so
#     the same protection covers manual cuts.

worktree_verify_clean() {
  local wt_path="${1:-$PWD}"
  if [ ! -d "$wt_path" ]; then
    echo "skipped (path does not exist: $wt_path)"
    return 0
  fi
  # Canonicalize: only act on a real working tree.
  local toplevel
  toplevel="$(git -C "$wt_path" rev-parse --show-toplevel 2>/dev/null)" || {
    echo "skipped (not a git repository: $wt_path)"
    return 0
  }
  wt_path="$toplevel"

  local path head_sha disk_sha repaired=0 checked=0
  # `-z --name-only` prints null-delimited paths and tolerates spaces
  # in filenames. `git rev-parse HEAD:<path>` returns the SHA-1 of the
  # blob HEAD records for that path; for nested paths this still works
  # because git's path syntax uses `/` as the separator.
  while IFS= read -r -d '' path; do
    checked=$((checked + 1))
    [ -f "$wt_path/$path" ] || continue
    head_sha="$(git -C "$wt_path" rev-parse "HEAD:$path" 2>/dev/null)" || continue
    # `git hash-object` on a working-tree path gives the SHA-1 of its
    # on-disk content without staging — the cheapest way to compare.
    disk_sha="$(git -C "$wt_path" hash-object "$path" 2>/dev/null)" || continue
    if [ "$disk_sha" != "$head_sha" ]; then
      # `git checkout HEAD -- <path>` is the documented restore path;
      # `git restore` is newer but not available on every host we ship
      # to. The double-dash keeps the path from being interpreted as a
      # flag in the (unlikely) event the path starts with "-".
      if git -C "$wt_path" checkout HEAD -- "$path" 2>/dev/null; then
        repaired=$((repaired + 1))
      fi
    fi
  done < <(git -C "$wt_path" ls-tree -r HEAD -z --name-only 2>/dev/null)

  echo "checked=$checked repaired=$repaired"
  return 0
}
