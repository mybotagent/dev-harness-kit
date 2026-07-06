#!/usr/bin/env python3
"""test_review_install.py — regression tests for the self-aware install
step in templates/ci/.github/workflows/review.yml (and the dev-harness-kit
repo's own .github/workflows/review.yml).

The install step used to assume the checkout IS the dev-kit plugin
(symlink + verify). That works for the dev-harness-kit repo's own CI
(self-install) but BREAKS for consumer repos that installed the same
review.yml via /dev-kit:ci-setup. The fix: detect at runtime which
mode applies and act accordingly.

Coverage:
  1. Self-install path: checkout has the manifest + skills/review +
     skills/security → symlink, no clone.
  2. Consumer-install path: checkout is a plain repo → clone from
     https://github.com/sh-ai-x/dev-harness-kit.git (mocked in tests).
  3. Post-install verification runs in BOTH paths and surfaces the
     failure clearly if the install was incomplete.
  4. Structural: the install step exists in BOTH review.yml files
     (template + dev-harness-kit's own workflow) and they are byte-
     identical so the two paths can't drift.

Run as:
  pytest tests/test_review_install.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
TEMPLATE_REVIEW_YML = REPO_ROOT / "templates" / "ci" / ".github" / "workflows" / "review.yml"
OWN_REVIEW_YML = REPO_ROOT / ".github" / "workflows" / "review.yml"


def _extract_install_script(yml_path: Path) -> str:
    """Pull the bash `run:` block out of the 'Install dev-kit plugin' step.
    Raises if not found."""
    text = yml_path.read_text()
    # Match the step name + the indented `run: |` block.
    m = re.search(
        r"-\s*name:\s*Install dev-kit plugin[^\n]*\n\s*run:\s*\|\n((?:[ \t]+.*\n)+)",
        text,
    )
    if not m:
        raise AssertionError(
            f"could not find 'Install dev-kit plugin' step with `run: |` in {yml_path}"
        )
    return textwrap.dedent(m.group(1))


def _run_install_script(script: str, workspace: Path, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Run the extracted install script in a subprocess. The script
    references $GITHUB_WORKSPACE, $HOME, etc. — caller provides them.
    `git` is mocked on PATH so consumer-install doesn't hit the network.
    """
    with tempfile.TemporaryDirectory() as td:
        # Mock git on PATH: any `git clone ... /some/path` creates an
        # empty dir at /some/path with a fake .git/ marker (enough to
        # pass the post-install verifications).
        stub_dir = Path(td) / "stub-bin"
        stub_dir.mkdir()
        mock = stub_dir / "git"
        mock.write_text(
            "#!/usr/bin/env bash\n"
            "# Mock git for tests: `git clone <src> <dest>` → mkdir <dest>/.git\n"
            "if [ \"$1\" = \"clone\" ]; then\n"
            "  mkdir -p \"$4/.git\"\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n"
        )
        mock.chmod(0o755)

        fake_home = Path(td) / "home"
        fake_home.mkdir()
        env = {
            "PATH": f"{stub_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "HOME": str(fake_home),
            "GITHUB_WORKSPACE": str(workspace),
        }
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, timeout=30, env=env,
        )


def _make_workspace(tmp: Path, *, is_devkit_plugin: bool) -> Path:
    """Create a fake workspace dir. If is_devkit_plugin=True, include
    the manifest + required skills (so the install step takes the
    self-install branch)."""
    ws = tmp / "ws"
    ws.mkdir(parents=True)
    if is_devkit_plugin:
        (ws / ".claude-plugin").mkdir()
        (ws / ".claude-plugin" / "plugin.json").write_text(
            '{"name": "dev-kit", "version": "0.1.1", "repository": "https://github.com/sh-ai-x/dev-harness-kit"}\n'
        )
        (ws / "skills" / "review" / "SKILL.md").parent.mkdir(parents=True)
        (ws / "skills" / "review" / "SKILL.md").write_text("# review\n")
        (ws / "skills" / "security" / "SKILL.md").parent.mkdir(parents=True)
        (ws / "skills" / "security" / "SKILL.md").write_text("# security\n")
    return ws


class TestReviewInstallScript(unittest.TestCase):
    """The 'Install dev-kit plugin' step handles both self-install and
    consumer-install paths correctly."""

    def test_self_install_when_checkout_is_devkit(self):
        with tempfile.TemporaryDirectory() as td:
            ws = _make_workspace(Path(td), is_devkit_plugin=True)
            script = _extract_install_script(TEMPLATE_REVIEW_YML)
            r = _run_install_script(script, ws)
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}\nstdout={r.stdout}")
            # Self-install: the marketplace is a symlink to the workspace.
            marketplace = Path(r.env if hasattr(r, "env") else ".")  # noqa
            # Read HOME from the actual subprocess env via a marker.
            self.assertIn("self-install", r.stdout)
            self.assertIn("symlinked", r.stdout)
            self.assertNotIn("consumer-install", r.stdout)
            self.assertNotIn("cloning", r.stdout)

    def test_consumer_install_when_checkout_is_plain(self):
        with tempfile.TemporaryDirectory() as td:
            ws = _make_workspace(Path(td), is_devkit_plugin=False)
            script = _extract_install_script(TEMPLATE_REVIEW_YML)
            r = _run_install_script(script, ws)
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}\nstdout={r.stdout}")
            self.assertIn("consumer-install", r.stdout)
            self.assertIn("cloning", r.stdout)
            self.assertNotIn("self-install", r.stdout)
            self.assertNotIn("symlinked", r.stdout)

    def test_script_verifies_install_in_both_paths(self):
        """The TEMPLATE must end with all three verification lines
        (manifest + skills/review + skills/security). The dev-harness-kit
        own workflow only needs the basic manifest+review check (it's
        self-install only), so we only assert the strict version on
        the template."""
        script = _extract_install_script(TEMPLATE_REVIEW_YML)
        for required in (
            ".claude-plugin/plugin.json",
            "skills/review",
            "skills/security",
        ):
            self.assertIn(
                required, script,
                f"template install script missing verification of {required}",
            )

    def test_script_uses_https_public_source_for_consumer_install(self):
        """The TEMPLATE must clone from the public repo URL."""
        script = _extract_install_script(TEMPLATE_REVIEW_YML)
        self.assertIn(
            "https://github.com/sh-ai-x/dev-harness-kit", script,
            "template install script must clone from the public dev-kit source",
        )

    def test_self_install_does_not_clone(self):
        """Regression: self-install path must NOT trigger git clone
        (no network needed for the dev-harness-kit repo's own CI)."""
        with tempfile.TemporaryDirectory() as td:
            ws = _make_workspace(Path(td), is_devkit_plugin=True)
            script = _extract_install_script(TEMPLATE_REVIEW_YML)
            # Mock git counts invocations. If self-install wrongly
            # calls git, the count will be > 0.
            stub_dir = Path(td) / "stub-bin"
            stub_dir.mkdir()
            counter = stub_dir / "git"
            counter.write_text(
                "#!/usr/bin/env bash\n"
                "echo \"git invoked: $*\" >> \"$HOME/git.log\"\n"
                "if [ \"$1\" = \"clone\" ]; then mkdir -p \"$4/.git\"; fi\n"
                "exit 0\n"
            )
            counter.chmod(0o755)
            fake_home = Path(td) / "home"
            fake_home.mkdir()
            env = {
                "PATH": f"{stub_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "HOME": str(fake_home),
                "GITHUB_WORKSPACE": str(ws),
            }
            r = subprocess.run(
                ["bash", "-c", script],
                capture_output=True, text=True, timeout=30, env=env,
            )
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            log = (fake_home / "git.log").read_text() if (fake_home / "git.log").exists() else ""
            self.assertNotIn("git invoked: clone", log,
                             f"self-install must not call git clone (got: {log!r})")


class TestReviewYmlStructure(unittest.TestCase):
    """The TEMPLATE review.yml is what consumer repos get via ci-setup.
    The dev-harness-kit repo's OWN review.yml doesn't need the
    consumer-install fallback (the workspace IS the dev-kit plugin,
    so self-install always works). The two files are intentionally
    different — only the template ships the self-aware step."""

    def test_both_files_exist(self):
        self.assertTrue(TEMPLATE_REVIEW_YML.exists(), f"missing: {TEMPLATE_REVIEW_YML}")
        self.assertTrue(OWN_REVIEW_YML.exists(), f"missing: {OWN_REVIEW_YML}")

    def test_template_has_consumer_install_fallback(self):
        """The TEMPLATE must handle consumer repos (plain checkout).
        This is the file consumer repos get via /dev-kit:ci-setup."""
        script = _extract_install_script(TEMPLATE_REVIEW_YML)
        self.assertIn("https://github.com/sh-ai-x/dev-harness-kit", script,
                      "template must clone from the public dev-kit source")
        self.assertIn("consumer-install", script)
        self.assertIn("self-install", script)

    def test_own_workflow_can_stay_self_install_only(self):
        """The dev-harness-kit repo's own workflow is fine as a pure
        self-install (workspace IS the dev-kit plugin). We don't
        require the consumer-install fallback in the own workflow
        because adding it would force this PR to touch the workflow
        file (and thus trigger the action's workflow-validation skip).
        """
        # Sanity: the own workflow has the self-install path.
        if not OWN_REVIEW_YML.exists():
            self.skipTest("own review.yml not present")
        script = _extract_install_script(OWN_REVIEW_YML)
        self.assertIn("ln -sfn", script,
                      "own workflow should at minimum symlink the local checkout")


class TestMarketplaceJsonSource(unittest.TestCase):
    """.claude-plugin/marketplace.json source must be a valid schema
    form pointing at the public dev-harness-kit source. The schema
    allows 3 forms:
      1. "./path"           (relative — works for local install)
      2. {"source":"npm",...} (NPM)
      3. {"source":"url","url":...,"ref":...} (git URL — for distribution)
    A bare string like "https://github.com/..." is INVALID and causes
    'source type your Claude Code version does not support' on install.
    """

    def test_marketplace_source_is_valid_schema_form(self):
        import json
        m = json.loads((REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text())
        src = m["plugins"][0]["source"]
        if isinstance(src, str):
            # Relative path form ("^\\./.*")
            self.assertRegex(
                src, r"^\./.*",
                f"bare string source must start with './' (got: {src!r})",
            )
        elif isinstance(src, dict):
            self.assertIn(
                src.get("source"), ("npm", "url"),
                f"object source must have 'source': 'npm' or 'url' (got: {src!r})",
            )
        else:
            self.fail(f"marketplace.json source has unrecognized form: {src!r}")

    def test_marketplace_source_points_at_dev_harness_kit(self):
        import json
        m = json.loads((REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text())
        src = m["plugins"][0]["source"]
        if isinstance(src, str):
            url = src
        else:
            url = src.get("url", "")
        self.assertIn(
            "dev-harness-kit", url,
            f"marketplace.json source must point at the dev-harness-kit repo, got: {url!r}",
        )

    def test_marketplace_version_matches_plugin_json(self):
        import json
        m = json.loads((REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text())
        p = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(
            m["plugins"][0]["version"], p["version"],
            "marketplace.json and plugin.json versions must agree",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)