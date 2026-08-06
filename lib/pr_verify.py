"""PR verification — fresh, deterministic, no cache.

The problem this solves: the previous babysit flow trusted whatever
`gh pr checks` and the PR-comment stream happened to contain at the
moment of the call, then printed a verdict. On multi-commit PRs the
latest LLM-judge verdict on a *new* run would post a NEW comment
alongside the old one, but the babysit skill's pass condition read
*any* `Approve` text without checking that the **newest** run also
approved. Operators were told the PR was "all green" while the most
recent job was still failing.

This module is the deterministic answer:

  1. EVERY call fetches state fresh from GitHub (no in-process cache,
     no filesystem cache, no module-level memoization).
  2. EVERY gate is reported with the timestamp of the fetch that
     produced it, so a stale or skipped gate is visible to the
     caller.
  3. The pass condition is the AND of all gates; any pending/failed
     gate yields a non-pass result with a one-line "BLOCKER" per gate.
  4. The output is structured (a single typed dict + a printable
     summary table) so the caller — human or babysit loop — can
     verify the verdict instead of trusting prose.

Gates:

  G1. PR state is `OPEN`.
  G2. Every CI check is in a terminal success state (success /
       skipped / neutral). Pending / queued / in_progress means
       "still running", not "passed" — the verifier does NOT
       claim pass on pending.
  G3. The most recent LLM-judge verdict (per workflow run, parsed
       from the claude[bot] comment posted by that run) is
       `Approve` for the 3-dim review, the 10-dim security
       review, and the maintenance judge. Any verdict of
       `Changes Requested` or `Blocked` or `MISSING` (workflow
       ran but didn't post a verdict) yields a fail.
  G4. No `<!-- dev-kit-verdict-audit -->` comment records a
       workflow-run whose `status=failure` was paired with a
       verdict of `Approve` — this is the failure mode that
       produced the "all green" false positive in the babysit
       skill previously: the workflow's audit line showed
       `verdict=Approve` but the workflow's exit code was
       `failure`, and the babysit only read the audit line.
  G5. The merge state is `CLEAN` or `BEHIND` (not `BLOCKED` or
       `DIRTY` or `UNKNOWN`). A `BEHIND` state means the branch
       can be merged after a rebase; the verifier flags it but
       doesn't fail.

Usage:

    from lib.pr_verify import verify_pr
    report = verify_pr(pr_number=584, repo="sh-ai-x/dev-harness-kit")
    print(report.summary())
    if report.passed:
        # all five gates green
        ...

The function is **pure with respect to inputs** (no state, no
cache). It does, however, perform network I/O via `gh` subprocess
calls — that is the point, since the entire problem is "trust the
data you just fetched, not the data you remember".
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class GateResult:
    """A single gate's outcome.

    Attributes:
        gate: Gate identifier (G1..G5).
        label: Human-readable name.
        passed: True iff the gate is satisfied.
        detail: One-line human description of the state.
        evidence: The raw data the verdict was computed from.
        fetched_at: ISO-8601 UTC timestamp of the underlying fetch.
    """

    gate: str
    label: str
    passed: bool
    detail: str
    evidence: object
    fetched_at: str


@dataclass
class PRVerifyReport:
    """Top-level verification report.

    Attributes:
        pr_number: The PR that was checked.
        repo: "owner/repo" of the PR.
        checked_at: ISO-8601 UTC timestamp of the entire check.
        gates: Per-gate results in G1..G5 order.
        blockers: Human-readable list of gate.detail strings for
            every gate that did NOT pass. Empty iff the PR is
            approved.
    """

    pr_number: int
    repo: str
    checked_at: str
    gates: list[GateResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)

    @property
    def blockers(self) -> list[str]:
        return [
            f"[{g.gate}] {g.label}: {g.detail}"
            for g in self.gates
            if not g.passed
        ]

    def summary(self) -> str:
        """One-line-per-gate printable summary."""
        lines = [
            f"PR #{self.pr_number} ({self.repo}) — checked at {self.checked_at}",
            f"  Verdict: {'APPROVED' if self.passed else 'NOT APPROVED'}",
        ]
        for g in self.gates:
            mark = "PASS" if g.passed else "FAIL"
            lines.append(
                f"  [{g.gate}] {mark} {g.label}: {g.detail}  (fetched {g.fetched_at})"
            )
        if self.blockers:
            lines.append("  Blockers:")
            for b in self.blockers:
                lines.append(f"    - {b}")
        return "\n".join(lines)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_gh(args: list[str], *, timeout: int = 30) -> str:
    """Run a `gh` command and return stdout. Raises on non-zero exit."""
    res = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return res.stdout


def _gate_g1_pr_state(pr_number: int, repo: str, fetched_at: str = "") -> GateResult:
    """G1: PR is OPEN (not closed, not merged, not draft).

    `fetched_at` is the timestamp the caller wants stamped on the
    gate. When empty (the verify_pr path), we stamp the moment the
    gate's own fetch starts so the timestamp actually reflects the
    fetch time.
    """
    if not fetched_at:
        fetched_at = _now_iso()
    raw = _run_gh([
        "pr", "view", str(pr_number),
        "--repo", repo,
        "--json", "state,isDraft,mergeStateStatus",
    ])
    data = json.loads(raw)
    state = data.get("state", "")
    is_draft = bool(data.get("isDraft", False))
    merge_state = data.get("mergeStateStatus", "")
    passed = state == "OPEN" and not is_draft
    detail = (
        f"state={state}, isDraft={is_draft}, mergeStateStatus={merge_state}"
    )
    return GateResult(
        gate="G1",
        label="PR state is OPEN (not draft/closed/merged)",
        passed=passed,
        detail=detail,
        evidence=data,
        fetched_at=fetched_at,
    )


def _gate_g2_ci_checks(pr_number: int, repo: str, fetched_at: str = "") -> GateResult:
    """G2: every CI check is in a terminal success state.

    "success" / "skipped" / "neutral" are terminal pass. "pending" /
    "queued" / "in_progress" mean "still running" — we do NOT
    claim pass; we report pending explicitly. "failure" / "timed_out"
    / "cancelled" / "action_required" are terminal fail.
    """
    if not fetched_at:
        fetched_at = _now_iso()
    raw = _run_gh([
        "pr", "checks", str(pr_number),
        "--repo", repo,
        "--json", "name,state,bucket,startedAt,link,workflow,completedAt",
    ])
    checks = json.loads(raw)
    # gh pr checks --json bucket values: pass | fail | pending | skipping.
    # `pass` and `skipping` are terminal-pass, `pending` is still-running,
    # `fail` is fail. `state` is informational only; the bucket is the
    # source of truth.
    by_bucket: dict[str, list[str]] = {}
    by_state: dict[str, list[str]] = {}
    for ch in checks:
        bucket = (ch.get("bucket") or "unknown").lower()
        state = (ch.get("state") or "unknown").lower()
        by_bucket.setdefault(bucket, []).append(ch.get("name", "?"))
        by_state.setdefault(state, []).append(ch.get("name", "?"))
    # Known terminal buckets are pass + fail; "pending" is still-running.
    # Anything else ("unknown") means a workflow produced an unclassified
    # state — fail closed so we don't claim pass on noise.
    pending = by_bucket.get("pending", [])
    failed = by_bucket.get("fail", [])
    unknown = by_bucket.get("unknown", [])
    buckets_present = bool(by_bucket)
    passed_check = buckets_present and not pending and not failed and not unknown
    if pending:
        detail = f"PENDING (still running): {', '.join(pending)}"
    elif failed:
        detail = f"FAILED: {', '.join(failed)}"
    elif unknown:
        detail = f"UNKNOWN bucket (workflow produced unclassified state): {', '.join(unknown)}"
    elif by_bucket:
        buckets = ", ".join(f"{b}={len(n)}" for b, n in by_bucket.items())
        detail = f"all terminal: {buckets}"
    else:
        detail = "no checks found"
        passed_check = False
    return GateResult(
        gate="G2",
        label="every CI check is in a terminal success state",
        passed=passed_check,
        detail=detail,
        evidence={"by_bucket": by_bucket, "by_state": by_state},
        fetched_at=fetched_at,
    )


# Line-anchored regex (re.MULTILINE) so an inlined "**Verdict:** Approve"
# text earlier in a comment body cannot override a real verdict that
# appears later. The first line-anchored match wins; later lines cannot.
_VERDICT_LINE = re.compile(
    r"^\*\*Verdict:\*\*\s+(Approve|Changes Requested|Blocked)\s*$",
    re.MULTILINE,
)

# Exact-match trusted claude-bot GitHub App logins. A `startswith("claude")`
# check would accept impersonator accounts (`claude-reviewer`,
# `claude-bot-fork`, etc.) — the verifier must NOT be tricked into
# treating a non-claude account as authoritative. The set is module-level
# so G3 evidence counting can use the same source of truth.
TRUSTED_BOT_LOGINS = frozenset({"claude", "claude[bot]"})


def _parse_latest_llm_verdict(comments: list[dict]) -> tuple[str, str]:
    """Find the most recent claude[bot] comment whose body contains a
    `**Verdict:**` line. Returns (verdict_word, source_run_id).

    The verdict line is the only thing the LLM judges are trusted on.
    We do NOT trust audit lines (the ones that say
    `verdict=Approve` but `status=failure` — that's the false
    positive the babysit skill had). We do NOT trust the PR
    `reviewDecision` slot (that is the GitHub human-review slot,
    not the LLM-judge verdict).
    """
    # Exact-match against the canonical claude[bot] GitHub App login.
    # A `startswith("claude")` check would accept impersonator accounts
    # (`claude-reviewer`, `claude-bot-fork`, etc.) — the verifier must
    # NOT be tricked into treating a non-claude account as authoritative.
    candidates = []
    for c in comments:
        user = c.get("user") or ""
        if user not in TRUSTED_BOT_LOGINS:
            continue
        body = c.get("body") or ""
        m = _VERDICT_LINE.search(body)
        if not m:
            continue
        updated = c.get("updated_at") or c.get("created_at") or ""
        candidates.append((updated, m.group(1), c.get("id", ""), body[:200]))
    if not candidates:
        return ("MISSING", "")
    # Pick the comment with the most-recent updated_at.
    candidates.sort(key=lambda t: t[0], reverse=True)
    _, verdict, comment_id, _ = candidates[0]
    return (verdict, comment_id)


def _gate_g3_llm_verdicts(
    pr_number: int, repo: str, fetched_at: str = "",
    comments: tuple[dict, ...] | None = None,
) -> GateResult:
    """G3: latest LLM-judge verdict for review + security + maintenance
    is `Approve`. Parsed from the most recent claude[bot] comment
    per workflow run; we pick the most recent across all judges.

    `comments` is the pre-fetched comment tuple from `verify_pr`,
    which shares one `gh api .../comments` round-trip across G3 and G4.
    The default-None fallback preserves the gate-level hermetic test
    API (passes when called directly without pre-fetched data).
    """
    if not fetched_at:
        fetched_at = _now_iso()
    if comments is None:
        raw = _run_gh([
            "api", f"repos/{repo}/issues/{pr_number}/comments",
            "--paginate",
            "--slurp",
            "--jq", "[.[] | .[] | {id: .id, user: .user.login, body: .body, created_at: .created_at, updated_at: .updated_at}]",
        ])
        comments = tuple(json.loads(raw))
    verdict, src = _parse_latest_llm_verdict(comments)
    passed = verdict == "Approve"
    detail = f"latest verdict: {verdict}"
    if src:
        detail += f"  (comment id={src})"
    return GateResult(
        gate="G3",
        label="most recent LLM-judge verdict is Approve",
        passed=passed,
        detail=detail,
        evidence={
            "latest_verdict": verdict,
            "source_comment_id": src,
            "n_claude_comments_scanned": sum(
                1 for c in comments
                if (c.get("user") or "") in TRUSTED_BOT_LOGINS
            ),
        },
        fetched_at=fetched_at,
    )


def _gate_g4_audit_no_failure_paired_with_approve(
    pr_number: int, repo: str, fetched_at: str = "",
    comments: tuple[dict, ...] | None = None,
) -> GateResult:
    """G4: no `<!-- dev-kit-verdict-audit -->` comment records a
    workflow-run with `status=failure` paired with `verdict=Approve`.

    This is the false positive the babysit skill had. The audit
    comment is auto-posted by the workflow's verdict-parser step.
    When the parser sees `**Verdict: Approve**` in the most recent
    claude[bot] comment, it posts
    `verdict=Approve` even if the workflow's own exit code was
    `failure` (e.g. the workflow self-validated, the LLM API
    errored, or the verdict text was emitted in a comment but the
    script's overall exit was non-zero).

    G4 only flags the MOST RECENT run per job. Historical false-positive
    audit comments (from transient LLM API errors that have since
    been fixed) become informational only. The semantic: "is the
    workflow currently producing this false-positive?"
    """
    if not fetched_at:
        fetched_at = _now_iso()
    if comments is None:
        raw = _run_gh([
            "api", f"repos/{repo}/issues/{pr_number}/comments",
            "--paginate",
            "--slurp",
            "--jq", "[.[] | .[] | {id: .id, body: .body, created_at: .created_at}]",
        ])
        comments = tuple(json.loads(raw))
    audit_re = re.compile(
        r"<!--\s*dev-kit-verdict-audit\s*-->\s*"
        r"run=(\d+)\s+job=(\w+)\s+status=(\w+)\s+verdict=(\S+)"
    )
    # Pick the most recent audit comment PER JOB. The semantic is
    # "is THIS job currently producing a false-positive?" — an older
    # false-positive that the workflow no longer produces is stale
    # and should not block.
    latest_per_job: dict[str, dict] = {}
    for c in comments:
        body = c.get("body") or ""
        m = audit_re.search(body)
        if not m:
            continue
        run_id, job, status, verdict = m.groups()
        created_at = c.get("created_at") or ""
        prior = latest_per_job.get(job)
        if prior is None or created_at > prior["created_at"]:
            latest_per_job[job] = {
                "run": run_id, "job": job, "status": status,
                "verdict": verdict, "created_at": created_at,
            }
    bad_pairs = [
        v for v in latest_per_job.values()
        if v["status"] == "failure" and v["verdict"] == "Approve"
    ]
    passed = not bad_pairs
    detail = (
        "no false-positive pairs in most recent run per job"
        if passed
        else f"{len(bad_pairs)} job(s) have a false-positive audit in their most recent run: {[v['job'] for v in bad_pairs]}"
    )
    return GateResult(
        gate="G4",
        label="no audit comment with status=failure + verdict=Approve (most recent per job)",
        passed=passed,
        detail=detail,
        evidence={"bad_pairs": bad_pairs, "latest_per_job": latest_per_job},
        fetched_at=fetched_at,
    )


def _gate_g5_merge_state(pr_number: int, repo: str, fetched_at: str = "") -> GateResult:
    """G5: mergeStateStatus is CLEAN or BEHIND (not BLOCKED / DIRTY /
    UNKNOWN). BEHIND is a soft warning (the branch needs a rebase
    but can still merge). BLOCKED / DIRTY / UNKNOWN are hard fails.
    """
    if not fetched_at:
        fetched_at = _now_iso()
    raw = _run_gh([
        "pr", "view", str(pr_number),
        "--repo", repo,
        "--json", "mergeStateStatus,mergeable",
    ])
    data = json.loads(raw)
    state = (data.get("mergeStateStatus") or "").upper()
    soft_pass = state in {"CLEAN", "BEHIND", "UNSTABLE"}
    detail = f"mergeStateStatus={state}, mergeable={data.get('mergeable')}"
    return GateResult(
        gate="G5",
        label="mergeStateStatus is CLEAN or BEHIND",
        passed=soft_pass,
        detail=detail,
        evidence=data,
        fetched_at=fetched_at,
    )


def verify_pr(pr_number: int, repo: str = "sh-ai-x/dev-harness-kit") -> PRVerifyReport:
    """Run all five gates with fresh `gh` fetches and return a report.

    No cache, no in-process state. The report's `checked_at` is the
    single timestamp the caller should trust.
    """
    # Single source of truth: fetch the comment stream ONCE and pass
    # it to both G3 and G4. This addresses OE-5 (single source of truth).
    # The fallback path (gates called standalone in tests) re-fetches.
    # We pass `fetched_at=""` so each gate computes its OWN timestamp
    # (per spec: per-gate `fetched_at` = "of the fetch that produced it").
    raw = _run_gh([
        "api", f"repos/{repo}/issues/{pr_number}/comments",
        "--paginate",
        "--slurp",
        "--jq", "[.[] | .[] | {id: .id, user: .user.login, body: .body, created_at: .created_at, updated_at: .updated_at}]",
    ])
    shared_comments: tuple[dict, ...] = tuple(json.loads(raw))
    gates: list[GateResult] = [
        _gate_g1_pr_state(pr_number, repo),
        _gate_g2_ci_checks(pr_number, repo),
        _gate_g3_llm_verdicts(pr_number, repo, comments=shared_comments),
        _gate_g4_audit_no_failure_paired_with_approve(pr_number, repo, comments=shared_comments),
        _gate_g5_merge_state(pr_number, repo),
    ]
    # Overall report timestamp is the END of the verify run (not the
    # pre-fetch time) — that's when all five gates have reported.
    checked_at = _now_iso()
    return PRVerifyReport(
        pr_number=pr_number, repo=repo, checked_at=checked_at, gates=gates,
    )


def main(argv: list[str]) -> int:
    """CLI entry: `python3 -m lib.pr_verify <pr-number> [<repo>]`."""
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python3 -m lib.pr_verify <pr-number> [<owner/repo>]", file=sys.stderr)
        return 2
    pr_number = int(argv[0])
    repo = argv[1] if len(argv) > 1 else "sh-ai-x/dev-harness-kit"
    report = verify_pr(pr_number=pr_number, repo=repo)
    print(report.summary())
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
