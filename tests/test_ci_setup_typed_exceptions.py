#!/usr/bin/env python3
"""test_ci_setup_typed_exceptions.py — Regression tests for issue #92.

Pins two bugs in `lib/ci_setup.py` where bare `except Exception: pass`
silently swallowed real failures:

1. `preflight_probe` line ~544 (`gh secret list` probe) — when gh is on
   PATH and authenticated but the `gh secret list` subprocess fails (rate
   limit, network error, GH API outage), the bare `except Exception: pass`
   leaves `secrets_json == ""`. Downstream code then reports every secret
   as "absent" — the user cannot distinguish "absent" from "unable to
   check". Misdiagnosis leads them to spend an hour wondering why CI keeps
   redacting their runs.

2. `_detect_owner_repo` line ~586 (`git remote get-url`) — when `git` is
   missing from PATH (CI container, minimal runner image), the bare
   `except Exception: pass` returns the empty string. The post-install
   checklist then prints literal `<OWNER>/<REPO>` placeholder text with
   no hint about why auto-detection failed. User pastes the placeholder
   into `gh secret set --repo ...` and gets rejected with no clue.

Fix: narrow both `except Exception: pass` clauses to typed exceptions
(`subprocess.SubprocessError`, `subprocess.TimeoutExpired`, `FileNotFoundError`,
`OSError`) and surface the degradation in the ProbeResult.detail /
_detect_owner_repo return value so the user sees the cause.

Pins:
1. `preflight_probe` MUST surface gh subprocess failures with a visible
   "degraded: <exception type>: <message>" detail, not silently fall
   through to "absent".
2. `_detect_owner_repo` MUST surface the auto-detect failure mode
   (e.g. "<OWNER>/<REPO> (auto-detect failed: FileNotFoundError)") instead
   of returning empty string.
3. `preflight_probe` MUST NOT crash on FileNotFoundError from subprocess
   (today the bare except catches it; tomorrow a narrower except must
   still cover FileNotFoundError because `gh` resolved via shutil.which
   but `git` may not).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class TestPreflightProbeGhSecretFailure(unittest.TestCase):
    """Bug 1: gh secret list failure must surface as a visible detail.

    When `gh secret list` raises (rate limit, network, GH API outage),
    the secrets probe must NOT silently report all secrets as "absent".
    The user must see WHY the probe degraded so they can distinguish
    "secret not configured" from "probe could not run".
    """

    def setUp(self):
        from lib import ci_setup
        self.ci_setup = ci_setup

    def test_preflight_surfaces_gh_secret_list_subprocess_failure(self):
        """When `gh secret list` raises subprocess.SubprocessError, the
        resulting ProbeResult rows for each secret must include a detail
        string that names the failure mode (e.g. contains 'degraded' or
        'unable to check' or the exception class name).
        """
        with mock.patch.object(self.ci_setup.shutil, "which", return_value="/usr/bin/gh"):
            def fake_run(args, **kwargs):
                # `gh auth status` → success
                if "auth" in args and "status" in args:
                    cp = mock.Mock()
                    cp.returncode = 0
                    cp.stdout = ""
                    cp.stderr = ""
                    return cp
                # `gh repo view` → success (otherwise preflight short-circuits
                # BEFORE the secret-list probe runs)
                if "repo" in args and "view" in args:
                    cp = mock.Mock()
                    cp.returncode = 0
                    cp.stdout = '{"name":"repo"}'
                    cp.stderr = ""
                    return cp
                # `gh secret list` → fail
                raise subprocess.SubprocessError(
                    "simulated gh secret list rate-limit"
                )

            with mock.patch.object(subprocess, "run", side_effect=fake_run):
                results = self.ci_setup.preflight_probe(repo="owner/repo")

        secret_labels = {
            "DEV_KIT_GITHUB_TOKEN set",
            "MINIMAX_API_KEY set",
            "ANTHROPIC_API_KEY set",
        }
        secret_results = [r for r in results if r.label in secret_labels]
        self.assertEqual(
            len(secret_results), 3,
            f"expected 3 secret probe results, got {[r.label for r in results]}",
        )
        for r in secret_results:
            detail_lower = r.detail.lower()
            self.assertTrue(
                "degraded" in detail_lower
                or "subprocesserror" in detail_lower,
                f"secret probe for {r.label!r} silently reported "
                f"detail={r.detail!r} — failure mode not surfaced "
                f"(issue #92 bug 1)",
            )

    def test_preflight_surfaces_gh_secret_list_timeout(self):
        """subprocess.TimeoutExpired on `gh secret list` must surface."""
        with mock.patch.object(self.ci_setup.shutil, "which", return_value="/usr/bin/gh"):
            def fake_run(args, **kwargs):
                if "auth" in args and "status" in args:
                    cp = mock.Mock()
                    cp.returncode = 0
                    cp.stdout = ""
                    cp.stderr = ""
                    return cp
                if "repo" in args and "view" in args:
                    cp = mock.Mock()
                    cp.returncode = 0
                    cp.stdout = '{"name":"repo"}'
                    cp.stderr = ""
                    return cp
                raise subprocess.TimeoutExpired(cmd="gh", timeout=10)

            with mock.patch.object(subprocess, "run", side_effect=fake_run):
                results = self.ci_setup.preflight_probe(repo="owner/repo")

        secret_results = [
            r for r in results
            if r.label in {
                "DEV_KIT_GITHUB_TOKEN set",
                "MINIMAX_API_KEY set",
                "ANTHROPIC_API_KEY set",
            }
        ]
        self.assertEqual(len(secret_results), 3)
        for r in secret_results:
            detail_lower = r.detail.lower()
            self.assertTrue(
                "timeouterror" in detail_lower
                or "degraded" in detail_lower,
                f"timeout probe for {r.label!r} silently reported "
                f"detail={r.detail!r} — must surface timeout "
                f"(issue #92 bug 1)",
            )


class TestDetectOwnerRepoFailure(unittest.TestCase):
    """Bug 2: missing git binary must surface in checklist.

    `_detect_owner_repo` returns "" when git is missing (FileNotFoundError
    on subprocess.run). The post-install checklist then prints literal
    "<OWNER>/<REPO>" placeholder with no hint. User copies the placeholder
    into gh CLI commands and gets rejected.

    Fix: the function must return a string that includes a marker like
    "(auto-detect failed: <ExceptionType>)" so the checklist can show
    "absent" with a hint.
    """

    def setUp(self):
        from lib import ci_setup
        self.ci_setup = ci_setup

    def test_detect_owner_repo_surfaces_filenotfound(self):
        """When git is missing (FileNotFoundError), the return value must
        include a degradation marker (not the empty string).
        """
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            with mock.patch.object(
                self.ci_setup.subprocess, "run",
                side_effect=FileNotFoundError("git not on PATH"),
            ):
                result = self.ci_setup._detect_owner_repo(target)
        self.assertNotEqual(
            result, "",
            f"_detect_owner_repo returned empty string on FileNotFoundError "
            f"instead of surfacing the failure mode (issue #92 bug 2). "
            f"Got: {result!r}",
        )
        # Must mention FileNotFoundError so the user sees the cause.
        self.assertIn(
            "FileNotFoundError", result,
            f"_detect_owner_repo degraded marker missing FileNotFoundError: "
            f"{result!r}",
        )
        # And must contain the literal "<OWNER>/<REPO>" so the checklist's
        # `.replace("<OWNER>/<REPO>", repo)` still substitutes the failure
        # hint into the rendered output.
        self.assertIn(
            "<OWNER>/<REPO>", result,
            f"_detect_owner_repo degraded marker must contain "
            f"<OWNER>/<REPO> literal so checklist rendering substitutes "
            f"the failure hint. Got: {result!r}",
        )

    def test_detect_owner_repo_surfaces_calledprocesserror(self):
        """When git remote fails (CalledProcessError), surface it."""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            err = subprocess.CalledProcessError(
                returncode=128, cmd=["git"], stderr="fatal: not a git repo",
            )
            with mock.patch.object(
                self.ci_setup.subprocess, "run", side_effect=err,
            ):
                result = self.ci_setup._detect_owner_repo(target)
        self.assertIn("CalledProcessError", result)
        self.assertIn("<OWNER>/<REPO>", result)

    def test_detect_owner_repo_surfaces_timeouterror(self):
        """When git remote times out (TimeoutExpired), surface it."""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            with mock.patch.object(
                self.ci_setup.subprocess, "run",
                side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5),
            ):
                result = self.ci_setup._detect_owner_repo(target)
        self.assertIn("TimeoutExpired", result)


class TestPreflightProbeDoesNotCrashOnMissingGit(unittest.TestCase):
    """Regression: the bare except in #92 also covered the case where git
    is missing from PATH but gh is present. The narrower except MUST still
    cover FileNotFoundError (since `subprocess.run(['git', ...])` raises
    FileNotFoundError when git is not installed).
    """

    def setUp(self):
        from lib import ci_setup
        self.ci_setup = ci_setup

    def test_preflight_does_not_raise_on_filenotfound(self):
        """preflight_probe MUST NOT raise even when git is missing
        (FileNotFoundError from subprocess.run). The typed-exception fix
        must keep FileNotFoundError in the catch list.
        """
        with mock.patch.object(self.ci_setup.shutil, "which", return_value="/usr/bin/gh"):
            def fake_run(args, **kwargs):
                if "auth" in args and "status" in args:
                    cp = mock.Mock()
                    cp.returncode = 0
                    cp.stdout = ""
                    cp.stderr = ""
                    return cp
                if "repo" in args and "view" in args:
                    cp = mock.Mock()
                    cp.returncode = 0
                    cp.stdout = '{"name":"repo"}'
                    cp.stderr = ""
                    return cp
                raise FileNotFoundError("git not on PATH (simulated)")

            with mock.patch.object(subprocess, "run", side_effect=fake_run):
                # MUST NOT raise.
                results = self.ci_setup.preflight_probe(repo="owner/repo")
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)


if __name__ == "__main__":
    unittest.main()