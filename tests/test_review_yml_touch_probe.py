"""test_review_yml_touch_probe.py — static regression guard for the
`scope` job's touch-probe regex in `.github/workflows/review.yml`.

Discovered live (2026-08-11): the touch-probe regex used to decide
`touches_prod` — which gates whether the expensive `/dev-kit:review`
and `/dev-kit:security` LLM-judge jobs even run in CI — was missing
`bin/` and `commands/` from its production-root list, even though
`bin/review-local.sh`'s OWN internal touch-probe regex (used for the
local `--auto-approve` L3-evidence gate) already includes both. A PR
that ONLY touches `bin/*.sh` or `commands/*.md` was silently
classified as "docs/infra-only", so the LLM review + security jobs
never ran in GH-Actions at all (no review comments posted -- observed
against a real PR).

These tests are deliberately static (grep the YAML text directly)
rather than spinning up an actual workflow run — GH-Actions jobs
aren't unit-testable in this repo's suite, so a content-level
regression guard is the practical alternative. Mirrors the style of
tests/test_review_local_sh.py::TestLocalAuthFallback's static
no-bashism check.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
REVIEW_YML = PROJECT_ROOT / ".github" / "workflows" / "review.yml"

# The canonical, already-correct list lives in bin/review-local.sh's
# own touch-probe regex. review.yml's scope job MUST match it exactly
# so "does this PR touch production code" means the same thing in
# both the local and CI code paths.
CANONICAL_ROOTS = (
    "bin", "commands", "lib", "tools", "hooks", "skills",
    "\\.githooks", "\\.claude", "\\.codex", "\\.github",
)


class TestReviewYmlTouchProbeRootsMatchCanonical(unittest.TestCase):
    def setUp(self) -> None:
        self.text = REVIEW_YML.read_text(encoding="utf-8")

    def test_review_yml_exists(self) -> None:
        self.assertTrue(REVIEW_YML.exists(), f"missing: {REVIEW_YML}")

    def test_scope_job_touch_probe_regex_includes_bin(self) -> None:
        """The scope job's grep -E pattern must include `bin` -- a PR
        touching only bin/*.sh scripts must be classified as
        production code."""
        m = re.search(r"grep -E '\^\(([^)]+)\)/'", self.text)
        self.assertIsNotNone(m, "could not find the scope job's grep -E touch-probe pattern")
        roots = m.group(1).split("|")
        self.assertIn("bin", roots, f"touch-probe pattern missing 'bin': {roots}")

    def test_scope_job_touch_probe_regex_includes_commands(self) -> None:
        m = re.search(r"grep -E '\^\(([^)]+)\)/'", self.text)
        self.assertIsNotNone(m, "could not find the scope job's grep -E touch-probe pattern")
        roots = m.group(1).split("|")
        self.assertIn("commands", roots, f"touch-probe pattern missing 'commands': {roots}")

    def test_scope_job_touch_probe_regex_matches_canonical_set(self) -> None:
        """Full parity check against bin/review-local.sh's already-
        correct list -- catches ANY future drift, not just bin/commands.
        """
        m = re.search(r"grep -E '\^\(([^)]+)\)/'", self.text)
        self.assertIsNotNone(m, "could not find the scope job's grep -E touch-probe pattern")
        roots = set(m.group(1).split("|"))
        expected = set(CANONICAL_ROOTS)
        self.assertEqual(
            roots, expected,
            f"review.yml scope-job roots {sorted(roots)} != canonical "
            f"{sorted(expected)} (source of truth: bin/review-local.sh's "
            f"own touch-probe regex)",
        )

    def test_docs_infra_only_message_mentions_bin_and_commands(self) -> None:
        """The human-readable messages that ENUMERATE the production
        roots (not the short "::notice::...advisory here" summary
        line) should stay consistent with the regex they describe -- a
        silent drift here is a documentation bug, not a functional
        one, but it misleads operators debugging a skipped review job.
        """
        occurrences = [
            line for line in self.text.splitlines()
            if "echo" in line and (
                "no bin/commands/lib" in line or "did not touch" in line
            )
        ]
        self.assertTrue(
            occurrences,
            "expected at least one path-enumerating 'docs/infra-only' message",
        )
        for line in occurrences:
            self.assertIn("bin", line, f"message doesn't mention bin/: {line!r}")
            self.assertIn("commands", line, f"message doesn't mention commands/: {line!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
