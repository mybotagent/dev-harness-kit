"""pr resource — ``lcs://pr/<number>``.

Exposes a single GitHub pull-request as a normalized JSON snapshot.
URI form:

  lcs://pr/<number>
      → {"status": "ok", "data": {number, title, status, checks, reviews, unresolved_threads}}

Source: ``gh pr view <number> --json number,title,state,statusCheckRollup,reviews,comments``.
The JSON output is the live snapshot of the PR at fetch() time — no
caching beyond the LCS server's own TTL.

Failure mode: if ``gh`` is not installed (``FileNotFoundError``) or the
command exits non-zero (auth failure, PR not found, network error),
the resource returns a partial envelope with only the PR number set
and a ``missing`` field explaining the gap. This mirrors the
worktrees resource's "one bad subtree doesn't kill the snapshot" rule.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import unquote

from lcs_server import LCSError, ParsedURI, Resource

NAME = "pr"


def _run_gh(args: list[str]) -> subprocess.CompletedProcess:
    """Run a ``gh`` CLI command and return the CompletedProcess.

    Centralized so test code can mock a single function instead of
    patching subprocess globally. ``capture_output=True`` + ``text=True``
    so stderr/stdout are strings; ``check=False`` so failures surface
    as a non-zero ``returncode`` rather than an exception (the caller
    decides whether to raise, partial-fallback, or pass through).
    """
    return subprocess.run(
        ["gh"] + args,
        capture_output=True, text=True, check=False,
    )


def _count_unresolved_threads(comments: list[dict]) -> int:
    """Count unresolved review threads in the PR's comment list.

    A comment is "unresolved" when its ``isResolved`` field is False
    (the explicit getter) or missing (defensive fallback for older
    gh versions that don't emit the field). Resolved threads are
    filtered out; everything else counts as still-open work.
    """
    count = 0
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        resolved = comment.get("isResolved")
        if resolved is False or resolved is None:
            count += 1
    return count


def _fetch_pr(number: str) -> dict:
    """Call ``gh pr view`` and return the parsed JSON payload.

    Raises :class:`FileNotFoundError` if ``gh`` isn't installed, or
    :class:`subprocess.CalledProcessError`-style failure (non-zero
    returncode) if the underlying command fails. The caller maps
    both to a partial envelope.
    """
    proc = _run_gh([
        "pr", "view", number,
        "--json", "number,title,state,statusCheckRollup,reviews,comments",
    ])
    if proc.returncode != 0:
        raise RuntimeError(f"gh pr view failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


class PRResource(Resource):
    """LCS resource for ``lcs://pr/<number>``."""

    name = NAME

    def __init__(self, repo_root: Path) -> None:
        # ``repo_root`` is kept for symmetry with WorktreesResource
        # even though ``gh`` resolves the repo from its own CWD —
        # future resources may want to scope PR lookups to a specific
        # checkout, and the uniform signature keeps the registry code
        # trivial.
        self._repo_root = repo_root

    def fetch(self, parsed: ParsedURI) -> dict:
        # Collection form (lcs://pr, lcs://pr/) is not meaningful —
        # there is no "list all PRs" snapshot in this resource. The
        # worktrees resource exposes a collection; pr/ is item-only.
        if not parsed.path_segments[1:]:
            raise LCSError(
                "lcs://pr requires a PR number; use lcs://pr/<number>"
            )

        # URL-decode so a "lcs://pr/29%2Fdraft" style URI round-trips
        # without surprising the gh CLI.
        number = unquote(parsed.path_segments[1])

        try:
            payload = _fetch_pr(number)
        except FileNotFoundError:
            return {
                "status": "partial",
                "data": {"number": number},
                "missing": ["gh unavailable"],
            }
        except (RuntimeError, json.JSONDecodeError) as exc:
            return {
                "status": "partial",
                "data": {"number": number},
                "missing": [f"gh pr view failed: {exc}"],
            }

        # Build the snapshot. ``statusCheckRollup`` is itself a list of
        # check runs; pass it through verbatim so the caller can see
        # per-check state without a second round-trip.
        checks = payload.get("statusCheckRollup") or []
        reviews = payload.get("reviews") or []
        comments = payload.get("comments") or []
        return {
            "status": "ok",
            "data": {
                "number": payload.get("number"),
                "title": payload.get("title"),
                "status": payload.get("state"),
                "checks": checks,
                "reviews": reviews,
                "unresolved_threads": _count_unresolved_threads(comments),
            },
        }
