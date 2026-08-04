#!/usr/bin/env python3
"""test_sub_agent_handoff_hook.py — regression for SHO-154 hook."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK = REPO_ROOT / "hooks" / "sub-agent-handoff.sh"


def _has_jq() -> bool:
    return shutil.which("jq") is not None


def _agent_payload(response: str, tool_name: str = "Agent") -> str:
    return json.dumps({"tool_name": tool_name, "tool_response": response})


def _run_hook(payload: str, cwd: Path | None = None,
              env_extra: dict | None = None,
              strip_jq: bool = False,
              timeout: int = 15) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    if strip_jq:
        cleaned = env.get("PATH", "")
        parts = [p for p in cleaned.split(":") if p and not _which_in(p, "jq")]
        env["PATH"] = ":".join(parts)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
    )


def _which_in(path_dir: str, binary: str) -> bool:
    try:
        return shutil.which(binary, path=path_dir) is not None
    except Exception:
        return False


def _new_tmp_cwd() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory()


class HasAllThreePieces(unittest.TestCase):
    def test_full_handoff_passes(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        response = textwrap.dedent("""
            ## Sub-agent: cut worktree [SUCCESS]

            **Status**: ✅ success

            **PR**: https://github.com/foo/bar/pull/42
            **Branch**: fix/example

            ### Evidence (Iron Law L3, quoted)
            - `python3 -m pytest tests/ -v` -> `52 passed` (exit 0)
            - `bash -n hooks/sub-agent-handoff.sh` -> `OK` (exit 0)

            ### Files changed
            - `hooks/sub-agent-handoff.sh` -- new hook
            - `tests/test_sub_agent_handoff_hook.py` -- new tests

            ### Next action
            Open the PR and wait for CI.
        """).strip()
        proc = _run_hook(_agent_payload(response))
        self.assertEqual(proc.returncode, 0,
                         msg=f"exit={proc.returncode} stderr={proc.stderr!r}")
        self.assertIn("STATUS OK", proc.stderr,
                      msg=f"expected status-ok marker in stderr, got {proc.stderr!r}")
        self.assertNotIn("missing STATUS", proc.stderr,
                         msg=f"unexpected advisory: {proc.stderr!r}")
        self.assertNotIn("missing EVIDENCE", proc.stderr)
        self.assertNotIn("missing NEXT-ACTION", proc.stderr)


class MissingPiece(unittest.TestCase):
    def test_status_only_advisory_lists_others(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        response = textwrap.dedent("""
            **Status**: ✅ success

            I shipped the hook.
        """).strip()
        proc = _run_hook(_agent_payload(response))
        self.assertEqual(proc.returncode, 0,
                         msg=f"exit={proc.returncode} stderr={proc.stderr!r}")
        self.assertIn("missing EVIDENCE", proc.stderr,
                      msg=f"expected missing-EVIDENCE advisory, got {proc.stderr!r}")
        self.assertIn("missing NEXT-ACTION", proc.stderr,
                      msg=f"expected missing-NEXT-ACTION advisory, got {proc.stderr!r}")
        self.assertNotIn("missing STATUS", proc.stderr)

    def test_evidence_only_advisory_lists_others(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        response = textwrap.dedent("""
            `python3 -m pytest tests/ -v` -> `52 passed` (exit 0)
        """).strip()
        proc = _run_hook(_agent_payload(response))
        self.assertEqual(proc.returncode, 0)
        self.assertIn("missing STATUS", proc.stderr)
        self.assertIn("missing NEXT-ACTION", proc.stderr)
        self.assertNotIn("missing EVIDENCE", proc.stderr)


class EmptyPayload(unittest.TestCase):
    def test_empty_stdin_exits_zero(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        proc = _run_hook("")
        self.assertEqual(proc.returncode, 0,
                         msg=f"exit={proc.returncode} stderr={proc.stderr!r}")
        self.assertEqual(proc.stderr.strip(), "",
                         msg=f"expected empty stderr, got {proc.stderr!r}")


class JqMissing(unittest.TestCase):
    def test_fails_closed_when_jq_absent(self) -> None:
        if not _has_jq():
            self.skipTest("this test REQUIRES jq initially present to strip it")
        proc = _run_hook(_agent_payload("anything"), strip_jq=True)
        self.assertEqual(proc.returncode, 2,
                         msg=f"expected exit=2, got {proc.returncode} stderr={proc.stderr!r}")
        self.assertIn("permissionDecision", proc.stderr,
                      msg=f"expected deny envelope in stderr, got {proc.stderr!r}")
        self.assertIn("jq", proc.stderr.lower(),
                      msg=f"expected 'jq' in reason, got {proc.stderr!r}")


class MalformedPayload(unittest.TestCase):
    def test_invalid_json_non_blocking(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        proc = _run_hook("not-json-at-all {{ broken")
        self.assertEqual(proc.returncode, 0,
                         msg=f"expected non-blocking exit 0 on parse error, "
                             f"got {proc.returncode} stderr={proc.stderr!r}")
        self.assertTrue(
            any(token in proc.stderr.lower()
                for token in ("parse", "json", "malformed", "non-blocking")),
            msg=f"expected parse-error warn in stderr, got {proc.stderr!r}",
        )


class PerWorktreeOptOut(unittest.TestCase):
    def test_disabled_file_suppresses_advisory(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        tmp = _new_tmp_cwd()
        try:
            dev_kit_dir = Path(tmp.name) / ".dev-kit"
            dev_kit_dir.mkdir(parents=True, exist_ok=True)
            (dev_kit_dir / ".sub-agent-handoff-disabled").write_text("on\n")
            response = textwrap.dedent("""
                **Status**: ✅ success

                No evidence, no next action.
            """).strip()
            proc = _run_hook(_agent_payload(response), cwd=Path(tmp.name))
            self.assertEqual(proc.returncode, 0,
                             msg=f"exit={proc.returncode} stderr={proc.stderr!r}")
            self.assertNotIn("missing EVIDENCE", proc.stderr,
                             msg=f"opt-out did not suppress advisory: {proc.stderr!r}")
            self.assertNotIn("missing NEXT-ACTION", proc.stderr)
            self.assertIn("sub-agent-handoff", proc.stderr.lower(),
                          msg=f"expected opt-out notice in stderr, got {proc.stderr!r}")
        finally:
            tmp.cleanup()


class NonAgentTool(unittest.TestCase):
    def test_bash_tool_payload_skipped(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        response = "agent-style response with no structure at all"
        proc = _run_hook(_agent_payload(response, tool_name="Bash"))
        self.assertEqual(proc.returncode, 0,
                         msg=f"exit={proc.returncode} stderr={proc.stderr!r}")
        self.assertEqual(proc.stderr.strip(), "",
                         msg=f"non-Agent tool should not produce stderr, got {proc.stderr!r}")


class KoreanEvidence(unittest.TestCase):
    def test_quoted_exit_code_recognized(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        response = textwrap.dedent("""
            **Status**: ⚠️ partial

            `python3 -m pytest tests/ -v` -> `52 passed` (exit 0)
            `bash -n hooks/sub-agent-handoff.sh` -> `syntax ok` (exit 0)

            ### Next action
            별도 PR에서 후속 작업을 진행해주세요.
        """).strip()
        proc = _run_hook(_agent_payload(response))
        self.assertEqual(proc.returncode, 0,
                         msg=f"exit={proc.returncode} stderr={proc.stderr!r}")
        self.assertNotIn("missing EVIDENCE", proc.stderr,
                         msg=f"evidence should be detected: {proc.stderr!r}")


if __name__ == "__main__":
    unittest.main()
