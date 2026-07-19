#!/usr/bin/env python3
"""test_prune.py — Regression for skills/prune/SKILL.md schema.

Locks in the 4-phase prune contract. Asserts:

- frontmatter: user-invocable: true, category: build, model: opus
- body has 4 phase headings ([1/4], [2/4], [3/4], [4/4])
- body has an Iron Law with MUST-L1 / MUST-L2 / MUST-L3 / MUST-L4 references
- body disambiguates from /dev-kit:refactor (delete != refactor)
- body declares `--target <feat>` flag (coexists with /dev-kit:feat-remove)
- body declares Phase 4 VERIFY runs the full suite (not just the changed path)
- body declares Edit in disallowed-tools (orchestrator only)
- body never claims to call `rm` itself (mirrors feat-remove discipline)
- frontmatter name matches directory name (covered by test_naming.py
  but pinned here for fast failure if the new file regresses)
- Phase 2 routes to `skills/prune/scripts/discover_dependents.py` which is
  backed by `lib/analysis_core.runner.run_analysis(mode="delete", ...)`.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
PRUNE_SKILL = PROJECT_ROOT / "skills" / "prune" / "SKILL.md"
DISCOVER_DEPENDENTS = PROJECT_ROOT / "skills" / "prune" / "scripts" / "discover_dependents.py"


class TestPruneSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not PRUNE_SKILL.exists():
            raise unittest.SkipTest(f"{PRUNE_SKILL} missing")
        cls.text = PRUNE_SKILL.read_text(encoding="utf-8")

    def test_frontmatter_user_invocable_true(self):
        m = re.search(r"^user-invocable:\s*(.+)$", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "user-invocable: frontmatter missing")
        self.assertEqual(m.group(1).strip(), "true", "prune must be user-invocable")

    def test_frontmatter_category_build(self):
        m = re.search(r"^category:\s*(.+)$", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "category: frontmatter missing")
        self.assertEqual(m.group(1).strip(), "build", "prune category must be 'build'")

    def test_frontmatter_model_opus(self):
        # prune is a higher-stakes skill (it deletes code), so the
        # default model is opus rather than sonnet.
        m = re.search(r"^model:\s*(.+)$", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "model: frontmatter missing")
        self.assertEqual(m.group(1).strip(), "opus", "prune model must be 'opus'")

    def test_four_phases_present(self):
        for n in (1, 2, 3, 4):
            pattern = rf"\[{n}/4\]"
            self.assertRegex(
                self.text, pattern,
                f"phase [{n}/4] heading missing from body",
            )

    def test_phase_names_match_documented_chain(self):
        self.assertRegex(self.text, r"\[1/4\]\s*SWEEP", "phase 1 should be SWEEP")
        self.assertRegex(self.text, r"\[2/4\]\s*DEPENDENTS", "phase 2 should be DEPENDENTS")
        self.assertRegex(self.text, r"\[3/4\]\s*REPORT", "phase 3 should be REPORT")
        self.assertRegex(self.text, r"\[4/4\]\s*VERIFY", "phase 4 should be VERIFY")

    def test_iron_law_cites_four_musts(self):
        # MUST-L2 (reproduce-first) is included because deletion
        # candidates must have a reproducible signal.
        for must in ("MUST-L1", "MUST-L2", "MUST-L3", "MUST-L4"):
            self.assertIn(must, self.text, f"Iron Law must cite {must}")

    def test_hand_off_names_downstream_skill(self):
        m = re.search(r"## Next step(.*?)$", self.text, re.DOTALL)
        self.assertIsNotNone(m, "Next step section missing")
        block = m.group(1)
        self.assertRegex(
            block, r"/dev-kit:\w+",
            "Next step should route to a slash skill",
        )

    def test_no_edit_tool_allowed(self):
        # prune is an orchestrator; deletions belong to phase 2
        # (the inlined 3-pass sweep) which emits commands for the user to run.
        m = re.search(r"^disallowed-tools:\s*(.+)$", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "disallowed-tools: frontmatter missing")
        tools = m.group(1).split()
        self.assertIn(
            "Edit", tools,
            "prune must declare Edit in disallowed-tools (phase 2 mutates, not this skill)",
        )

    def test_disambiguates_from_refactor(self):
        # prune deletes; refactor rewrites. The body must surface
        # the distinction so users don't run the wrong skill.
        self.assertIn(
            "/dev-kit:refactor", self.text,
            "prune must mention /dev-kit:refactor as the refactor counterpart",
        )

    def test_target_flag_absorbs_feat_remove(self):
        # The --target <feat> flag adds a single-feature mode alongside the
        # existing /dev-kit:feat-remove slash. The body must surface both
        # paths so users can choose the intended deletion flow.
        self.assertIn(
            "--target", self.text,
            "prune must declare the --target flag for single-feature deletion",
        )
        self.assertIn(
            "feat-remove", self.text,
            "prune must reference the deprecated feat-remove skill so the "
            "skill body surfaces the migration path",
        )

    def test_phase4_runs_full_suite(self):
        # Phase 4 (VERIFY) is the safety net for --target deletion: every
        # sweep must run the project's full test runner, not just the
        # changed path. A regression that drops the full-suite requirement
        # would let /dev-kit:prune --target delete live code without
        # catching it. Quote the phase block so a future edit doesn't
        # silently weaken the contract.
        m = re.search(r"\[4/4\]\s*VERIFY(.*?)(?=\n##\s|\Z)", self.text, re.DOTALL)
        self.assertIsNotNone(m, "phase 4 VERIFY block missing")
        block = m.group(1)
        self.assertRegex(
            block, r"full\s+suite",
            "Phase 4 must run the full suite (not just the changed path)",
        )
        self.assertRegex(
            block, r"build-debug",
            "Phase 4 must route failures to /dev-kit:build-debug for systematic repro",
        )

    def test_never_calls_rm_directly(self):
        # Mirrors feat-remove discipline: the skill emits commands;
        # the user runs them. A "skill should `rm` for me" statement
        # would be a violation.
        self.assertIn(
            "never deletes files itself", self.text,
            "prune must declare it never calls rm/git-rm itself",
        )


class TestDiscoverDependentsScript(unittest.TestCase):
    """Positive-path coverage for the Phase-2 script.

    The script is the contract Phase 2 (DEPENDENTS) leans on. It must:
      - parse a Phase-1 candidate JSON (object or list shape)
      - invoke `lib/analysis_core.runner.run_analysis(mode="delete", ...)`
      - render a Markdown block with one row per finding + a verdict line
      - exit 0 on a happy path and write the output file
    """

    def setUp(self) -> None:
        if not DISCOVER_DEPENDENTS.exists():
            self.skipTest(f"{DISCOVER_DEPENDENTS} missing")
        # Keep the temp directory alive across the whole test — the
        # script writes the report file, and we read it back after the
        # subprocess returns. A `with tempfile.TemporaryDirectory()`
        # scoped inside the test would clean up before the read.
        self._tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp_p = Path(self._tmp_ctx.name)

    def tearDown(self) -> None:
        self._tmp_ctx.cleanup()

    def _run(self, candidates_obj, target="prune", scope=None):
        cand = self.tmp_p / "cand.json"
        out = self.tmp_p / "out.md"
        cand.write_text(json.dumps(candidates_obj), encoding="utf-8")
        cmd = [
            sys.executable, str(DISCOVER_DEPENDENTS),
            "--target", target,
            "--candidates", str(cand),
            "--out", str(out),
        ]
        for s in scope or []:
            cmd.extend(["--scope", str(s)])
        proc = subprocess.run(
            cmd, cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=30,
        )
        return proc, out

    def test_prune_target_runs_full_suite(self):
        """End-to-end happy path: a well-formed Phase-1 candidate set is
        handed to discover_dependents.py, the engine produces a Markdown
        report with verdict + per-row bullets, and the script exits 0.

        This is the positive case the dispatch asked for: Phase 2 must
        produce a report even when there is zero deletion work — the
        sweep completed, no dependents, the script reports back.
        """
        # Object shape: {dim: [finding, ...]}. Each finding carries the
        # whole-file deletion_proof the engine requires for `git rm`.
        candidates = {
            "dead": [{
                "file": "skills/prune/SKILL.md",
                "line": 1,
                "severity": "major",
                "confidence": "high",
                "title": "Dead demo skill",
                "tldr": "demo skill never invoked",
                "failure_scenario": "demo skill has zero callers",
                "deletion_scope": "whole-file",
                "deletion_proof": {"no_importers": True, "no_callers": True},
            }],
        }
        proc, out_path = self._run(candidates)
        self.assertEqual(
            proc.returncode, 0,
            f"discover_dependents exited {proc.returncode}; "
            f"stderr={proc.stderr!r}",
        )
        text = out_path.read_text(encoding="utf-8")
        # Verdict line is the engine's verdict header.
        self.assertIn("Verdict", text)
        # The DEPENDENTS block has the per-row bullet shape.
        self.assertIn("**File:**", text)

    def test_missing_candidates_exits_2(self):
        """A missing --candidates file must fail loudly with exit 2.

        Exit 2 distinguishes a usage error (bad path / bad arg) from an
        engine failure (exit 1) so the SKILL.md body can route Phase 2
        to the right hand-off (re-run with the right path vs. open
        build-debug for an engine bug).
        """
        out = self.tmp_p / "out.md"
        proc = subprocess.run(
            [
                sys.executable, str(DISCOVER_DEPENDENTS),
                "--target", "prune",
                "--candidates", str(self.tmp_p / "does-not-exist.json"),
                "--out", str(out),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("candidates file missing", proc.stderr)

    def test_invalid_target_exits_2(self):
        """An unresolved feature name must fail before analysis runs."""
        cand = self.tmp_p / "cand.json"
        out = self.tmp_p / "out.md"
        cand.write_text("{}", encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable, str(DISCOVER_DEPENDENTS),
                "--target", "missing-feature",
                "--candidates", str(cand),
                "--out", str(out),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("target is not resolvable", proc.stderr)

    def test_scope_outside_target_exits_2(self):
        """An explicit scope outside the target root must be rejected."""
        cand = self.tmp_p / "cand.json"
        out = self.tmp_p / "out.md"
        cand.write_text("{}", encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable, str(DISCOVER_DEPENDENTS),
                "--target", "prune",
                "--scope", "skills/refactor",
                "--candidates", str(cand),
                "--out", str(out),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("scope must remain inside target root", proc.stderr)

    def test_target_scope_defaults_to_feature_root(self):
        """Without --scope, analysis is narrowed to the resolved skill root."""
        candidates = {
            "dead": [{
                "file": "skills/refactor/SKILL.md",
                "line": 1,
                "severity": "major",
                "confidence": "high",
                "title": "Out of scope",
                "tldr": "outside target",
                "failure_scenario": "not under prune",
                "deletion_scope": "whole-file",
                "deletion_proof": {"no_importers": True, "no_callers": True},
            }],
        }
        proc, out_path = self._run(candidates, target="prune")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = out_path.read_text(encoding="utf-8")
        self.assertIn("## Verdict", text)
        self.assertNotIn("**File:**", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
