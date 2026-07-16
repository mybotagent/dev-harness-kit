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
                "schema_version", "installed_at",
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
        """Schema is content-only (1.0.0) — no version-gate field."""
        self.assertEqual(self.ci_setup.MARKER_SCHEMA_VERSION, "1.0.0")
        self.assertTrue(hasattr(self.ci_setup, "plugin_version"),
                        "ci_setup must expose a runtime `plugin_version()` reader")

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

    def test_ci_template_branch_policy_has_checkout_step(self):
        """Issue #202: branch-policy job must include `actions/checkout@v4`.

        Without this step, consumer repos whose branch-policy job depends
        on working-tree state (or that previously added a local checkout
        fix like commit 445a0b7 in sh-ai-x/claude-statusline) silently
        regress on the next `--force` install. The upstream template
        itself must own the checkout, so the consumer's local customizations
        layer on top rather than getting overwritten away.
        """
        import yaml  # PyYAML — already a dev dep; see pyproject.toml
        template = (PROJECT_ROOT / "templates" / "ci" / ".github" / "workflows" / "ci.yml")
        self.assertTrue(template.is_file(), f"template missing: {template}")
        data = yaml.safe_load(template.read_text())
        jobs = data.get("jobs", {})
        self.assertIn("branch-policy", jobs, "branch-policy job missing")
        steps = jobs["branch-policy"].get("steps", [])
        checkout_steps = [
            s for s in steps
            if isinstance(s, dict) and "uses" in s
            and str(s["uses"]).startswith("actions/checkout")
        ]
        self.assertTrue(
            checkout_steps,
            f"branch-policy job has no actions/checkout step; issue #202. steps={steps!r}",
        )

    def test_auto_fix_pr_template_cap_step_exits_one(self):
        """Issue #202: 5-iteration cap must hard-stop the job with exit 1.

        `exit 0` lets the subsequent agent steps run anyway, which
        re-triggers the loop and defeats the cap. `exit 1` fails the
        step (job stops, red CI check, human review gets visibility).
        """
        template = (PROJECT_ROOT / "templates" / "ci" / ".github" / "workflows" / "auto-fix-pr.yml")
        self.assertTrue(template.is_file(), f"template missing: {template}")
        content = template.read_text()
        # The cap block's body is unique: it references "5 auto-fix iterations"
        # and the PR-comment "🤖 Auto-fix reached 5-iteration cap". Within
        # that block, the line right after the comment must be `exit 1`,
        # not `exit 0`.
        cap_marker = "Reached 5 auto-fix iterations"
        self.assertIn(cap_marker, content, "cap warning text missing from template")
        # Slice the script block from the cap step onward (next step header).
        cap_idx = content.index(cap_marker)
        next_step = content.find("\n      - name:", cap_idx)
        cap_block = content[cap_idx:next_step if next_step != -1 else len(content)]
        self.assertIn(
            "exit 1", cap_block,
            f"cap block must hard-stop with `exit 1` (issue #202); block was:\n{cap_block}",
        )
        self.assertNotIn(
            "exit 0", cap_block,
            f"cap block must NOT contain `exit 0` (issue #202); block was:\n{cap_block}",
        )

    def test_gitignore_fragment_created_on_fresh_install(self):
        """Issue #202: empty target gets a `.gitignore` with the dev-kit fragment."""
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as td:
            target = _P(td)
            r = self.ci_setup.install_ci_config(target)
            self.assertEqual(r.errors, [], r.errors)
            gi = target / ".gitignore"
            self.assertTrue(gi.is_file(), ".gitignore should be created on fresh install")
            content = gi.read_text()
            # The fragment's distinctive lines must be present.
            for needle in (".dev-kit/.cost-gate/", ".dev-kit/.eval-cache/",
                           ".dev-kit/logs/", "logs/"):
                self.assertIn(needle, content,
                              f".gitignore missing dev-kit fragment line: {needle}")

    def test_gitignore_fragment_preserves_consumer_lines(self):
        """Issue #202: existing `.gitignore` is appended to, never overwritten.

        Lines outside the marked block must survive a `--force` install.
        A consumer's tracked `.env.example` and `# project header` comment
        must remain in the file after the install.
        """
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as td:
            target = _P(td)
            gi = target / ".gitignore"
            gi.write_text("# project header — do not touch\nnode_modules/\n.env\n")
            r = self.ci_setup.install_ci_config(target)
            self.assertEqual(r.errors, [], r.errors)
            content = gi.read_text()
            self.assertIn("# project header — do not touch", content,
                          "consumer header line was overwritten")
            self.assertIn("node_modules/", content, "consumer line was overwritten")
            self.assertIn(".env", content, "consumer line was overwritten")
            # And the dev-kit fragment lines are now in the file too.
            self.assertIn(".dev-kit/.cost-gate/", content)

    def test_gitignore_fragment_block_is_idempotent(self):
        """Issue #202: re-running `--force` does not duplicate the dev-kit block."""
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as td:
            target = _P(td)
            self.ci_setup.install_ci_config(target)
            first = (target / ".gitignore").read_text()
            self.ci_setup.install_ci_config(target, force=True)
            second = (target / ".gitignore").read_text()
            # The dev-kit block markers should appear exactly once each.
            self.assertEqual(
                first.count(self.ci_setup._GITIGNORE_BLOCK_START), 1,
                f"block-start marker not unique in first install:\n{first}",
            )
            self.assertEqual(
                second.count(self.ci_setup._GITIGNORE_BLOCK_START), 1,
                f"block-start marker duplicated after --force:\n{second}",
            )

    def test_marker_records_per_file_sha_after_install(self):
        """Issue #202: marker must record SHA-256 of every EXPECTED_PATHS file.

        The drift-detection pass (issue #202) compares the SHA recorded
        at install-time against the file's current SHA on the next
        `--force`. Without per-file SHAs in the marker, drift detection
        is impossible.
        """
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as td:
            target = _P(td)
            self.ci_setup.install_ci_config(target)
            marker = json.loads((target / ".dev-kit" / "ci-config.json").read_text())
            self.assertIn("installed_file_shas", marker,
                          "marker missing installed_file_shas field (issue #202)")
            shas = marker["installed_file_shas"]
            self.assertIsInstance(shas, dict)
            # Every EXPECTED_PATHS file with a recordable SHA must have one.
            for rel in self.ci_setup.EXPECTED_PATHS:
                p = target / rel
                if p.is_file():
                    self.assertIn(rel, shas,
                                  f"marker missing SHA for installed file: {rel}")
                    # SHA must be a 64-char hex string (SHA-256).
                    self.assertEqual(len(shas[rel]), 64)
                    int(shas[rel], 16)  # must parse as hex

    def test_drift_detected_when_local_file_modified_before_force(self):
        """Issue #202: locally-modified file triggers a drift warning on `--force`.

        Reproduces the silent-overwrite regression: a consumer adds a
        local fix (e.g. the actions/checkout step at sh-ai-x/claude-statusline
        commit 445a0b7) between installs; the next `--force` install must
        warn the user before the change is overwritten.
        """
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as td:
            target = _P(td)
            # Initial install — marker records SHAs.
            self.ci_setup.install_ci_config(target)
            # Consumer locally modifies a workflow file.
            ci_yml = target / ".github" / "workflows" / "ci.yml"
            original = ci_yml.read_text()
            ci_yml.write_text(original + "\n# LOCAL CUSTOMIZATION — do not lose this\n")
            # `--force` install: drift must be reported.
            r = self.ci_setup.install_ci_config(target, force=True)
            self.assertTrue(
                any("locally modified since last install" in w and "ci.yml" in w
                    for w in r.warnings),
                f"expected drift warning for ci.yml, got: {r.warnings!r}",
            )
            # After --force, the file has been overwritten: the local
            # customization is gone. The warning is advisory only — the
            # overwrite still happens (we don't silently revert; the
            # user explicitly asked for --force).
            final = ci_yml.read_text()
            self.assertNotIn("LOCAL CUSTOMIZATION", final,
                             "--force overwrote the local customization")

    def test_no_drift_warning_when_files_unchanged(self):
        """Issue #202: a no-op re-install (or --force with no local mods)
        produces zero drift warnings."""
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as td:
            target = _P(td)
            self.ci_setup.install_ci_config(target)
            # Second install (no force): no-op path → still no drift.
            r1 = self.ci_setup.install_ci_config(target)
            self.assertEqual(
                [w for w in r1.warnings if "locally modified since last install" in w],
                [],
                "no-op re-install should not report drift when files unchanged",
            )
            # Third install with --force but no local mods: zero drift.
            r2 = self.ci_setup.install_ci_config(target, force=True)
            self.assertEqual(
                [w for w in r2.warnings if "locally modified since last install" in w],
                [],
                "--force with unchanged files should not report drift",
            )

    def test_sha_tracking_round_trip_after_overwrite(self):
        """Issue #202: SHAs in the marker must reflect the template bytes
        that landed on disk AFTER the install, not the stale SHA from
        the previous install."""
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as td:
            target = _P(td)
            self.ci_setup.install_ci_config(target)
            # Locally modify.
            ci_yml = target / ".github" / "workflows" / "ci.yml"
            ci_yml.write_text("# trash\n")
            # `--force` overwrites; the new SHA must equal the template's
            # bytes, not the local trash or the prior install's SHA.
            self.ci_setup.install_ci_config(target, force=True)
            marker = json.loads((target / ".dev-kit" / "ci-config.json").read_text())
            recorded = marker["installed_file_shas"][".github/workflows/ci.yml"]
            actual = self.ci_setup._sha256_file(ci_yml)
            self.assertEqual(recorded, actual,
                             "marker SHA must match post-install file bytes")

    # === Issue #212: provider-file install + secrets catalog ===

    def test_provider_file_landed_in_empty_target(self):
        """Issue #212-A1: .github/ci-review-provider.txt is in EXPECTED_PATHS
        and contains a valid provider name on fresh install."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            r = self.ci_setup.install_ci_config(target)
            self.assertEqual(r.errors, [], f"errors: {r.errors}")
            provider_path = target / ".github" / "ci-review-provider.txt"
            self.assertTrue(
                provider_path.exists(),
                ".github/ci-review-provider.txt missing after install",
            )
            content = provider_path.read_text(encoding="utf-8").strip().lower()
            self.assertIn(
                content, self.ci_setup.PROVIDER_SECRETS,
                f"provider file content '{content}' not in catalog",
            )

    def test_provider_file_appears_in_expected_paths(self):
        """Issue #212-A1 sanity: the provider file path lives in EXPECTED_PATHS."""
        self.assertIn(
            ".github/ci-review-provider.txt",
            self.ci_setup.EXPECTED_PATHS,
            "ci-review-provider.txt not in EXPECTED_PATHS; consumers will not see it",
        )

    def test_required_secrets_catalog_contains_known_providers(self):
        """Issue #212-B1/B2: every supported provider has a secret entry."""
        for provider in ("minimax", "anthropic", "deepseek"):
            secrets = self.ci_setup.required_secrets_for_provider(provider)
            self.assertIn(
                "DEV_KIT_GITHUB_TOKEN", secrets,
                f"{provider}: missing DEV_KIT_GITHUB_TOKEN",
            )
            self.assertGreater(
                len(secrets), 1,
                f"{provider}: catalog only returned the consumer PAT; "
                "provider-specific API key is missing",
            )

    def test_required_secrets_unknown_provider_falls_back_to_minimax(self):
        """Unknown provider names fall back to the minimax catalog (matches the
        gate's default fallback). Always includes DEV_KIT_GITHUB_TOKEN."""
        secrets = self.ci_setup.required_secrets_for_provider("not-a-provider")
        self.assertIn("DEV_KIT_GITHUB_TOKEN", secrets)
        self.assertIn("MINIMAX_API_KEY", secrets)

    def test_gh_secret_set_command_format(self):
        """Issue #212-B3: helper renders an exact, paste-able gh command."""
        cmd = self.ci_setup.gh_secret_set_command("OWNER/REPO", "MINIMAX_API_KEY")
        self.assertEqual(cmd, "gh secret set MINIMAX_API_KEY --repo OWNER/REPO")

    def test_read_provider_file_returns_minimax_when_missing(self):
        """Issue #212-A1: read_provider_file falls back to 'minimax' (not raises)
        when the file is absent or unreadable, so the gate's default applies."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            # No file: returns 'minimax'.
            self.assertEqual(self.ci_setup.read_provider_file(target), "minimax")
            # Unknown value: returns 'minimax' (treated as missing).
            (target / ".github").mkdir(parents=True)
            (target / ".github" / "ci-review-provider.txt").write_text("garbage\n")
            self.assertEqual(self.ci_setup.read_provider_file(target), "minimax")
            # Recognized value: returns normalized value.
            (target / ".github" / "ci-review-provider.txt").write_text("DeepSeek\n")
            self.assertEqual(self.ci_setup.read_provider_file(target), "deepseek")

    def test_marker_verifies_after_install(self):
        """Issue #212-A3/E1: the marker must round-trip through a real
        read after atomic_write_json — empty/zero-byte markers fail loudly,
        not silently."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            r = self.ci_setup.install_ci_config(target)
            self.assertEqual(r.errors, [], f"errors: {r.errors}")
            marker = target / ".dev-kit" / "ci-config.json"
            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertIsInstance(payload, dict)
            self.assertGreater(len(payload), 0)
            # ci_review_provider_file pointer recorded for ci-doctor to read.
            self.assertEqual(
                payload.get("ci_review_provider_file"),
                ".github/ci-review-provider.txt",
            )


def tempfile_path(name: str):
    """Return a Path to a tempfile file (helper for test_invalid_target_dir_raises)."""
    import tempfile
    fd, p = tempfile.mkstemp(prefix=f"ci_setup_{name}_", suffix=".txt")
    os.close(fd)
    return Path(p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
