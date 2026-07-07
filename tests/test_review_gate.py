#!/usr/bin/env python3
"""test_review_gate.py — Regression tests for the verdict-extraction regex in
templates/ci/.github/workflows/review.yml (and its sibling
.github/workflows/review.yml).

Background
----------
The severity-gate pipeline extracts the verdict from `claude[bot]` PR
comments via:

    gh api .../issues/${PR}/comments --jq '.[] | ... | .body' \\
      | grep -E '\\*\\*Verdict:\\*\\*' | tail -1 \\
      | grep -oE '\\*\\*Verdict:\\*\\*\\s*(Approve|Blocked|Changes Requested)' \\
      | sed -E 's/.*\\*\\*Verdict:\\*\\*[[:space:]]*//'

The bug
-------
`grep -E '\\*\\*Verdict:\\*\\*'` matches the substring `**Verdict:**`
anywhere on a line. When the agent's prose references the keyword
mid-sentence (a common phrasing in /dev-kit:review output), `tail -1`
picks that prose line instead of the verdict-line declaration. The
next filter then finds no match, the pipeline returns empty, and the
severity gate exits 1 with `Missing verdict`.

The fix
-------
Anchor the regex with `^` so only verdict-line declarations match.
This file asserts both the regex semantics and the on-disk byte shape
of the two review.yml files.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
TEMPLATE_REVIEW_YML = REPO_ROOT / "templates" / "ci" / ".github" / "workflows" / "review.yml"
OWN_REVIEW_YML = REPO_ROOT / ".github" / "workflows" / "review.yml"

ANCHORED = re.compile(r"^\*\*Verdict:\*\*\s*(Approve|Blocked|Changes Requested)")
UNANCHORED_LITERAL = r"grep -E '\*\*Verdict:\*\*'"


class TestVerdictRegex(unittest.TestCase):
    """Pure-regex semantics."""

    def test_matches_anchored_header(self):
        body = "**Verdict:** Approve\n\nrest of summary"
        self.assertEqual(ANCHORED.findall(body), ["Approve"])

    def test_ignores_prose_substring(self):
        body = "the reviewer noted **Verdict:** here is mid-sentence"
        self.assertEqual(ANCHORED.findall(body), [])

    def test_grep_tail_1_picks_last_header(self):
        body = (
            "**Verdict:** Approve\n"
            "prose with **Verdict:** in middle\n"
            "**Verdict:** Blocked\n"
        )
        last = [ln for ln in body.splitlines() if ANCHORED.match(ln)][-1]
        self.assertIn("Blocked", ANCHORED.findall(last))

    def test_handles_all_three_values(self):
        for v in ("Approve", "Blocked", "Changes Requested"):
            self.assertEqual(ANCHORED.findall(f"**Verdict:** {v}"), [v])

    def test_handles_crlf(self):
        body = "**Verdict:** Approve\r\n\r\nrest"
        last = [ln for ln in body.splitlines() if ANCHORED.match(ln)][-1]
        self.assertEqual(ANCHORED.findall(last), ["Approve"])

    def test_no_leading_whitespace_match(self):
        self.assertEqual(ANCHORED.findall("   **Verdict:** Approve"), [])


class TestReviewYmlAnchoring(unittest.TestCase):
    """Both review.yml files MUST use the anchored regex at the
    verdict-extraction step, and MUST NOT contain the unanchored form.
    """

    TARGETS = (TEMPLATE_REVIEW_YML, OWN_REVIEW_YML)

    def _verdict_grep_lines(self, path: Path) -> list:
        return [
            ln for ln in path.read_text().splitlines()
            if "Verdict" in ln and "grep -E" in ln
        ]

    def test_template_uses_anchored_regex(self):
        self.assertTrue(TEMPLATE_REVIEW_YML.exists(), f"missing: {TEMPLATE_REVIEW_YML}")
        lines = self._verdict_grep_lines(TEMPLATE_REVIEW_YML)
        self.assertTrue(lines, f"no Verdict grep step in {TEMPLATE_REVIEW_YML}")
        for ln in lines:
            self.assertIn(
                r"grep -E '^\*\*Verdict:\*\*'", ln,
                f"unanchored Verdict grep in template: {ln!r}",
            )
            self.assertNotIn(
                UNANCHORED_LITERAL, ln,
                f"unanchored literal in template: {ln!r}",
            )

    def test_own_workflow_uses_anchored_regex(self):
        if not OWN_REVIEW_YML.exists():
            self.skipTest(f"missing: {OWN_REVIEW_YML}")
        lines = self._verdict_grep_lines(OWN_REVIEW_YML)
        self.assertTrue(lines, f"no Verdict grep step in {OWN_REVIEW_YML}")
        for ln in lines:
            self.assertIn(
                r"grep -E '^\*\*Verdict:\*\*'", ln,
                f"unanchored Verdict grep in own workflow: {ln!r}",
            )
            self.assertNotIn(
                UNANCHORED_LITERAL, ln,
                f"unanchored literal in own workflow: {ln!r}",
            )

    def test_template_and_own_share_verdict_grep_lines(self):
        """Verdict-extraction grep lines MUST be byte-equal between the two
        files. Drift here means a fix landed in one but not the other.

        Only the verdict-grep lines are compared — the rest of the workflow
        can legitimately diverge (e.g., workflow_dispatch validation logic
        differs between self-install and consumer-install).
        """
        pairs = []
        for p in self.TARGETS:
            if not p.exists():
                self.skipTest(f"missing: {p}")
            pairs.append((p, self._verdict_grep_lines(p)))
        if len(pairs) < 2:
            self.skipTest("only one review.yml present")
        (p1, lines1), (p2, lines2) = pairs
        self.assertEqual(
            lines1, lines2,
            f"verdict-grep lines drifted between {p1} and {p2}",
        )


if __name__ == "__main__":
    unittest.main()
