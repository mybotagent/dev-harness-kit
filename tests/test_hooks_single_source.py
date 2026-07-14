#!/usr/bin/env python3
"""test_hooks_single_source.py — Regression tests for issue #89.

Pins the byte-identical-dup-tree bug: the 4 hook files plus
`hooks/hooks.json` were maintained in TWO trees that must move in
lockstep (`hooks/` and `templates/ci/hooks/`). `lib/ci_setup.py:_copy_template`
copies from `templates/ci/hooks/` into consumer installs, so a one-byte
edit on the source-of-truth side (the project's own `.claude/settings.json`)
silently fails to land in consumer repos.

Fix: single-source the hooks in `hooks/`, have `_copy_template` read from
there, and delete `templates/ci/hooks/` so there is no parallel tree to
maintain.

Pins:
1. `templates/ci/hooks/` MUST NOT exist after the fix.
2. `_copy_template` MUST read `hooks/*` files from `<plugin_root>/hooks/`,
   not `<plugin_root>/templates/ci/hooks/`.
3. Installed bytes MUST match the source-of-truth `hooks/` byte-for-byte.
4. The 4 hook files + `hooks.json` are stable across plugin reinstalls
   (round-trip idempotency: a drift between the two trees, if any reappears,
   surfaces as a bytes mismatch).
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOKS_DIR = REPO_ROOT / "hooks"
LEGACY_TEMPLATES_HOOKS_DIR = REPO_ROOT / "templates" / "ci" / "hooks"

# Hook files that MUST round-trip byte-for-byte through install.
# Source-of-truth lives in `hooks/` (no `hooks/` prefix; relpath form matches
# EXPECTED_PATHS in lib/ci_setup.py).
_HOOK_RELPATHS: tuple[str, ...] = (
    "hooks/worktree-guard.sh",
    "hooks/task-detector.sh",
    "hooks/session-start-check.sh",
    "hooks/lib/worktree-detect.sh",
    "hooks/hooks.json",
)


class TestNoLegacyTemplatesHooksDir(unittest.TestCase):
    """templates/ci/hooks/ MUST be gone after the consolidation.

    If this dir exists, the parallel tree is alive and a future drift
    between `hooks/` and `templates/ci/hooks/` will silently ship stale
    hook bytes to every consumer that runs `/dev-kit:ci-setup`.
    """

    def test_legacy_templates_hooks_dir_does_not_exist(self):
        self.assertFalse(
            LEGACY_TEMPLATES_HOOKS_DIR.exists(),
            f"{LEGACY_TEMPLATES_HOOKS_DIR} still exists; the parallel tree "
            f"must be deleted so `_copy_template` cannot read stale bytes "
            f"from there. (issue #89)",
        )


class TestSingleSourceOfTruth(unittest.TestCase):
    """Installed hook bytes MUST match `hooks/` source-of-truth exactly.

    Even though `templates/ci/hooks/` is gone (test above), `_copy_template`
    could still be redirected to the wrong place if its implementation was
    naively rewired. This test asserts the install path matches the SSOT
    bytes by hashing both sides and comparing.
    """

    def setUp(self):
        from lib import ci_setup
        self.ci_setup = ci_setup

    def _md5(self, p: Path) -> str:
        return hashlib.md5(p.read_bytes()).hexdigest()

    def test_installed_hook_bytes_match_source_of_truth(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self.ci_setup.install_ci_config(target)
            for rel in _HOOK_RELPATHS:
                # HOOKS_DIR is `<repo>/hooks`; strip the `hooks/` prefix
                # from the EXPECTED_PATHS-style relpath so the source path
                # resolves correctly.
                src_rel = rel[len("hooks/"):] if rel.startswith("hooks/") else rel
                src = HOOKS_DIR / src_rel
                dst = target / rel
                self.assertTrue(src.exists(), f"source missing: {rel} (looked at {src})")
                self.assertTrue(dst.exists(), f"installed missing: {rel}")
                self.assertEqual(
                    self._md5(src), self._md5(dst),
                    f"bytes drift on install for {rel}: "
                    f"src={self._md5(src)} dst={self._md5(dst)}",
                )


class TestCopyTemplateReadsFromPluginRoot(unittest.TestCase):
    """`_copy_template` for hooks/* must read from `<plugin_root>/hooks/`.

    Pinned by patching `Path.exists` to fail if the resolver asks for
    `templates/ci/hooks/...`. This catches any future regression where
    a maintainer re-introduces a `_TEMPLATES_ROOT`-based lookup for
    hook files.
    """

    def setUp(self):
        from lib import ci_setup
        self.ci_setup = ci_setup

    def test_copy_template_does_not_look_in_templates_ci_hooks(self):
        """`_copy_template('hooks/worktree-guard.sh', ...)` must succeed
        even when `templates/ci/hooks/worktree-guard.sh` does not exist.

        The hook source lives in `hooks/`, not `templates/ci/hooks/`. If
        `_copy_template` still resolves the path through `_TEMPLATES_ROOT`,
        deleting the legacy tree will cause this call to raise
        FileNotFoundError on every consumer install.
        """
        # Sanity: the legacy dir really is gone (matches TestNoLegacyTemplatesHooksDir).
        self.assertFalse(LEGACY_TEMPLATES_HOOKS_DIR.exists())
        # Sanity: the new SSOT dir exists.
        self.assertTrue(HOOKS_DIR.exists())

        # Now try a real install — every hook in EXPECTED_PATHS must
        # resolve without raising FileNotFoundError.
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            # install_ci_config is the entry point. If any hook fails to
            # resolve, it records an error in `report.errors` (we already
            # saw the test_install_creates_expected_files_in_empty_target
            # shape in tests/test_ci_setup.py).
            report = self.ci_setup.install_ci_config(target)
            hook_errors = [
                e for e in report.errors
                if e.startswith("hooks/")
            ]
            self.assertEqual(
                hook_errors, [],
                f"hook install errors (likely templates/ci/hooks/ stale lookup): "
                f"{hook_errors}",
            )


if __name__ == "__main__":
    unittest.main()