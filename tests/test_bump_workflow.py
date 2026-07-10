#!/usr/bin/env python3
"""test_bump_workflow.py — regression for `.github/workflows/version-bump.yml`.

Pre-history: the original file (`bump-and-push` mode) registered as a
healthy GitHub Actions workflow on `push: branches: [main]` but had
**zero** runs in production (`gh api .../actions/workflows/version-bump.yml/runs`).
That meant `.claude-plugin/plugin.json:version` was stuck at `0.3.0`,
which made marketplace updates a no-op (install contract gated on
marketplace-version != cache-version; identical versions = no install).

This test pins the structural contract the replacement workflow must
satisfy so the regression cannot drift silently:

  T1: workflow file exists and parses as YAML.
  T2: push trigger on branches: [main] is present.
  T3: pull_request trigger with types: [closed] is present.
  T4: job `if` permits push events OR (pull_request closed AND merged AND base=main).
  T5: permissions include `contents: write` and `pull-requests: write`.
  T6: concurrency group is configured with `cancel-in-progress`.
  T7: bump commit message literal contains "[skip ci]" (loop guard).
  T8: auto-merge is wired via `peter-evans/enable-pull-request-automerge`.
  T9: tag pattern `dev-kit--vX.Y.Z` is present in the workflow steps.
  T10: idempotency check verifies the head-commit message shape before
       publishing the bump PR (loop guard for the bump PR's own merge).
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
    return doc["jobs"]["bump"]["steps"]


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
        """PyYAML ≥1.1 treats `on:` as the boolean True; coerce to a dict key either way."""
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
        self.assertIn("bump", doc["jobs"])

    def test_03_push_trigger_on_main(self):
        doc = _yaml_doc()
        on_dict = self._on(doc)
        self.assertIn("push", on_dict)
        push = on_dict["push"]
        self.assertEqual(push.get("branches"), ["main"],
                         "push trigger must pin to branches: [main]")

    def test_04_pull_request_closed_trigger(self):
        doc = _yaml_doc()
        on_dict = self._on(doc)
        self.assertIn("pull_request", on_dict, "pull_request trigger required for auto-bump-on-PR-merge")
        pr = on_dict["pull_request"]
        types = pr.get("types")
        self.assertIsNotNone(types, "pull_request trigger must declare types")
        self.assertIn("closed", types,
                      "pull_request types must include 'closed' (merged-only filter is enforced via job `if`)")

    def test_05_merged_only_filter_in_job_if(self):
        doc = _yaml_doc()
        job_if = doc["jobs"]["bump"].get("if", "")
        # The replacement workflow must not bump on PR close-without-merge.
        self.assertIn("merged", job_if,
                      "job `if` must check pull_request.merged == true")
        self.assertIn("pull_request.base.ref", job_if,
                      "job `if` must constrain to base ref == 'main'")
        self.assertIn("'main'", job_if,
                      "job `if` must pin base.ref == 'main' (string literal)")

    def test_06_permissions_declares_write_scopes(self):
        doc = _yaml_doc()
        perms = doc.get("permissions", {})
        self.assertEqual(perms.get("contents"), "write",
                         "workflow needs contents: write to push bump commit + tag")
        self.assertEqual(perms.get("pull-requests"), "write",
                         "workflow needs pull-requests: write for gh pr create + auto-merge action")

    def test_07_concurrency_group_set(self):
        doc = _yaml_doc()
        conc = doc.get("concurrency", {})
        self.assertIn("group", conc, "concurrency.group required to serialise racing bumps")
        self.assertTrue(conc.get("cancel-in-progress") is False,
                        "cancel-in-progress MUST be false — true drops newer runs that come in while a "
                        "current run is going, which is the opposite of serialisation. The idempotency "
                        "step is the only thing preventing duplicate bump PRs from racing.")

    def test_08_skip_ci_literal_in_commit_message(self):
        text = _yaml_text()
        self.assertIn("[skip ci]", text,
                      "loop guard: the bump commit message must carry [skip ci]")

    def test_09_auto_merge_via_peter_evans_action(self):
        doc = _yaml_doc()
        found = False
        for step in _resolve_steps(doc):
            uses = step.get("uses", "")
            if "peter-evans/enable-pull-request-automerge" in uses:
                with_block = step.get("with", {})
                self.assertIn("pull-request-number", with_block,
                              "auto-merge action must take pull-request-number input")
                self.assertIn("merge-method", with_block,
                              "auto-merge action must declare merge-method")
                self.assertEqual(with_block.get("merge-method"), "squash",
                                 "use squash merge for the bump PR")
                found = True
                break
        self.assertTrue(found,
                        "auto-merge step using peter-evans/enable-pull-request-automerge is required")

    def test_10_dev_kit_tag_pattern_present(self):
        text = _yaml_text()
        self.assertRegex(text, r"dev-kit--v\$\{?\{?NEW_VERSION\}\}?",
                         "tag emission step must produce dev-kit--vX.Y.Z")

    def test_11_idempotency_check_blocks_replay(self):
        doc = _yaml_doc()
        bump_step = _find_step(doc, "bump patch")
        self.assertIsNotNone(bump_step,
                             "expected a 'Bump PATCH in plugin.json' step")
        run = bump_step.get("run", "")
        # T11: structural anchors — the idempotency step must exist and
        # short-circuit on its skip flag. The exact regex shape (use of
        # ${VERSION} not ${NEW_VERSION} + bash regex `=~` with optional
        # (#PR-number) suffix) is pinned by T14, T15.
        self.assertIn("idempotent_skip", run,
                      "idempotency step must short-circuit on its skip flag")
        self.assertIn("NORMALISED_HEAD_MSG", run,
                      "idempotency check must read the head-commit message")
        self.assertIn("should_publish_pr=false", run,
                      "idempotent path must set should_publish_pr=false")

    def test_12_idempotent_skip_emits_no_pr(self):
        doc = _yaml_doc()
        # The PR-open step must be guarded on `should_publish_pr == 'true'`
        # so idempotent skips don't open phantom PRs.
        for step in _resolve_steps(doc):
            if "auto-merge pr" in step.get("name", "").lower() or "open auto-merge" in step.get("name", "").lower() or "open" in step.get("name", "").lower():
                self.assertIn("should_publish_pr", step.get("if", ""),
                              "PR-open step must be gated on should_publish_pr == 'true'")
                return
        self.fail("expected an 'Open auto-merge PR' step that gates on should_publish_pr")

    def test_13_tag_step_runs_on_idempotent_skip(self):
        """Tag step must run on the idempotent-skip path (new_version != '')
        — NOT be gated on should_publish_pr — so the tag lands even when the
        bump PR's own squash-merge re-fires the workflow.

        Scenario that exposes the bug if regressed:
          1. Workflow fires on `pull_request: closed` (merged).
          2. bumps 0.3.0 -> 0.3.1, publishes chore/bump-v0.3.1 PR.
          3. Auto-merge takes >60s; tag step times out and exits 0.
          4. Auto-merge completes (head commit on main is now the 0.3.1 bump).
          5. Next push-to-main fires version-bump.
          6. Idempotency step: head message matches bump-of-0.3.1, skips.
          7. Tag step gated on should_publish_pr == 'true': SKIPPED.
          8. Tag dev-kit--v0.3.1 never pushed.
        """
        doc = _yaml_doc()
        tag_step = None
        for step in _resolve_steps(doc):
            name = step.get("name", "").lower()
            if "tag" in name and "version" in name:
                tag_step = step
                break
        self.assertIsNotNone(tag_step, "expected a 'Tag ... version' step")
        cond = tag_step.get("if", "")
        self.assertNotIn("should_publish_pr", cond,
                         "Tag step MUST NOT be gated on should_publish_pr — "
                         "the head-commit idempotency check sets that to false "
                         "on the very run where the tag needs to be pushed.")
        self.assertIn("new_version", cond,
                      "Tag step should be gated on new_version != '' (set on both paths)")

    def test_14_idempotency_uses_current_version_not_next(self):
        """The idempotency check MUST compare against ${VERSION} (current
        plugin.json value), NOT ${NEW_VERSION} (the next bump target).

        Off-by-one scenario if regressed:
          - Iter 1: VERSION=0.3.0, NEW_VERSION=0.3.1. head irrelevant.
          - Iter 2 (squash re-fire): VERSION=0.3.1, NEW_VERSION=0.3.2.
                    head = "bump v0.3.1". Compare against "bump v0.3.2"
                    -> never matches -> bumps 0.3.1 -> 0.3.2 anyway.
          - Iter 3: head = "v0.3.2", compare = "v0.3.3" -> bumps again. Infinite.
        """
        doc = _yaml_doc()
        bump_step = _find_step(doc, "bump patch")
        run = bump_step.get("run", "")
        self.assertIn("v${VERSION}", run,
                      "idempotency regex must reference ${VERSION} (current)")
        self.assertNotIn("v${NEW_VERSION}", run,
                         "idempotency MUST NOT compare against ${NEW_VERSION} — "
                         "causes infinite bump loop on squash re-fire")

    def test_15_idempotency_accepts_squash_merge_pr_suffix(self):
        """The idempotency regex must use bash `=~` (regex match) and accept
        GitHub's optional ` (#PR-number)` suffix that squash-merge prepends.
        Plain string equality never matches post-squash because the suffix
        breaks the literal comparison."""
        doc = _yaml_doc()
        bump_step = _find_step(doc, "bump patch")
        run = bump_step.get("run", "")
        self.assertRegex(run, r"=~",
                         "idempotency check must use bash regex match (=~), "
                         "not plain [ \"...\" = \"...\" ]")
        self.assertIn("#[0-9]+", run,
                      "idempotency regex must allow GitHub's optional "
                      "` (#PR-number)` suffix on squash-merge commits")

    def test_13_tag_step_runs_on_idempotent_skip(self):
        """Tag step must run on the idempotent-skip path (new_version != '')
        — NOT be gated on should_publish_pr — so the tag lands even when the
        bump PR's own squash-merge re-fires the workflow.

        Scenario that exposes the bug if regressed:
          1. Workflow fires on `pull_request: closed` (merged).
          2. bumps 0.3.0 -> 0.3.1, publishes chore/bump-v0.3.1 PR.
          3. Auto-merge takes >60s; tag step times out and exits 0.
          4. Auto-merge completes (head commit on main is now the 0.3.1 bump).
          5. Next push-to-main fires version-bump.
          6. Idempotency step: head message matches bump-of-0.3.1, skips
             (should_publish_pr=false).
          7. Tag step gated on should_publish_pr == 'true': SKIPPED.
          8. Tag dev-kit--v0.3.1 never pushed.
        """
        doc = _yaml_doc()
        tag_step = None
        for step in _resolve_steps(doc):
            name = step.get("name", "").lower()
            if "tag" in name and "version" in name:
                tag_step = step
                break
        self.assertIsNotNone(tag_step, "expected a 'Tag ... version' step")
        cond = tag_step.get("if", "")
        self.assertNotIn("should_publish_pr", cond,
                         "Tag step MUST NOT be gated on should_publish_pr — "
                         "the head-commit idempotency check sets that to false "
                         "on the very run where the tag needs to be pushed.")
        self.assertIn("new_version", cond,
                      "Tag step should be gated on new_version != '' (set on both paths)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
# verify
