#!/usr/bin/env python3
"""test_ci_setup_split_install.py — Tests for the bootstrap/body phase split.

The split exists so consumers can land `.github/workflows/review.yml` on the
default branch in its own PR (--bootstrap). After merge, the rest of the
templates (--body) install in a second PR where anthropics/claude-code-action
actually runs the /dev-kit:review and /dev-kit:security agents.

Covers lib/ci_setup.py:install_ci_config(phase=...) and the marker schema
addition (`phase` field). Mirrors the import pattern in test_ci_setup.py.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))


def _load_ci_setup():
    name = "ci_setup"
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "lib" / "ci_setup.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestSplitInstall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ci_setup = _load_ci_setup()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ci_setup_split_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- path-set partitioning ----------

    def test_bootstrap_paths_are_the_three_workflows(self):
        self.assertEqual(
            set(self.ci_setup.BOOTSTRAP_PATHS),
            {
                ".github/workflows/ci.yml",
                ".github/workflows/auto-fix-pr.yml",
                ".github/workflows/review.yml",
            },
        )

    def test_body_paths_exclude_bootstrap_paths(self):
        self.assertEqual(
            set(self.ci_setup.BODY_PATHS),
            set(self.ci_setup.EXPECTED_PATHS) - set(self.ci_setup.BOOTSTRAP_PATHS),
        )

    def test_expected_paths_is_union(self):
        self.assertEqual(
            len(self.ci_setup.EXPECTED_PATHS),
            len(self.ci_setup.BOOTSTRAP_PATHS) + len(self.ci_setup.BODY_PATHS),
        )

    # ---------- _resolve_paths ----------

    def test_resolve_paths_default_is_all(self):
        self.assertEqual(self.ci_setup._resolve_paths(None), self.ci_setup.EXPECTED_PATHS)
        self.assertEqual(self.ci_setup._resolve_paths("all"), self.ci_setup.EXPECTED_PATHS)

    def test_resolve_paths_bootstrap(self):
        self.assertEqual(
            self.ci_setup._resolve_paths("bootstrap"),
            self.ci_setup.BOOTSTRAP_PATHS,
        )

    def test_resolve_paths_body(self):
        self.assertEqual(
            self.ci_setup._resolve_paths("body"),
            self.ci_setup.BODY_PATHS,
        )

    def test_resolve_paths_rejects_unknown_phase(self):
        with self.assertRaises(ValueError):
            self.ci_setup._resolve_paths("garbage")

    # ---------- install_ci_config with phase ----------

    def test_bootstrap_phase_creates_only_workflows(self):
        report = self.ci_setup.install_ci_config(self.tmp, phase="bootstrap")
        self.assertEqual(report.created, [
            ".github/workflows/ci.yml",
            ".github/workflows/auto-fix-pr.yml",
            ".github/workflows/review.yml",
        ])
        self.assertEqual(report.errors, [])
        for rel in self.ci_setup.BODY_PATHS:
            self.assertFalse((self.tmp / rel).exists(), f"body file leaked: {rel}")

    def test_body_phase_creates_only_non_workflows(self):
        self.ci_setup.install_ci_config(self.tmp, phase="bootstrap")
        for rel in self.ci_setup.BODY_PATHS:
            (self.tmp / rel).unlink(missing_ok=True)
        report = self.ci_setup.install_ci_config(self.tmp, phase="body")
        self.assertEqual(set(report.created), set(self.ci_setup.BODY_PATHS))
        self.assertEqual(report.errors, [])
        for rel in self.ci_setup.BOOTSTRAP_PATHS:
            self.assertTrue((self.tmp / rel).exists(), f"workflow vanished: {rel}")

    def test_marker_records_phase_bootstrap(self):
        report = self.ci_setup.install_ci_config(self.tmp, phase="bootstrap")
        marker = json.loads(Path(report.marker_path).read_text())
        self.assertEqual(marker["phase"], "bootstrap")

    def test_marker_records_phase_body(self):
        self.ci_setup.install_ci_config(self.tmp, phase="bootstrap")
        report = self.ci_setup.install_ci_config(self.tmp, phase="body")
        marker = json.loads(Path(report.marker_path).read_text())
        self.assertEqual(marker["phase"], "body")

    def test_marker_records_phase_all_when_no_flag(self):
        report = self.ci_setup.install_ci_config(self.tmp)
        marker = json.loads(Path(report.marker_path).read_text())
        self.assertEqual(marker["phase"], "all")

    # ---------- idem + force ----------

    def test_bootstrap_then_body_then_body_is_idempotent(self):
        self.ci_setup.install_ci_config(self.tmp, phase="bootstrap")
        self.ci_setup.install_ci_config(self.tmp, phase="body")
        report = self.ci_setup.install_ci_config(self.tmp, phase="body")
        self.assertEqual(report.created, [])
        self.assertEqual(report.overwritten, [])
        self.assertEqual(set(report.skipped), set(self.ci_setup.BODY_PATHS))

    def test_force_overwrites_only_resolved_phase(self):
        """force=True on phase="bootstrap" must NOT touch BODY_PATHS (they're
        outside the phase's scope). Body files stay byte-identical."""
        self.ci_setup.install_ci_config(self.tmp, phase="bootstrap")
        self.ci_setup.install_ci_config(self.tmp, phase="body")
        # Snapshot body mtimes so we can detect any churn.
        body_mtimes_before = {
            rel: (self.tmp / rel).stat().st_mtime
            for rel in self.ci_setup.BODY_PATHS
        }
        report = self.ci_setup.install_ci_config(self.tmp, phase="bootstrap", force=True)
        # Only BOOTSTRAP_PATHS were touched.
        self.assertEqual(set(report.overwritten), set(self.ci_setup.BOOTSTRAP_PATHS))
        # BODY_PATHS are entirely outside this phase — not in created,
        # overwritten, OR skipped (they simply aren't iterated).
        self.assertEqual(report.created, [])
        self.assertFalse(any(rel in report.skipped for rel in self.ci_setup.BODY_PATHS))
        # Confirm body files were not rewritten by checking mtime is unchanged.
        for rel, mtime_before in body_mtimes_before.items():
            self.assertEqual(
                (self.tmp / rel).stat().st_mtime,
                mtime_before,
                f"body file was rewritten: {rel}",
            )

    # ---------- executable bits ----------

    def test_body_phase_sets_executable_on_body_scripts_only(self):
        self.ci_setup.install_ci_config(self.tmp, phase="bootstrap")
        for rel in self.ci_setup.BODY_PATHS:
            if (self.tmp / rel).exists():
                (self.tmp / rel).chmod(0o644)
        self.ci_setup.install_ci_config(self.tmp, phase="body")
        for rel in self.ci_setup.BODY_PATHS:
            if rel in self.ci_setup.EXECUTABLE_PATHS:
                mode = (self.tmp / rel).stat().st_mode
                self.assertTrue(mode & 0o111, f"missing +x: {rel}")

    # ---------- validation ----------

    def test_invalid_phase_raises(self):
        with self.assertRaises(ValueError):
            self.ci_setup.install_ci_config(self.tmp, phase="garbage")


if __name__ == "__main__":
    unittest.main()
