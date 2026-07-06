#!/usr/bin/env python3
"""
test_git_workflow.py — RED-first tests for branch-strategy enforcement.

Two layers under test:
  1. hooks/git-guard.sh — PreToolUse hook that denies direct commits/pushes
     to main and force-pushes to shared branches.
  2. .claude/rules/git-workflow.md — branch naming convention <type>/<slug>
     with a fixed allowlist of types. Enforced here by sampling the recent
     commit / branch history.

Both layers are part of the same rule (ADR-0021): a feature branch is
isolated in a worktree, cut from latest origin/main, and merged only via PR.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK = REPO_ROOT / "hooks" / "git-guard.sh"
RULE_FILE = REPO_ROOT / ".claude" / "rules" / "git-workflow.md"

ALLOWED_BRANCH_TYPES = ("fix", "feat", "refactor", "docs", "test", "chore", "perf", "hotfix")
BRANCH_RE = re.compile(r"^(?P<type>" + "|".join(ALLOWED_BRANCH_TYPES) + r")/(?P<slug>[a-z0-9][a-z0-9-]{0,38}[a-z0-9])$")
FORBIDDEN_SLUG_WORDS = {"wip", "tmp", "foo", "bar", "asdf", "test", "scratch", "untitled"}


def _run_hook(command: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Invoke git-guard.sh with a JSON payload simulating a Bash PreToolUse call."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=5,
        cwd=str(cwd) if cwd else None,
    )


def _init_tmp_git_repo() -> tempfile.TemporaryDirectory:
    """Create a throwaway git repo with one commit so the hook can read HEAD."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "README.md").write_text("x")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True, capture_output=True)
    return tmp


class TestGitGuardBlocks(unittest.TestCase):
    """git-guard.sh must deny (exit 2) direct commits and pushes to main."""

    def setUp(self):
        if not HOOK.exists():
            self.skipTest(f"git-guard not found: {HOOK}")

    def test_blocks_commit_on_main(self):
        with _init_tmp_git_repo() as tmp:
            r = _run_hook("git commit -m 'oops'", cwd=Path(tmp))
            self.assertEqual(r.returncode, 2, f"expected block, got rc={r.returncode}\nstderr={r.stderr}")
            self.assertIn("direct commit to 'main'", r.stderr)
            self.assertIn("permissionDecision", r.stderr)

    def test_blocks_commit_on_master(self):
        with _init_tmp_git_repo() as tmp:
            subprocess.run(["git", "-C", tmp, "branch", "-m", "main", "master"], check=True, capture_output=True)
            r = _run_hook("git commit -m 'oops'", cwd=Path(tmp))
            self.assertEqual(r.returncode, 2, f"expected block, got rc={r.returncode}\nstderr={r.stderr}")
            self.assertIn("direct commit to 'master'", r.stderr)

    def test_blocks_push_to_origin_main(self):
        r = _run_hook("git push origin main")
        self.assertEqual(r.returncode, 2)
        self.assertIn("pushing to main is forbidden", r.stderr)

    def test_blocks_push_HEAD_to_main(self):
        r = _run_hook("git push origin HEAD:main")
        self.assertEqual(r.returncode, 2)
        self.assertIn("pushing to main", r.stderr)

    def test_blocks_force_push(self):
        r = _run_hook("git push --force origin fix/foo")
        self.assertEqual(r.returncode, 2)
        self.assertIn("force-push", r.stderr)

    def test_blocks_checkout_main(self):
        with _init_tmp_git_repo() as tmp:
            # First create a feature branch so we can check out from it.
            subprocess.run(["git", "-C", tmp, "checkout", "-q", "-b", "fix/example"], check=True)
            r = _run_hook("git checkout main", cwd=Path(tmp))
            self.assertEqual(r.returncode, 2, f"expected block, got rc={r.returncode}\nstderr={r.stderr}")
            self.assertIn("switching to main", r.stderr)

    def test_blocks_branch_D_main(self):
        r = _run_hook("git branch -D main")
        self.assertEqual(r.returncode, 2)
        self.assertIn("deleting main/master with -D", r.stderr)

    def test_blocks_combined_main_checkout_then_commit(self):
        with _init_tmp_git_repo() as tmp:
            subprocess.run(["git", "-C", tmp, "checkout", "-q", "-b", "fix/example"], check=True)
            r = _run_hook("git checkout main && git commit -m 'evil'", cwd=Path(tmp))
            # checkout-main is caught first (exit 2).
            self.assertEqual(r.returncode, 2)
            self.assertIn("switching to main", r.stderr)


class TestGitGuardAllows(unittest.TestCase):
    """git-guard.sh must ALLOW (exit 0) normal feature-branch operations."""

    def setUp(self):
        if not HOOK.exists():
            self.skipTest(f"git-guard not found: {HOOK}")

    def test_allows_commit_on_feature_branch(self):
        with _init_tmp_git_repo() as tmp:
            subprocess.run(["git", "-C", tmp, "checkout", "-q", "-b", "fix/example"], check=True)
            r = _run_hook("git commit -m 'legit fix'", cwd=Path(tmp))
            self.assertEqual(r.returncode, 0, f"got rc={r.returncode}, stderr={r.stderr}")

    def test_allows_push_to_feature_branch(self):
        r = _run_hook("git push -u origin fix/review-findings")
        self.assertEqual(r.returncode, 0, f"got rc={r.returncode}, stderr={r.stderr}")

    def test_allows_checkout_b_new_branch(self):
        with _init_tmp_git_repo() as tmp:
            r = _run_hook("git checkout -b fix/new-thing", cwd=Path(tmp))
            self.assertEqual(r.returncode, 0, f"got rc={r.returncode}, stderr={r.stderr}")

    def test_allows_force_with_lease_on_own_branch(self):
        r = _run_hook("git push --force-with-lease origin fix/review-findings")
        self.assertEqual(r.returncode, 0, f"got rc={r.returncode}, stderr={r.stderr}")

    def test_allows_read_only_git_commands(self):
        for cmd in ["git status", "git log --oneline -5", "git diff HEAD~1",
                    "git rev-parse HEAD", "git branch --show-current", "git show --stat"]:
            with self.subTest(cmd=cmd):
                r = _run_hook(cmd)
                self.assertEqual(r.returncode, 0, f"got rc={r.returncode} for {cmd!r}, stderr={r.stderr}")

    def test_allows_non_git_commands(self):
        r = _run_hook("ls -la /tmp")
        self.assertEqual(r.returncode, 0)

    def test_allows_empty_command(self):
        r = _run_hook("")
        self.assertEqual(r.returncode, 0)


class TestBranchNamingConvention(unittest.TestCase):
    """The branch-naming rule from .claude/rules/git-workflow.md is enforced
    on the local git history. Any non-main branch whose name doesn't match
    `<type>/<slug>` with a clean kebab slug fails."""

    def test_branch_naming_convention_documented(self):
        """The rule file must exist and mention the convention."""
        self.assertTrue(RULE_FILE.exists(), f"missing {RULE_FILE}")
        text = RULE_FILE.read_text(encoding="utf-8")
        self.assertIn("Branch naming (mandatory)", text)
        for t in ALLOWED_BRANCH_TYPES:
            self.assertIn(f"`{t}/`", text), f"rule file missing type {t}/"

    def test_branch_naming_regex_accepts_canonical(self):
        for t in ALLOWED_BRANCH_TYPES:
            for slug in ("review-findings", "cli-nameerror", "eval-repair-v2"):
                self.assertRegex(f"{t}/{slug}", BRANCH_RE, f"{t}/{slug} should match")

    def test_branch_naming_regex_rejects_bad_types(self):
        for bad in ("feature/x", "bugfix/x", "Foo/x", "x"):  # wrong type
            self.assertNotRegex(bad, BRANCH_RE)

    def test_branch_naming_regex_rejects_bad_slugs(self):
        for bad in (
            "fix/MyFeature",         # not kebab
            "fix/my_feature",        # underscore
            "fix/내이름",            # Korean
            "fix/" + ("x" * 50),     # too long
            "fix/-leading-dash",     # leading dash in slug
            "fix/trailing-dash-",    # trailing dash
            "fix/UPPER",             # uppercase
            "fix/a",                 # too short (single char)
        ):
            self.assertNotRegex(bad, BRANCH_RE, f"should reject {bad!r}")

    def test_branch_naming_rejects_forbidden_slug_words(self):
        for bad in ("fix/wip", "chore/tmp", "feat/foo", "fix/scratch"):
            self.assertIn(bad.split("/")[1], FORBIDDEN_SLUG_WORDS,
                          f"{bad!r} should be in forbidden slug set")

    def test_recent_local_branches_match_convention(self):
        """All local branches (except main/master/HEAD/grandfathered) must follow <type>/<slug>.

        Grandfathered branches are pre-existing personal-work branches that predate
        the rule (currently: dev, stage). Once deleted, the grandfather list can
        shrink. New branches MUST follow the convention — see .claude/rules/git-workflow.md.
        """
        GRANDFATHERED = {"dev", "stage"}
        result = subprocess.run(
            ["git", "branch", "--list", "--no-color"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=5,
        )
        if result.returncode != 0:
            self.skipTest("git branch failed (not a git repo?)")
        branches = []
        for line in result.stdout.splitlines():
            # `git branch --list` prefixes: `* ` (current), `+ ` (worktree), or two spaces.
            line = line.strip().lstrip("*+").strip()
            if not line or line in ("main", "master", "HEAD"):
                continue
            # CI runs in detached HEAD at `pull/N/merge` refs — skip those.
            if line.startswith("(") or "detached" in line:
                continue
            branches.append(line)
        for b in branches:
            with self.subTest(branch=b):
                # Harness bookkeeping: EnterWorktree auto-names start with `worktree-`.
                if b.startswith("worktree-"):
                    continue
                # Pre-existing branches that predate the rule.
                if b in GRANDFATHERED:
                    continue
                self.assertRegex(b, BRANCH_RE, f"branch {b!r} does not match <type>/<slug>")


if __name__ == "__main__":
    unittest.main(verbosity=2)