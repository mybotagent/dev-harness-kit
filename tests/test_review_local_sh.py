"""test_review_local_sh.py — shell-level tests for bin/review-local.sh.

The script is the local equivalent of `.github/workflows/review.yml`
(provider switch + verdict extraction + combined gate + L3-evidence
gate + optional auto-approve). These tests are deliberately hermetic:
they shell out to the script with `--help` and the bare-minimum argv
that fails BEFORE any `gh` / `claude` / network call. End-to-end
smoke tests against a real PR are run manually (the script's
interactive loop calls `claude -p` which isn't exercisable in CI).

Coverage:
  - bash -n syntax check (catches shell parse errors).
  - --help prints the documented usage block.
  - Missing --pr exits non-zero with an error.
  - Non-numeric --pr exits non-zero with an error.
  - Unknown flag exits non-zero with --help hint.
  - The script is executable (mode includes the +x bit).
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SCRIPT = PROJECT_ROOT / "bin" / "review-local.sh"


def _run(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=check,
    )


class TestReviewLocalShell(unittest.TestCase):
    def test_script_exists(self) -> None:
        self.assertTrue(SCRIPT.exists(), f"missing script: {SCRIPT}")

    def test_script_is_executable(self) -> None:
        mode = SCRIPT.stat().st_mode
        self.assertTrue(
            mode & 0o111,
            f"bin/review-local.sh must be executable (mode={oct(mode)})",
        )

    def test_bash_n_syntax_check(self) -> None:
        """`bash -n` parses the script without executing anything. Catches
        shell grammar errors that would otherwise surface only at the
        first real invocation.
        """
        r = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_help_prints_usage(self) -> None:
        r = _run("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        # Header must name the script.
        self.assertIn("review-local.sh", r.stdout)
        # Documented flags must appear in the help block.
        for flag in (
            "--pr",
            "--provider",
            "--auto-approve",
            "--review-only",
            "--security-only",
            "--maintenance-only",
            "--dry-run",
            "--no-touch-probe",
        ):
            self.assertIn(flag, r.stdout, f"--help missing flag {flag}")

    def test_help_short_flag_also_works(self) -> None:
        r = _run("-h")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("review-local.sh", r.stdout)

    def test_missing_pr_exits_nonzero(self) -> None:
        """Bare invocation -- no --pr -- must fail fast with a clear
        error pointing at --pr.
        """
        r = _run()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--pr", r.stderr)

    def test_non_numeric_pr_exits_nonzero(self) -> None:
        r = _run("--pr", "abc")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("numeric", r.stderr)

    def test_unknown_flag_exits_nonzero(self) -> None:
        r = _run("--pr", "1", "--no-such-flag")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--help", r.stderr)

    def test_short_help_does_not_invoke_gh(self) -> None:
        """Sanity: --help must exit before any gh / python call. The
        script reaches the `usage` block at argparse-time, so no
        subprocess is spawned. This is a contract test: a regression
        that defers --help past the provider-resolution block would
        fail (or hang) in CI where gh is unauthenticated.
        """
        r = _run("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        # No "gh" or "python" in stderr — argv-only path.
        self.assertNotIn("gh ", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
