#!/usr/bin/env python3
"""test_llm_pricing_public.py — RED-first tests for the public llm_pricing lookup.

Issue #310 (overarch finding): ``lib/cost_gate.py`` reaches into
``lib/llm_pricing._pricing_cache`` (a private lru_cache-backed function).
The cross-module coupling on a private symbol made it impossible to
refactor the cache without silently breaking cost_gate.

Fix: expose a public lookup surface (``is_known_model`` /
``iter_known_ids``) on `llm_pricing`. Update cost_gate to use it.
No behavior change for existing call sites.

Scope: only the public lookup. The legacy fallback dict and the
internal `_pricing_cache` continue to exist; cost_gate's
`_looks_like_known` is replaced by the public `is_known_model`.
"""
from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))


def _load_llm_pricing():
    name = "llm_pricing"
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "lib" / "llm_pricing.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestPublicLookupAPI(unittest.TestCase):
    """The public lookup surface exists and is callable."""

    @classmethod
    def setUpClass(cls):
        cls.lp = _load_llm_pricing()

    def test_is_known_model_is_callable(self):
        self.assertTrue(
            callable(getattr(self.lp, "is_known_model", None)),
            "llm_pricing.is_known_model must be a public callable "
            "(issue #310 overarch)",
        )

    def test_iter_known_ids_is_callable(self):
        self.assertTrue(
            callable(getattr(self.lp, "iter_known_ids", None)),
            "llm_pricing.iter_known_ids must be a public callable "
            "(issue #310 overarch)",
        )


class TestIsKnownModel(unittest.TestCase):
    def setUp(self):
        self.lp = _load_llm_pricing()
        self.lp.clear_cache()

    def test_known_model_returns_true(self):
        # `claude-opus-4-8` is in docs/llm-info/claude.json; the loader
        # reads it via the JSON SSOT, so this must resolve to True.
        self.assertTrue(self.lp.is_known_model("claude-opus-4-8"))

    def test_unknown_model_returns_false(self):
        self.assertFalse(self.lp.is_known_model("totally-bogus-model-xyz"))

    def test_empty_string_returns_false(self):
        self.assertFalse(self.lp.is_known_model(""))

    def test_substring_match_returns_true(self):
        # The same normalized-prefix matching that `pricing_for` uses
        # applies here — `gpt-5.5-pro` must hit the `gpt-5-5-pro` slug.
        self.assertTrue(self.lp.is_known_model("gpt-5.5-pro"))

    def test_case_insensitive(self):
        self.assertTrue(self.lp.is_known_model("CLAUDE-OPUS-4-8"))


class TestIterKnownIds(unittest.TestCase):
    def setUp(self):
        self.lp = _load_llm_pricing()
        self.lp.clear_cache()

    def test_returns_iterable(self):
        ids = list(self.lp.iter_known_ids())
        self.assertIsInstance(ids, list)
        self.assertGreater(len(ids), 0, "loader produced an empty id list")

    def test_includes_known_claude_id(self):
        ids = list(self.lp.iter_known_ids())
        self.assertIn("claude-opus-4-8", ids,
                      "expected the canonical Claude id in iter_known_ids")

    def test_includes_legacy_fallback_keys(self):
        # Legacy fallback ids (opus/sonnet/haiku/minimax/...) must stay
        # in the known set even when the JSON SSOT is present — they
        # are the names cost_gate and the analyzer may pass in.
        ids = set(self.lp.iter_known_ids())
        for legacy in ("opus", "sonnet", "haiku", "minimax"):
            self.assertIn(legacy, ids,
                          f"legacy fallback id {legacy!r} missing from iter_known_ids")

    def test_no_stderr_warn_when_iterating(self):
        # Iterating must NOT trigger the "WARN: unknown model" path —
        # we are listing known ids, not resolving one.
        buf = io.StringIO()
        with redirect_stderr(buf):
            list(self.lp.iter_known_ids())
        self.assertNotIn("WARN: unknown model", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
