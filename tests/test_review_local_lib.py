"""test_review_local_lib.py — behavioural tests for lib/review_local_lib.sh.

The library is sourced by `bin/review-local.sh` (and is the only
source of truth for `rank()`, `is_bump_pr()`, `extract_pytest_tail()`,
`provider_env_for()`, and `verdict_default_for()`). Each test runs
the helper in a fresh subshell so the assertions stay hermetic and
order-independent.

Coverage:
  rank()
    T25: Approve -> 0
    T26: Changes Requested -> 1
    T27: Blocked -> 2
    T28: Unknown verdict -> 99 (PARSE_FAILED guard)
    T29: empty -> 99
    T30: worst-of loop ranks highest correctly
  is_bump_pr()
    T31: matches `chore(release): bump dev-kit to v0.3.239` -> yes
    T32: matches `chore(release): bump dev-kit to v` -> yes (prefix)
    T33: arbitrary title -> no
    T34: empty -> no
  extract_pytest_tail()
    T35: `47 passed in 1.23s` -> yes
    T36: `3 failed, 1 xfailed in 0.50s` -> yes
    T37: no test output -> no
    T38: random prose with "passed" -> no (no number anchor)
  provider_env_for()
    T39: minimax -> five lines, correct base URL
    T40: deepseek -> five lines, correct base URL
    T41: anthropic -> empty
    T42: unknown -> exit 1
  verdict_default_for()
    T43: empty -> yes (default to Approve)
    T44: Approve -> no
    T45: Blocked -> no
"""
from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
LIB = REPO_ROOT / "lib" / "review_local_lib.sh"


def _bash(code: str) -> subprocess.CompletedProcess:
    """Run `code` in a fresh bash that has lib/review_local_lib.sh sourced."""
    return subprocess.run(
        ["bash", "-c", textwrap.dedent(code)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class TestRank(unittest.TestCase):
    def test_approve_is_zero(self) -> None:
        r = _bash("source lib/review_local_lib.sh; rank Approve")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "0"))

    def test_changes_requested_is_one(self) -> None:
        r = _bash("source lib/review_local_lib.sh; rank 'Changes Requested'")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "1"))

    def test_blocked_is_two(self) -> None:
        r = _bash("source lib/review_local_lib.sh; rank Blocked")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "2"))

    def test_unknown_is_99(self) -> None:
        """Unknown / PARSE_FAILED must sort above every known verdict so
        the worst-of loop surfaces a hard fail, not a silent approve.
        """
        r = _bash("source lib/review_local_lib.sh; rank PARSE_FAILED")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "99"))

    def test_empty_is_99(self) -> None:
        r = _bash("source lib/review_local_lib.sh; rank ''")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "99"))

    def test_worst_of_loop_picks_highest_rank(self) -> None:
        """The combined gate iterates `rank "$V"` and keeps the highest.
        Mirror that pattern here to prove rank() composes correctly.
        """
        r = _bash(
            """
            source lib/review_local_lib.sh
            WORST='Approve'; VR=0
            for V in 'Approve' 'Changes Requested' 'Blocked' 'Approve'; do
              R=$(rank "$V")
              if [ "$R" -gt "$VR" ]; then VR=$R; WORST=$V; fi
            done
            printf '%s (%d)' "$WORST" "$VR"
            """
        )
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "Blocked (2)"))


class TestIsBumpPr(unittest.TestCase):
    def test_typical_bump_title_matches(self) -> None:
        r = _bash("source lib/review_local_lib.sh; is_bump_pr 'chore(release): bump dev-kit to v0.3.239'")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "yes"))

    def test_bump_prefix_alone_matches(self) -> None:
        """`is_bump_pr` is prefix-based; an in-progress bump-PR title that
        hasn't been finalized yet still matches the auto-skip.
        """
        r = _bash("source lib/review_local_lib.sh; is_bump_pr 'chore(release): bump dev-kit to v'")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "yes"))

    def test_non_bump_title_does_not_match(self) -> None:
        r = _bash("source lib/review_local_lib.sh; is_bump_pr 'feat(ci): add local CI mode'")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "no"))

    def test_empty_does_not_match(self) -> None:
        r = _bash("source lib/review_local_lib.sh; is_bump_pr ''")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "no"))


class TestExtractPytestTail(unittest.TestCase):
    def test_standard_pass_tail_matches(self) -> None:
        body = "Some prose\n\n47 passed in 1.23s\n"
        r = _bash(f"source lib/review_local_lib.sh; extract_pytest_tail {shq(body)}")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "yes"))

    def test_failed_with_xfailed_tail_matches(self) -> None:
        body = "Some prose\n\n3 failed, 1 xfailed in 0.50s\n"
        r = _bash(f"source lib/review_local_lib.sh; extract_pytest_tail {shq(body)}")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "yes"))

    def test_no_test_output_does_not_match(self) -> None:
        body = "Some prose without any test line"
        r = _bash(f"source lib/review_local_lib.sh; extract_pytest_tail {shq(body)}")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "no"))

    def test_random_prose_with_word_passed_does_not_match(self) -> None:
        """The regex anchors on a digit; 'I passed the exam' must not
        trigger the gate. Catches the previous LLM-judge finding that
        a crafted PR body could spoof the L3 regex.
        """
        body = "I passed the exam; nothing to test here."
        r = _bash(f"source lib/review_local_lib.sh; extract_pytest_tail {shq(body)}")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "no"))


class TestProviderEnvFor(unittest.TestCase):
    def test_minimax_emits_five_lines_with_correct_base_url(self) -> None:
        r = _bash("source lib/review_local_lib.sh; provider_env_for minimax")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[0], "ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic")
        # The MiniMax model id includes `[1m]`; quote-escape is irrelevant
        # because bash preserves the literal text from the heredoc.
        self.assertIn("ANTHROPIC_MODEL=", lines[1])

    def test_deepseek_emits_five_lines_with_correct_base_url(self) -> None:
        r = _bash("source lib/review_local_lib.sh; provider_env_for deepseek")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[0], "ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic")

    def test_anthropic_emits_no_env_overrides(self) -> None:
        """Anthropic uses its default base URL; no MODEL override is
        emitted. The empty-output contract is what `claude -p` expects.
        """
        r = _bash("source lib/review_local_lib.sh; provider_env_for anthropic")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "")

    def test_unknown_provider_exits_nonzero(self) -> None:
        r = _bash("source lib/review_local_lib.sh; provider_env_for nonsense")
        self.assertNotEqual(r.returncode, 0)


class TestVerdictDefaultFor(unittest.TestCase):
    def test_empty_returns_yes(self) -> None:
        """Missing/empty verdict triggers the default-to-Approve path
        (mirrors review.yml:521-522).
        """
        r = _bash('source lib/review_local_lib.sh; verdict_default_for ""')
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "yes"))

    def test_approve_returns_no(self) -> None:
        r = _bash("source lib/review_local_lib.sh; verdict_default_for Approve")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "no"))

    def test_blocked_returns_no(self) -> None:
        r = _bash("source lib/review_local_lib.sh; verdict_default_for Blocked")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "no"))


def shq(s: str) -> str:
    """Single-quote a string for safe inclusion in a bash command line."""
    return "'" + s.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    unittest.main(verbosity=2)
