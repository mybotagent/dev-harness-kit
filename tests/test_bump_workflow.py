#!/usr/bin/env python3
"""test_bump_workflow.py — regression for `.github/workflows/version-bump.yml`.

After the trunk-owns-the-version refactor (post-#439), this workflow:
  1. Reads the current version from .claude-plugin/plugin.json
  2. Bumps PATCH (0.3.129 -> 0.3.130)
  3. Updates both plugin manifests
  4. Commits + pushes the bump to main
  5. Emits the annotated tag (idempotent on tag-already-exists)

The full chain is:
  user edits skill on feature branch
    -> PR opens; branch's plugin.json:version equals origin/main's
       (no auto-bump on feature branches; parallel PRs never conflict)
    -> ci.yml:version-freshness check (HEAD > BASE) gates the merge
    -> squash-merge lands the PR on main
    -> version-bump.yml fires on push-to-main, bumps PATCH, commits,
       pushes, then emits dev-kit--vX.Y.Z

This test pins the structural contract the workflow must satisfy so the
refactor cannot drift silently:

  T1: workflow file exists and parses as YAML.
  T2: workflow ONLY triggers on push to main (no pull_request trigger).
  T3: permissions include `contents: write` (for tag push + commit push).
  T4: concurrency group is configured with `cancel-in-progress: false`
      (bump+tag must serialize; never drop in-flight pushes).
  T5: tag pattern `dev-kit--vX.Y.Z` is emitted by the workflow.
  T6: tag emission is skipped if the tag already exists on origin.
  T7: workflow bumps BOTH plugin manifests (.claude-plugin and .codex-plugin).
  T8: workflow commits the bump with a chore(release): ... message.
  T9: pre-push hook does NOT auto-bump; it only enforces version freshness.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml

WORKFLOW_PATH = (
    Path(__file__).parent.parent / ".github" / "workflows" / "version-bump.yml"
)
PRE_PUSH_PATH = Path(__file__).parent.parent / ".githooks" / "pre-push"


def _yaml_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _yaml_doc() -> dict:
    return yaml.safe_load(_yaml_text())


def _resolve_steps(doc: dict) -> list[dict]:
    # Job name may be 'tag' (legacy) or 'bump-and-tag' (post-refactor).
    jobs = doc["jobs"]
    job_name = next(iter(jobs.keys()))
    return jobs[job_name]["steps"]


def _find_step(doc: dict, name_substr: str) -> dict | None:
    for step in _resolve_steps(doc):
        if name_substr.lower() in step.get("name", "").lower():
            return step
    return None


class TestBumpWorkflow(unittest.TestCase):

    def test_plugin_manifest_versions_are_in_sync(self):
        """The two published plugin surfaces must expose one release version."""
        import json

        root = PRE_PUSH_PATH.parent.parent
        claude = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
        codex = json.loads((root / ".codex-plugin" / "plugin.json").read_text())
        self.assertEqual(claude["version"], codex["version"])

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
        # Exactly one job expected post-refactor: bump-and-tag (or legacy 'tag').
        self.assertEqual(len(doc["jobs"]), 1,
                         "workflow must declare exactly one job")

    def test_03_push_only_trigger_no_pull_request(self):
        """The workflow is push-to-main only. No pull_request trigger —
        the trunk owns the version bump after a PR merges. Pin this to
        prevent re-introduction of the old bump-PR creation path."""
        doc = _yaml_doc()
        on_dict = self._on(doc)
        self.assertIn("push", on_dict)
        push = on_dict["push"]
        self.assertEqual(push.get("branches"), ["main"],
                         "push trigger must pin to branches: [main]")
        self.assertNotIn("pull_request", on_dict,
                         "version-bump.yml must NOT trigger on pull_request; "
                         "the trunk owns the version bump post-merge")

    def test_04_permissions_declares_contents_write(self):
        doc = _yaml_doc()
        perms = doc.get("permissions", {})
        self.assertEqual(perms.get("contents"), "write",
                         "workflow needs contents: write to push the bump commit "
                         "and the tag")
        self.assertNotIn("pull-requests", perms,
                         "pull-requests: write is unnecessary -- the workflow "
                         "does not create or merge PRs")

    def test_05_concurrency_group_set(self):
        doc = _yaml_doc()
        conc = doc.get("concurrency", {})
        self.assertIn("group", conc, "concurrency.group required")
        self.assertTrue(conc.get("cancel-in-progress") is False,
                        "cancel-in-progress MUST be false -- true drops newer "
                        "bumps that come in while a current bump is running")

    def test_06_tag_pattern_present(self):
        text = _yaml_text()
        self.assertRegex(text, r"dev-kit--v\$\{?\{?VERSION\}\}?",
                         "tag emission step must produce dev-kit--vX.Y.Z")

    def test_07_tag_skipped_if_already_exists(self):
        """Tag emission must be a no-op when the tag already exists on
        origin. Idempotent re-runs (e.g. workflow re-fire on a force-push
        that didn't change the head version) must not fail."""
        doc = _yaml_doc()
        tag_step = _find_step(doc, "tag") or _find_step(doc, "emit")
        self.assertIsNotNone(tag_step, "expected a 'Tag' / 'Emit' step")
        run = tag_step.get("run", "")
        self.assertIn("already exists", run,
                      "tag step must skip (with exit 0) when the tag is "
                      "already on origin; otherwise re-runs will fail with "
                      "'tag already exists' from git push")

    def test_07b_workflow_configures_git_identity(self):
        """`git tag -a` and the bump commit both require a configured
        user.name + user.email on the runner. Without it, the next
        release push fails with `fatal: unable to auto-detect email
        address`. Pin the identity setup so a future refactor can't
        silently drop it — either as a dedicated step or inline in the
        step that runs git commit / git tag."""
        doc = _yaml_doc()
        all_runs = "\n".join(step.get("run", "") for step in _resolve_steps(doc))
        self.assertIn("git config user.name", all_runs,
                      "workflow must configure git user.name somewhere "
                      "(dedicated step or inline in commit/tag step)")
        self.assertIn("git config user.email", all_runs,
                      "workflow must configure git user.email somewhere "
                      "(dedicated step or inline in commit/tag step)")

    def test_08_workflow_bumps_both_manifests(self):
        """The bump step must update BOTH .claude-plugin/plugin.json and
        .codex-plugin/plugin.json. The two surfaces publish the same
        version; only one plugin on the bump would desync releases."""
        doc = _yaml_doc()
        bump_step = _find_step(doc, "bump") or _find_step(doc, "manifest")
        self.assertIsNotNone(bump_step, "expected a 'Bump manifests' step")
        run = bump_step.get("run", "")
        self.assertIn(".claude-plugin/plugin.json", run,
                      "bump step must touch .claude-plugin/plugin.json")
        self.assertIn(".codex-plugin/plugin.json", run,
                      "bump step must touch .codex-plugin/plugin.json")

    def test_09_workflow_commits_the_bump(self):
        """The workflow must `git commit` the bump with a chore(release)
        message, then push the bump back to main. This is the trunk
        version advance that subsequent PRs will compare against."""
        doc = _yaml_doc()
        commit_step = _find_step(doc, "commit") or _find_step(doc, "push version")
        self.assertIsNotNone(commit_step, "expected a 'Commit + push version bump' step")
        run = commit_step.get("run", "")
        self.assertIn("git commit", run,
                      "commit step must call git commit (the bump itself)")
        self.assertIn("chore(release)", run,
                      "commit message must use chore(release): prefix so "
                      "changelog generators pick it up")
        self.assertIn("git push origin HEAD:main", run,
                      "commit step must push the bump back to main")

    def test_10_bump_step_uses_patch_plus_plus(self):
        """The version advance is strictly PATCH++. Bumping MAJOR or MINOR
        on a routine merge would surprise downstream consumers."""
        doc = _yaml_doc()
        next_step = _find_step(doc, "next") or _find_step(doc, "compute")
        self.assertIsNotNone(next_step, "expected a 'Compute next version' step")
        run = next_step.get("run", "")
        self.assertIn("PATCH", run,
                      "next-version step must reference the PATCH component")
        self.assertIn("PATCH + 1", run,
                      "next-version step must increment PATCH by 1")
        self.assertNotIn("MAJOR + 1", run,
                         "MAJOR bumps require explicit maintainer action; "
                         "this workflow must not auto-bump MAJOR")
        self.assertNotIn("MINOR + 1", run,
                         "MINOR bumps require explicit maintainer action; "
                         "this workflow must not auto-bump MINOR")


class TestBumpWorkflowOmissions(unittest.TestCase):
    """Pin the refactor's REMOVALS. The old bump-PR creation path
    (chore/bump-vX.Y.Z branches, gh pr create, peter-evans/enable-pull-
    request-automerge) is gone. These tests guard against re-introduction.
    """

    def test_no_bump_branch_creation(self):
        text = _yaml_text()
        self.assertNotIn("chore/bump-v", text,
                         "workflow must NOT cut chore/bump-v* branches; "
                         "the trunk owns the version bump post-merge")
        self.assertNotIn("gh pr create", text,
                         "workflow must NOT create PRs; only commit + tag")

    def test_no_peter_evans_automerge(self):
        text = _yaml_text()
        self.assertNotIn("enable-pull-request-automerge", text,
                         "workflow must NOT enable auto-merge on a bump PR; "
                         "that was the source of the orphan-bump cycle")

    def test_no_cherry_pick_recovery(self):
        text = _yaml_text()
        self.assertNotIn("cherry-pick", text,
                         "workflow must NOT do cherry-pick recovery; the "
                         "freshness check on PR + trunk-bump on merge close "
                         "the race")


class TestPrePushRefactor(unittest.TestCase):
    """The pre-push hook no longer auto-bumps; it only enforces version
    freshness (refuse push if local < origin/main). Pin the new contract
    so the old auto-bump cannot regress.
    """

    def test_pre_push_does_not_auto_bump(self):
        """The hook must NOT modify plugin.json. The trunk workflow owns
        the version advance; pre-push only checks freshness."""
        text = PRE_PUSH_PATH.read_text(encoding="utf-8")
        self.assertNotIn('jq --arg v "$NEW_VERSION"', text,
                         "pre-push must NOT auto-bump (the jq --arg v "
                         "$NEW_VERSION rewrite is the old auto-bump path)")
        self.assertNotIn('git add "$CLAUDE_PLUGIN" "$CODEX_PLUGIN"', text,
                         "pre-push must NOT stage a version bump commit")
        self.assertNotIn("chore(release): bump", text,
                         "pre-push must NOT create a chore(release) commit")

    def test_pre_push_enforces_freshness(self):
        """The hook MUST refuse a push when local version is older than
        origin/main's. This is the only behavior it retains."""
        text = PRE_PUSH_PATH.read_text(encoding="utf-8")
        self.assertIn("OLDER than origin/main", text,
                      "pre-push must refuse when local < origin/main")
        self.assertIn("Rebase onto origin/main", text,
                      "pre-push error message must tell the user to rebase")

    def test_pre_push_blocks_direct_main_push(self):
        """Direct push to main remains forbidden (PR-only workflow)."""
        text = PRE_PUSH_PATH.read_text(encoding="utf-8")
        self.assertIn("BLOCKED: direct push", text,
                      "pre-push must block direct push to main/master")


class TestVersionFreshnessCheck(unittest.TestCase):
    """The cross-PR freshness check lives in .github/workflows/ci.yml.
    It must (a) read PR base's plugin.json:version, (b) read PR head's
    plugin.json:version, (c) fail if HEAD < BASE (stale), (d) be skipped
    for bump-PRs (those are the user's own bump -- always equal or higher).
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
        self.assertIn("HIGHER=", run,
                      "freshness step must compute a HIGHER variable")
        self.assertIn("sort -V", run,
                      "freshness step must use version-aware sort")
        self.assertIn("tail -1", run,
                      "freshness step must take the tail of sort -V output")
        self.assertIn('"$BASE_VERSION"', run,
                      "freshness step must reference BASE_VERSION in the rejection check")


if __name__ == "__main__":
    unittest.main(verbosity=2)
# verify
