#!/usr/bin/env python3
"""test_ci_setup_atomic_import.py — Regression tests for issue #90.

Pins the bug: `lib/ci_setup.py` inlines a 19-line copy of
`lib/atomic.atomic_write_json` with a docstring claiming "target projects
install ONLY what's inside templates/ci/, not lib/*.py". That rationale
is wrong — `lib/install.sh:53` copies every `lib/*.py` to `target/lib/`,
and line 94 explicitly verifies `atomic.py` is shipped. So the inline
copy is dead-code drift waiting to happen: any improvement to
`lib/atomic.atomic_write_json` (fsync-on-replace, mode preservation,
locale-safe tmp prefix, fallback `default=str`) silently fails to land
in ci_setup.py's marker write path, and the two copies diverge over time
with no test asserting they stay byte-equivalent.

Fix:
1. Replace `lib/ci_setup.py:_atomic_write_json` with `from atomic import atomic_write_json`.
2. Replace the single internal call site (`_atomic_write_json(marker, _build_marker())`)
   with `atomic_write_json(marker, _build_marker())`.
3. Delete the inline copy + the docstring claim.
4. Folded in #80 item 6: remove the duplicate `import re` (lines 20 and 23).

Pins (post-fix):
1. `lib/ci_setup.py` MUST import `atomic_write_json` from `lib/atomic` (not
   redefine it). This catches any future regression where a maintainer
   re-inlines the function or copies a stale version.
2. The marker written by `install_ci_config` MUST go through the canonical
   `lib/atomic.atomic_write_json` (asserted via a sentinel injection test
   on `atomic.atomic_write_json`).
3. `lib/ci_setup.py` MUST NOT have duplicate top-level `import re`
   statements (#80 item 6, folded in).
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import re as _re
import sys
import tempfile
import unittest
from pathlib import Path

# Mirror tests/test_ci_setup.py:13-19 — `lib/` is not a package (no
# __init__.py), so we add it to sys.path and load ci_setup.py by file path.
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))


def _load_ci_setup():
    """Load lib/ci_setup.py via spec_from_file_location (test_ci_setup.py pattern)."""
    name = "ci_setup"
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "lib" / "ci_setup.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestCiSetupImportsCanonicalAtomicWrite(unittest.TestCase):
    """Issue #90: ci_setup must NOT redefine atomic_write_json."""

    def setUp(self):
        # Force a fresh import so the module body re-runs after any
        # worktree-local edits. `lib/` is not a package (no __init__.py),
        # so we use spec_from_file_location like tests/test_ci_setup.py:22-33.
        sys.modules.pop("ci_setup", None)
        self.ci_setup = _load_ci_setup()
        from atomic import atomic_write_json
        self.atomic_write_json = atomic_write_json

    def test_ci_setup_imports_atomic_write_json_from_lib(self):
        """`lib.ci_setup` must expose `atomic_write_json` as an alias for
        `lib.atomic.atomic_write_json` (or directly import + use it). It
        must NOT define its own `_atomic_write_json` function with its own
        implementation.
        """
        self.assertTrue(
            hasattr(self.ci_setup, "atomic_write_json"),
            "ci_setup must import atomic_write_json from lib.atomic",
        )
        # If both exist, the imported one must equal the canonical.
        imported = getattr(self.ci_setup, "atomic_write_json", None)
        self.assertIs(
            imported, self.atomic_write_json,
            "ci_setup.atomic_write_json is NOT the canonical "
            "lib.atomic.atomic_write_json — drift has reappeared (issue #90)",
        )

    def test_ci_setup_does_not_define_atomic_write_json_inline(self):
        """The module must NOT define its own `def _atomic_write_json(...)` or
        `def atomic_write_json(...)`. Both functions must resolve to the
        canonical implementation in lib.atomic.
        """
        # If `_atomic_write_json` exists in ci_setup, it must be an alias
        # for the canonical (or absent entirely).
        if hasattr(self.ci_setup, "_atomic_write_json"):
            local = self.ci_setup._atomic_write_json
            self.assertIs(
                local, self.atomic_write_json,
                "ci_setup._atomic_write_json is a private reimplementation "
                "of atomic_write_json — inline-copy drift reappeared "
                "(issue #90)",
            )


class TestMarkerWriteGoesThroughCanonicalAtomic(unittest.TestCase):
    """End-to-end: the marker written by install_ci_config must come from
    the canonical `lib.atomic.atomic_write_json` (not a side-channel copy).

    Pin via sentinel injection: monkey-patch `lib.atomic.atomic_write_json`
    with a wrapper that tags the result. If install_ci_config uses the
    canonical function, the marker carries the sentinel tag.
    """

    def setUp(self):
        sys.modules.pop("ci_setup", None)
        self.ci_setup = _load_ci_setup()

    def test_marker_write_invokes_canonical_atomic_write_json(self):
        """install_ci_config must invoke lib.atomic.atomic_write_json
        (sentinel-injected). If it bypasses the import and calls an
        inline copy, the sentinel never fires and the marker is written
        via the side-channel implementation — drift.

        NB: `lib/ci_setup.py` does `from atomic import atomic_write_json`
        at module load, so `ci_setup.atomic_write_json` is a bound name
        pointing at the function object captured at load time. To
        sentinel-instrument it, we patch the bound name directly on
        `ci_setup` (rather than on `atomic`), so the function name
        actually called by install_ci_config is replaced with our wrapper.
        """
        original = self.ci_setup.atomic_write_json
        sentinel_calls: list[tuple[Path, object]] = []

        def sentinel(path, data):
            sentinel_calls.append((path, data))
            return original(path, data)

        self.ci_setup.atomic_write_json = sentinel
        try:
            with tempfile.TemporaryDirectory() as td:
                target = Path(td)
                report = self.ci_setup.install_ci_config(target)
        finally:
            self.ci_setup.atomic_write_json = original

        self.assertTrue(
            report.ok, f"install_ci_config reported errors: {report.errors}",
        )
        marker_calls = [
            (p, d) for (p, d) in sentinel_calls
            if str(p).endswith(".dev-kit/ci-config.json")
            or str(p).endswith("ci-config.json")
        ]
        self.assertGreater(
            len(marker_calls), 0,
            f"install_ci_config did not call canonical atomic_write_json "
            f"for the marker. Sentinel saw calls to: "
            f"{[str(p) for (p, _) in sentinel_calls]}",
        )
        # The data passed must be a dict (marker schema) — catches any
        # accidental call with the wrong arg shape.
        _, marker_data = marker_calls[0]
        self.assertIsInstance(
            marker_data, dict,
            f"marker data passed to atomic_write_json must be a dict, "
            f"got {type(marker_data).__name__}",
        )
        self.assertIn(
            "schema_version", marker_data,
            "marker data missing schema_version — install_ci_config may "
            "be writing the wrong payload (issue #90 regression)",
        )


class TestCiSetupHasNoDuplicateImportRe(unittest.TestCase):
    """#80 item 6 (folded into #90 fix): lib/ci_setup.py must not have
    two top-level `import re` statements.
    """

    def setUp(self):
        sys.modules.pop("ci_setup", None)
        self.ci_setup = _load_ci_setup()

    def test_no_duplicate_import_re_in_ci_setup_source(self):
        """lib/ci_setup.py top-level must contain exactly one
        `import re` statement. Pre-fix it has two (lines 20 + 23).

        Scope: only the top-level import block (before any `def`/`class`).
        Function-local imports (e.g. `import re as _re` inside
        """
        src_path = Path(self.ci_setup.__file__)
        src_lines = src_path.read_text().splitlines()
        top_level_end = 0
        for i, line in enumerate(src_lines):
            if _re.match(r"^(def|class)\s+\w+", line):
                top_level_end = i
                break
        top_level = "\n".join(src_lines[:top_level_end])
        re_imports = _re.findall(
            r"^\s*import\s+re\b", top_level, flags=_re.MULTILINE,
        )
        self.assertEqual(
            len(re_imports), 1,
            f"lib/ci_setup.py top-level import block has {len(re_imports)} "
            f"`import re` statements (expected exactly 1). Pre-fix count "
            f"was 2. (#80 item 6)",
        )


if __name__ == "__main__":
    unittest.main()