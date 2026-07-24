"""branches resource — ``lcs://branches/<name>``.

Returns a single branch's git snapshot: local_head, origin_head,
ahead/behind vs origin/<branch>, last CI run, and optional
slot_version from ``.claude-plugin/plugin.json``. Missing branch
locally raises ``LCSPartialError`` so the server returns
``status="partial"`` with ``missing=["no such branch"]``.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

from lcs_server import LCSPartialError, ParsedURI, Resource

NAME = "branches"


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd)] + args,
        capture_output=True, text=True, check=False,
    )


def _local_head(repo: Path, branch: str) -> str | None:
    proc = _run_git(["rev-parse", "--verify", branch], repo)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _origin_head(repo: Path, branch: str) -> str | None:
    proc = _run_git(["rev-parse", "--verify", f"origin/{branch}"], repo)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _ahead_behind(repo: Path, branch: str) -> tuple[int, int]:
    # ``git rev-list --left-right --count A...B`` prints "<left>\t<right>"
    # where <left> = commits in A but not B, <right> = commits in B but
    # not A. With A=origin/<branch>, B=HEAD: <left>=behind, <right>=ahead.
    # Return as (ahead, behind). Missing upstream → (0, 0).
    proc = _run_git(
        ["rev-list", "--left-right", "--count", f"origin/{branch}...HEAD"],
        repo,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return (0, 0)
    parts = proc.stdout.strip().split("\t")
    if len(parts) != 2:
        return (0, 0)
    try:
        behind, ahead = int(parts[0]), int(parts[1])
    except ValueError:
        return (0, 0)
    return ahead, behind


def _slot_version(repo_root: Path) -> str | None:
    """Read ``.claude-plugin/plugin.json::version`` from repo_root.

    Fallback for ``bin/dev-kit-version-slot compute <branch>``; once
    that script ships, swap to it so the value reflects the branch's
    slot, not the repo's HEAD slot.
    """
    plugin_json = repo_root / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        return None
    try:
        return json.loads(plugin_json.read_text()).get("version")
    except (OSError, ValueError, KeyError):
        return None


def _last_ci_run(repo: Path, branch: str) -> dict | None:
    """Return ``{status, conclusion, name}`` for the latest CI run on
    ``branch`` via ``gh run list``, or None if ``gh`` is absent / no
    runs. ``repo`` is the cwd for the gh subprocess so the call
    resolves the right repository."""
    if shutil.which("gh") is None:
        return None
    proc = subprocess.run(
        ["gh", "run", "list", "--branch", branch, "--limit", "1",
         "--json", "status,conclusion,name"],
        capture_output=True, text=True, check=False, cwd=str(repo),
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        runs = json.loads(proc.stdout)
    except ValueError:
        return None
    return runs[0] if runs else None


class BranchesResource(Resource):
    """LCS resource for ``lcs://branches/<name>``."""

    name = NAME

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def fetch(self, parsed: ParsedURI) -> dict:
        if len(parsed.path_segments) < 2 or not parsed.path_segments[1]:
            raise LCSPartialError(data={}, missing=["no branch name in URI"])
        branch = unquote(parsed.path_segments[1])
        local = _local_head(self._repo_root, branch)
        if local is None:
            raise LCSPartialError(
                data={"name": branch},
                missing=["no such branch"],
            )
        ahead, behind = _ahead_behind(self._repo_root, branch)
        data: dict = {
            "name": branch,
            "local_head": local,
            "origin_head": _origin_head(self._repo_root, branch),
            "ahead": ahead,
            "behind": behind,
            "last_ci_run": _last_ci_run(self._repo_root, branch),
        }
        slot = _slot_version(self._repo_root)
        if slot is not None:
            data["slot_version"] = slot
        return {"status": "ok", "data": data}
