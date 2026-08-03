#!/usr/bin/env python3
"""test_push_intent_judge.py — RED-first tests for lib/push_intent_judge.py.

The CLI is a thin wrapper around ``llm_judge.call_judge`` for the
``push_intent`` dim. It prints a parseable
``VERDICT=<OK|DRIFT_WARNING|ROT> REASON="..."`` line to stdout and exits
non-zero on ROT/DRIFT_WARNING so the pre-push hook can ``exit 1`` on a
bad intent signal.

All HTTP is mocked via ``llm_judge._http_post`` (the existing test seam
in lib/llm_judge.py). No network access.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import llm_judge  # noqa: E402
import push_intent_judge  # noqa: E402


class TestPushIntentJudge(unittest.TestCase):
    """CLI behavior for the pre-push hook's intent judge."""

    REPO_ROOT = Path(__file__).parent.parent

    def _make_mock_response(self, scores: dict) -> dict:
        return {
            "content": [{"type": "text", "text": json.dumps(scores)}],
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }

    def _fake_key_env(self):
        """Patch env so load_config finds a fake api_key for the LLM path."""
        return patch.dict(os.environ, {
            "JUDGE_PROVIDER": "minimax",
            "JUDGE_MODEL": "MiniMax-M3[1m]",
            "MINIMAX_API_KEY": "test-fake-key",
            "ANTHROPIC_API_KEY": "",
        }, clear=True)

    def test_rot_verdict_returns_exit_1(self):
        scores = {
            "intent_clarity": 2.0,
            "scope_discipline": 1.5,
            "change_necessity": 2.5,
            "value_alignment": 2.0,
        }
        with self._fake_key_env(), \
             patch.object(llm_judge, "_http_post", return_value=self._make_mock_response(scores)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = push_intent_judge.run(
                    project_root=self.REPO_ROOT,
                    commit_message="x",
                    diff_stat=" x 1 +1 -1",
                    diff_sample="",
                )
        self.assertEqual(rc, 1)
        self.assertIn("VERDICT=ROT", buf.getvalue())
        self.assertIn("REASON=", buf.getvalue())

    def test_ok_verdict_returns_exit_0(self):
        scores = {
            "intent_clarity": 9.0,
            "scope_discipline": 9.5,
            "change_necessity": 9.0,
            "value_alignment": 9.0,
        }
        with self._fake_key_env(), \
             patch.object(llm_judge, "_http_post", return_value=self._make_mock_response(scores)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = push_intent_judge.run(
                    project_root=self.REPO_ROOT,
                    commit_message="feat(eval): add maintenance gate prompt",
                    diff_stat=" eval/prompts/judge-maintenance.md | 50 +++++++++++++++",
                    diff_sample="+ # Maintenance Judge ...",
                )
        self.assertEqual(rc, 0)
        self.assertIn("VERDICT=OK", buf.getvalue())

    def test_drift_warning_returns_exit_1(self):
        # DRIFT_WARNING also blocks the push (matches verdict_from_score
        # band) — only OK is non-blocking. Otherwise pushing a "mostly
        # OK" commit would silently pass under opt-in.
        scores = {
            "intent_clarity": 7.0,
            "scope_discipline": 6.0,
            "change_necessity": 5.5,
            "value_alignment": 7.5,
        }
        with self._fake_key_env(), \
             patch.object(llm_judge, "_http_post", return_value=self._make_mock_response(scores)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = push_intent_judge.run(
                    project_root=self.REPO_ROOT,
                    commit_message="wip",
                    diff_stat=" x 1 +1 -1",
                    diff_sample="",
                )
        self.assertEqual(rc, 1)
        self.assertIn("VERDICT=DRIFT_WARNING", buf.getvalue())

    def test_missing_api_key_returns_exit_2(self):
        with patch.dict(os.environ, {
            "JUDGE_PROVIDER": "minimax",
            "JUDGE_MODEL": "MiniMax-M3[1m]",
            "MINIMAX_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
        }, clear=True):
            with tempfile.TemporaryDirectory() as td:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = push_intent_judge.run(
                        project_root=Path(td),
                        commit_message="x",
                        diff_stat=" x 1 +1 -1",
                        diff_sample="",
                    )
        self.assertEqual(rc, 2)
        self.assertIn("VERDICT=ROT", buf.getvalue())
        self.assertIn("api_key", buf.getvalue().lower())

    def test_malformed_json_falls_back_to_regex_parse(self):
        # Some model responses put the JSON inside prose. The fallback
        # regex in parse_scores_json must catch it. Verify the CLI
        # returns a verdict (not ROT) when the score block is recoverable.
        text = (
            "Here are my scores:\n"
            '{"intent_clarity": 9, "scope_discipline": 8,'
            ' "change_necessity": 9, "value_alignment": 8}\n'
            "Done."
        )
        with self._fake_key_env(), \
             patch.object(llm_judge, "_http_post", return_value={
                "content": [{"type": "text", "text": text}],
                "usage": {"input_tokens": 5, "output_tokens": 15},
             }):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = push_intent_judge.run(
                    project_root=self.REPO_ROOT,
                    commit_message="x",
                    diff_stat=" x 1 +1 -1",
                    diff_sample="",
                )
        self.assertEqual(rc, 0)
        self.assertIn("VERDICT=OK", buf.getvalue())

    def test_cli_invocation_returns_parseable_output(self):
        # End-to-end subprocess invocation: run the CLI as `python3 -m
        # lib.push_intent_judge ...` and assert stdout is the canonical
        # `VERDICT=... REASON="..."` shape. Uses a mock JSON-shaped input
        # to keep the test hermetic.
        py = sys.executable
        env = os.environ.copy()
        # Ensure no live API key path is taken; the script should ROT
        # when both keys are missing and we feed it real-looking inputs.
        env["MINIMAX_API_KEY"] = ""
        env["ANTHROPIC_API_KEY"] = ""
        result = subprocess.run(
            [py, "-m", "lib.push_intent_judge",
             "--project-root", tempfile.mkdtemp(),
             "--commit-message", "feat: add x",
             "--diff-stat", " x 1 +1 -1",
             "--diff-sample", "+x"],
            env=env,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent),
            timeout=30,
        )
        self.assertEqual(result.returncode, 2,
                         f"expected exit 2 (no api key), got {result.returncode}; "
                         f"stdout={result.stdout!r} stderr={result.stderr!r}")
        self.assertIn("VERDICT=ROT", result.stdout)
        self.assertIn("REASON=", result.stdout)


class TestPushIntentVerdictBoundary(unittest.TestCase):
    """The CLI must mirror verdict_from_score's band boundaries."""

    REPO_ROOT = Path(__file__).parent.parent

    def _fake_key_env(self):
        return patch.dict(os.environ, {
            "JUDGE_PROVIDER": "minimax",
            "JUDGE_MODEL": "MiniMax-M3[1m]",
            "MINIMAX_API_KEY": "test-fake-key",
            "ANTHROPIC_API_KEY": "",
        }, clear=True)

    def test_boundary_8_is_ok(self):
        scores = {
            "intent_clarity": 8.0,
            "scope_discipline": 8.0,
            "change_necessity": 8.0,
            "value_alignment": 8.0,
        }
        with self._fake_key_env(), \
             patch.object(llm_judge, "_http_post", return_value={
                "content": [{"type": "text", "text": json.dumps(scores)}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
             }):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = push_intent_judge.run(
                    project_root=self.REPO_ROOT,
                    commit_message="x", diff_stat=" x 1 +1 -1", diff_sample="",
                )
        self.assertEqual(rc, 0)
        self.assertIn("VERDICT=OK", buf.getvalue())

    def test_boundary_5_is_drift_warning(self):
        scores = {
            "intent_clarity": 5.0,
            "scope_discipline": 5.0,
            "change_necessity": 5.0,
            "value_alignment": 5.0,
        }
        with self._fake_key_env(), \
             patch.object(llm_judge, "_http_post", return_value={
                "content": [{"type": "text", "text": json.dumps(scores)}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
             }):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = push_intent_judge.run(
                    project_root=self.REPO_ROOT,
                    commit_message="x", diff_stat=" x 1 +1 -1", diff_sample="",
                )
        self.assertEqual(rc, 1)
        self.assertIn("VERDICT=DRIFT_WARNING", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
