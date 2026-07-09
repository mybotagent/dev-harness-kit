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
            self.assertEqual(data["schema_version"], "1.0.0")
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

    def test_presence_short_circuit(self):
        """When marker + all EXPECTED_PATHS exist, install is a no-op (no files touched)."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            r1 = self.ci_setup.install_ci_config(target)
            self.assertEqual(len(r1.created), len(self.ci_setup.EXPECTED_PATHS))
            # Sentinel each EXPECTED_PATH so we can detect any re-touch
            sentinels = {}
            for rel in self.ci_setup.EXPECTED_PATHS:
                p = target / rel
                sentinels[rel] = p.read_text()
            r2 = self.ci_setup.install_ci_config(target)
            self.assertEqual(r2.created, [], "short-circuit must skip create")
            self.assertEqual(r2.overwritten, [], "short-circuit must skip overwrite")
            self.assertEqual(
                len(r2.skipped), len(self.ci_setup.EXPECTED_PATHS),
                "short-circuit must list every EXPECTED_PATH in skipped",
            )
            # Confirm files on disk were not re-written (content preserved)
            for rel in self.ci_setup.EXPECTED_PATHS:
                self.assertEqual(
                    (target / rel).read_text(), sentinels[rel],
                    f"file re-touched during short-circuit: {rel}",
                )
            # Marker still present at the expected location (path may be resolved to /private/... on macOS)
            self.assertTrue((target / ".dev-kit" / "ci-config.json").exists())
            self.assertTrue(r2.marker_path.endswith("ci-config.json"))

    def test_partial_install_completes_remaining(self):
        """If marker exists but some templates are missing, install copies only the missing ones."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self.ci_setup.install_ci_config(target)
            # Delete one file + the marker so install must re-copy
            (target / self.ci_setup.EXPECTED_PATHS[0]).unlink()
            (target / ".dev-kit" / "ci-config.json").unlink()
            r = self.ci_setup.install_ci_config(target)
            self.assertTrue(
                len(r.created) + len(r.overwritten) >= 1,
                f"at least the deleted path should be re-copied; created={r.created} overwritten={r.overwritten}",
            )

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

    def test_marker_schema_version_current(self):
        """Schema is content-only (1.0.0). The ci_setup_version gate is separate."""
        self.assertEqual(self.ci_setup.MARKER_SCHEMA_VERSION, "1.0.0")
        self.assertTrue(hasattr(self.ci_setup, "PLUGIN_CI_SETUP_VERSION"))
        # Lexicographic gate threshold (skills/build/SKILL.md reads >= "0.1.0").
        self.assertGreaterEqual(
            tuple(int(x) for x in self.ci_setup.PLUGIN_CI_SETUP_VERSION.split(".")),
            (0, 1, 0),
        )

    def test_marker_writes_ci_setup_version(self):
        """Marker JSON carries `ci_setup_version` (regression for issue #61).

        skills/build/SKILL.md reads `ci_setup_version` as a pre-flight gate.
        Before the fix, the field was absent so `data.get('ci_setup_version',
        '0.0.0') < '0.1.0'` was True and the build refused to start. The
        marker must now mirror the contract declared in
        templates/ci/ci-config.example.json.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self.ci_setup.install_ci_config(target)
            marker = json.loads((target / ".dev-kit" / "ci-config.json").read_text())
            self.assertIn("ci_setup_version", marker, "marker missing ci_setup_version")
            self.assertEqual(
                marker["ci_setup_version"],
                self.ci_setup.PLUGIN_CI_SETUP_VERSION,
                "marker ci_setup_version must match the plugin constant",
            )
            # The gate evaluates lexicographically; the value must clear 0.1.0.
            self.assertGreaterEqual(
                marker["ci_setup_version"], "0.1.0",
                f"ci_setup_version {marker['ci_setup_version']!r} fails the build gate",
            )

    def test_marker_ci_setup_version_matches_template_contract(self):
        """The template contract (templates/ci/ci-config.example.json) and the
        runtime marker carry the same ci_setup_version field — gates and
        templates can't drift."""
        import tempfile
        template_marker = json.loads(
            (PROJECT_ROOT / "templates" / "ci" / "ci-config.example.json").read_text()
        )
        self.assertIn(
            "ci_setup_version", template_marker,
            "template contract lost the ci_setup_version field",
        )
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self.ci_setup.install_ci_config(target)
            installed_marker = json.loads(
                (target / ".dev-kit" / "ci-config.json").read_text()
            )
            self.assertEqual(
                installed_marker["ci_setup_version"],
                template_marker["ci_setup_version"],
                "installed marker drifted from template contract",
            )

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

    def test_marker_writes_installed_skill_versions(self):
        """feat/skill-versions: fresh install writes the skill-version mirror."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self.ci_setup.install_ci_config(target)
            marker = json.loads((target / ".dev-kit" / "ci-config.json").read_text())
            self.assertIn("installed_skill_versions", marker, "marker missing installed_skill_versions")
            mirror = marker["installed_skill_versions"]
            self.assertIsInstance(mirror, dict)
            # Mirror should contain an entry for every skill in the plugin
            from importlib.util import spec_from_file_location, module_from_spec
            spec = spec_from_file_location(
                "_cs_min_skill_versions",
                Path(__file__).parent.parent / "lib" / "ci_setup.py",
            )
            cs = module_from_spec(spec)
            sys.modules["_cs_min_skill_versions"] = cs  # @dataclass needs sys.modules (Py3.14)
            spec.loader.exec_module(cs)
            live = cs.extract_skill_versions(Path(__file__).parent.parent)
            self.assertEqual(
                set(mirror), set(live),
                f"mirror missing/extra skills: {set(mirror) ^ set(live)}",
            )
            for skill, ver in mirror.items():
                self.assertRegex(
                    ver, r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$",
                    f"{skill}: {ver!r} is not valid semver",
                )

    def test_marker_min_skill_versions_default_empty(self):
        """feat/skill-versions: first install writes min_skill_versions: {} (permissive)."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self.ci_setup.install_ci_config(target)
            marker = json.loads((target / ".dev-kit" / "ci-config.json").read_text())
            self.assertIn("min_skill_versions", marker)
            self.assertEqual(marker["min_skill_versions"], {},
                             "fresh install must default to empty floor")

    def test_ci_setup_force_preserves_consumer_min_skill_versions(self):
        """feat/skill-versions: `--force` rewrites the mirror but PRESERVES the
        consumer's opt-in `min_skill_versions` declaration."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self.ci_setup.install_ci_config(target)
            # Consumer opts into a floor
            marker_path = target / ".dev-kit" / "ci-config.json"
            data = json.loads(marker_path.read_text())
            data["min_skill_versions"] = {"build": "0.2.0", "ci-setup": "0.1.5"}
            marker_path.write_text(json.dumps(data))
            # `--force` must NOT clobber the floor
            self.ci_setup.install_ci_config(target, force=True)
            reread = json.loads(marker_path.read_text())
            self.assertEqual(
                reread["min_skill_versions"],
                {"build": "0.2.0", "ci-setup": "0.1.5"},
                "--force clobbered the consumer's min_skill_versions",
            )
            # The mirror should still be (re)written — proves the install ran
            # end-to-end rather than short-circuiting.
            self.assertIn("installed_skill_versions", reread)
            self.assertGreater(len(reread["installed_skill_versions"]), 0)

    def test_post_install_checklist_is_complete(self):
        """5 numbered items; each is a gh secret set, a gh/git config, or a
        workflow-setting note. Must be actionable."""
        items = self.ci_setup.POST_INSTALL_CHECKLIST
        self.assertGreaterEqual(
            len(items), 5,
            f"expected >=5 post-install checklist items, got {len(items)}",
        )
        seen_numbers = set()
        for n, body in items:
            self.assertTrue(
                n.isdigit() and 1 <= int(n) <= 9,
                f"checklist number {n!r} must be a digit 1..9",
            )
            self.assertNotIn(int(n), seen_numbers, f"duplicate: {n}")
            seen_numbers.add(int(n))
            joined = body.lower()
            self.assertTrue(
                any(needle in joined for needle in (
                    "gh secret set", "git config", "push a feature branch",
                    "merge that", "/dev-kit:review",
                )),
                f"checklist item {n} does not mention any actionable command",
            )

    def test_preflight_probe_skips_on_missing_gh(self):
        """When gh is absent, every probe line is SKIP. Safe failure: a user
        without gh can still install; the checklist alone guides them."""
        import os
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = ""
        try:
            results = self.ci_setup.preflight_probe(repo="o/r")
            self.assertIsInstance(results, list)
            self.assertGreater(len(results), 0)
            for r in results:
                self.assertEqual(
                    r.state, "SKIP",
                    f"expected SKIP with PATH empty, got {r.state} for {r.label}",
                )
        finally:
            os.environ["PATH"] = old_path

    def test_lint_installed_workflows_flags_stale_gate_pattern(self):
        """Lint pass detects pre-0.1.3 PR-mode hard-fail gate.

        The pre-0.1.3 templates/ci/.github/workflows/review.yml shipped a
        gate that hard-failed in pull_request mode on missing verdicts
        while defaulting to Approve in workflow_dispatch mode. The
        distinctive substring 'Re-run via workflow_dispatch if needed'
        is unique to that block; the lint pass is keyed on it.
        """
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as td:
            review = _P(td) / ".github" / "workflows" / "review.yml"
            review.parent.mkdir(parents=True)
            review.write_text(
                "dummy\n          Re-run via workflow_dispatch if needed\n"
            )
            findings = self.ci_setup.lint_installed_workflows(_P(td))
            self.assertTrue(
                any(".github/workflows/review.yml" in f for f in findings),
                f"expected gate-tolerance finding, got {findings!r}",
            )

    def test_lint_installed_workflows_clean_on_fresh_install(self):
        """Fresh install of the current (post-0.1.3) template yields 0 lint warnings."""
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as td:
            r = self.ci_setup.install_ci_config(_P(td))
            self.assertEqual(r.warnings, [], r.warnings)
            self.assertEqual(self.ci_setup.lint_installed_workflows(_P(td)), [])

    def test_lint_runs_on_no_op_idempotent_reinstall(self):
        """Idempotent re-install (no --force) still lints and surfaces drift."""
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as td:
            r1 = self.ci_setup.install_ci_config(_P(td))
            self.assertEqual(r1.warnings, [])
            review = _P(td) / ".github" / "workflows" / "review.yml"
            review.write_text(
                review.read_text()
                + "\n          Re-run via workflow_dispatch if needed\n"
            )
            r2 = self.ci_setup.install_ci_config(_P(td), force=False)
            self.assertTrue(
                any("stale pull_request hard-fail gate" in w for w in r2.warnings),
                f"expected stale-gate warning, got {r2.warnings!r}",
            )

    def test_lint_kwarg_can_suppress(self):
        """`lint=False` suppresses the warning-class output."""
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as td:
            review = _P(td) / ".github" / "workflows" / "review.yml"
            review.parent.mkdir(parents=True)
            review.write_text(
                "          Re-run via workflow_dispatch if needed\n"
            )
            r = self.ci_setup.install_ci_config(_P(td), force=False, lint=False)
            self.assertEqual(
                r.warnings,
                [],
                "lint=False must suppress findings",
            )

    def test_print_checklist_kwarg_does_not_break_existing_callers(self):
        """install_ci_config(..., print_checklist=True) writes the marker and
        returns an InstallReport. Default (no kwarg) behavior unchanged."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            r_default = self.ci_setup.install_ci_config(target)
            self.assertEqual(r_default.errors, [])
            r_printing = self.ci_setup.install_ci_config(
                target, force=True, print_checklist=True,
            )
            self.assertEqual(r_printing.errors, [])
            self.assertTrue((target / ".dev-kit" / "ci-config.json").exists())


def tempfile_path(name: str):
    """Return a Path to a tempfile file (helper for test_invalid_target_dir_raises)."""
    import tempfile
    fd, p = tempfile.mkstemp(prefix=f"ci_setup_{name}_", suffix=".txt")
    os.close(fd)
    return Path(p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
