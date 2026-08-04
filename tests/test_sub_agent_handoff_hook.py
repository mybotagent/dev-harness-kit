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
    env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
    tmp_bin = None
    if strip_jq:
        # Build an isolated bin dir with every utility the hook needs
        # (bash, cat, mktemp, python3, rm, printf, ...) but NOT jq.
        # This lets us strip jq from PATH on minimal CI images where
        # jq lives in the same dir as bash (e.g. /usr/bin on
        # ubuntu-latest) without losing the other deps the hook needs
        # to run far enough to hit the fail-closed check.
        tmp_bin = tempfile.mkdtemp(prefix="sub-agent-hook-jq-test-")
        for util in (
            "bash", "sh", "cat", "rm", "mktemp", "printf", "echo",
            "python3", "env", "true", "tr", "cut", "grep", "head",
            "tail", "sed", "awk", "wc", "dirname", "basename", "expr",
        ):
            src = shutil.which(util)
            if src and not os.path.exists(os.path.join(tmp_bin, util)):
                try:
                    os.symlink(src, os.path.join(tmp_bin, util))
                except FileExistsError:
                    pass
        cleaned = env.get("PATH", "")
        parts = [tmp_bin]
        for p in cleaned.split(":"):
            if p and not _which_in(p, "jq"):
                parts.append(p)
        env["PATH"] = ":".join(parts)
    if env_extra:
        env.update(env_extra)
    try:
        return subprocess.run(
            ["bash", str(HOOK)],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
        )
    finally:
        if tmp_bin:
            shutil.rmtree(tmp_bin, ignore_errors=True)


def _which_in(path_dir: str, binary: str) -> bool:
    try:
        return shutil.which(binary, path=path_dir) is not None
    except Exception:
        return False


def _run_hook_with_stripped(payload: str, *, strip: tuple[str, ...], cwd=None, env_extra=None, timeout: int = 15):
    """Like _run_hook but strips a tuple of binaries from PATH by
    creating an isolated bin dir with everything else symlinked in.

    Used by the JqMissing and PythonMissing tests so that the test
    fails closed on the target binary's absence without losing the
    other utilities the hook needs (bash, cat, mktemp, python3, …).
    """
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
    tmp_bin = tempfile.mkdtemp(prefix="sub-agent-hook-binary-test-")
    try:
        utilities = (
            "bash", "sh", "cat", "rm", "mktemp", "printf", "echo",
            "python3", "python", "py", "env", "true", "tr", "cut",
            "grep", "head", "tail", "sed", "awk", "wc", "dirname",
            "basename", "expr", "touch", "tee", "sort", "uniq",
            "find", "xargs", "command", "ln",
            "jq",  # used by the hook for payload parsing
        )
        for util in utilities:
            if util in strip:
                continue  # do not symlink the binaries we're stripping
            src = shutil.which(util)
            if src and not os.path.exists(os.path.join(tmp_bin, util)):
                try:
                    os.symlink(src, os.path.join(tmp_bin, util))
                except FileExistsError:
                    pass
        cleaned = env.get("PATH", "")
        parts = [tmp_bin]
        for p in cleaned.split(":"):
            if p and not any(_which_in(p, b) for b in strip):
                parts.append(p)
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
    finally:
        shutil.rmtree(tmp_bin, ignore_errors=True)


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
        proc = _run_hook_with_stripped(_agent_payload("anything"), strip=("jq",))
        self.assertEqual(proc.returncode, 2,
                         msg=f"expected exit=2, got {proc.returncode} stderr={proc.stderr!r}")
        # Plain stderr ERROR (PostToolUse cannot actually block; we
        # do NOT emit a permissionDecision envelope — see the hook
        # header for the rationale).
        self.assertNotIn("permissionDecision", proc.stderr,
                         msg=f"permissionDecision must not be emitted in PostToolUse; got {proc.stderr!r}")
        self.assertIn("jq", proc.stderr.lower(),
                      msg=f"expected 'jq' in reason, got {proc.stderr!r}")


class PythonMissing(unittest.TestCase):
    def test_fails_closed_when_python3_absent(self) -> None:
        # The hook's scan runs in Python (tolerates dict+list payload
        # shapes). Stripping only python3 (not python / py) simulates
        # a host where no Python interpreter is on PATH.
        proc = _run_hook_with_stripped(_agent_payload("anything"), strip=("python3", "python", "py"))
        self.assertEqual(proc.returncode, 2,
                         msg=f"expected exit=2, got {proc.returncode} stderr={proc.stderr!r}")
        self.assertNotIn("permissionDecision", proc.stderr)
        self.assertIn("python3", proc.stderr.lower(),
                      msg=f"expected 'python3' in reason, got {proc.stderr!r}")


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


class ProseEvidence(unittest.TestCase):
    """Finding SHO-154 / /dev-kit:review #3 — EVIDENCE regex too narrow.

    Real agent responses use prose forms that the canonical backtick
    arrow regex missed. The loosened regex now matches any `(exit N)`,
    bare `exit N`, `Ran 'cmd':` form, and shell-tool invocation
    prefixes as a line on its own.
    """

    def test_parenthesized_exit_in_prose(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        response = textwrap.dedent("""
            **Status**: ✅ success

            The patch landed; CI was green (exit 0) on the first push.

            ### Next action
            Run the suite locally before opening the PR.
        """).strip()
        proc = _run_hook(_agent_payload(response))
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("missing EVIDENCE", proc.stderr,
                         msg=f"prose evidence should be detected: {proc.stderr!r}")

    def test_bare_exit_in_prose(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        response = textwrap.dedent("""
            **Status**: ✅ success

            pytest finished with exit 0 across the touched modules.

            Open the PR and wait for CI.
        """).strip()
        proc = _run_hook(_agent_payload(response))
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("missing EVIDENCE", proc.stderr,
                         msg=f"bare 'exit N' should count as evidence: {proc.stderr!r}")
        self.assertNotIn("missing NEXT-ACTION", proc.stderr,
                         msg=f"final imperative should count as next-action: {proc.stderr!r}")

    def test_ran_clause_form(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        response = textwrap.dedent("""
            **Status**: ✅ success

            Ran 'pytest tests/ -q': 9 passed in 0.3s.

            Ship the PR.
        """).strip()
        proc = _run_hook(_agent_payload(response))
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("missing EVIDENCE", proc.stderr,
                         msg=f"`Ran 'cmd':` form should count as evidence: {proc.stderr!r}")

    def test_arrow_unicode_variant(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        response = textwrap.dedent("""
            **Status**: ✅ success

            `pytest tests/ -q` → `9 passed` (exit 0)

            ### Next action
            Land the PR.
        """).strip()
        proc = _run_hook(_agent_payload(response))
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("missing EVIDENCE", proc.stderr,
                         msg=f"`→` arrow variant should be recognized: {proc.stderr!r}")


class FinalImperativeNextAction(unittest.TestCase):
    """Finding SHO-154 / /dev-kit:review #4 — NEXT-ACTION regex too narrow.

    Real responses often close with an imperative sentence rather than
    an explicit `### Next action` heading. The loosened check accepts
    a final EN/KO imperative sentence.
    """

    def test_english_final_imperative(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        response = textwrap.dedent("""
            **Status**: ✅ success

            `pytest tests/ -v` -> `9 passed` (exit 0)
        """).strip() + "\n\nOpen the PR and wait for CI."
        proc = _run_hook(_agent_payload(response))
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("missing NEXT-ACTION", proc.stderr,
                         msg=f"final EN imperative should count as next-action: {proc.stderr!r}")

    def test_korean_final_imperative(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        response = textwrap.dedent("""
            **Status**: ✅ success

            `pytest tests/ -v` -> `9 passed` (exit 0)
        """).strip() + "\n\n마지막으로 PR을 열고 CI 결과를 기다려주세요."
        proc = _run_hook(_agent_payload(response))
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("missing NEXT-ACTION", proc.stderr,
                         msg=f"final KO imperative should count as next-action: {proc.stderr!r}")


class CanonicalMultiBlockDict(unittest.TestCase):
    """Finding SHO-154 / /dev-kit:review #7 — payload shape coverage.

    The Python block at hooks/sub-agent-handoff.sh:97-115 handles
    `tool_response` as a string, a dict with `content: list[dict]`,
    a dict with `content: str`, or `None`. The original test only
    built string payloads. Add the canonical multi-block dict here.
    """

    def test_multi_block_dict_payload(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        payload = json.dumps({
            "tool_name": "Agent",
            "tool_response": {
                "content": [
                    {"type": "text", "text": "**Status**: ✅ success\n\n`pytest` -> `9 passed` (exit 0)\n\n### Next action\nShip it."},
                ],
            },
        })
        proc = _run_hook(payload)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("missing STATUS", proc.stderr, msg=proc.stderr)
        self.assertNotIn("missing EVIDENCE", proc.stderr, msg=proc.stderr)
        self.assertNotIn("missing NEXT-ACTION", proc.stderr, msg=proc.stderr)

    def test_string_content_dict_payload(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        payload = json.dumps({
            "tool_name": "Agent",
            "tool_response": {
                "content": "**Status**: ✅ success\n\n`pytest` -> `9 passed` (exit 0)\n\n### Next action\nShip it.",
            },
        })
        proc = _run_hook(payload)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("missing STATUS", proc.stderr, msg=proc.stderr)
        self.assertNotIn("missing EVIDENCE", proc.stderr, msg=proc.stderr)
        self.assertNotIn("missing NEXT-ACTION", proc.stderr, msg=proc.stderr)

    def test_none_payload_is_silent(self) -> None:
        if not _has_jq():
            self.skipTest("jq is required on $PATH")
        payload = json.dumps({"tool_name": "Agent", "tool_response": None})
        proc = _run_hook(payload)
        self.assertEqual(proc.returncode, 0)
        # No text → no advisory, no stderr noise.
        self.assertEqual(proc.stderr.strip(), "", msg=proc.stderr)


if __name__ == "__main__":
    unittest.main()
