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

    def test_08_no_skip_ci_literal_in_bump_commit_message(self):
        """`[skip ci]` (or `[no ci]`, `[ci skip]`, `[skip actions]`, `[actions skip]`)
        in any commit message tells GitHub Actions to globally suppress
        ALL workflows on that push — including `version-bump.yml` itself,
        which broke the auto-tag cycle (after squash-merge of the bump PR,
        version-bump.yml never re-fired so `dev-kit--vX.Y.Z` never got pushed).
        Per-workflow `if:` filters on `ci.yml` / `review.yml` now skip
        the bump commit instead.

        Note: the file as a whole may still mention `[skip ci]` inside the
        idempotency regex (T10's tolerance for backward-compat with old
        format bump commits). What matters is the *bump commit MESSAGE*
        — every `git commit -m "..."` invocation — does NOT carry it.

        The 3-path race-recovery block (Path 1 + Path 3) introduces two
        distinct bump-commit invocations instead of the original single
        one. Both must carry the same message format and neither must
        carry `[skip ci]` — this is the structural invariant we pin here.
        """
        text = _yaml_text()
        # Locate every `git commit -m ...` line that produces a bump
        # commit (each path in the race-recovery block has one).
        bump_lines = [
            l for l in text.splitlines()
            if "git commit -m" in l and "bump dev-kit to v" in l
        ]
        self.assertGreaterEqual(
            len(bump_lines), 1,
            "expected at least one `git commit -m` line containing "
            "'bump dev-kit to v'; ensure the race-recovery block hasn't been removed")
        for bump_line in bump_lines:
            for forbidden in ("[skip ci]", "[no ci]", "[ci skip]", "[actions skip]"):
                self.assertNotIn(
                    forbidden, bump_line,
                    f"bump commit message must NOT contain {forbidden!r} — "
                    "GitHub Actions globally suppresses ALL workflows on such "
                    f"commits (and would break version-bump.yml's auto-tag step). Offending line: {bump_line!r}")
        # Sanity check: the idempotency regex (further down) still mentions
        # `[skip ci]` as an OPTIONAL suffix. That is intentional — it lets
        # old-format bump commits (which DID carry `[skip ci]`) still match
        # the regex on a squash-merge re-fire, preserving idempotency while
        # we transition. We pin that line to catch accidental cleanups.
        self.assertIn(
            "\\[skip\\ ci\\]", text,
            "idempotency regex must still tolerate '[skip ci]' as optional "
            "suffix (for backward compat with old-format bump commits)")

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

    def test_23_race_recovery_paths_present(self):
        """The PR-open step's bash must implement the 3-path race-recovery
        block (Path 1 / Path 2 / Path 3). Path 2 must use the colon-refspec
        `git push origin "${REMOTE_TIP}:${BRANCH}"` so the orphan tip is
        preserved as-is (no new SHA → no non-fast-forward). Path 3 must
        close the orphan's open PR before `force-with-lease` so
        peter-evans/enable-pull-request-automerge does not race-merge a
        stale-version commit.

        Regression: the original `git cherry-pick` recovery produced a fresh
        SHA `f86f059` on top of NEW origin/main, which was rejected as
        non-fast-forward because the remote tip was the OLDER orphan SHA.
        See `gh run view 29327530942 --log-failed` for the failing trace.
        """
        doc = _yaml_doc()
        open_step = _find_step(doc, "open auto-merge")
        self.assertIsNotNone(open_step, "expected an 'Open auto-merge PR' step")
        run = open_step.get("run", "")
        # Pin the 3-path structure
        for marker in ("Path 1", "Path 2", "Path 3"):
            self.assertIn(marker, run,
                          f"race-recovery block must declare {marker!r} "
                          "(prevents silent regression to the broken cherry-pick path)")
        # Pin Path 2's colon-refspec (the actual fix)
        self.assertRegex(run, r'git push origin "\$\{REMOTE_TIP\}:\$\{BRANCH\}"',
                         "Path 2 must push REMOTE_TIP directly via colon-refspec "
                         "so origin/${BRANCH} == REMOTE_TIP without producing a new SHA")
        # Pin Path 3's close-then-force-with-lease (defends against auto-merge race)
        self.assertIn("gh pr close", run,
                      "Path 3 must close the orphan's open PR before force-pushing "
                      "(peter-evans/enable-pull-request-automerge would race-merge otherwise)")
        self.assertIn("force-with-lease", run,
                      "Path 3 must use --force-with-lease (not --force) so the "
                      "push aborts if a concurrent racer advanced the remote")
        self.assertNotIn("git cherry-pick", run,
                         "the broken cherry-pick path must be removed; Path 2 is "
                         "the replacement (preserves orphan SHA via colon-refspec)")

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


def _load_yaml(path: Path) -> dict:
    """Load a workflow YAML file and return its parsed doc."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class TestBumpSkipFilters(unittest.TestCase):
    """Per-workflow `if:` filters that skip the bump PR (title
    `chore(release): bump dev-kit to vX.Y.Z`). This replaces the
    previous `[skip ci]` literal in the bump commit message, which
    suppressed ALL workflows on the bump push — including
    version-bump.yml's own auto-tag re-fire, which broke the round-trip.

    Files covered: ci.yml (test + validate), review.yml (review +
    security + gate). auto-fix-pr.yml triggers on `pull_request_review:
    submitted` (not on PR open/synchronize), and the bump PR is
    auto-merged by `peter-evans/enable-pull-request-automerge` so a
    human review is unlikely; left untouched here.
    """

    BUMP_TITLE_PREFIX = "chore(release): bump dev-kit to v"

    @staticmethod
    def _job_if(workflow_path: Path, job_name: str) -> str:
        """Return the `if:` clause of the named job in the workflow,
        or '' if the job has no `if:` condition at all."""
        doc = _load_yaml(workflow_path)
        jobs = doc.get("jobs", {}) or {}
        job = jobs.get(job_name, {}) or {}
        return job.get("if", "") or ""

    @staticmethod
    def _wf(name: str) -> Path:
        # WORKFLOW_PATH is `<repo>/.github/workflows/version-bump.yml`. Its
        # parent is already `.github/workflows/`, so siblings resolve there.
        return WORKFLOW_PATH.parent / name

    def _assert_skips_bump(self, workflow: Path, job_name: str):
        cond = self._job_if(workflow, job_name)
        self.assertTrue(cond,
                        f"{workflow.name}: job={job_name!r} has no `if:` — "
                        "bump-PRs would re-fire this job and cause feedback-loop noise. "
                        f"Add `!startsWith(github.event.pull_request.title, '{self.BUMP_TITLE_PREFIX}')` "
                        "(or equivalent) to its `if:` condition.")
        self.assertIn(self.BUMP_TITLE_PREFIX, cond,
                      f"{workflow.name}: job={job_name!r} `if:` must mention "
                      f"'{self.BUMP_TITLE_PREFIX}' so the bump PR is skipped")
        self.assertRegex(cond, r"!startsWith\(github\.event\.pull_request\.title",
                         f"{workflow.name}: job={job_name!r} must guard the bump-PR "
                         "skip with !startsWith(...) — not just an existence check")

    def test_16_ci_test_skips_bump_pr(self):
        self._assert_skips_bump(self._wf("ci.yml"), "test")

    def test_17_ci_validate_skips_bump_pr(self):
        self._assert_skips_bump(self._wf("ci.yml"), "validate")

    def test_18_review_review_skips_bump_pr(self):
        self._assert_skips_bump(self._wf("review.yml"), "review")

    def test_19_review_security_skips_bump_pr(self):
        self._assert_skips_bump(self._wf("review.yml"), "security")

    def test_20_review_gate_skips_bump_pr_even_under_always(self):
        """`gate` uses `if: always()` (because it depends on review +
        security and must run after a partial failure). The bump-PR skip
        must compose WITH `always()`, not replace it — i.e. the `if:` is
        `always() && !<bump-skip>` (or a YAML equivalent)."""
        cond = self._job_if(self._wf("review.yml"), "gate")
        self.assertIn("always()", cond,
                      "review.yml: job='gate' must preserve `if: always()` semantics")
        self.assertIn(self.BUMP_TITLE_PREFIX, cond,
                      f"review.yml: job='gate' `if:` must skip bump-PRs by title-prefix "
                      f"('{self.BUMP_TITLE_PREFIX}')")
        # The compose order matters: AND with always(). Accept either
        # `always() && !startsWith(...)` or `!startsWith(...) && always()`.
        self.assertRegex(cond, r"always\(\)\s*(&&|and)\s*!?startsWith",
                         "review.yml: job='gate' `if:` must compose `always()` AND "
                         "the bump-skip with a logical AND")

    def test_21_review_workflow_pull_request_trigger_includes_opened(self):
        """Sanity: review.yml must continue to trigger on `pull_request:
        opened` so the per-PR review chain still fires for non-bump PRs."""
        doc = _load_yaml(self._wf("review.yml"))
        on = doc.get("on") or doc.get(True) or {}
        pr = on.get("pull_request")
        self.assertIsNotNone(pr, "review.yml must declare pull_request trigger")
        types = pr.get("types") or []
        self.assertIn("opened", types,
                      "review.yml pull_request.types must include 'opened' "
                      "(otherwise per-PR review never fires)")

    def test_22_ci_workflow_pull_request_types_include_synchronize(self):
        """Sanity: ci.yml must include `pull_request: synchronize` so
        re-running edits to existing PRs still trigger the suite."""
        doc = _load_yaml(self._wf("ci.yml"))
        on = doc.get("on") or doc.get(True) or {}
        pr = on.get("pull_request")
        self.assertIsNotNone(pr, "ci.yml must declare pull_request trigger")
        types = pr.get("types") or []
        self.assertIn("synchronize", types,
                      "ci.yml pull_request.types must include 'synchronize' "
                      "(otherwise re-running edits skip CI)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
# verify
