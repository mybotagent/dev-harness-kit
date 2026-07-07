#!/usr/bin/env python3
"""test_ci_local.py — regression tests for templates/ci/scripts/ci-local.sh.

The previous form was:
    REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null \\
                || cd \"$(dirname \"$0\")/..\" && pwd)"
    cd "$REPO_ROOT"

This silently broke on most setups. Bash parses `A || B && C`
as `(A || B) && C`, so `pwd` ran unconditionally and its
newline-terminated output concatenated with the toplevel path.
`cd "$REPO_ROOT"` then saw two args (the toplevel + the cwd)
and errored with "No such file or directory" on a path that
visually contained a newline.

Fix: scope the fallback in a subshell so the inner pwd stays
inside it. Tests cover the buggy + fixed forms so the regression
is caught if anyone reverts.

Scope note: ci-local.sh is a TEMPLATE that gets installed to
<consumer>/scripts/ci-local.sh via /dev-kit:ci-setup. It is NOT
meant to run in the dev-harness-kit source tree itself, so we
test the REPO_ROOT derivation in isolation (not the full script).
The full install is tested by tests/test_ci_setup.py.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "templates" / "ci" / "scripts" / "ci-local.sh"


def _run_minimal_repo(extra_lines: str, *, init_git: bool) -> subprocess.CompletedProcess:
    """Build a minimal repo + script that only echoes REPO_ROOT, then
    run it with `cwd=` set to the workspace. `init_git=False`
    simulates a non-git fallback path.

    Note: `cwd=` matters because subprocess inherits the parent's
    CWD. Without it, `git rev-parse` from inside the script would
    walk up from the parent's CWD (e.g. the worktree) and return
    the parent's toplevel, not the tempdir's. That would make the
    "git succeeds" path always run and the fallback path never
    trigger.
    """
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        if init_git:
            ws.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main", str(ws)],
                           check=True, capture_output=True)
        else:
            ws.mkdir(parents=True)
        (ws / "scripts").mkdir(exist_ok=True)
        script = ws / "scripts" / "ci-local.sh"
        script.write_text(
            "#!/usr/bin/env bash\n"
            "set -eo pipefail\n"
            f"{extra_lines}\n"
            'cd "$REPO_ROOT"\n'
            'echo "REPO_ROOT=$REPO_ROOT"\n'
        )
        script.chmod(0o755)
        return subprocess.run(
            ["bash", str(script)],
            capture_output=True, text=True, timeout=10,
            cwd=str(ws),  # CRITICAL: must pass cwd so git rev-parse sees the tempdir
        )


class TestRepoRootDerivation(unittest.TestCase):
    """The REPO_ROOT variable in ci-local.sh must be a single path
    (no embedded newlines) so `cd "$REPO_ROOT"` works."""

    BUGGY = 'REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || cd "$(dirname "$0")/.." && pwd)"'
    FIXED = 'REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "$0")/.." && pwd))"'

    def test_buggy_form_reproduces_within_git_repo(self):
        """The OLD form MUST still fail (regression lock — if this
        test ever starts passing, the bash version has changed and
        the fix may no longer be needed; investigate before
        removing)."""
        r = _run_minimal_repo(self.BUGGY, init_git=True)
        # The bug manifests as: rc != 0 (the cd fails) AND/OR a
        # multi-line REPO_ROOT value (the toplevel + the cwd
        # concatenated with a newline).
        rc_bad = r.returncode != 0
        if "REPO_ROOT=" in r.stdout:
            value = r.stdout.split("REPO_ROOT=", 1)[1].strip()
            nl_bad = "\n" in value
        else:
            nl_bad = False
        self.assertTrue(
            rc_bad or nl_bad,
            "buggy form should reproduce the REPO_ROOT bug; "
            "if this test starts failing, the bash version has changed "
            "and the fix may no longer be needed — investigate",
        )

    def test_fixed_form_works_within_git_repo(self):
        r = _run_minimal_repo(self.FIXED, init_git=True)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr}\nstdout={r.stdout}")
        self.assertIn("REPO_ROOT=", r.stdout)
        value = r.stdout.split("REPO_ROOT=", 1)[1].strip()
        self.assertNotIn("\n", value,
                         f"REPO_ROOT contains a newline (the bug): {value!r}")
        # Inside a git repo, REPO_ROOT must be the toplevel.
        # /tmp/.../ws is the workspace we just created.
        self.assertTrue(
            value.endswith("/ws") or "/private" in value and value.endswith("/ws"),
            f"REPO_ROOT should be the workspace toplevel, got: {value!r}",
        )

    def test_fixed_form_falls_back_outside_git_repo(self):
        """When the script runs from a non-git directory, the
        fallback (cd to parent of $0, then pwd) must produce a
        clean single-line path."""
        r = _run_minimal_repo(self.FIXED, init_git=False)
        self.assertEqual(r.returncode, 0, f"stderr={r.stderr}\nstdout={r.stdout}")
        value = r.stdout.split("REPO_ROOT=", 1)[1].strip()
        self.assertNotIn("\n", value,
                         f"REPO_ROOT contains a newline: {value!r}")
        # Outside a git repo, REPO_ROOT = parent of $0's dir (= /ws).
        # The /tmp path may be /tmp/... or /private/tmp/... on macOS.
        self.assertTrue(
            value.endswith("/ws"),
            f"REPO_ROOT should end with /ws (parent of scripts/), got: {value!r}",
        )


class TestTemplateShape(unittest.TestCase):
    """The shipped templates/ci/scripts/ci-local.sh has the correct
    REPO_ROOT form. These are text-level checks; runtime checks are
    covered by tests/test_ci_setup.py (full install + run)."""

    @classmethod
    def setUpClass(cls):
        if not SCRIPT.exists():
            raise unittest.SkipTest(f"ci-local.sh not found: {SCRIPT}")

    def test_template_uses_subshell_scoped_fallback(self):
        """The template must use the subshell-scoped fallback form
        (cd ... && pwd inside a ( ... ) group), NOT the buggy
        `(git || cd ...) && pwd` which concatenates two stdout
        paths with a newline."""
        text = SCRIPT.read_text()
        # Match: REPO_ROOT="$(git rev-parse ... || (cd "$(...) ..." && pwd))"
        # The double-double-quotes inside make a simple regex brittle,
        # so we look for the structural markers instead:
        #   - "|| (cd "    (subshell opener)
        #   - "&& pwd))"  (subshell closer)
        self.assertRegex(
            text, r"REPO_ROOT=.*\|\| \(cd",
            "ci-local.sh must use '|| (cd ...' (subshell-scoped fallback)",
        )
        self.assertRegex(
            text, r"&& pwd\)\)\"",
            "ci-local.sh must close the subshell: '&& pwd))'",
        )

    def test_template_does_not_have_buggy_form(self):
        text = SCRIPT.read_text()
        # The buggy form would have: `|| cd "..." && pwd)"`  (no inner parens)
        self.assertNotRegex(
            text, r"\|\| cd \"[^\"]*\"\) && pwd\)",
            "ci-local.sh still has the buggy form (no subshell grouping)",
        )

    def test_all_scripts_in_templates_have_fixed_form(self):
        """PR #30's review caught the SAME bug in templates/ci/scripts/test.sh.
        Defensive: scan every shell script in templates/ for the buggy
        pattern. If anyone re-introduces it, the test fires."""
        import glob
        for f in glob.glob(str(REPO_ROOT / "templates" / "ci" / "scripts" / "*.sh")) + \
                 glob.glob(str(REPO_ROOT / "templates" / "ci" / ".githooks" / "pre-push")):
            text = Path(f).read_text()
            self.assertNotRegex(
                text, r"\|\| cd \"[^\"]*\"\) && pwd\)",
                f"{f} still has the buggy form (no subshell grouping)",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)