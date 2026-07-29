"""pr resource — ``lcs://pr/<number>`` and ``lcs://prs``.

Two URI forms:

  lcs://prs
      → {"status": "ok|partial", "data": {"prs": [...], "summary": {...}}}
        List form: small per-PR snapshot + summary block (see
        ``_fetch_prs_list``). Reached via the ``prs`` alias on
        ``PRResource`` (see :attr:`PRResource.aliases`).

  lcs://pr/<number>
      → {"status": "ok|partial", "data": {number, title, status, checks,
          reviews, unresolved_threads}}
        Per-PR detail. ``gh pr view <number> --json ...`` is the
        source; missing PR / gh binary → partial envelope.

Discovery endpoint (Gap 3, issue #455):
- The list form is reached via ``lcs://prs`` (alias). It enumerates
  PRs via ``gh pr list --limit 100 --json ...`` and reports a small
  per-PR row (no ``status`` / ``checks`` / ``reviews`` / ``comments``
  — those live on the per-record URI). ``status="partial"`` is the
  failure mode when ``gh`` is absent (source unavailable, not
  empty index).
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from lcs_server import LCSError, ParsedURI, Resource

NAME = "pr"

# Aliases for the PR resource. ``prs`` is the discovery endpoint
# (list form); ``PRResource.fetch`` dispatches on ``first_segment``
# to decide between list form (alias path) and per-record form.
ALIASES = ("prs",)


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


def _fetch_prs_list() -> list[dict]:
    """Call ``gh pr list`` and return the parsed JSON list payload.

    Raises :class:`FileNotFoundError` if ``gh`` isn't installed, or
    :class:`RuntimeError` / :class:`json.JSONDecodeError` if the
    underlying command fails. Caller maps both to a partial
    envelope (list form's source is unavailable, not "empty index").
    """
    proc = _run_gh([
        "pr", "list", "--limit", "100",
        "--json", "number,title,headRefName,state,statusCheckRollup,reviewDecision",
    ])
    if proc.returncode != 0:
        raise RuntimeError(f"gh pr list failed: {proc.stderr.strip()}")
    payload = json.loads(proc.stdout)
    if not isinstance(payload, list):
        raise RuntimeError("gh pr list returned non-array payload")
    return payload


def _summarize_ci(rollup: list) -> str | None:
    """Reduce a ``statusCheckRollup`` list to a single ci_state string.

    Returns ``"success"``, ``"failure"``, ``"pending"``, or ``None``
    when the rollup is empty (the common case for MERGED / CLOSED
    PRs whose checks are no longer surfaced). The exact mapping is:

    - Empty rollup                → ``None`` (no CI signal)
    - Any check ``status != COMPLETED`` → ``"pending"``
    - Any check ``conclusion in (FAILURE, failure)`` → ``"failure"``
    - All checks ``SUCCESS``       → ``"success"``
    - Mixed/ambiguous             → ``"failure"`` (defensive)
    """
    if not rollup:
        return None
    has_pending = False
    has_failure = False
    has_success = False
    for entry in rollup:
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        conclusion = entry.get("conclusion")
        if status and status != "COMPLETED":
            has_pending = True
            continue
        if conclusion in ("FAILURE", "failure"):
            has_failure = True
        elif conclusion in ("SUCCESS", "success"):
            has_success = True
    if has_pending:
        return "pending"
    if has_failure:
        return "failure"
    if has_success:
        return "success"
    return None


def _now_iso() -> str:
    """Current UTC time as ISO8601 with explicit +00:00 suffix."""
    return datetime.now(timezone.utc).isoformat()


class PRResource(Resource):
    """LCS resource for ``lcs://pr/<number>`` and ``lcs://prs``.

    Declares ``aliases = ("prs",)`` so the dispatcher routes
    ``lcs://prs`` to this same handler. ``fetch`` decides between
    list form and per-record form based on the URI's first segment.
    """

    name = NAME
    aliases = ALIASES

    def __init__(self, repo_root: Path) -> None:
        # ``repo_root`` is kept for symmetry with WorktreesResource
        # even though ``gh`` resolves the repo from its own CWD —
        # future resources may want to scope PR lookups to a specific
        # checkout, and the uniform signature keeps the registry code
        # trivial.
        self._repo_root = repo_root

    def fetch(self, parsed: ParsedURI) -> dict:
        # List form via the "prs" alias.
        if parsed.first_segment == "prs" and not parsed.path_segments[1:]:
            return self._fetch_prs_list_envelope()

        # Collection form on the primary name: no list endpoint at
        # lcs://pr; only lcs://prs exposes a list.
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

    def _fetch_prs_list_envelope(self) -> dict:
        """Build the ``lcs://prs`` list payload + summary block.

        Source: ``gh pr list --limit 100 --json ...``. When ``gh`` is
        absent or the call fails, ``status="partial"`` with empty
        rows + a ``missing`` note — the source is unavailable, not
        "the index happens to be empty".

        Per-row fields (small-list): ``n, title, head, ci_state,
        review_state``. Heavy fields (``status``, ``checks``,
        ``reviews``, ``unresolved_threads``, ``comments``) stay on
        the per-record URI.

        Summary block: ``total, open, closed, merged, as_of``.
        """
        try:
            rows_raw = _fetch_prs_list()
        except FileNotFoundError:
            return {
                "status": "partial",
                "data": {
                    "prs": [],
                    "summary": {
                        "total": 0,
                        "open": 0,
                        "closed": 0,
                        "merged": 0,
                        "as_of": _now_iso(),
                    },
                },
                "missing": ["gh unavailable"],
            }
        except (RuntimeError, json.JSONDecodeError) as exc:
            return {
                "status": "partial",
                "data": {
                    "prs": [],
                    "summary": {
                        "total": 0,
                        "open": 0,
                        "closed": 0,
                        "merged": 0,
                        "as_of": _now_iso(),
                    },
                },
                "missing": [f"gh pr list failed: {exc}"],
            }

        rows: list[dict] = []
        open_count = closed_count = merged_count = 0
        for entry in rows_raw:
            if not isinstance(entry, dict):
                continue
            state = entry.get("state") or ""
            if state == "OPEN":
                open_count += 1
            elif state == "CLOSED":
                closed_count += 1
            elif state == "MERGED":
                merged_count += 1
            rows.append({
                "n": entry.get("number"),
                "title": entry.get("title"),
                "head": entry.get("headRefName"),
                "ci_state": _summarize_ci(entry.get("statusCheckRollup") or []),
                "review_state": entry.get("reviewDecision"),
            })

        return {
            "status": "ok",
            "data": {
                "prs": rows,
                "summary": {
                    "total": len(rows),
                    "open": open_count,
                    "closed": closed_count,
                    "merged": merged_count,
                    "as_of": _now_iso(),
                },
            },
        }
