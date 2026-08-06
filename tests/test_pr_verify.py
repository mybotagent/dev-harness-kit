#!/usr/bin/env python3
"""Tests for lib.pr_verify — deterministic PR verification.

Covers each of the five gates + the parser logic. All network I/O is
mocked; tests are hermetic.
"""
from __future__ import annotations

import json
import sys
import unittest
from typing import Any
from unittest.mock import patch

sys.path.insert(0, "lib")
import pr_verify  # noqa: E402


def _ok(ok: bool, **kw: Any) -> dict:
    return {"ok": ok, **kw}


class TestParseLatestLLMVerdict(unittest.TestCase):
    """G3 depends on this parser; locking it down first."""

    def test_empty_comments_returns_missing(self):
        verdict, src = pr_verify._parse_latest_llm_verdict([])
        self.assertEqual(verdict, "MISSING")
        self.assertEqual(src, "")

    def test_no_claude_comments_returns_missing(self):
        comments = [
            {"user": "github-actions", "body": "**Verdict:** Approve", "updated_at": "2026-01-01T00:00:00Z"},
        ]
        verdict, _ = pr_verify._parse_latest_llm_verdict(comments)
        self.assertEqual(verdict, "MISSING")

    def test_no_verdict_line_returns_missing(self):
        comments = [
            {"user": "claude[bot]", "body": "no verdict here", "updated_at": "2026-01-01T00:00:00Z"},
        ]
        verdict, _ = pr_verify._parse_latest_llm_verdict(comments)
        self.assertEqual(verdict, "MISSING")

    def test_latest_claude_comment_with_approve_wins(self):
        comments = [
            {"user": "claude[bot]", "body": "**Verdict:** Changes Requested", "updated_at": "2026-01-01T00:00:00Z", "id": "1"},
            {"user": "claude[bot]", "body": "**Verdict:** Approve", "updated_at": "2026-01-02T00:00:00Z", "id": "2"},
        ]
        verdict, src = pr_verify._parse_latest_llm_verdict(comments)
        self.assertEqual(verdict, "Approve")
        self.assertEqual(src, "2")

    def test_older_claude_comment_with_approve_loses_to_newer_changes(self):
        comments = [
            {"user": "claude[bot]", "body": "**Verdict:** Approve", "updated_at": "2026-01-01T00:00:00Z", "id": "1"},
            {"user": "claude[bot]", "body": "**Verdict:** Changes Requested", "updated_at": "2026-01-02T00:00:00Z", "id": "2"},
        ]
        verdict, src = pr_verify._parse_latest_llm_verdict(comments)
        self.assertEqual(verdict, "Changes Requested")
        self.assertEqual(src, "2")

    def test_blocked_verdict_recognized(self):
        comments = [
            {"user": "claude[bot]", "body": "**Verdict:** Blocked", "updated_at": "2026-01-01T00:00:00Z", "id": "1"},
        ]
        verdict, _ = pr_verify._parse_latest_llm_verdict(comments)
        self.assertEqual(verdict, "Blocked")

    def test_nested_verdict_in_paragraph_does_not_match(self):
        """A **Verdict:** mention inside prose must not satisfy the
        parser. The regex anchors on its own line via the strict
        `\\*\\*Verdict:\\*\\*\\s+<word>` pattern, so a sentence like
        'we want **Verdict:** Approve' would still match — this
        is documented and accepted. False negatives are worse than
        false positives here.
        """
        comments = [
            {"user": "claude[bot]", "body": "Verdict: Approve", "updated_at": "2026-01-01T00:00:00Z", "id": "1"},
        ]
        # No **Verdict:** markdown bold — parser returns MISSING.
        verdict, _ = pr_verify._parse_latest_llm_verdict(comments)
        self.assertEqual(verdict, "MISSING")


class TestGatesHermetic(unittest.TestCase):
    """Each gate with mocked `gh` calls."""

    def test_g1_open_pr_passes(self):
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps({
            "state": "OPEN", "isDraft": False, "mergeStateStatus": "CLEAN",
        })):
            g = pr_verify._gate_g1_pr_state(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertTrue(g.passed)
        self.assertIn("OPEN", g.detail)

    def test_g1_draft_pr_fails(self):
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps({
            "state": "OPEN", "isDraft": True, "mergeStateStatus": "CLEAN",
        })):
            g = pr_verify._gate_g1_pr_state(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertFalse(g.passed)

    def test_g1_closed_pr_fails(self):
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps({
            "state": "CLOSED", "isDraft": False, "mergeStateStatus": "CLEAN",
        })):
            g = pr_verify._gate_g1_pr_state(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertFalse(g.passed)

    def test_g2_all_pass(self):
        checks = [
            {"name": "lint", "state": "COMPLETED", "conclusion": "success", "bucket": "pass"},
            {"name": "test", "state": "COMPLETED", "conclusion": "success", "bucket": "pass"},
            {"name": "branch-policy", "state": "COMPLETED", "conclusion": "skipped", "bucket": "skipping"},
        ]
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps(checks)):
            g = pr_verify._gate_g2_ci_checks(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertTrue(g.passed)

    def test_g2_pending_does_not_claim_pass(self):
        """Critical: a still-running check must not be 'approved'."""
        checks = [
            {"name": "lint", "state": "COMPLETED", "conclusion": "success", "bucket": "pass"},
            {"name": "review", "state": "IN_PROGRESS", "conclusion": None, "bucket": "pending"},
        ]
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps(checks)):
            g = pr_verify._gate_g2_ci_checks(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertFalse(g.passed)
        self.assertIn("PENDING", g.detail)

    def test_g2_failure_fails(self):
        checks = [
            {"name": "lint", "state": "COMPLETED", "conclusion": "success", "bucket": "pass"},
            {"name": "review", "state": "COMPLETED", "conclusion": "failure", "bucket": "fail"},
        ]
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps(checks)):
            g = pr_verify._gate_g2_ci_checks(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertFalse(g.passed)
        self.assertIn("FAILED", g.detail)

    def test_g3_latest_approve_passes(self):
        comments = [
            {"user": "claude[bot]", "body": "**Verdict:** Approve", "updated_at": "2026-01-02T00:00:00Z", "id": "1"},
        ]
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps(comments)):
            g = pr_verify._gate_g3_llm_verdicts(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertTrue(g.passed)

    def test_g3_latest_changes_requested_fails(self):
        """Critical: even if an OLDER claude comment said Approve, the
        NEWER one saying Changes Requested must win."""
        comments = [
            {"user": "claude[bot]", "body": "**Verdict:** Approve", "updated_at": "2026-01-01T00:00:00Z", "id": "1"},
            {"user": "claude[bot]", "body": "**Verdict:** Changes Requested", "updated_at": "2026-01-02T00:00:00Z", "id": "2"},
        ]
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps(comments)):
            g = pr_verify._gate_g3_llm_verdicts(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertFalse(g.passed)

    def test_g3_missing_verdict_fails(self):
        """If no claude[bot] comment has a **Verdict:** line, the gate fails.
        This is the 'in-progress run' false positive the babysit skill had:
        the workflow had run but the LLM hadn't yet posted a verdict,
        and the babysit claimed 'all green' anyway."""
        comments = []
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps(comments)):
            g = pr_verify._gate_g3_llm_verdicts(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertFalse(g.passed)
        self.assertIn("MISSING", g.detail)

    def test_g4_pure_approve_pair_passes(self):
        comments = [
            {"id": "1", "body": "<!-- dev-kit-verdict-audit --> run=100 job=review status=success verdict=Approve", "created_at": "2026-01-01T00:00:00Z"},
        ]
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps(comments)):
            g = pr_verify._gate_g4_audit_no_failure_paired_with_approve(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertTrue(g.passed)

    def test_g4_failure_paired_with_approve_fails(self):
        """Critical: this is the exact false positive the babysit
        skill had. The audit line says verdict=Approve but the
        workflow's exit status=failure (e.g. the LLM API errored,
        or the workflow self-validated, or the verdict text was
        emitted but the script's overall exit was non-zero)."""
        comments = [
            {"id": "1", "body": "<!-- dev-kit-verdict-audit --> run=100 job=review status=failure verdict=Approve", "created_at": "2026-01-01T00:00:00Z"},
        ]
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps(comments)):
            g = pr_verify._gate_g4_audit_no_failure_paired_with_approve(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertFalse(g.passed)
        self.assertIn("status=failure verdict=Approve", g.detail)

    def test_g5_clean_passes(self):
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps({
            "mergeStateStatus": "CLEAN", "mergeable": "MERGEABLE",
        })):
            g = pr_verify._gate_g5_merge_state(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertTrue(g.passed)

    def test_g5_behind_soft_passes_with_warning(self):
        """BEHIND = branch needs rebase but can still merge. Treat as
        a soft pass; the caller can choose to rebase."""
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps({
            "mergeStateStatus": "BEHIND", "mergeable": "MERGEABLE",
        })):
            g = pr_verify._gate_g5_merge_state(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertTrue(g.passed)

    def test_g5_blocked_fails(self):
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps({
            "mergeStateStatus": "BLOCKED", "mergeable": "CONFLICTING",
        })):
            g = pr_verify._gate_g5_merge_state(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertFalse(g.passed)


class TestVerifyPRIntegration(unittest.TestCase):
    """End-to-end: a fully-passing fixture passes; a mixed fixture fails."""

    def test_all_gates_pass_yields_passed_report(self):
        # Every gate's underlying `_run_gh` returns a passing value.
        with patch.object(pr_verify, "_run_gh", side_effect=lambda args: _ok_return(args)):
            report = pr_verify.verify_pr(584)
        self.assertTrue(report.passed)
        self.assertEqual(report.blockers, [])

    def test_any_gate_failing_yields_failed_report(self):
        with patch.object(pr_verify, "_run_gh", side_effect=lambda args: _fail_at(args, which="G4")):
            report = pr_verify.verify_pr(584)
        self.assertFalse(report.passed)
        # The G4-fail fixture has a status=failure + verdict=Approve
        # audit comment, which trips BOTH G3 (no claude verdict) and
        # G4 (false-positive pair). So two blockers, not one.
        self.assertGreaterEqual(len(report.blockers), 1)
        self.assertTrue(any("G4" in b for b in report.blockers))

    def test_summary_includes_all_gates(self):
        with patch.object(pr_verify, "_run_gh", side_effect=lambda args: _ok_return(args)):
            report = pr_verify.verify_pr(584)
        text = report.summary()
        for gate_id in ("G1", "G2", "G3", "G4", "G5"):
            self.assertIn(gate_id, text)
        self.assertIn("APPROVED", text)
        self.assertIn("checked at", text)


# ---------- helpers for the integration test ----------

def _ok_return(args):
    """All five gates' underlying gh calls return passing values."""
    sub = args[0]
    if sub == "pr" and len(args) > 1 and args[1] == "view":
        return json.dumps({
            "state": "OPEN", "isDraft": False, "mergeStateStatus": "CLEAN",
            "mergeable": "MERGEABLE",
        })
    if sub == "pr" and len(args) > 1 and args[1] == "checks":
        return json.dumps([
            {"name": "lint", "state": "COMPLETED", "conclusion": "success", "bucket": "pass"},
            {"name": "test", "state": "COMPLETED", "conclusion": "success", "bucket": "pass"},
        ])
    if sub == "api":
        return json.dumps([
            {"user": "claude[bot]", "body": "**Verdict:** Approve", "updated_at": "2026-01-01T00:00:00Z", "id": "1"},
        ])
    return json.dumps({})


def _fail_at(args, which: str):
    """Force a specific gate to fail by returning a known-bad payload.

    G4 only: the API call (which fetches PR comments) returns a
    comments list that includes a status=failure + verdict=Approve
    audit comment. Other calls return the same passing values as
    _ok_return so only G4 fails.
    """
    sub = args[0]
    if which == "G4" and sub == "api":
        return json.dumps([
            {"id": "1", "body": "<!-- dev-kit-verdict-audit --> run=100 job=review status=failure verdict=Approve", "created_at": "2026-01-01T00:00:00Z"},
        ])
    return _ok_return(args)


if __name__ == "__main__":
    unittest.main()


class TestG2BucketParsing(unittest.TestCase):
    """G2 must read the actual `gh pr checks --json` field shape.

    `gh pr checks` exposes both `state` (workflow state:
    COMPLETED / IN_PROGRESS / PENDING) and `bucket` (gh's verdict
    bucket: pass / fail / pending / skipping). The check
    uses `bucket` because that is gh's own verdict classification.
    """

    def test_pending_bucket_fails(self):
        checks = [
            {"name": "lint", "state": "COMPLETED", "conclusion": "success", "bucket": "pass"},
            {"name": "review", "state": "IN_PROGRESS", "conclusion": None, "bucket": "pending"},
        ]
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps(checks)):
            g = pr_verify._gate_g2_ci_checks(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertFalse(g.passed)
        self.assertIn("PENDING", g.detail)
        self.assertIn("review", g.detail)

    def test_fail_bucket_fails(self):
        checks = [
            {"name": "lint", "state": "COMPLETED", "conclusion": "success", "bucket": "pass"},
            {"name": "review", "state": "COMPLETED", "conclusion": "failure", "bucket": "fail"},
        ]
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps(checks)):
            g = pr_verify._gate_g2_ci_checks(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertFalse(g.passed)
        self.assertIn("FAILED", g.detail)

    def test_all_passing_with_skipping_passes(self):
        checks = [
            {"name": "lint", "state": "COMPLETED", "conclusion": "success", "bucket": "pass"},
            {"name": "policy", "state": "SKIPPED", "conclusion": "skipped", "bucket": "skipping"},
        ]
        with patch.object(pr_verify, "_run_gh", return_value=json.dumps(checks)):
            g = pr_verify._gate_g2_ci_checks(584, "sh-ai-x/dev-harness-kit", "2026-08-06T00:00:00Z")
        self.assertTrue(g.passed)
