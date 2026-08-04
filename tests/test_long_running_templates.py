#!/usr/bin/env python3
"""test_long_running_templates.py — RED-first tests for Pattern 2 long-running session templates.

Validates the four-template artifact bundle defined in
`docs/proposals/playbook-application/02-reanalysis.yaml`:

  - templates/init.sh         — bash bootstrap (valid syntax, executable)
  - templates/feature_list.example.json — JSON array example of feature entries
  - templates/progress.log.md  — per-session log template
  - templates/session_handoff.md — resume-from-cold-context checklist

Plus a wiring test ensuring `skills/build/SKILL.md` references the
templates so the build stage emits them for >1-session tasks.

Pure stdlib; uses `subprocess.check_output` for `bash -n` and JSON
parsing for the JSON template. No pytest fixtures needed (each test
is independent and reads the file directly).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"


class TestFeatureListExists(unittest.TestCase):
    """feature_list.example.json parses, is a non-empty list, every
    entry has the required keys, and at least one entry exists in `failing`
    status so init.sh has an example feature to pick."""

    def setUp(self):
        self.path = TEMPLATES_DIR / "feature_list.example.json"

    def test_file_exists(self):
        self.assertTrue(self.path.is_file(), f"missing: {self.path}")

    def test_parses_as_json(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIsInstance(data, list, "feature_list.example.json must be a JSON array")
        self.assertGreater(len(data), 0, "feature_list.example.json must have at least one entry")

    def test_entries_have_required_keys(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        required = {"id", "description", "status", "depends_on", "test_path"}
        for i, entry in enumerate(data):
            missing = required - set(entry.keys())
            self.assertFalse(missing, f"entry #{i} ({entry.get('id')!r}) missing keys: {missing}")

    def test_status_values_are_valid(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        valid = {"failing", "passing", "skipped", "blocked"}
        for entry in data:
            self.assertIn(
                entry["status"], valid,
                f"entry {entry['id']!r} has invalid status {entry['status']!r}",
            )

    def test_depends_on_references_known_ids(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        ids = {e["id"] for e in data}
        for entry in data:
            for dep in entry.get("depends_on", []):
                self.assertIn(
                    dep, ids,
                    f"entry {entry['id']!r} depends on unknown id {dep!r}",
                )

    def test_at_least_one_failing_entry(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        failing = [e for e in data if e["status"] == "failing"]
        self.assertGreater(
            len(failing), 0,
            "feature_list.example.json must contain at least one failing entry "
            "for init.sh to have an example feature to pick",
        )


class TestProgressLogHasRequiredSections(unittest.TestCase):
    """progress.log.md template documents the 6 sub-sections proposed in
    02-reanalysis.yaml: Goal, Work done, Tests status, Blockers, Next
    session should, Commits. Each subsection must appear at least once
    so the per-session log structure is enforced."""

    def setUp(self):
        self.path = TEMPLATES_DIR / "progress.log.md"

    def test_file_exists(self):
        self.assertTrue(self.path.is_file(), f"missing: {self.path}")

    def test_has_all_six_subsections(self):
        text = self.path.read_text(encoding="utf-8")
        required = [
            "Goal",
            "Work done",
            "Tests status",
            "Blockers",
            "Next session should",
            "Commits",
        ]
        for section in required:
            # Match ### Section heading or inline mention in a checklist.
            pattern = re.compile(
                r"(###\s+" + re.escape(section) + r"|^" + re.escape(section) + r"\s*$)",
                re.MULTILINE,
            )
            self.assertRegex(
                text, pattern,
                f"progress.log.md must define a '{section}' subsection (got text length {len(text)})",
            )

    def test_has_example_session(self):
        text = self.path.read_text(encoding="utf-8")
        self.assertRegex(
            text, re.compile(r"^##\s+Session\s+\d+", re.MULTILINE),
            "progress.log.md must include at least one '## Session N' example "
            "so the template teaches the per-session heading shape.",
        )


class TestSessionHandoffHasResumeSections(unittest.TestCase):
    """session_handoff.md must cover the resume-from-cold-context checklist
    end-to-end: branch check, env verify, prior-session read, baseline,
    goal state, in-scope work, end-of-session append, push+sync, hand-off,
    and an anti-patterns list. Each section is a top-level ## heading."""

    def setUp(self):
        self.path = TEMPLATES_DIR / "session_handoff.md"

    def test_file_exists(self):
        self.assertTrue(self.path.is_file(), f"missing: {self.path}")

    def test_required_top_level_sections(self):
        text = self.path.read_text(encoding="utf-8")
        required_headings = [
            "Confirm you are on the right branch",
            "Read the previous session",
            "Verify the environment",
            "Verify the test suite",
            "State the goal",
            "Work, in scope",
            "appending a new section",  # tolerate either wording
            "Push + sync",
            "Hand-off record",
            "Anti-patterns",
        ]
        for needle in required_headings:
            self.assertIn(
                needle, text,
                f"session_handoff.md must mention '{needle}' (resume-from-cold checklist step)",
            )

    def test_references_init_and_progress_files(self):
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("templates/init.sh", text, "must reference init.sh as the bootstrap step")
        self.assertIn("templates/progress.log.md", text, "must reference progress.log.md as the prior-session read")


class TestInitShHasValidBashSyntax(unittest.TestCase):
    """init.sh must have valid bash syntax and be executable. We invoke
    `bash -n` to parse without running, and `help` the executable bit
    so subsequent invocations work without a `chmod +x` round trip."""

    def setUp(self):
        self.path = TEMPLATES_DIR / "init.sh"

    def test_file_exists(self):
        self.assertTrue(self.path.is_file(), f"missing: {self.path}")

    def test_has_bash_shebang(self):
        first_line = self.path.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(
            first_line.startswith("#!/usr/bin/env bash") or first_line.startswith("#!/bin/bash"),
            f"init.sh must start with a bash shebang (got {first_line!r})",
        )

    def test_bash_parses_clean(self):
        result = subprocess.run(
            ["bash", "-n", str(self.path)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(
            result.returncode, 0,
            f"bash -n failed (rc={result.returncode}): {result.stderr}",
        )

    def test_executable_bit_set(self):
        import stat
        mode = self.path.stat().st_mode
        self.assertTrue(
            mode & stat.S_IXUSR,
            f"init.sh must be executable by the owner (mode={oct(mode)})",
        )

    def test_documents_exit_codes(self):
        text = self.path.read_text(encoding="utf-8")
        for code, label in [("0", "success"), ("2", "missing"), ("3", "failing feature")]:
            self.assertIn(
                f"exit {code}",
                text,
                f"init.sh must document exit code {code} ({label}) so consumers can branch on it",
            )


class TestSkillBuildReferencesTemplates(unittest.TestCase):
    """skills/build/SKILL.md must reference the four templates so a >1-session
    build phase knows to emit them. We accept either an inline mention
    or a relative-path reference; the gate is presence of each name."""

    def setUp(self):
        self.path = REPO_ROOT / "skills" / "build" / "SKILL.md"

    def test_file_exists(self):
        self.assertTrue(self.path.is_file(), f"missing: {self.path}")

    def test_references_all_four_templates(self):
        text = self.path.read_text(encoding="utf-8")
        for name in ("init.sh", "feature_list.json", "progress.log.md", "session_handoff.md"):
            self.assertIn(
                name, text,
                f"skills/build/SKILL.md must reference templates/{name} "
                f"so the build stage emits the template bundle for >1-session tasks",
            )

    def test_references_pattern_2_proposal(self):
        text = self.path.read_text(encoding="utf-8")
        self.assertIn(
            "Pattern 2",
            text,
            "skills/build/SKILL.md must cite the Pattern 2 proposal anchor "
            "so reviewers can trace the design rationale.",
        )

    def test_section_is_dedicated_long_running_block(self):
        text = self.path.read_text(encoding="utf-8")
        # Look for a heading that explicitly names the bundle.
        self.assertRegex(
            text, re.compile(r"^##\s+Long-running session templates", re.MULTILINE),
            "skills/build/SKILL.md must have a dedicated '## Long-running session templates' "
            "section (not just inline mentions).",
        )



class TestInitShExecutesInDocumentedLayout(unittest.TestCase):
    """Behavioral test: actually run `init.sh` against a tmpdir fixture that
    mirrors the documented layout (script in `templates/`, feature_list.json
    next to it). Catches the FEATURE_LIST default-path bug codex flagged
    (script defaulted to ./feature_list.json instead of templates/feature_list.json
    so the bootstrap was unreachable from its own install location)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lrt-init-sh-")
        # Mirror the documented layout: <tmpdir>/{templates/, tests/}.
        self.tpl_dir = Path(self.tmp) / "templates"
        self.tpl_dir.mkdir(parents=True, exist_ok=True)
        (Path(self.tmp) / "tests").mkdir(parents=True, exist_ok=True)
        # Drop a stub pytest.ini so init.sh auto-detects the test runner.
        (Path(self.tmp) / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
        src_dir = TEMPLATES_DIR
        for source_name, target_name in (
            ("init.sh", "init.sh"),
            ("feature_list.example.json", "feature_list.json"),
        ):
            (self.tpl_dir / target_name).write_bytes((src_dir / source_name).read_bytes())
        (self.tpl_dir / "init.sh").chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dry_run_picks_next_failing_feature(self):
        """DRY_RUN=1 bash templates/init.sh should:
        - exit 0
        - print the next failing feature id (F-EX1 in the example data)
        - NOT create .session-baseline.json.baseline (DRY_RUN guard)."""
        proc = subprocess.run(
            ["bash", "templates/init.sh"],
            cwd=self.tmp,
            env={**os.environ, "DRY_RUN": "1"},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(
            proc.returncode, 0,
            f"init.sh exited {proc.returncode} (stderr: {proc.stderr})",
        )
        self.assertIn(
            "F-EX1", proc.stderr,
            f"init.sh should report the next failing feature id (stderr: {proc.stderr!r})",
        )
        self.assertFalse(
            (Path(self.tmp) / ".session-baseline.json.baseline").exists(),
            "DRY_RUN=1 must not write .session-baseline.json.baseline at repo root",
        )

    def test_missing_feature_list_exits_2(self):
        """When feature_list.json is absent, init.sh must exit 2 with the
        'missing prerequisite' signal documented in its header."""
        (self.tpl_dir / "feature_list.json").unlink()
        proc = subprocess.run(
            ["bash", "templates/init.sh"],
            cwd=self.tmp,
            env={**os.environ, "DRY_RUN": "1"},
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(
            proc.returncode, 2,
            f"missing feature_list.json must exit 2 (got {proc.returncode}; stderr: {proc.stderr})",
        )

    def test_all_passing_exits_3(self):
        """When every feature in feature_list.json is passing, init.sh must
        exit 3 with the 'no failing feature remaining' signal."""
        payload = json.dumps([
            {"id": "DONE-1", "description": "x", "status": "passing",
             "depends_on": [], "test_path": "x"},
        ])
        (self.tpl_dir / "feature_list.json").write_text(payload, encoding="utf-8")
        proc = subprocess.run(
            ["bash", "templates/init.sh"],
            cwd=self.tmp,
            env={**os.environ, "DRY_RUN": "1"},
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(
            proc.returncode, 3,
            f"all-passing list must exit 3 (got {proc.returncode}; stderr: {proc.stderr})",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
