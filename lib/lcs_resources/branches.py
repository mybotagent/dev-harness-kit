"""branches resource — ``lcs://branches`` and ``lcs://branches/<name>``.

Two URI forms:

  lcs://branches
      → {"status": "ok|partial", "data": {"branches": [...], "summary": {...}}}
        List form: small per-branch snapshot + summary block (see
        ``_fetch_branches_list``).

  lcs://branches/<name>
      → {"status": "ok|partial", "data": {name, local_head, origin_head,
          ahead, behind, last_ci_run, [slot_version]}}
        Per-branch detail. Missing branch locally raises
        ``LCSPartialError`` so the server returns ``status="partial"``
        with ``missing=["no such branch"]``.

Discovery endpoint (Gap 3, issue #455):
- The list form enumerates branches via ``git for-each-ref`` and
  reports a small per-branch row set (no ``origin_head`` /
  ``slot_version`` — those are heavy and surfaced on the per-record
  URI). The summary block carries ``as_of`` plus the freshness
  dimensions an operator needs (``total``, ``local_only``,
  ``ahead_of_origin``, ``behind_origin``).
- ahead/behind on the list form is ``origin/<branch>...<branch>`` —
  i.e. how far the local branch has drifted from its upstream. The
  per-record form uses ``origin/<branch>...HEAD`` (existing).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
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


def _ahead_behind_local(repo: Path, branch: str) -> tuple[int, int]:
    """ahead/behind of ``<branch>`` from ``origin/<branch>`` (list form).

    Computes ``origin/<branch>...<branch>`` so the operator sees how
    much the local branch has drifted from its upstream — independent
    of HEAD. Missing upstream → (0, 0) so the row still surfaces.
    """
    proc = _run_git(
        ["rev-list", "--left-right", "--count", f"origin/{branch}...{branch}"],
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


def _last_ci_conclusion(repo: Path, branch: str) -> str | None:
    """Reduce ``_last_ci_run`` to the conclusion string only.

    Returns one of ``"success"``, ``"failure"``, ``"pending"``, or
    ``None`` when no CI run is available (``gh`` absent, no runs).
    Used by the list form so callers don't have to walk the full
    per-record ``last_ci_run`` dict for the common "is this branch
    green?" question.
    """
    run = _last_ci_run(repo, branch)
    if not run:
        return None
    conclusion = run.get("conclusion")
    status = run.get("status")
    if status and status != "COMPLETED":
        return "pending"
    if conclusion in ("SUCCESS", "success"):
        return "success"
    if conclusion in ("FAILURE", "failure"):
        return "failure"
    if conclusion:
        return conclusion.lower()
    return None


def _now_iso() -> str:
    """Current UTC time as ISO8601 with explicit +00:00 suffix."""
    return datetime.now(timezone.utc).isoformat()


def _list_branch_refs(repo: Path) -> list[tuple[str, str]]:
    """Return ``[(branch_name, short_sha), ...]`` for local branches.

    Uses ``git for-each-ref --format='%(refname:short)%09%(objectname:short)' refs/heads/``
    so the output is one ``<name>\t<sha>`` per line. Returns ``[]``
    on git error (the caller converts that to a partial envelope).
    """
    proc = _run_git(
        ["for-each-ref", "--format=%(refname:short)%09%(objectname:short)",
         "refs/heads/"],
        repo,
    )
    if proc.returncode != 0:
        raise LCSPartialError(
            data={"repo_root": str(repo)},
            missing=[f"git for-each-ref failed: {proc.stderr.strip()}"],
        )
    out: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        name, sha = parts
        if not name or not sha:
            continue
        out.append((name, sha))
    return out


def _list_origin_refs(repo: Path) -> set[str]:
    """Return the set of branch names under ``refs/remotes/origin/``.

    The trailing ``/`` strip keeps ``origin/main`` -> ``main``. Used
    by the list form to compute ``local_only`` (branches with no
    upstream) in a single git call rather than one subprocess per
    branch. A failed git call yields an empty set (no origin
    configured is equivalent to "every branch is local-only").
    """
    proc = _run_git(
        ["for-each-ref", "--format=%(refname:short)",
         "refs/remotes/origin/"],
        repo,
    )
    if proc.returncode != 0:
        return set()
    names: set[str] = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("origin/"):
            line = line[len("origin/"):]
        if line and line != "HEAD":
            names.add(line)
    return names


class BranchesResource(Resource):
    """LCS resource for ``lcs://branches[/<name>]``."""

    name = NAME

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def fetch(self, parsed: ParsedURI) -> dict:
        # List form: lcs://branches (with or without trailing slash).
        if not parsed.path_segments[1:]:
            return self._fetch_branches_list()

        # Per-branch form: lcs://branches/<name>.
        if not parsed.path_segments[1]:
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

    def _fetch_branches_list(self) -> dict:
        """Build the ``lcs://branches`` list payload + summary block.

        The summary aggregates across every local branch:
        - ``total``         — branch count
        - ``local_only``    — branches with no ``origin/<branch>``
        - ``ahead_of_origin`` — branches with ahead > 0
        - ``behind_origin``   — branches with behind > 0
        - ``as_of``           — ISO8601 UTC timestamp

        The list rows carry the small-list fields only (no
        ``origin_head`` / ``slot_version`` — those live on the
        per-record URI). ``last_ci_conclusion`` is the conclusion
        string (``"success"`` / ``"failure"`` / ``"pending"`` /
        ``None``) so the list stays compact.
        """
        try:
            refs = _list_branch_refs(self._repo_root)
        except LCSPartialError as exc:
            # git itself failed — partial envelope with empty list.
            return {
                "status": "partial",
                "data": {
                    "branches": [],
                    "summary": {
                        "total": 0,
                        "local_only": 0,
                        "ahead_of_origin": 0,
                        "behind_origin": 0,
                        "as_of": _now_iso(),
                    },
                },
                "missing": exc.missing,
            }

        # One git call enumerates origin branches so we can compute
        # ``local_only`` without a per-branch subprocess.
        origin_branches = _list_origin_refs(self._repo_root)

        rows: list[dict] = []
        ahead_of_origin = 0
        behind_origin = 0
        local_only = 0

        for name, sha in refs:
            has_origin = name in origin_branches
            if has_origin:
                ahead, behind = _ahead_behind_local(self._repo_root, name)
            else:
                # No upstream — nothing to compare against. Convention:
                # ahead=behind=0 so the row still surfaces the branch.
                ahead, behind = 0, 0
                local_only += 1
            if ahead > 0:
                ahead_of_origin += 1
            if behind > 0:
                behind_origin += 1
            rows.append({
                "name": name,
                "local_head": sha,
                "ahead": ahead,
                "behind": behind,
                "last_ci_conclusion": _last_ci_conclusion(
                    self._repo_root, name,
                ),
            })

        return {
            "status": "ok",
            "data": {
                "branches": rows,
                "summary": {
                    "total": len(rows),
                    "local_only": local_only,
                    "ahead_of_origin": ahead_of_origin,
                    "behind_origin": behind_origin,
                    "as_of": _now_iso(),
                },
            },
        }
