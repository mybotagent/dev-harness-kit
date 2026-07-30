#!/usr/bin/env python3
"""test_ci_triage.py — regression tests for lib/ci_triage.py.

Black-box coverage:

  1. Dedup signature — stable across identical failures, distinct across
     different workflow/job/marker combinations.
  2. Case store round-trip (load/save) and the unjudged -> open lifecycle.
  3. `runs_for_commit` refuses short SHAs (the `gh run list --commit`
     silent-empty-list gotcha this module exists to avoid).
  4. `scan()` end-to-end with subprocess mocked: two commits sharing one
     failure signature collapse into a single case with two occurrences;
     a second scan against a third commit bumps occurrences without
     re-flagging the case as unjudged.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).parent.parent
LIB = REPO_ROOT / "lib"


class TestSignature(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LIB))
        from ci_triage import signature
        self.signature = signature

    def test_same_workflow_and_marker_is_stable(self):
        sig_a = self.signature("cost-flag.yml", {"job_name": None, "marker": "a workflow file issue"})
        sig_b = self.signature("cost-flag.yml", {"job_name": None, "marker": "a workflow file issue"})
        self.assertEqual(sig_a, sig_b)

    def test_different_marker_changes_signature(self):
        sig_a = self.signature("cost-flag.yml", {"job_name": None, "marker": "a workflow file issue"})
        sig_b = self.signature("cost-flag.yml", {"job_name": None, "marker": "a timeout"})
        self.assertNotEqual(sig_a, sig_b)

    def test_different_workflow_changes_signature(self):
        sig_a = self.signature("cost-flag.yml", {"job_name": "aggregate", "marker": "step X"})
        sig_b = self.signature("ci.yml", {"job_name": "aggregate", "marker": "step X"})
        self.assertNotEqual(sig_a, sig_b)


class TestStoreRoundtrip(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LIB))
        from ci_triage import SCHEMA_VERSION, load_store, save_store
        self.load_store = load_store
        self.save_store = save_store
        self.schema_version = SCHEMA_VERSION

    def test_missing_store_returns_empty_schema(self):
        with tempfile.TemporaryDirectory() as d:
            store = self.load_store(Path(d) / "nope.json")
            self.assertEqual(store, {"schema_version": self.schema_version, "cases": []})

    def test_save_then_load_roundtrips(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "store.json"
            store = {"schema_version": 1, "cases": [{"id": "abc", "occurrences": []}]}
            self.save_store(path, store)
            self.assertTrue(path.exists())
            self.assertEqual(self.load_store(path), store)


class TestRecordOccurrenceAndJudgment(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LIB))
        from ci_triage import find_case, record_judgment, record_occurrence
        self.record_occurrence = record_occurrence
        self.record_judgment = record_judgment
        self.find_case = find_case

    def test_first_occurrence_creates_unjudged_stub(self):
        store = {"schema_version": 1, "cases": []}
        case = self.record_occurrence(store, "sig1", "cost-flag.yml", {"commit": "a", "run_id": 1})
        self.assertEqual(case["status"], "unjudged")
        self.assertEqual(len(case["occurrences"]), 1)
        self.assertEqual(len(store["cases"]), 1)

    def test_second_occurrence_appends_not_duplicates(self):
        store = {"schema_version": 1, "cases": []}
        self.record_occurrence(store, "sig1", "cost-flag.yml", {"commit": "a", "run_id": 1})
        self.record_occurrence(store, "sig1", "cost-flag.yml", {"commit": "b", "run_id": 2})
        self.assertEqual(len(store["cases"]), 1)
        self.assertEqual(len(store["cases"][0]["occurrences"]), 2)

    def _judge_kwargs(self, **overrides):
        base = dict(
            primary_cause="harness", secondary_cause="state-contamination",
            evidence="workflow updated_at (2026-07-14) predates file's last commit (2026-07-16)",
            repro="gh api repos/:owner/:repo/actions/workflows/312869658 | jq .updated_at",
            regression_test="tests/test_ci_doctor.py::test_workflow_registration_freshness",
            proposal="gh api -X PUT .../workflows/312869658/disable then enable",
        )
        base.update(overrides)
        return base

    def test_record_judgment_transitions_to_open(self):
        store = {"schema_version": 1, "cases": []}
        self.record_occurrence(store, "sig1", "cost-flag.yml", {"commit": "a", "run_id": 1})
        self.record_judgment(store, "sig1", **self._judge_kwargs(hook_proposal="post-edit re-registration check"))
        case = self.find_case(store, "sig1")
        self.assertEqual(case["status"], "open")
        self.assertEqual(case["primary_cause"], "harness")
        self.assertEqual(case["secondary_cause"], "state-contamination")
        self.assertEqual(case["hook_proposal"], "post-edit re-registration check")

    def test_record_judgment_unknown_id_raises(self):
        store = {"schema_version": 1, "cases": []}
        with self.assertRaises(KeyError):
            self.record_judgment(store, "missing", **self._judge_kwargs())

    def test_record_judgment_rejects_unknown_primary_cause(self):
        store = {"schema_version": 1, "cases": []}
        self.record_occurrence(store, "sig1", "cost-flag.yml", {"commit": "a", "run_id": 1})
        with self.assertRaises(ValueError):
            self.record_judgment(store, "sig1", **self._judge_kwargs(primary_cause="infra"))

    def test_record_judgment_rejects_secondary_not_under_primary(self):
        store = {"schema_version": 1, "cases": []}
        self.record_occurrence(store, "sig1", "cost-flag.yml", {"commit": "a", "run_id": 1})
        with self.assertRaises(ValueError):
            self.record_judgment(
                store, "sig1", **self._judge_kwargs(primary_cause="model", secondary_cause="state-contamination"),
            )

    def test_record_judgment_requires_regression_test(self):
        store = {"schema_version": 1, "cases": []}
        self.record_occurrence(store, "sig1", "cost-flag.yml", {"commit": "a", "run_id": 1})
        with self.assertRaises(ValueError):
            self.record_judgment(store, "sig1", **self._judge_kwargs(regression_test=""))

    def test_record_judgment_requires_repro(self):
        store = {"schema_version": 1, "cases": []}
        self.record_occurrence(store, "sig1", "cost-flag.yml", {"commit": "a", "run_id": 1})
        with self.assertRaises(ValueError):
            self.record_judgment(store, "sig1", **self._judge_kwargs(repro=""))

    def test_record_judgment_allows_na_regression_test_with_reason(self):
        store = {"schema_version": 1, "cases": []}
        self.record_occurrence(store, "sig1", "cost-flag.yml", {"commit": "a", "run_id": 1})
        self.record_judgment(
            store, "sig1", **self._judge_kwargs(regression_test="N/A: third-party outage, no repo-side guard possible"),
        )
        case = self.find_case(store, "sig1")
        self.assertTrue(case["regression_test"].startswith("N/A:"))


class TestRunsForCommitValidation(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LIB))
        from ci_triage import runs_for_commit
        self.runs_for_commit = runs_for_commit

    def test_short_sha_raises_before_any_subprocess_call(self):
        with self.assertRaises(ValueError):
            self.runs_for_commit("060d53b")


class TestScanIntegration(unittest.TestCase):
    """End-to-end scan() with subprocess mocked at the module's `_run` seam."""

    def setUp(self):
        sys.path.insert(0, str(LIB))
        import ci_triage
        self.mod = ci_triage
        self.commit_a = "a" * 40
        self.commit_b = "b" * 40
        self.commit_c = "c" * 40

    def _fake_run(self, cmd: list[str]) -> str:
        if cmd[:2] == ["git", "rev-parse"]:
            ref = cmd[2]
            return {"A": self.commit_a, "B": self.commit_b, "C": self.commit_c}[ref] + "\n"
        if cmd[:2] == ["git", "log"] and "-1" in cmd:
            sha = cmd[-1]
            return f"docs: fix thing {sha[0]}\x1fbot@users.noreply.github.com\x1f\n"
        if cmd[:3] == ["gh", "run", "list"]:
            sha = cmd[cmd.index("--commit") + 1]
            run_id = {self.commit_a: 101, self.commit_b: 102, self.commit_c: 103}[sha]
            return json.dumps([{
                "databaseId": run_id, "name": "cost-flag.yml", "status": "completed",
                "conclusion": "failure", "event": "push", "headBranch": "main",
                "createdAt": "2026-07-30T08:00:00Z", "url": f"https://example/{run_id}",
            }])
        if cmd[:3] == ["gh", "api", "repos/:owner/:repo/actions/runs/101/jobs"] or \
           cmd[2].endswith("/jobs"):
            return json.dumps({"total_count": 0, "jobs": []})
        if cmd[:3] == ["gh", "run", "view"] and "--log-failed" not in cmd:
            return "X This run likely failed because of a workflow file issue.\n"
        raise AssertionError(f"unexpected command: {cmd}")

    def test_two_commits_same_failure_collapse_to_one_case(self):
        with tempfile.TemporaryDirectory() as d:
            store_path = Path(d) / "store.json"
            with patch.object(self.mod, "_run", side_effect=self._fake_run):
                result = self.mod.scan(commits=["A", "B"], count=None, store_path=store_path)

            self.assertEqual(len(result["unjudged"]), 1)
            case = result["unjudged"][0]["case"]
            self.assertEqual(len(case["occurrences"]), 2)

            store = self.mod.load_store(store_path)
            self.assertEqual(len(store["cases"]), 1)
            self.assertEqual(store["cases"][0]["status"], "unjudged")

    def test_rescan_after_judging_bumps_occurrence_not_unjudged(self):
        with tempfile.TemporaryDirectory() as d:
            store_path = Path(d) / "store.json"
            with patch.object(self.mod, "_run", side_effect=self._fake_run):
                first = self.mod.scan(commits=["A"], count=None, store_path=store_path)
            case_id = first["unjudged"][0]["case"]["id"]

            store = self.mod.load_store(store_path)
            self.mod.record_judgment(
                store, case_id, primary_cause="harness", secondary_cause="state-contamination",
                evidence="ev", repro="repro", regression_test="tests/test_x.py::test_y", proposal="prop",
            )
            self.mod.save_store(store_path, store)

            with patch.object(self.mod, "_run", side_effect=self._fake_run):
                second = self.mod.scan(commits=["C"], count=None, store_path=store_path)

            self.assertEqual(len(second["unjudged"]), 0)
            self.assertEqual(len(second["already_known"]), 1)
            self.assertEqual(len(second["already_known"][0]["occurrences"]), 2)


class TestFailureSignalsMultiJob(unittest.TestCase):
    """Regression test for a real dogfooding failure: a single run can fail
    more than one job at the same step name (e.g. `review` and `security`
    both failing at "Resolve PR + provider"). `failure_signals` must return
    one entry per failing job, not just the first, and must not cross-
    attribute one job's log lines to another job's entry."""

    def setUp(self):
        sys.path.insert(0, str(LIB))
        import ci_triage
        self.mod = ci_triage

    def _fake_run(self, cmd: list[str]) -> str:
        if cmd[:2] == ["gh", "api"] and cmd[2].endswith("/jobs"):
            return json.dumps({"jobs": [
                {"name": "/dev-kit:review (3-dim)", "conclusion": "failure",
                 "steps": [{"name": "Resolve PR + provider", "conclusion": "failure"}]},
                {"name": "/dev-kit:security (10-dim OWASP)", "conclusion": "failure",
                 "steps": [{"name": "Resolve PR + provider", "conclusion": "failure"}]},
                {"name": "severity gate", "conclusion": "success", "steps": []},
            ]})
        if cmd[:3] == ["gh", "run", "view"] and "--log-failed" in cmd:
            return (
                "/dev-kit:review (3-dim)\tResolve PR + provider\tts review-specific error line\n"
                "/dev-kit:security (10-dim OWASP)\tResolve PR + provider\tts security-specific error line\n"
            )
        raise AssertionError(f"unexpected command: {cmd}")

    def test_returns_one_signal_per_failing_job(self):
        with patch.object(self.mod, "_run", side_effect=self._fake_run):
            signals = self.mod.failure_signals(999)
        self.assertEqual(len(signals), 2)
        job_names = {s["job_name"] for s in signals}
        self.assertEqual(job_names, {"/dev-kit:review (3-dim)", "/dev-kit:security (10-dim OWASP)"})

    def test_detail_is_not_cross_attributed_between_jobs(self):
        with patch.object(self.mod, "_run", side_effect=self._fake_run):
            signals = self.mod.failure_signals(999)
        by_job = {s["job_name"]: s["detail"] for s in signals}
        self.assertIn("review-specific error line", by_job["/dev-kit:review (3-dim)"])
        self.assertNotIn("security-specific error line", by_job["/dev-kit:review (3-dim)"])
        self.assertIn("security-specific error line", by_job["/dev-kit:security (10-dim OWASP)"])
        self.assertNotIn("review-specific error line", by_job["/dev-kit:security (10-dim OWASP)"])

    def test_scan_creates_two_distinct_cases_for_one_run_with_two_failed_jobs(self):
        def fake_run(cmd: list[str]) -> str:
            if cmd[:2] == ["git", "rev-parse"]:
                return "d" * 40 + "\n"
            if cmd[:2] == ["git", "log"] and "-1" in cmd:
                return "subject\x1fauthor@x\x1f\n"
            if cmd[:3] == ["gh", "run", "list"]:
                return json.dumps([{
                    "databaseId": 999, "name": "PR Review", "status": "completed",
                    "conclusion": "failure", "event": "pull_request", "headBranch": "x",
                    "createdAt": "2026-07-30T09:00:00Z", "url": "https://example/999",
                }])
            return self._fake_run(cmd)

        with tempfile.TemporaryDirectory() as d:
            store_path = Path(d) / "store.json"
            with patch.object(self.mod, "_run", side_effect=fake_run):
                result = self.mod.scan(commits=["D"], count=None, store_path=store_path)
            self.assertEqual(len(result["unjudged"]), 2)


class TestFailureSignalsErrorAnnotationPreferred(unittest.TestCase):
    """Regression test for a second dogfooding failure: the real error is a
    `##[error]` annotation mid-log, but a large "Post job cleanup" section
    (git config teardown boilerplate that's present on every job,
    pass or fail) follows it. Blindly tailing the last 4000 chars of a
    job's lines landed in that boilerplate and lost the actual error."""

    def setUp(self):
        sys.path.insert(0, str(LIB))
        import ci_triage
        self.mod = ci_triage

    def _fake_run(self, cmd: list[str]) -> str:
        if cmd[:2] == ["gh", "api"] and cmd[2].endswith("/jobs"):
            return json.dumps({"jobs": [
                {"name": "review", "conclusion": "failure",
                 "steps": [{"name": "Resolve PR + provider", "conclusion": "failure"}]},
            ]})
        if cmd[:3] == ["gh", "run", "view"] and "--log-failed" in cmd:
            cleanup = "".join(f"review\tUNKNOWN STEP\tts cleanup line {i}\n" for i in range(200))
            return (
                "review\tResolve PR + provider\tts ##[error]No provider resolved. Set the GitHub repo variable:\n"
                "review\tResolve PR + provider\tts ##[error]Process completed with exit code 1.\n"
                + cleanup
            )
        raise AssertionError(f"unexpected command: {cmd}")

    def test_error_annotation_survives_despite_trailing_cleanup_boilerplate(self):
        with patch.object(self.mod, "_run", side_effect=self._fake_run):
            signals = self.mod.failure_signals(999)
        self.assertEqual(len(signals), 1)
        self.assertIn("No provider resolved", signals[0]["detail"])
        self.assertNotIn("cleanup line", signals[0]["detail"])


class TestRenderReport(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LIB))
        from ci_triage import render_report
        self.render_report = render_report

    def test_empty_store(self):
        out = self.render_report({"schema_version": 1, "cases": []})
        self.assertIn("No failure cases recorded yet.", out)

    def test_judged_case_includes_cause_repro_and_regression_test(self):
        store = {"schema_version": 1, "cases": [{
            "id": "sig1", "workflow": "cost-flag.yml", "status": "open",
            "primary_cause": "harness", "secondary_cause": "state-contamination",
            "evidence": "ev", "repro": "gh api ...", "proposal": "prop",
            "regression_test": "tests/test_ci_doctor.py::test_x", "hook_proposal": "hook",
            "occurrences": [{"commit": "a"}],
        }]}
        out = self.render_report(store)
        self.assertIn("harness / state-contamination", out)
        self.assertIn("tests/test_ci_doctor.py::test_x", out)


if __name__ == "__main__":
    unittest.main()
