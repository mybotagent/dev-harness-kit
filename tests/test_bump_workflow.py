#!/usr/bin/env python3
"""test_bump_workflow.py — regression for `.github/workflows/version-bump.yml`.

After the pre-commit auto-bump + freshness-check refactor, this workflow is
tag-only emission. It does NOT create bump PRs, does NOT race-recover
orphans, does NOT carry a commit message. The full chain is:

  user edits skill
    -> .githooks/pre-commit auto-bumps plugin.json:version (PATCH++)
    -> user pushes branch, opens PR
    -> ci.yml:version-freshness check (PR head > PR base) gates the merge
    -> squash-merge lands the bump commit on main
    -> version-bump.yml:tag job detects the bump via head-commit message
       and emits dev-kit--vX.Y.Z

This test pins the structural contract the workflow must satisfy so the
refactor cannot drift silently:

  T1: workflow file exists and parses as YAML.
  T2: workflow ONLY triggers on push to main (no pull_request trigger).
  T3: permissions include `contents: write` (for tag push); pull-requests
      is no longer required (no PR creation).
  T4: concurrency group is configured with `cancel-in-progress: false`
      (tag emission must serialize; never drop in-flight tag pushes).
  T5: tag pattern `dev-kit--vX.Y.Z` is emitted by the tag job.
  T6: tag emission is skipped if the tag already exists on origin.
  T7: tag emission is skipped if the head commit is NOT a bump commit
      matching the current plugin.json:version (defends against spurious
      tag pushes from unrelated force-pushes).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


WORKFLOW_PATH = (
    Path(__file__).parent.parent / ".github" / "workflows" / "version-bump.yml"
)


def _yaml_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _yaml_doc() -> dict:
    return yaml.safe_load(_yaml_text())


def _resolve_steps(doc: dict) -> list[dict]:
    return doc["jobs"]["tag"]["steps"]


def _find_step(doc: dict, name_substr: str) -> dict | None:
    for step in _resolve_steps(doc):
        if name_substr.lower() in step.get("name", "").lower():
            return step
    return None


class TestBumpWorkflow(unittest.TestCase):

    def test_01_workflow_file_exists(self):
        self.assertTrue(WORKFLOW_PATH.exists(),
                        f"missing workflow: {WORKFLOW_PATH}")

    def _on(self, doc) -> dict:
        """PyYAML >=1.1 treats `on:` as the boolean True; coerce to a dict key either way."""
        if isinstance(doc.get(True), dict):
            return doc[True]
        if isinstance(doc.get("on"), dict):
            return doc["on"]
        self.fail(f"workflow has no `on:` triggers; doc keys = {list(doc)}")
        return {}  # unreachable

    def test_02_workflow_parses_as_yaml(self):
        doc = _yaml_doc()
        self.assertEqual(doc["name"], "version-bump")
        self.assertTrue(("on" in doc) or (True in doc),
                        "workflow must declare triggers under `on:`")
        self.assertIn("jobs", doc)
        self.assertIn("tag", doc["jobs"],
                      "workflow must declare a `tag` job (the only job)")

    def test_03_push_only_trigger_no_pull_request(self):
        """The refactored workflow is push-to-main only. No pull_request
        trigger -- PRs already carry their own version bump via
        .githooks/pre-commit, so the workflow does not need to react to
        PR-closed events. Pin this to prevent re-introduction of the old
        bump-PR creation path."""
        doc = _yaml_doc()
        on_dict = self._on(doc)
        self.assertIn("push", on_dict)
        push = on_dict["push"]
        self.assertEqual(push.get("branches"), ["main"],
                         "push trigger must pin to branches: [main]")
        self.assertNotIn("pull_request", on_dict,
                         "version-bump.yml must NOT trigger on pull_request; "
                         "the pre-commit hook carries the bump onto the PR "
                         "and this workflow only emits the tag post-merge")

    def test_04_permissions_declares_contents_write(self):
        doc = _yaml_doc()
        perms = doc.get("permissions", {})
        self.assertEqual(perms.get("contents"), "write",
                         "workflow needs contents: write to push the tag")
        # pull-requests: write is no longer required (no PR creation).
        self.assertNotIn("pull-requests", perms,
                         "pull-requests: write is unnecessary -- the workflow "
                         "no longer creates or merges PRs")

    def test_05_concurrency_group_set(self):
        doc = _yaml_doc()
        conc = doc.get("concurrency", {})
        self.assertIn("group", conc, "concurrency.group required")
        self.assertTrue(conc.get("cancel-in-progress") is False,
                        "cancel-in-progress MUST be false -- true drops newer "
                        "tag pushes that come in while a current tag emit is "
                        "running, which would skip tag emission")

    def test_06_tag_pattern_present(self):
        text = _yaml_text()
        self.assertRegex(text, r"dev-kit--v\$\{?\{?VERSION\}\}?",
                         "tag emission step must produce dev-kit--vX.Y.Z")

    def test_07_tag_skipped_if_already_exists(self):
        """Tag emission must be a no-op when the tag already exists on
        origin. Idempotent re-runs (e.g. workflow re-fire on a force-push
        that didn't change the head version) must not fail."""
        doc = _yaml_doc()
        tag_step = None
        for step in _resolve_steps(doc):
            name = step.get("name", "").lower()
            if "tag" in name or "read version" in name:
                tag_step = step
                break
        self.assertIsNotNone(tag_step, "expected a 'Tag' / 'Read version' step")
        run = tag_step.get("run", "")
        self.assertIn("already exists", run,
                      "tag step must skip (with exit 0) when the tag is "
                      "already on origin; otherwise re-runs will fail with "
                      "'tag already exists' from git push")

    def test_08_no_head_commit_msg_predicate(self):
        """The tag-emission step must NOT predicate on the head commit's
        message. Under the pre-commit auto-bump design, the head commit
        on main is the squash-merge of the user's PR (title = PR title
        like "fix(x): ..."), NOT a "chore(release): bump dev-kit to
        v..." commit. Tag-emission is gated by (a) tag-already-exists
        and (b) ci.yml:validate Version freshness. A head-msg predicate
        here would silently drop every release.

        This is the inverse of the previous T8 — pin the absence of the
        predicate so it cannot regress.
        """
        doc = _yaml_doc()
        tag_step = None
        for step in _resolve_steps(doc):
            name = step.get("name", "").lower()
            if "tag" in name or "read version" in name:
                tag_step = step
                break
        self.assertIsNotNone(tag_step)
        run = tag_step.get("run", "")
        self.assertNotIn(r"chore\(release\):\ bump", run,
                         "tag step must NOT predicate on the head-commit "
                         "message; under squash-merge, the head title is "
                         "the PR title, not a bump-commit")


class TestBumpWorkflowOmissions(unittest.TestCase):
    """Pin the refactor's REMOVALS. The old bump-PR creation path
    (chore/bump-vX.Y.Z branches, gh pr create, peter-evans/enable-pull-
    request-automerge) is gone. These tests guard against re-introduction.
    """

    def test_no_bump_branch_creation(self):
        text = _yaml_text()
        self.assertNotIn("chore/bump-v", text,
                         "workflow must NOT cut chore/bump-v* branches; "
                         "PRs carry their own bump via pre-commit auto-bump")
        self.assertNotIn("gh pr create", text,
                         "workflow must NOT create PRs; only emit tags")

    def test_no_peter_evans_automerge(self):
        text = _yaml_text()
        self.assertNotIn("enable-pull-request-automerge", text,
                         "workflow must NOT enable auto-merge on a bump PR; "
                         "that was the source of the orphan-bump cycle")

    def test_no_cherry_pick_recovery(self):
        text = _yaml_text()
        self.assertNotIn("cherry-pick", text,
                         "workflow must NOT do cherry-pick recovery; the "
                         "pre-commit hook + freshness check close the race")

    def test_no_commit_in_workflow(self):
        """The bump-commit message no longer exists in this workflow (no
        commit is made here). Pin the absence of `git commit -m` as a
        future-proofing guard against re-introducing the bump-PR path."""
        text = _yaml_text()
        self.assertNotIn("git commit -m", text,
                         "workflow must NOT make any commits; commits are "
                         "the user's responsibility (via pre-commit hook)")


class TestVersionFreshnessCheck(unittest.TestCase):
    """The cross-PR freshness check lives in .github/workflows/ci.yml.
    It enforces STRICT inequality: PR head version > PR base version
    (NOT >=). The auto-bump source of truth is .githooks/pre-push,
    which advances PATCH to (BASE + 1) right before pushing. If the
    check fires with HEAD == BASE, the user bypassed pre-push
    (`--no-verify`).
    """

    @staticmethod
    def _wf() -> Path:
        return WORKFLOW_PATH.parent / "ci.yml"

    def _doc(self):
        return yaml.safe_load(self._wf().read_text(encoding="utf-8"))

    def test_validate_job_has_freshness_step(self):
        doc = self._doc()
        validate = doc["jobs"]["validate"]
        steps = validate.get("steps", [])
        freshness = [s for s in steps if "freshness" in s.get("name", "").lower()]
        self.assertEqual(len(freshness), 1,
                         "validate job must have exactly one version-freshness step")

    def test_freshness_step_runs_only_on_pull_request(self):
        doc = self._doc()
        step = [s for s in doc["jobs"]["validate"]["steps"]
                if "freshness" in s.get("name", "").lower()][0]
        self.assertIn("pull_request", step.get("if", ""),
                      "freshness step must be gated on pull_request event "
                      "(push-to-main triggers should not re-run this)")

    def test_freshness_step_compares_base_and_head(self):
        doc = self._doc()
        step = [s for s in doc["jobs"]["validate"]["steps"]
                if "freshness" in s.get("name", "").lower()][0]
        run = step.get("run", "")
        self.assertIn("BASE_SHA", run,
                      "freshness step must read PR base SHA via env")
        self.assertIn("BASE_VERSION", run,
                      "freshness step must extract base version")
        self.assertIn("HEAD_VERSION", run,
                      "freshness step must extract head version")
        self.assertIn("sort -V", run,
                      "freshness step must use version-aware sort to compare "
                      "versions (not lexicographic -- 0.3.10 < 0.3.9 lex)")

    def test_freshness_step_enforces_strict_greater_than(self):
        """The check must reject HEAD <= BASE. The pre-push hook is the
        source of truth (auto-bumps to BASE+1); a HEAD == BASE here
        means the user pushed with --no-verify and bypassed it."""
        doc = self._doc()
        step = [s for s in doc["jobs"]["validate"]["steps"]
                if "freshness" in s.get("name", "").lower()][0]
        run = step.get("run", "")
        self.assertIn("strict", step.get("name", "").lower(),
                      "freshness step name must declare STRICT semantics")
        # Pin the check shape: HIGHER == BASE_VERSION catches both
        # HEAD < BASE and HEAD == BASE (rejects the second case too).
        self.assertIn("HIGHER=", run,
                      "freshness step must compute a HIGHER variable")
        self.assertIn("sort -V", run,
                      "freshness step must use version-aware sort")
        self.assertIn("tail -1", run,
                      "freshness step must take the tail of sort -V output")
        self.assertIn('"$BASE_VERSION"', run,
                      "freshness step must reference BASE_VERSION in the rejection check")
        # The STRICT predicate is `if [ "$HIGHER" = "$BASE_VERSION" ]`.
        # This catches both HEAD < BASE and HEAD == BASE; only HEAD > BASE
        # passes (because then HIGHER == HEAD != BASE).
        self.assertRegex(run, r'\[\s*"\$\{?HIGHER\}?"\s*=\s*"\$\{?BASE_VERSION\}?"\s*\]',
                         "freshness step must check HIGHER == BASE_VERSION (rejects HEAD <= BASE)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
# verify
