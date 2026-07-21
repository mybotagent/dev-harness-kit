#!/usr/bin/env python3
"""test_llm_judge_except_narrowing.py — slice 315 of #310.

The bare ``except Exception:`` in ``llm_judge.parse_scores_json`` (line
124) was narrowed to ``(json.JSONDecodeError, KeyError, TypeError,
ValueError)``. This file pins the propagation contract — KeyboardInterrupt
and SystemExit must still escape the fallback try block so a Ctrl-C and a
clean interpreter exit work as expected.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import llm_judge  # noqa: E402


class _FakeMatch:
    """Minimal stand-in for re.Match: returns the given text from .group()."""

    def __init__(self, text: str) -> None:
        self._text = text

    def group(self, *_args, **_kwargs) -> str:
        return self._text


class TestParseScoresJsonNarrowing(unittest.TestCase):
    """parse_scores_json — narrowing at line 124 must not catch BaseException."""

    def test_keyboard_interrupt_propagates(self):
        """A KeyboardInterrupt raised from inside the fallback try escapes."""
        with patch("llm_judge.re.search", return_value=_FakeMatch("{}")), \
             patch("llm_judge.json.loads", side_effect=KeyboardInterrupt("stop")):
            with pytest.raises(KeyboardInterrupt):
                llm_judge.parse_scores_json("garbage with {truthfulness:5}")

    def test_system_exit_propagates(self):
        with patch("llm_judge.re.search", return_value=_FakeMatch("{}")), \
             patch("llm_judge.json.loads", side_effect=SystemExit(0)):
            with pytest.raises(SystemExit):
                llm_judge.parse_scores_json("garbage with {truthfulness:5}")

    def test_value_error_in_coercion_becomes_empty(self):
        """ValueError IS in the narrowed set — must be swallowed, return {}.

        The first ``json.loads`` fails (input is not pure JSON), so the
        regex fallback runs and extracts the axis block. Inside the
        fallback, ``float(data[ax])`` raises ValueError — that must be
        caught by the narrowed except and the function returns ``{}``.
        """
        bad = 'garbage {truthfulness: "not-a-number"} more'
        out = llm_judge.parse_scores_json(bad, axes=("truthfulness",))
        self.assertEqual(out, {})

    def test_json_decode_error_in_fallback_becomes_empty(self):
        """When the regex extracts a non-JSON block, narrowed except returns {}."""
        out = llm_judge.parse_scores_json("xxxx {not_json} yyyy", axes=("truthfulness",))
        self.assertEqual(out, {})


if __name__ == "__main__":
    unittest.main()
