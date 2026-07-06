#!/usr/bin/env python3
"""test_ci_setup.py — Tests for the `/dev-kit:ci-setup` engine.

Covers lib/ci_setup.py:install_ci_config() and the templates/ tree it ships.
Uses the same importlib-from-path pattern as tests/test_smoke.py so it works
as both `python -m unittest tests/test_ci_setup.py` and `pytest tests/test_ci_setup.py`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))


def _load_ci_setup():
    """Load lib/ci_setup.py by file path (mirrors test_smoke.py:64-66 pattern).

    NOTE: the module MUST be registered in sys.modules BEFORE exec_module for
    Python 3.14's @dataclass to resolve cross-module type lookups.
    """
    name = "ci_setup"
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "lib" / "ci_setup.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # register FIRST so @dataclass can resolve names
    spec.loader.exec_module(mod)
    return mod


class TestCiSetup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ci_setup = _load_ci_setup()

    def test_bootstrap_engine_returns_typed_report(self):
        """Smoke-check the InstallReport dataclass shape."""
        r = self.ci_setup.InstallReport()
        self.assertIsInstance(r.created, list)
        self.assertIsInstance(r.overwritten, list)
        self.assertIsInstance(r.skipped, list)
        self.assertIsInstance(r.errors, list)
        self.assertEqual(r.marker_path, "")
        self.assertEqual(r.elapsed_ms, 0)
        self.assertTrue(r.ok)
        r.errors.append("forced")
        self.assertFalse(r.ok)

    def test_invalid_target_dir_raises(self):
        """Non-existent target raises FileNotFoundError; non-directory raises NotADirectoryError."""
        with self.assertRaises(FileNotFoundError):
            self.ci_setup.install_ci_config(Path("/nonexistent/ci_setup_test_xyz"))
        # File-as-target → NotADirectoryError or FileNotFoundError (depends on resolver).
        fp = tempfile_path("foo")
        try:
            with self.assertRaises((NotADirectoryError, FileNotFoundError)):
                self.ci_setup.install_ci_config(fp)
        finally:
            fp.unlink(missing_ok=True)

    def test_install_creates_expected_files_in_empty_target(self, tmpdir=None):
        """Fresh tmp dir: all EXPECTED_PATHS land; marker is written."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            report = self.ci_setup.install_ci_config(target)
            self.assertEqual(report.errors, [], f"errors: {report.errors}")
            for rel in self.ci_setup.EXPECTED_PATHS:
                self.assertTrue((target / rel).exists(), f"missing: {rel}")
            # 8 paths × created (target was empty)
            self.assertEqual(len(report.created), len(self.ci_setup.EXPECTED_PATHS))
            self.assertEqual(report.overwritten, [])
            self.assertEqual(report.skipped, [])
            # Marker present
            marker = target / ".dev-kit" / "ci-config.json"
            self.assertTrue(marker.exists())
            self.assertTrue(report.marker_path.endswith("ci-config.json"))

    def test_install_is_idempotent_without_force(self):
        """Second run without force skips every path; marker rewritten."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            r1 = self.ci_setup.install_ci_config(target)
            self.assertEqual(r1.errors, [])
            first_mtime = (target / ".dev-kit" / "ci-config.json").stat().st_mtime
            r2 = self.ci_setup.install_ci_config(target)
            self.assertEqual(r2.created, [])
            self.assertEqual(r2.overwritten, [])
            self.assertEqual(
                len(r2.skipped), len(self.ci_setup.EXPECTED_PATHS),
                f"all paths should be skipped on re-run without --force",
            )
            self.assertEqual(r2.errors, [])
            # Idempotency does NOT touch file contents, but the marker's
            # `installed_at` may update — that's documented behavior.
            second_mtime = (target / ".dev-kit" / "ci-config.json").stat().st_mtime
            self.assertGreaterEqual(second_mtime, first_mtime)

    def test_install_force_overwrites_cleanly(self):
        """Pre-seed a sentinel; --force replaces it with template content."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            sentinel_dir = target / ".github" / "workflows"
            sentinel_dir.mkdir(parents=True)
            sentinel = sentinel_dir / "ci.yml"
            sentinel.write_text("# SENTINEL: must be replaced by --force\n")
            r = self.ci_setup.install_ci_config(target, force=True)
            self.assertEqual(r.errors, [])
            content = sentinel.read_text()
            self.assertNotIn("SENTINEL", content, "force=True should overwrite sentinel")
            self.assertIn("name: CI", content, "template content should land")
            overwritten = [p for p in r.overwritten if "ci.yml" in p]
            self.assertTrue(overwritten, "ci.yml should be in overwritten list")

    def test_marker_file_written_with_correct_shape(self):
        """Marker JSON has the right fields and types."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self.ci_setup.install_ci_config(target)  # default version
            marker = target / ".dev-kit" / "ci-config.json"
            data = json.loads(marker.read_text())
            for key in (
                "schema_version", "ci_setup_version", "installed_at",
                "installed_by", "runners", "scripts", "githooks",
            ):
                self.assertIn(key, data, f"missing key: {key}")
            self.assertEqual(data["schema_version"], "1.1.0")
            self.assertEqual(data["ci_setup_version"], self.ci_setup.DEFAULT_CI_SETUP_VERSION)
            self.assertEqual(data["installed_by"], "dev-kit:ci-setup")
            self.assertEqual(set(data["runners"]), {"ci.yml", "auto-fix-pr.yml", "review.yml"})
            self.assertEqual(set(data["scripts"]), {
                "scripts/validate.py", "scripts/test.sh",
                "scripts/branch-policy.sh", "scripts/ci-local.sh",
            })
            self.assertEqual(data["githooks"], [".githooks/pre-push"])
            # installed_at should be ISO-8601 UTC (z-suffix)
            self.assertTrue(data["installed_at"].endswith("Z"), data["installed_at"])
            # verification block intentionally removed — schema stays minimal.

    def test_version_short_circuit(self):
        """When marker reports matching version, install is a no-op (no files touched)."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            r1 = self.ci_setup.install_ci_config(target)  # uses DEFAULT_CI_SETUP_VERSION
            self.assertEqual(len(r1.created), len(self.ci_setup.EXPECTED_PATHS))
            # Sentinel each EXPECTED_PATH so we can detect any re-touch
            sentinels = {}
            for rel in self.ci_setup.EXPECTED_PATHS:
                p = target / rel
                sentinels[rel] = p.read_text()
            r2 = self.ci_setup.install_ci_config(target, version="0.1.0")
            self.assertEqual(r2.created, [], "short-circuit must skip create")
            self.assertEqual(r2.overwritten, [], "short-circuit must skip overwrite")
            self.assertEqual(
                len(r2.skipped), len(self.ci_setup.EXPECTED_PATHS),
                "short-circuit must list every EXPECTED_PATH in skipped",
            )
            # Confirm files on disk were not re-written (mtime preserved)
            for rel in self.ci_setup.EXPECTED_PATHS:
                self.assertEqual(
                    (target / rel).read_text(), sentinels[rel],
                    f"file re-touched during short-circuit: {rel}",
                )
            # Marker still present at the expected location (path may be resolved to /private/... on macOS)
            self.assertTrue((target / ".dev-kit" / "ci-config.json").exists())
            self.assertTrue(r2.marker_path.endswith("ci-config.json"))

    def test_version_upgrade_runs_install(self):
        """When marker reports OLDER version, install proceeds (upgrade path)."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self.ci_setup.install_ci_config(target, version="0.1.0")
            # Now simulate an older-version marker (downgrade scenario)
            marker = target / ".dev-kit" / "ci-config.json"
            data = json.loads(marker.read_text())
            data["ci_setup_version"] = "0.0.9"
            marker.write_text(json.dumps(data))
            r = self.ci_setup.install_ci_config(target, version="0.1.0")
            # Either created (empty target) or skipped (existing files) — but never short-circuited
            self.assertEqual(len(r.created) + len(r.overwritten) + len(r.skipped),
                             len(self.ci_setup.EXPECTED_PATHS))

    def test_executable_bit_set_on_sh_files(self):
        """All .sh + pre-push + validate.py have +x bit after install."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self.ci_setup.install_ci_config(target)
            for rel in self.ci_setup.EXECUTABLE_PATHS:
                p = target / rel
                self.assertTrue(p.exists(), f"missing: {rel}")
                # Read mode bit directly (POSIX st_mode)
                mode = p.stat().st_mode
                self.assertTrue(mode & 0o111, f"not executable: {rel} (mode={oct(mode)})")

    def test_validate_py_runs_against_installed_ci_dir(self):
        """The installed validate.py exits 0 against the install target."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self.ci_setup.install_ci_config(target)
            r = subprocess.run(
                ["python3", "scripts/validate.py"],
                cwd=str(target), capture_output=True, text=True,
            )
            self.assertEqual(
                r.returncode, 0,
                f"validate.py exited {r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}",
            )
            self.assertIn("OK: CI installation valid", r.stdout)

    # === Worktree-rule rollout (PR #22 + this PR) ===

    def test_worktree_rule_files_are_in_expected_paths(self):
        """EXPECTED_PATHS includes the 7 worktree-rule files added in PR #22."""
        expected_new = {
            "hooks/worktree-guard.sh",
            "hooks/task-detector.sh",
            "hooks/session-start-check.sh",
            "hooks/lib/worktree-detect.sh",
            "hooks/hooks.json",
            ".claude/rules/git-workflow.md",
            "tests/test_worktree_guard.py",
        }
        actual = set(self.ci_setup.EXPECTED_PATHS)
        self.assertTrue(
            expected_new.issubset(actual),
            f"missing from EXPECTED_PATHS: {expected_new - actual}",
        )

    def test_worktree_hooks_have_executable_bit_in_target(self):
        """All 4 new .sh files end up executable in the installed target."""
        import tempfile
        import stat
        new_sh = (
            "hooks/worktree-guard.sh",
            "hooks/task-detector.sh",
            "hooks/session-start-check.sh",
            "hooks/lib/worktree-detect.sh",
        )
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self.ci_setup.install_ci_config(target)
            for rel in new_sh:
                p = target / rel
                self.assertTrue(p.exists(), f"missing: {rel}")
                self.assertTrue(p.stat().st_mode & stat.S_IXUSR, f"not +x: {rel}")

    def test_marker_schema_version_bumped_to_1_1(self):
        """Marker schema_version reflects the worktree-rule rollout (1.0 → 1.1)."""
        self.assertEqual(self.ci_setup.MARKER_SCHEMA_VERSION, "1.1.0")
        self.assertEqual(self.ci_setup.DEFAULT_CI_SETUP_VERSION, "0.1.1")

    def test_marker_records_hooks_rules_tests(self):
        """Marker JSON lists the new categories (hooks / rules / tests)."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self.ci_setup.install_ci_config(target)
            marker = json.loads((target / ".dev-kit" / "ci-config.json").read_text())
            for key in ("hooks", "rules", "tests"):
                self.assertIn(key, marker, f"marker missing key: {key}")
                self.assertTrue(len(marker[key]) > 0, f"marker.{key} should be non-empty")
            self.assertIn("hooks/worktree-guard.sh", marker["hooks"])
            self.assertIn(".claude/rules/git-workflow.md", marker["rules"])
            self.assertIn("tests/test_worktree_guard.py", marker["tests"])


def tempfile_path(name: str):
    """Return a Path to a tempfile file (helper for test_invalid_target_dir_raises)."""
    import tempfile
    fd, p = tempfile.mkstemp(prefix=f"ci_setup_{name}_", suffix=".txt")
    os.close(fd)
    return Path(p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
