#!/usr/bin/env python3
"""test_runtime_adapters_init.py — Pins Phase 0.7 (issue #343) export contract.

Acceptance criteria from issue #343 body:
  from runtime_adapters import ClaudeCodeAdapter, CodexAdapter works

Plus the explicit `__all__` contract:
  - RuntimeAdapter (Protocol)
  - TokenLog (dataclass)
  - SessionEvent (dataclass)
  - ClaudeCodeAdapter
  - CodexAdapter
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

# Mirror the rest of the repo's tests: add lib/ to sys.path so `import
# runtime_adapters` resolves directly without a setup.cfg install step.
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))


class TestRuntimeAdaptersExports(unittest.TestCase):
    def test_import_top_level_classes(self):
        mod = importlib.import_module("runtime_adapters")
        # Acceptance: the two adapter classes importable from the package root.
        self.assertTrue(hasattr(mod, "ClaudeCodeAdapter"))
        self.assertTrue(hasattr(mod, "CodexAdapter"))
        self.assertTrue(callable(mod.ClaudeCodeAdapter))
        self.assertTrue(callable(mod.CodexAdapter))

    def test_import_protocol_and_data_classes(self):
        mod = importlib.import_module("runtime_adapters")
        # RuntimeAdapter Protocol + TokenLog + SessionEvent are exported.
        self.assertTrue(hasattr(mod, "RuntimeAdapter"))
        self.assertTrue(hasattr(mod, "TokenLog"))
        self.assertTrue(hasattr(mod, "SessionEvent"))

    def test___all___is_declared_and_complete(self):
        mod = importlib.import_module("runtime_adapters")
        self.assertTrue(hasattr(mod, "__all__"))
        expected = {"RuntimeAdapter", "TokenLog", "SessionEvent",
                    "ClaudeCodeAdapter", "CodexAdapter"}
        self.assertTrue(
            expected.issubset(set(mod.__all__)),
            f"__all__ missing entries. Got: {sorted(mod.__all__)}, want superset of {sorted(expected)}",
        )

    def test_adapters_instantiate_with_no_args(self):
        """Both adapters expose a zero-arg constructor — the rest of the
        kit builds instances via `Adapter()` and wires dependencies through
        methods like `is_current()` that read env at call time."""
        from runtime_adapters import ClaudeCodeAdapter, CodexAdapter
        ClaudeCodeAdapter()
        CodexAdapter()

    def test_no_legacy_shadows(self):
        """Re-importing the same module twice must yield the same object —
        guard against any accidental module-shadow pattern that would split
        the API surface across two module objects."""
        import runtime_adapters as a
        import runtime_adapters as b
        self.assertIs(a, b)
        self.assertIs(a.ClaudeCodeAdapter, b.ClaudeCodeAdapter)


if __name__ == "__main__":
    unittest.main()
