"""worktrees resource — ``lcs://worktrees`` and ``lcs://worktrees/<branch>``.

Exposes the project's worktree set as a normalized JSON snapshot.
Two URI forms:

  lcs://worktrees/
      → {"status": "ok", "data": {"worktrees": [...], "summary": {...}}}
        list of {branch, path, head, dirty, last_touched} plus collection
        summary fields {total, active, stale, slot_drift, as_of}

  lcs://worktrees/<branch>/
      → {"status": "ok", "data": {...}}
        single worktree detail including dirty_files, hooks_wired, slot_version

Source: ``git worktree list --porcelain`` + ``git -C <wt> status --porcelain``.
The porcelain output is stable across git versions and easy to parse without
pulling in a git library.

Failure mode: if the git call fails (subprocess exits non-zero), the
resource raises ``LCSPartialError`` with the broken sub-field set so
the LCS server can surface ``status="partial"`` to the caller. This
matches the Phase 1.1 server contract — a single broken worktree
shouldn't kill the whole read.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from lcs_resources._summary import summarize_worktrees
from lcs_server import LCSPartialError, ParsedURI, Resource

# Module-level: registering this resource with a registry is the
# consumer's job. The default LCS CLI does it in
# ``build_default_registry``.

NAME = "worktrees"


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a git command and return the CompletedProcess.

    Centralized so test code can mock a single function instead of
    patching subprocess globally.
    """
    return subprocess.run(
        ["git", "-C", str(cwd)] + args,
        capture_output=True, text=True, check=False,
    )


def _list_worktrees_porcelain(repo_root: Path) -> list[dict]:
    """Parse ``git worktree list --porcelain`` into a list of dicts.

    Each worktree's porcelain block ends with a blank line; we split on
    that. Within a block, ``worktree <path>`` is mandatory, plus
    optionally ``HEAD <sha>``, ``branch <refs/heads/...>``, ``detached``,
    ``prunable ...``.
    """
    proc = _run_git(["worktree", "list", "--porcelain"], repo_root)
    if proc.returncode != 0:
        raise LCSPartialError(
            data={"repo_root": str(repo_root)},
            missing=[f"git worktree list failed: {proc.stderr.strip()}"],
        )
    blocks: list[dict] = []
    current: dict = {}
    for raw in proc.stdout.splitlines():
        if raw == "":
            if current:
                blocks.append(current)
                current = {}
            continue
        if raw.startswith("worktree "):
            current = {"path": raw[len("worktree "):]}
        elif raw.startswith("HEAD "):
            current["head"] = raw[len("HEAD "):]
        elif raw.startswith("branch "):
            # Strip the refs/heads/ prefix so the JSON value is a usable
            # branch name (e.g. "main", not "refs/heads/main").
            ref = raw[len("branch "):]
            current["branch"] = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
        elif raw == "detached":
            current["detached"] = True
    if current:
        blocks.append(current)
    return blocks


def _status_porcelain(worktree_path: Path) -> list[str]:
    """Run ``git status --porcelain`` and return the list of dirty files.

    Empty list = clean. Each line in porcelain format is one file
    change (XY followed by a space and the path).
    """
    proc = _run_git(["status", "--porcelain"], worktree_path)
    if proc.returncode != 0:
        # A non-zero status here usually means the worktree is in a
        # bad state (e.g. mid-rebase). Surface as partial so the
        # caller can still see the rest of the snapshot.
        raise LCSPartialError(
            data={"path": str(worktree_path)},
            missing=[f"git status failed: {proc.stderr.strip()}"],
        )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _hooks_wired(worktree_path: Path) -> bool:
    """Return True iff the worktree's hooks dir is the project's .githooks.

    Reads the ``core.hooksPath`` config inside the worktree. An empty /
    unset hooksPath means the worktree is using the default
    ``.git/hooks/`` directory, which is "not wired" by our convention.
    """
    proc = _run_git(["config", "--get", "core.hooksPath"], worktree_path)
    if proc.returncode != 0 or not proc.stdout.strip():
        return False
    hooks_path = Path(proc.stdout.strip())
    if not hooks_path.is_absolute():
        hooks_path = (worktree_path / hooks_path).resolve()
    # Walk up to find the project root (where .githooks/ lives).
    for candidate in (worktree_path, *worktree_path.parents):
        if (candidate / ".githooks").is_dir() and hooks_path == (candidate / ".githooks").resolve():
            return True
    return False


def _last_touched(worktree_path: Path) -> str | None:
    """Return the ISO timestamp of the most recent state change in
    ``worktree_path``, or None if the path doesn't exist.

    Uses the directory's mtime as a cheap proxy; "last touched" here
    means "last time any file in the worktree was modified", which is
    a useful signal for "is anyone still using this branch".
    """
    if not worktree_path.exists():
        return None
    try:
        mtime = worktree_path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def _slot_version(worktree_path: Path) -> str | None:
    """Return the dev-kit slot version (plugin.json ``version`` field) of
    the worktree's plugin install, or None if the file is missing /
    unparseable.

    Slot version = the version the worktree was BUILT against, used
    by the version-slot rule to detect stale-PR conflicts.
    """
    for candidate in (worktree_path, *worktree_path.parents):
        plugin_json = candidate / ".claude-plugin" / "plugin.json"
        if plugin_json.is_file():
            try:
                return json.loads(plugin_json.read_text()).get("version")
            except (OSError, ValueError, KeyError):
                return None
    return None


def _summarize(blocks: list[dict], repo_root: Path) -> list[dict]:
    """Turn the porcelain blocks into the JSON snapshot the resource
    returns. One summary per worktree. Failures on per-worktree
    subprocess calls degrade to partial entries — the list still
    surfaces the worktrees that succeeded.
    """
    out: list[dict] = []
    for block in blocks:
        path = Path(block["path"])
        entry: dict = {
            "branch": block.get("branch", ""),
            "path": str(path),
            "head": block.get("head", ""),
            "detached": bool(block.get("detached")),
        }
        try:
            entry["dirty_files"] = _status_porcelain(path)
            entry["dirty"] = bool(entry["dirty_files"])
        except LCSPartialError as exc:
            entry["dirty"] = None
            entry["dirty_error"] = exc.missing[0]
        entry["hooks_wired"] = _hooks_wired(path)
        entry["last_touched"] = _last_touched(path)
        entry["slot_version"] = _slot_version(path)
        out.append(entry)
    return out


class WorktreesResource(Resource):
    """LCS resource for ``lcs://worktrees[/<branch>]``."""

    name = NAME

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def fetch(self, parsed: ParsedURI) -> dict:
        blocks = _list_worktrees_porcelain(self._repo_root)
        worktrees = _summarize(blocks, self._repo_root)

        if not parsed.path_segments[1:]:
            # Collection form: return the list with the Gap-2 summary
            # block (active/stale counts, slot drift, as_of) so the
            # operator sees freshness at a glance instead of eyeballing
            # 14 per-row timestamps.
            return {
                "status": "ok",
                "data": {
                    "worktrees": worktrees,
                    "summary": summarize_worktrees(worktrees),
                },
            }

        # Item form: filter to the requested branch (segments[1] is the
        # branch name; URL-decoded so a "feat%2Ffoo" branch id works).
        branch = unquote(parsed.path_segments[1])
        for wt in worktrees:
            if wt["branch"] == branch:
                return {"status": "ok", "data": wt}
        # No match — not an error from the subprocess side, just an
        # empty result. The caller can branch on data being None.
        return {
            "status": "ok",
            "data": None,
            "missing": [f"no worktree for branch {branch!r}"],
        }
