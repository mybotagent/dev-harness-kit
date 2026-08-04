"""babysit_pr_reliability.py -- reliability helpers for /dev-kit:babysit-pr.

Two pure-function primitives consumed by the babysit-pr skill
(`skills/babysit-pr/SKILL.md`):

  is_stale_lock(path, ttl_seconds=LOCK_TTL_SECONDS)
      Detect a stale babysit.lock left behind by a SIGKILL / OOM /
      network-partition during a previous run. Stale locks wedge every
      future babysit-pr iteration. Returns True when EITHER
        (a) the lock file mtime is older than ttl_seconds ago, OR
        (b) the recorded pid= field names a process that no longer
            exists (Linux: pid absent from /proc; macOS: kill(0)
            fails with ESRCH).

  classify_check(check, now_epoch, ghost_threshold_seconds=GHOST_CHECK_THRESHOLD_SECONDS)
      Classify a single `gh pr checks` entry. Returns one of
        approved  -- conclusion in {success, skipped, neutral}
        failing   -- conclusion in {failure, cancelled, timed_out,
                                    stale, error}
        pending   -- conclusion is None and the check looks alive
                     (startedAt/updatedAt within ghost_threshold_seconds,
                     OR neither is set yet -- a freshly requested/queued
                     check has no timestamp to measure elapsed time
                     against, so it stays pending rather than ghosting
                     at age zero)
        ghost     -- conclusion is None AND (startedAt/updatedAt is set
                     but older than ghost_threshold_seconds, OR explicit
                     databaseId is missing entirely -- GitHub's signal
                     that the workflow run has been pruned from the
                     checks table). The skill should stop waiting on a
                     ghost check and surface it as a recovery-required
                     failure.
      The function never raises: malformed inputs return "pending" (the
      most conservative non-alarming default).

Both helpers are deterministic (no time-of-day randomness -- callers
pass `now_epoch`) so regression tests can reproduce ghost / fresh-lock
states without sleeping.

The default TTL (LOCK_TTL_SECONDS = 1800) and ghost threshold
(GHOST_CHECK_THRESHOLD_SECONDS = 300) are exported as module-level
constants so a future tweak in one place is reflected everywhere
(function defaults, docstrings, any future caller that wants the
canonical value).

This module is the exclusive home for babysit-pr reliability
primitives. It does not touch `lib/analysis_core/*` or
`tools/skill_usage.py`.
"""
from __future__ import annotations

import calendar
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, Union

PathLike = Union[str, os.PathLike]

# Default TTL for an `is_stale_lock` check: 30 minutes. Generous for the
# babysit-pr per-iteration push cycle, but tight enough that a SIGKILL
# during a run leaves a stale lock the next iteration can detect.
LOCK_TTL_SECONDS: int = 1800

# Default ghost-check threshold for `classify_check`: 5 minutes. Any
# check that has been pending longer than this with no fresh
# startedAt/updatedAt (or no databaseId at all) is treated as a ghost
# the babysit-pr loop should stop waiting on.
GHOST_CHECK_THRESHOLD_SECONDS: int = 300

# Outcome strings observed by `gh pr checks --json name,state,conclusion`
# in the wild (union of GitHub Actions conclusion vocabulary).
APPROVED_CONCLUSIONS = frozenset({"success", "skipped", "neutral"})
FAILING_CONCLUSIONS = frozenset({
    "failure", "failures", "cancelled", "timed_out", "stale", "error",
})


def _pid_alive(pid: int) -> bool:
    """Return True when `pid` refers to a running process on this host.

    Linux: a running pid has an entry under /proc/<pid>.
    macOS: kill(pid, 0) succeeds when the pid exists, fails ESRCH when
    not, EPERM when the pid exists but we do not own it (treat as alive
    so we do not falsely classify the lock as stale).
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _parse_pid_from_lock(content: str) -> int | None:
    """Best-effort parse of `pid=<int>` from a lock file body.

    Returns the first integer after `pid=` on any line, or None.
    Tolerates surrounding whitespace and arbitrary trailing characters
    -- the babysit-pr format is `<ISO> pid=<n> branch=<x>`.
    """
    for line in content.splitlines():
        m = re.search(r"pid=(\d+)", line)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def is_stale_lock(
    path: PathLike,
    ttl_seconds: int = LOCK_TTL_SECONDS,
    *,
    now_epoch: float | None = None,
) -> bool:
    """Return True when the lock file at `path` is stale.

    A lock is stale when it is older than `ttl_seconds` (default 30
    minutes, generous for babysit-pr's per-iteration push cycle), OR the
    recorded pid no longer exists.

    Missing `path` returns False -- there is nothing to be stale -- so
    callers can short-circuit without a try/except dance:

        if not is_stale_lock(".dev-kit/babysit.lock"):
            return already_running_error

    The `now_epoch` parameter is for tests only.
    """
    p = Path(path)
    try:
        st = p.stat()
    except FileNotFoundError:
        return False
    except OSError:
        return False

    now = now_epoch if now_epoch is not None else time.time()
    age = now - st.st_mtime
    if age > ttl_seconds:
        return True

    try:
        body = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        # Read failure on a lock we just stat()'d: be conservative and
        # call it non-stale. The next babysit-pr run can re-evaluate.
        return False

    pid = _parse_pid_from_lock(body)
    if pid is not None and not _pid_alive(pid):
        return True

    return False


def _epoch_from_iso(s: Any) -> float | None:
    """Convert an ISO-8601-ish timestamp to epoch seconds (UTC).

    Accepts the shapes GitHub emits in `startedAt` / `updatedAt`:
        2026-07-18T14:23:45Z
        2026-07-18T14:23:45.123Z
        2026-07-18T14:23:45+00:00
    Returns None on unparseable input. Never raises.

    Uses `calendar.timegm` so the result is a UTC epoch (not local-
    time-dependent) -- callers compare against their own UTC `now_epoch`.
    """
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    base = s.split(".")[0]
    if base.endswith("Z"):
        base = base[:-1]
    # Drop trailing "+HH:MM" / "-HH:MM" timezone marker if present.
    # Date-only strings or naive timestamps stay as-is.
    for marker in ("+", "-"):
        idx = base.rfind(marker)
        if idx > 10:
            base = base[:idx]
    base = base[:19]
    try:
        return calendar.timegm(time.strptime(base, "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return None


def classify_check(
    check: Mapping[str, Any],
    now_epoch: float,
    *,
    ghost_threshold_seconds: int = GHOST_CHECK_THRESHOLD_SECONDS,
) -> str:
    """Classify a `gh pr checks` entry.

    Returns one of: "approved" | "failing" | "pending" | "ghost".

    `ghost` is the recovery contract: a check that has been pending long
    enough that no live workflow will ever resolve it (worktree removed,
    workflow file renamed or deleted, OR the run was cancelled at the
    GitHub side and never reported back). The babysit-pr loop should
    stop blocking on ghost checks and surface them as recovery-required
    failures.
    """
    if not isinstance(check, Mapping):
        return "pending"

    conclusion = check.get("conclusion")

    # Terminal conclusions: never ghost.
    if isinstance(conclusion, str):
        c = conclusion.lower()
        if c in APPROVED_CONCLUSIONS:
            return "approved"
        if c in FAILING_CONCLUSIONS:
            return "failing"
        # Unknown conclusion string -- treat as pending rather than ghost
        # so the babysit does not silence a check the gateway may yet
        # report on.
        return "pending"

    # No conclusion yet. Distinguish live-pending from ghost.
    raw_db = check.get("databaseId")
    database_id_present = (
        isinstance(raw_db, int)
        or (isinstance(raw_db, str) and raw_db.strip().isdigit())
    )
    started_epoch = _epoch_from_iso(check.get("startedAt"))
    updated_epoch = _epoch_from_iso(check.get("updatedAt"))

    last_seen_candidates = [t for t in (started_epoch, updated_epoch) if t is not None]
    last_seen = max(last_seen_candidates) if last_seen_candidates else None

    if not database_id_present:
        # No databaseId is GitHub's "this run has been pruned from the
        # checks table" signal. Ghost regardless of state.
        return "ghost"

    if last_seen is None:
        # No timestamp to anchor against. "expected" / "waiting" /
        # "queued" / "requested" states mean a check that has never
        # started -- with no startedAt/updatedAt there is no elapsed
        # time to compare against ghost_threshold_seconds, so a
        # freshly-requested check (age zero) is pending, not ghost.
        # They ghost out only once the threshold below is actually
        # exceeded -- which requires a timestamp to measure against, so
        # a check that legitimately ages past the threshold will carry
        # a stale startedAt/updatedAt and fall through to the
        # `last_seen is not None` branch instead.
        return "pending"

    age = now_epoch - last_seen
    if age > ghost_threshold_seconds:
        return "ghost"
    return "pending"

# --------------------------------------------------------------------------- #
# Verdict freshness check (issue SHO-179)
# --------------------------------------------------------------------------- #

# Maximum acceptable age (seconds) between the most recent claude[bot]
# verdict comment and the workflow run that produced the current
# check conclusion. Beyond this, the extraction step is presumed to
# be reading a stale comment. Default 600s (10 min) is generous; the
# Claude action typically posts a comment within 60-180s of the gate
# firing.
VERDICT_FRESHNESS_WINDOW_SECONDS: int = 600

# Status strings returned by `check_verdict_freshness`.
FRESH = "fresh"          # latest comment is newer than the run
STALE = "stale"          # latest comment is older than the run (or missing)
GHOST = "ghost"          # no claude[bot] comment AND the run completed without one


def check_verdict_freshness(
    pr_number: int,
    run_started_epoch: float,
    now_epoch: float,
    expected_run_id: int | None = None,
    expected_job_key: str | None = None,
) -> dict:
    """Return whether the most recent claude[bot] verdict comment is
    fresh relative to the given workflow run.

    A comment is FRESH when its `updated_at` is at or after the run's
    `started_at` AND within `VERDICT_FRESHNESS_WINDOW_SECONDS` of
    `now_epoch`. STALE when the comment is older than the run but still
    within the window (extraction page-1'd past a newer verdict the
    next job posted). GHOST when no claude verdict comment is found,
    the comment is older than both the run and the window, or the
    comment is newer than the run but arbitrarily old (past the
    window). When `expected_run_id` is provided, the candidate set is
    restricted to comments whose body contains `run=<expected_run_id>`
    so a fresh verdict from one gate cannot certify another gate's
    verdict (closes CROSS-GATE-FALSE-FRESH).

    Returns a dict with `status` (FRESH / STALE / GHOST) and `reason`.
    No raw comments are returned (closes RETURN-SURFACE). The function
    never raises; transport errors return `status="ghost"`.

    Usage in babysit skill (skills/babysit-pr/SKILL.md step 8.5):

        result = check_verdict_freshness(
            pr_number=566,
            run_started_epoch=...,
            now_epoch=...,
        )
        if result["status"] in (STALE, GHOST):
            # do NOT claim "all green" — surface the staleness
            ...
    """
    repo = os.environ.get("GITHUB_REPOSITORY") or os.environ.get("GITHUB_REPO", "")
    try:
        # The babysit skill shell that calls this helper already has
        # `gh` authenticated — `gh api` avoids token plumbing here.
        result = subprocess.run(
            ["gh", "api",
             f"repos/{repo}/issues/{pr_number}/comments?per_page=100",
             "--jq", ".",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"status": GHOST,
                    "reason": f"gh api exit={result.returncode}"}
        comments = json.loads(result.stdout)
    except (subprocess.SubprocessError, OSError, ValueError):
        # SubprocessError: `gh` missing / killed / timeout. OSError:
        # file / network errors. ValueError: malformed JSON. All three
        # are fail-closed -> GHOST (the conservative call); the
        # babysit layer surfaces the reason in its own log.
        return {"status": GHOST, "reason": "transport or parse error"}

    # Build the set of claude[bot] verdict comments.
    claude_verdicts = [
        c for c in comments
        if (c.get("user", {}).get("login") or "").startswith("claude")
        and "**Verdict:**" in (c.get("body") or "")
    ]
    if not claude_verdicts:
        return {"status": GHOST, "reason": "no claude verdict comment"}

    # Build candidate set: if expected_run_id is given, the candidate
    # must be a verdict audit comment that names that run. Otherwise
    # any claude verdict is a candidate (preserves the original
    # "newest of any" behavior for tests that don't pin a run).
    candidates = claude_verdicts
    if expected_run_id is not None:
        run_match = [
            c for c in claude_verdicts
            if f"run={expected_run_id}" in (c.get("body") or "")
        ]
        candidates = run_match
    if not candidates:
        return {
            "status": GHOST,
            "reason": (
                f"no claude verdict comment for run_id={expected_run_id} "
                f"(comments inspected: {len(claude_verdicts)})"
            ),
        }

    # Pick the most recent.
    latest = max(candidates, key=lambda c: c.get("updated_at", ""))
    latest_epoch = _epoch_from_iso(latest.get("updated_at"))
    if latest_epoch is None:
        return {"status": GHOST,
                "reason": f"unparseable updated_at: {latest.get('updated_at')!r}"}

    age = now_epoch - latest_epoch

    # Apply both freshness conditions independently (closes the
    # FRESH-WINDOW-BYPASS issue from SHO-179). A comment is FRESH
    # only when BOTH:
    #   (a) it was posted after the run started (i.e. this run is the
    #       source of the verdict), AND
    #   (b) it is within VERDICT_FRESHNESS_WINDOW_SECONDS of now_epoch
    #       (an arbitrarily old comment is not a fresh verdict).
    if latest_epoch < run_started_epoch:
        if age > VERDICT_FRESHNESS_WINDOW_SECONDS:
            return {"status": GHOST,
                    "reason": (f"comment older than the run AND older "
                               f"than {VERDICT_FRESHNESS_WINDOW_SECONDS}s "
                               f"window (age={int(age)}s)")}
        return {"status": STALE,
                "reason": (f"comment older than the run but within "
                           f"{VERDICT_FRESHNESS_WINDOW_SECONDS}s window "
                           f"(age={int(age)}s)")}
    if age > VERDICT_FRESHNESS_WINDOW_SECONDS:
        return {"status": GHOST,
                "reason": (f"comment newer than the run but older than "
                           f"{VERDICT_FRESHNESS_WINDOW_SECONDS}s window "
                           f"(age={int(age)}s)")}
    return {"status": FRESH,
            "reason": (f"comment newer than the run AND within "
                       f"{VERDICT_FRESHNESS_WINDOW_SECONDS}s window "
                       f"(age={int(age)}s)")}
    try:
        # The babysit skill shell that calls this helper already has
        # `gh` authenticated — `gh api` avoids token plumbing here.
        result = subprocess.run(
            ["gh", "api",
             f"repos/{repo}/issues/{pr_number}/comments?per_page=100",
             "--jq", ".",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"status": GHOST, "comment_id": None,
                    "comment_age_seconds": None, "comments": []}
        comments = json.loads(result.stdout)
    except (subprocess.SubprocessError, OSError, ValueError):
        # SubprocessError: `gh` missing / killed / timeout. OSError:
        # file / network errors. ValueError: malformed JSON. All three
        # are fail-closed -> GHOST (the conservative call); the
        # babysit layer surfaces the reason in its own log.
        return {"status": GHOST, "comment_id": None,
                "comment_age_seconds": None, "comments": []}

    claude_comments = [
        c for c in comments
        if (c.get("user", {}).get("login") or "").startswith("claude")
        and "**Verdict:**" in (c.get("body") or "")
    ]
    if not claude_comments:
        return {"status": GHOST, "comment_id": None,
                "comment_age_seconds": None, "comments": []}

    # Pick the most recent (newest updated_at) and parse via the same
    # _epoch_from_iso helper classify_check already uses.
    latest = max(claude_comments, key=lambda c: c.get("updated_at", ""))
    latest_epoch = _epoch_from_iso(latest.get("updated_at"))
    if latest_epoch is None:
        return {"status": GHOST, "comment_id": latest.get("id"),
                "comment_age_seconds": None, "comments": claude_comments}

    age = now_epoch - latest_epoch
    # If the latest comment is OLDER than the run started (the run
    # completed but no fresh comment was posted) -> STALE, but only
    # while the comment is still within VERDICT_FRESHNESS_WINDOW_SECONDS
    # of `now_epoch`. Past that window, the comment is from an
    # unrelated older run and the extraction is reading genuinely
    # stale data -> GHOST (fail-closed).
    if latest_epoch < run_started_epoch:
        if age > VERDICT_FRESHNESS_WINDOW_SECONDS:
            return {"status": GHOST, "comment_id": latest.get("id"),
                    "comment_age_seconds": age, "comments": claude_comments}
        return {"status": STALE, "comment_id": latest.get("id"),
                "comment_age_seconds": age, "comments": claude_comments}
    return {"status": FRESH, "comment_id": latest.get("id"),
            "comment_age_seconds": age, "comments": claude_comments}

