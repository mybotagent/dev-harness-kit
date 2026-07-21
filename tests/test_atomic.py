#!/usr/bin/env python3
"""test_atomic.py — RED-first tests for lib/atomic.py read helpers.

Targets the `read_json_or_default` helper extracted from the codecs
(state_codec, active_hooks_codec, ci_setup) that all repeat the same
"file missing → default, corrupt → default, otherwise json.loads"
pattern. Pure stdlib; uses tmpdirs only.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import atomic  # noqa: E402


class TestReadJsonOrDefault(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_returns_default(self):
        sentinel = {"_default": True}
        result = atomic.read_json_or_default(self.root / "missing.json", sentinel)
        self.assertEqual(result, sentinel)

    def test_valid_json_returns_parsed_dict(self):
        p = self.root / "ok.json"
        p.write_text(json.dumps({"k": 1, "nested": {"x": [1, 2]}}), encoding="utf-8")
        result = atomic.read_json_or_default(p, {"_default": True})
        self.assertEqual(result, {"k": 1, "nested": {"x": [1, 2]}})

    def test_valid_json_list_returns_list(self):
        p = self.root / "list.json"
        p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        result = atomic.read_json_or_default(p, [])
        self.assertEqual(result, [1, 2, 3])

    def test_corrupt_json_returns_default(self):
        p = self.root / "corrupt.json"
        p.write_text("not-json{", encoding="utf-8")
        sentinel = {"_default": True}
        result = atomic.read_json_or_default(p, sentinel)
        self.assertEqual(result, sentinel)

    def test_empty_file_returns_default(self):
        p = self.root / "empty.json"
        p.write_text("", encoding="utf-8")
        sentinel = {"_default": True}
        result = atomic.read_json_or_default(p, sentinel)
        self.assertEqual(result, sentinel)

    def test_default_can_be_none(self):
        # load_transcript / _load_session_cache in eval_runner use
        # default=None; verify the helper honors it.
        result = atomic.read_json_or_default(self.root / "missing.json", None)
        self.assertIsNone(result)

    def test_default_is_returned_by_reference_not_copied(self):
        # Mutating the returned default must NOT mutate the caller's
        # object — the helper returns the *same* object only on miss,
        # but mutating it is the caller's responsibility. The contract
        # is: on miss, return the exact default; on hit, return the
        # parsed JSON (a fresh object).
        sentinel: dict = {"_default": True}
        result = atomic.read_json_or_default(self.root / "missing.json", sentinel)
        self.assertIs(result, sentinel)

    def test_unicode_content_round_trips(self):
        p = self.root / "ko.json"
        p.write_text(json.dumps({"name": "테스트", "emoji": "🚀"}), encoding="utf-8")
        result = atomic.read_json_or_default(p, {})
        self.assertEqual(result, {"name": "테스트", "emoji": "🚀"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
