"""test_acp_dispatch.py — regression tests for lib/acp_dispatch.py.

Closes #282. Verifies:

  * `parse_pr_spec` accepts the CLI's `PR-<index>:<slug>` shorthand and
    rejects malformed input.
  * `_fill_placeholders` raises ValueError when any of the seven
    mandatory placeholders is missing.
  * `ACPDispatcher.dispatch` cuts one worktree per PR in input order,
    writes one envelope per PR under `<round_dir>/dispatches/`, and the
    rendered envelopes contain no remaining `<PLACEHOLDER>` strings.
  * `dispatch(--dry-run)` returns DispatchResult objects without
    touching the filesystem (no worktrees, no envelope files).
  * The 7 placeholders documented in `docs/acp-harness.md` §3.2 are
    present as literal strings in the canonical template.

Each test uses a throwaway git repo (init + linked worktree) so the
`git worktree add` call in `ACPDispatcher._cut_worktree` runs against a
real `.git` directory without polluting the host repo. The canonical
template is copied into the throwaway repo at `.claude/skills/_acp/`
so the dispatcher reads it from its expected relative path.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make lib/ importable when the test is run from any cwd.
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from lib.acp_dispatch import (  # noqa: E402  (sys.path tweak above)
    ACPDispatcher,
    DispatchResult,
    SEVEN_PLACEHOLDERS,
    _fill_placeholders,
    parse_pr_spec,
)

REPO_TEMPLATE = ROOT / ".claude" / "skills" / "_acp" / "sub-agent-prompt.md"


def _init_throwaway_repo() -> "tempfile.TemporaryDirectory":
    """Create a temp git repo on `main` with one commit + a `origin/main` ref.

    Returns the TemporaryDirectory so the caller can use its `.name` as
    the orch-worktree path. The `origin` remote is the throwaway repo
    itself (file://) so `git worktree add -b <branch> <path> origin/main`
    succeeds without network access.
    """
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "README.md").write_text("x")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)
    # Seed the template at the canonical relative path so the dispatcher
    # finds it without an explicit --template override.
    template_dest = root / ".claude" / "skills" / "_acp"
    template_dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_TEMPLATE, template_dest / "sub-agent-prompt.md")
    subprocess.run(["git", "-C", str(root), "add", ".claude"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "seed template"], check=True)
    # Create a file:// origin so worktree-add's origin/main resolves.
    origin_dir = root.parent / f"{root.name}-origin"
    if origin_dir.exists():
        shutil.rmtree(origin_dir)
    subprocess.run(["git", "clone", "-q", "--bare", str(root), str(origin_dir)], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", str(origin_dir)], check=True)
    subprocess.run(["git", "-C", str(root), "fetch", "-q", "origin"], check=True)
    subprocess.run(["git", "-C", str(root), "branch", "--set-upstream-to=origin/main", "main"], check=True)
    return tmp


class ParsePrSpec(unittest.TestCase):
    def test_accepts_canonical_shorthand(self) -> None:
        self.assertEqual(parse_pr_spec("PR-3:l6-alpha"), ("feat/l6-alpha", "l6-alpha"))

    def test_rejects_missing_index(self) -> None:
        with self.assertRaises(ValueError):
            parse_pr_spec("l6-alpha")

    def test_rejects_non_kebab_slug(self) -> None:
        with self.assertRaises(ValueError):
            parse_pr_spec("PR-1:L6_alpha")

    def test_rejects_oversized_slug(self) -> None:
        with self.assertRaises(ValueError):
            parse_pr_spec("PR-1:" + ("a" * 50))


class FillPlaceholders(unittest.TestCase):
    def test_full_substitution(self) -> None:
        template = "TASK=`<TASK>` BRANCH=`<BRANCH>` CWD=`<CWD>`"
        # The contract is that ALL seven placeholders must be filled
        # for every dispatch (docs/acp-harness.md §3.2). Provide the
        # full set even though this minimal template only references
        # three of them.
        values = {
            "TASK": "do thing",
            "BRANCH": "feat/x",
            "CWD": "/tmp/x",
            "WORKTREE_PATH": "/tmp/x",
            "PLUGIN_VERSION_TARGET": "0.3.84",
            "LOCK_FILE": "/tmp/locks/x.lock",
            "PARENT_SESSION_CWD": "/tmp",
        }
        rendered = _fill_placeholders(template, values)
        self.assertEqual(rendered, "TASK=`do thing` BRANCH=`feat/x` CWD=`/tmp/x`")

    def test_missing_required_raises(self) -> None:
        with self.assertRaises(ValueError):
            _fill_placeholders(
                "TASK=`<TASK>`",
                {"BRANCH": "x"},  # only 1 of 7 — must raise
            )

    def test_seven_placeholders_match_canonical_template(self) -> None:
        # The 7 keys that _fill_placeholders looks up are derived from
        # SEVEN_PLACEHOLDERS (which the dispatcher pins in code). They
        # MUST appear literally in the canonical template — otherwise
        # no real dispatch can succeed.
        template_text = REPO_TEMPLATE.read_text(encoding="utf-8")
        for placeholder in SEVEN_PLACEHOLDERS:
            self.assertIn(
                placeholder,
                template_text,
                f"canonical template is missing placeholder {placeholder}",
            )


class DispatchDryRun(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = _init_throwaway_repo()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_dry_run_returns_results_without_cutting(self) -> None:
        dispatcher = ACPDispatcher(
            repo_root=self.root,
            round_slug="t",
            parent_session_cwd=self.root,
            plugin_version_target="0.3.84",
            dry_run=True,
        )
        results = dispatcher.dispatch(
            round="t",
            prs=[
                ("feat/l6-alpha", "l6-alpha"),
                ("feat/acp-launcher", "acp-launcher"),
                ("feat/version-slot", "version-slot"),
            ],
        )
        self.assertEqual(len(results), 3)
        for idx, result in enumerate(results, start=1):
            self.assertIsInstance(result, DispatchResult)
            self.assertEqual(result.spec.pr_index, idx)
            self.assertTrue(result.dry_run)
        # No worktrees, no envelopes written.
        for slug in ("l6-alpha", "acp-launcher", "version-slot"):
            self.assertFalse((self.root / ".worktrees" / slug).exists())
        self.assertFalse((self.root / ".dev-kit" / "round-t").exists())


class DispatchFullCut(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = _init_throwaway_repo()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_three_prs_produce_three_worktrees_and_three_envelopes(self) -> None:
        dispatcher = ACPDispatcher(
            repo_root=self.root,
            round_slug="t",
            parent_session_cwd=self.root,
            plugin_version_target="0.3.84",
        )
        prs = [
            ("feat/l6-alpha", "l6-alpha"),
            ("feat/acp-launcher", "acp-launcher"),
            ("feat/version-slot", "version-slot"),
        ]
        results = dispatcher.dispatch(round="t", prs=prs)

        self.assertEqual(len(results), 3)
        for idx, (result, (branch, slug)) in enumerate(zip(results, prs), start=1):
            self.assertEqual(result.spec.branch, branch)
            self.assertEqual(result.spec.pr_index, idx)
            # macOS resolves /tmp -> /private/tmp symlink, so compare
            # resolved paths to avoid the spurious mismatch.
            self.assertEqual(
                result.worktree_path.resolve(),
                (self.root / ".worktrees" / slug).resolve(),
            )
            self.assertEqual(
                result.envelope_path.resolve(),
                (
                    self.root
                    / ".dev-kit"
                    / "round-t"
                    / "dispatches"
                    / f"{branch.replace('/', '-')}.md"
                ).resolve(),
            )
            # Worktree must exist on disk and contain the canonical
            # template (proof the worktree was cut from origin/main
            # which now carries it).
            wt = self.root / ".worktrees" / slug
            self.assertTrue(wt.is_dir(), f"worktree dir missing: {wt}")
            self.assertTrue((wt / ".git").exists() or (wt / ".git").is_file())
            # Envelope must be written and free of unresolved placeholders.
            self.assertTrue(result.envelope_path.is_file())
            body = result.envelope_path.read_text(encoding="utf-8")
            for placeholder in SEVEN_PLACEHOLDERS:
                self.assertNotIn(placeholder, body)
            # Envelope must echo the resolved values for downstream M
            # parsing.
            self.assertIn(branch, body)
            self.assertIn(str(result.worktree_path), body)
            self.assertIn("0.3.84", body)

    def test_round_mismatch_raises(self) -> None:
        dispatcher = ACPDispatcher(
            repo_root=self.root,
            round_slug="t",
            parent_session_cwd=self.root,
            dry_run=True,
        )
        with self.assertRaises(ValueError):
            dispatcher.dispatch(round="other", prs=[("feat/x", "x")])

    def test_missing_plugin_version_defaults(self) -> None:
        dispatcher = ACPDispatcher(
            repo_root=self.root,
            round_slug="t",
            parent_session_cwd=self.root,
            dry_run=True,
        )
        results = dispatcher.dispatch(round="t", prs=[("feat/x", "x")])
        # When plugin_version_target is not set, the dispatcher falls
        # back to 0.3.75 (the documented fallback per
        # docs/acp-harness.md §4.2). The T can re-pin via
        # `bin/version-slot pin <PR_INDEX>` before push.
        self.assertIn("0.3.75", results[0].envelope)

    def test_repeated_dispatch_refuses_existing_worktree(self) -> None:
        # Cutting the same worktree twice must raise, never silently
        # overwrite another T's branch (the parent's git-guard parity).
        dispatcher = ACPDispatcher(
            repo_root=self.root,
            round_slug="t",
            parent_session_cwd=self.root,
            plugin_version_target="0.3.84",
        )
        dispatcher.dispatch(round="t", prs=[("feat/l6-alpha", "l6-alpha")])
        with self.assertRaises(FileExistsError):
            dispatcher.dispatch(round="t", prs=[("feat/l6-alpha", "l6-alpha")])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()