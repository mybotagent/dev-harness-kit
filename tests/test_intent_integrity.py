#!/usr/bin/env python3
"""test_intent_integrity.py — RED-first tests for lib/intent_integrity.py.

Covers IC-1..IC-4 (pre-build checks only). Tests build fixtures inline so
the suite is self-contained and fast — no shell-out to `python -m`.

Convention (matches tests/test_atomic.py): `sys.path.insert(0, lib/)`
so the module-under-test is importable as a flat name.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import intent_integrity  # noqa: E402

# ---------- helpers (test-only, never imported elsewhere) ----------


def _write_step(
    step_num: int,
    name: str,
    *,
    acceptance: list[str] | None = None,
    dependencies: list[int] | None = None,
    verification: str = "pytest tests/test_x.py -q",
    body_extras: str = "",
) -> str:
    """Render a phases/<name>/step<N>.md body."""
    lines = [f"step: {step_num}", f"name: {name}", "owner: dev", "acceptance:"]
    if acceptance is None:
        acceptance = [f"implements step {step_num}"]
    for a in acceptance:
        lines.append(f"  - {a}")
    lines.append("dependencies:")
    for d in dependencies or []:
        lines.append(f"  - {d}")
    lines.append("verification:")
    lines.append(f"  - {verification}")
    if body_extras:
        lines.append(body_extras)
    return "\n".join(lines) + "\n"


def _setup_phase(
    tmp: Path,
    *,
    prd_requirements: list[str],
    steps: list[dict],
) -> tuple[Path, Path]:
    """Materialize phases/demo/ + PRD.md under `tmp`. Return (prd_path, plan_dir)."""
    prd = tmp / "PRD.md"
    prd_lines = ["# PRD", ""]
    for req in prd_requirements:
        prd_lines.append(f"- {req}")
    prd.write_text("\n".join(prd_lines) + "\n", encoding="utf-8")

    phase_dir = tmp / "phases" / "demo"
    phase_dir.mkdir(parents=True, exist_ok=True)

    index = {"steps": []}
    for s in steps:
        sn = s["step_num"]
        body = _write_step(
            sn,
            s.get("name", f"step{sn}"),
            acceptance=s.get("acceptance"),
            dependencies=s.get("dependencies"),
            verification=s.get("verification", "pytest tests/test_x.py -q"),
            body_extras=s.get("body_extras", ""),
        )
        (phase_dir / f"step{sn}.md").write_text(body, encoding="utf-8")
        index["steps"].append({
            "step": sn,
            "name": s.get("name", f"step{sn}"),
            "status": "pending",
        })
    (phase_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")
    return prd, phase_dir


def _by_id(findings, code: str) -> list:
    return [f for f in findings if f.finding_id == code]


# ---------- IC-1 / IC-2 happy path ----------


class TestPreNoFindings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_three_reqs_three_steps_each_references_one(self):
        prd, phase = _setup_phase(
            self.root,
            prd_requirements=["REQ-1: alpha", "REQ-2: beta", "REQ-3: gamma"],
            steps=[
                {"step_num": 1, "name": "alpha",
                 "acceptance": ["implements REQ-1 — alpha feature"]},
                {"step_num": 2, "name": "beta",
                 "acceptance": ["implements REQ-2 — beta feature"]},
                {"step_num": 3, "name": "gamma",
                 "acceptance": ["implements REQ-3 — gamma feature"]},
            ],
        )
        findings = intent_integrity.analyze(phase, prd)
        self.assertEqual(
            findings, [],
            f"expected zero findings, got: "
            f"{[(f.finding_id, f.severity, f.evidence) for f in findings]}",
        )


# ---------- IC-1 ----------


class TestPreMissingRequirement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_three_reqs_only_one_step_referencing(self):
        prd, phase = _setup_phase(
            self.root,
            prd_requirements=["REQ-1: alpha", "REQ-2: beta", "REQ-3: gamma"],
            steps=[
                {"step_num": 1, "name": "alpha",
                 "acceptance": ["implements REQ-1 — alpha only"]},
            ],
        )
        findings = intent_integrity.analyze(phase, prd)
        ic1 = _by_id(findings, "IC-1")
        self.assertEqual(
            len(ic1), 2,
            f"expected 2 missing-requirement findings, got {len(ic1)}: {ic1}",
        )
        self.assertTrue(
            all(f.severity == "high" for f in ic1),
            f"all IC-1 findings must be high severity, got: "
            f"{[(f.finding_id, f.severity) for f in ic1]}",
        )
        evidences = " ".join(f.evidence for f in ic1)
        self.assertIn("REQ-2", evidences)
        self.assertIn("REQ-3", evidences)
        # Action should be actionable, not restate the problem.
        self.assertTrue(
            all(f.action and f.action != f.evidence for f in ic1),
            "every IC-1 finding must carry a distinct `action`",
        )


# ---------- IC-2 ----------


class TestPreOrphanStep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_req_two_steps_one_unreferenced(self):
        prd, phase = _setup_phase(
            self.root,
            prd_requirements=["REQ-1: alpha"],
            steps=[
                {"step_num": 1, "name": "alpha",
                 "acceptance": ["implements REQ-1"]},
                {"step_num": 2, "name": "delta",
                 "acceptance": ["does some extra work"]},
            ],
        )
        findings = intent_integrity.analyze(phase, prd)
        ic2 = _by_id(findings, "IC-2")
        self.assertEqual(
            len(ic2), 1,
            f"expected exactly 1 orphan-step finding, got {len(ic2)}: {ic2}",
        )
        self.assertEqual(ic2[0].severity, "high")
        # Evidence must point at step2 (the unreferenced one).
        self.assertIn("2", ic2[0].evidence)

    def test_no_prd_requirements_skips_orphan_check(self):
        """If PRD has no extractable requirements, IC-2 is N/A (not 'every step is orphan')."""
        prd, phase = _setup_phase(
            self.root,
            prd_requirements=[],  # empty PRD
            steps=[
                {"step_num": 1, "name": "alpha", "acceptance": ["anything"]},
            ],
        )
        findings = intent_integrity.analyze(phase, prd)
        ic2 = _by_id(findings, "IC-2")
        self.assertEqual(
            ic2, [],
            f"with no PRD requirements IC-2 must be skipped, got: {ic2}",
        )


# ---------- IC-3 ----------


class TestPreDependencyGap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dependency_on_missing_step(self):
        prd, phase = _setup_phase(
            self.root,
            prd_requirements=["REQ-1: alpha"],
            steps=[
                {"step_num": 1, "name": "alpha",
                 "acceptance": ["implements REQ-1"],
                 "dependencies": [99]},
            ],
        )
        findings = intent_integrity.analyze(phase, prd)
        ic3 = _by_id(findings, "IC-3")
        self.assertEqual(
            len(ic3), 1,
            f"expected 1 dependency-gap finding, got {len(ic3)}: {ic3}",
        )
        self.assertEqual(ic3[0].severity, "medium")
        self.assertIn("99", ic3[0].evidence)

    def test_dependency_on_existing_step_no_finding(self):
        prd, phase = _setup_phase(
            self.root,
            prd_requirements=["REQ-1: alpha", "REQ-2: beta"],
            steps=[
                {"step_num": 1, "name": "alpha",
                 "acceptance": ["implements REQ-1"],
                 "dependencies": [2]},
                {"step_num": 2, "name": "beta",
                 "acceptance": ["implements REQ-2"]},
            ],
        )
        findings = intent_integrity.analyze(phase, prd)
        ic3 = _by_id(findings, "IC-3")
        self.assertEqual(ic3, [], f"no dependency gap expected, got: {ic3}")


# ---------- IC-4 ----------


class TestPreDeadVerification(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_verification(self):
        prd, phase = _setup_phase(
            self.root,
            prd_requirements=["REQ-1: alpha"],
            steps=[
                {"step_num": 1, "name": "alpha",
                 "acceptance": ["implements REQ-1"],
                 "verification": ""},
            ],
        )
        findings = intent_integrity.analyze(phase, prd)
        ic4 = _by_id(findings, "IC-4")
        self.assertEqual(
            len(ic4), 1,
            f"expected 1 dead-verification finding, got {len(ic4)}: {ic4}",
        )
        self.assertEqual(ic4[0].severity, "medium")

    def test_garbage_verification(self):
        prd, phase = _setup_phase(
            self.root,
            prd_requirements=["REQ-1: alpha"],
            steps=[
                {"step_num": 1, "name": "alpha",
                 "acceptance": ["implements REQ-1"],
                 "verification": "this is not a command"},
            ],
        )
        findings = intent_integrity.analyze(phase, prd)
        ic4 = _by_id(findings, "IC-4")
        self.assertEqual(
            len(ic4), 1,
            f"non-shell text should be IC-4, got: {ic4}",
        )

    def test_real_command_passes(self):
        prd, phase = _setup_phase(
            self.root,
            prd_requirements=["REQ-1: alpha"],
            steps=[
                {"step_num": 1, "name": "alpha",
                 "acceptance": ["implements REQ-1"],
                 "verification": "pytest tests/test_alpha.py -q"},
            ],
        )
        findings = intent_integrity.analyze(phase, prd)
        ic4 = _by_id(findings, "IC-4")
        self.assertEqual(ic4, [], f"real command must not be IC-4, got: {ic4}")


# ---------- Confirmed flag (cross-run duplicate) ----------


class TestPreConfirmedFlag(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_duplicate_evidence_marks_second_as_confirmed(self):
        """Same finding_id+evidence appearing twice in one run → confirmed=True."""
        # Build a PRD with 2 missing reqs, then call analyze() twice and concat.
        prd, phase = _setup_phase(
            self.root,
            prd_requirements=["REQ-1: alpha", "REQ-2: beta"],
            steps=[
                {"step_num": 1, "name": "alpha",
                 "acceptance": ["implements REQ-1 only — really only REQ-1"]},
            ],
        )
        first = intent_integrity.analyze(phase, prd)
        second = intent_integrity.analyze(phase, prd)
        merged = first + second

        # The duplicates should now exist. Mark confirmed on second pass.
        intent_integrity.mark_confirmed(merged)
        ic1 = _by_id(merged, "IC-1")
        # At least one finding should be confirmed.
        self.assertTrue(
            any(f.confirmed for f in ic1),
            f"expected at least one confirmed finding, got: "
            f"{[(f.evidence, f.confirmed) for f in ic1]}",
        )


# ---------- Path-traversal guard (CLI entry point) ----------


class TestCliPathGuard(unittest.TestCase):
    """The CLI must reject `--pre` values that would escape
    `.dev-kit/integrity/` (e.g. `../../etc`). Regression for the
    /dev-kit:review minor findings."""

    def _run_main_capture(self, argv):
        """Run main() swallowing SystemExit (argparse calls sys.exit on error)."""
        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        with redirect_stderr(buf):
            try:
                rc = intent_integrity.main(argv)
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 2
        return rc

    def test_rejects_dotdot_phase(self):
        rc = self._run_main_capture(["--pre", "../etc"])
        self.assertEqual(rc, 2, "path-traversal phase must be rejected (exit 2)")

    def test_rejects_slash_phase(self):
        rc = self._run_main_capture(["--pre", "a/b"])
        self.assertEqual(rc, 2, "phase with slash must be rejected (exit 2)")

    def test_accepts_normal_phase(self):
        # Pass a benign phase + nonexistent root → we want to confirm the
        # regex guard did NOT trip. Exit code 2 is expected from the
        # phase-dir-not-found branch, which is a DIFFERENT code path.
        rc = self._run_main_capture(["--pre", "demo", "--root", "/nonexistent-root-xyz"])
        self.assertEqual(rc, 2)


# ---------- Substring-safety regression (Fix 1) ----------


class TestSubstringSafety(unittest.TestCase):
    """Regression: IC-1 / IC-2 must not treat `REQ-1` as referenced
    by a step mentioning `REQ-10`. Plain substring `in` check collides
    on shared prefixes; the fix uses word-boundary regex."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_req1_unreferenced_when_only_req10_present(self):
        """PRD: REQ-1, REQ-10. Step references REQ-1 only.
        Expectation: REQ-10 is missing (IC-1), no orphan (IC-2 = 0)."""
        prd, phase = _setup_phase(
            self.root,
            prd_requirements=["REQ-1: alpha", "REQ-10: beta"],
            steps=[
                {"step_num": 1, "name": "alpha",
                 "acceptance": ["implements REQ-1 only"]},
            ],
        )
        findings = intent_integrity.analyze(phase, prd)
        ic1 = _by_id(findings, "IC-1")
        ic2 = _by_id(findings, "IC-2")
        # Exactly one IC-1 (REQ-10 missing); word-boundary regex must
        # not flag REQ-1 as missing just because REQ-10 is also present.
        self.assertEqual(
            len(ic1), 1,
            f"expected exactly 1 IC-1 (REQ-10), got: {ic1}",
        )
        # The IC-1 evidence must open with the missing ID; this also
        # confirms the substring collision is gone (REQ-1 must NOT
        # appear as a standalone missing requirement).
        self.assertTrue(
            ic1[0].evidence.startswith("REQ-10"),
            f"only REQ-10 should be reported missing, got: {ic1[0].evidence!r}",
        )
        self.assertEqual(
            ic2, [],
            f"step1 references REQ-1 → no IC-2 orphan, got: {ic2}",
        )

    def test_req10_unreferenced_when_only_req1_present(self):
        """Mirror of the above: step references REQ-10 only.
        REQ-1 must be flagged as missing (no false-negative from prefix)."""
        prd, phase = _setup_phase(
            self.root,
            prd_requirements=["REQ-1: alpha", "REQ-10: beta"],
            steps=[
                {"step_num": 1, "name": "alpha",
                 "acceptance": ["implements REQ-10 only"]},
            ],
        )
        findings = intent_integrity.analyze(phase, prd)
        ic1 = _by_id(findings, "IC-1")
        ic2 = _by_id(findings, "IC-2")
        self.assertEqual(
            len(ic1), 1,
            f"expected exactly 1 IC-1 (REQ-1), got: {ic1}",
        )
        self.assertTrue(
            ic1[0].evidence.startswith("REQ-1"),
            f"only REQ-1 should be reported missing, got: {ic1[0].evidence!r}",
        )
        self.assertEqual(
            ic2, [],
            f"step1 references REQ-10 → no IC-2 orphan, got: {ic2}",
        )


if __name__ == "__main__":
    unittest.main()
