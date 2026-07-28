#!/usr/bin/env python3
"""test_maintenance_gate.py — RED-first tests for lib/maintenance_gate.py.

The maintenance gate runs in CI (`.github/workflows/maintenance.yml`)
and has two checks beyond the LLM judge's verdict:

  1. Verdict extraction — parse the `**Verdict:** ...` line from the
     claude-code-action's PR comment, matching review.yml's pattern.
  2. Docs-updated check — ensure the PR touches both a code path under
     `lib/` / `tools/` / `hooks/` / `skills/` / `.githooks/` AND at
     least one file under `docs/` (excluding auto-managed docs).

These two checks live in `lib/maintenance_gate.py` so they can be unit
tested without spinning up GitHub Actions. The workflow YAML invokes
the same module via `python3 -m lib.maintenance_gate ...`.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import maintenance_gate  # noqa: E402


class TestExtractVerdict(unittest.TestCase):
    """The verdict-extraction mirrors `scripts/extract-verdict` from
    review.yml's pattern: pick the last `**Verdict:** ...` line.
    """

    def test_extract_approve(self):
        body = "lots of prose\n\n**Verdict:** Approve\n\nmore prose"
        self.assertEqual(maintenance_gate.extract_verdict(body), "Approve")

    def test_extract_changes_requested(self):
        body = "**Verdict:** Changes Requested"
        self.assertEqual(maintenance_gate.extract_verdict(body), "Changes Requested")

    def test_extract_blocked(self):
        body = "**Verdict:** Blocked"
        self.assertEqual(maintenance_gate.extract_verdict(body), "Blocked")

    def test_extract_returns_last_when_multiple(self):
        body = (
            "**Verdict:** Approve\n"
            "Some chatter...\n"
            "**Verdict:** Changes Requested\n"
        )
        # The CI gate picks the most recent verdict (last match wins)
        # so an auto-fix-updated comment supersedes an earlier one.
        self.assertEqual(maintenance_gate.extract_verdict(body), "Changes Requested")

    def test_extract_returns_empty_on_no_verdict(self):
        self.assertEqual(maintenance_gate.extract_verdict("no verdict here"), "")

    def test_extract_ignores_lowercase(self):
        # Strict format: must be `**Verdict:** <Word>`. Lowercase is
        # not a valid verdict — gate tolerates this as no-verdict.
        self.assertEqual(maintenance_gate.extract_verdict("**verdict:** approve"), "")


class TestDocsUpdatedCheck(unittest.TestCase):
    """The docs-updated sub-gate logic."""

    def test_passes_when_no_prod_change(self):
        # PR only touches docs/ — no code change, no docs update needed.
        ok, reason = maintenance_gate.docs_updated_ok(
            changed_files=["docs/STAGES.md"],
            pr_body="",
        )
        self.assertTrue(ok, reason)

    def test_passes_when_prod_change_has_matching_docs(self):
        ok, reason = maintenance_gate.docs_updated_ok(
            changed_files=["lib/foo.py", "docs/foo.md"],
            pr_body="",
        )
        self.assertTrue(ok, reason)

    def test_fails_when_prod_change_lacks_docs(self):
        ok, reason = maintenance_gate.docs_updated_ok(
            changed_files=["lib/foo.py"],
            pr_body="",
        )
        self.assertFalse(ok)
        self.assertIn("lib/foo.py", reason)

    def test_passes_when_prod_change_justified_in_pr_body(self):
        # PR body quotes a pre-existing doc as justification.
        ok, reason = maintenance_gate.docs_updated_ok(
            changed_files=["lib/foo.py"],
            pr_body=(
                "Refs #42.\n\n"
                "docs-not-required: docs/foo.md already covers this behavior.\n"
            ),
        )
        self.assertTrue(ok, reason)

    def test_passes_for_tools_change_with_docs(self):
        ok, reason = maintenance_gate.docs_updated_ok(
            changed_files=["tools/foo.py", "docs/tools.md"],
            pr_body="",
        )
        self.assertTrue(ok, reason)

    def test_fails_for_skills_change_without_docs(self):
        ok, reason = maintenance_gate.docs_updated_ok(
            changed_files=["skills/foo/SKILL.md"],
            pr_body="",
        )
        # skills/ changes ARE prod changes (a skill ships with the
        # plugin and should be paired with a docs/skills/* doc).
        self.assertFalse(ok)

    def test_auto_managed_docs_dont_count(self):
        # STAGES.md and REPOSITORY-MAP.md are auto-managed and don't
        # count as "doc updates" — verify a PR that touches ONLY those
        # but no other docs file still fails when it also touches prod.
        ok, reason = maintenance_gate.docs_updated_ok(
            changed_files=["lib/foo.py", "docs/STAGES.md"],
            pr_body="",
        )
        self.assertFalse(ok)

    def test_hooks_change_with_docs_passes(self):
        ok, reason = maintenance_gate.docs_updated_ok(
            changed_files=[".githooks/pre-push", "docs/hooks.md"],
            pr_body="",
        )
        self.assertTrue(ok, reason)


class TestCombinedVerdictDerivation(unittest.TestCase):
    """The gate combines (judge_verdict, docs_ok) into a single CI
    verdict. Pure-function logic, no IO.
    """

    def test_approve_with_docs_passes(self):
        outcome = maintenance_gate.combine_verdict(
            judge_verdict="Approve",
            docs_ok=True,
            docs_reason="ok",
        )
        self.assertEqual(outcome["verdict"], "Approve")
        self.assertTrue(outcome["docs_ok"])

    def test_approve_without_docs_fails(self):
        outcome = maintenance_gate.combine_verdict(
            judge_verdict="Approve",
            docs_ok=False,
            docs_reason="lib/foo.py missing docs",
        )
        self.assertEqual(outcome["verdict"], "Changes Requested")
        self.assertFalse(outcome["docs_ok"])
        self.assertIn("lib/foo.py", outcome["reason"])

    def test_blocked_short_circuits(self):
        # Even with perfect docs, a Blocked judge is Blocked.
        outcome = maintenance_gate.combine_verdict(
            judge_verdict="Blocked",
            docs_ok=True,
            docs_reason="ok",
        )
        self.assertEqual(outcome["verdict"], "Blocked")


class TestCLISubprocess(unittest.TestCase):
    """End-to-end CLI invocation parity — the workflow calls the
    gate via `python3 -m lib.maintenance_gate ...` so we exercise that
    path here too.
    """

    def test_cli_extract_verdict(self):
        py = sys.executable
        result = subprocess.run(
            [py, "-m", "lib.maintenance_gate",
             "--project-root", tempfile.mkdtemp(),
             "--extract-verdict-from-stdin"],
            input="**Verdict:** Approve\n",
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Approve")

    def test_cli_docs_check_passes(self):
        py = sys.executable
        result = subprocess.run(
            [py, "-m", "lib.maintenance_gate",
             "--project-root", tempfile.mkdtemp(),
             "--docs-check",
             "--changed-files", "lib/foo.py",
             "--changed-files", "docs/foo.md",
             "--pr-body", ""],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["docs_ok"], True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
