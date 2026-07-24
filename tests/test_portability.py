#!/usr/bin/env python3
"""test_portability.py — Phase 0.8 (issue #344) interface compliance + adapter tests.

Pins the runtime-portability contract:

- Each adapter implements the ``RuntimeAdapter`` Protocol
  (8 methods: name, is_current, read_token_log, read_session_events,
  hook_event_name, prompt_user, workspace_root, install_skill).
- The two concrete adapters (``ClaudeCodeAdapter`` + ``CodexAdapter``)
  normalize identical inputs to identical outputs for tokens / events /
  hook-event names — the cross-runtime equality guarantee that Phase 1+
  code relies on.
- ``is_current()`` distinguishes the active runtime via env signals
  + binary probe.
- Prompt / install callbacks are mockable, deterministic, and
  raise ``RuntimeError`` with a clear message when unwired (so a
  misconfigured dependency is loud, not silent).
- ``workspace_root()`` honors explicit injection over env over cwd.

All assertions stay string-stable so a future adapter (third runtime)
can drop in without rewriting the suite.
"""
from __future__ import annotations

import inspect
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Add lib/ to sys.path so ``import runtime_adapters.*`` resolves without
# an install step. Mirrors the rest of the repo's tests.
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))

from runtime_adapters.base import (  # noqa: E402
    RuntimeAdapter,
    SessionEvent,
    TokenLog,
)
from runtime_adapters.claude_code import ClaudeCodeAdapter  # noqa: E402
from runtime_adapters.codex import CodexAdapter  # noqa: E402


def _make_claude(tmp=None, **overrides) -> ClaudeCodeAdapter:
    return ClaudeCodeAdapter(
        project_root=overrides.get("project_root", tmp),
        prompt_callback=overrides.get("prompt_callback"),
        skill_installer=overrides.get("skill_installer"),
    )


def _make_codex(tmp=None, **overrides) -> CodexAdapter:
    return CodexAdapter(
        project_root=overrides.get("project_root", tmp),
        prompt_callback=overrides.get("prompt_callback"),
        skill_installer=overrides.get("skill_installer"),
    )


class TestAdapterInterfaceCompliance(unittest.TestCase):
    """Both adapters must implement every method in the RuntimeAdapter Protocol."""

    def test_both_adapters_pass_protocol_check(self):
        claude = _make_claude()
        codex = _make_codex()
        # The Protocol is @runtime_checkable, so isinstance works.
        self.assertIsInstance(claude, RuntimeAdapter)
        self.assertIsInstance(codex, RuntimeAdapter)

    def test_protocol_exposes_eight_methods(self):
        # If we add a 9th method to RuntimeAdapter, this test will fail
        # FIRST (so the diff is obvious). Don't silently widen.
        expected = {
            "name", "is_current",
            "read_token_log", "read_session_events",
            "hook_event_name", "prompt_user",
            "workspace_root", "install_skill",
        }
        for adapter in (_make_claude(), _make_codex()):
            implemented = {
                name for name, _ in inspect.getmembers(adapter, callable)
                if not name.startswith("_") and name in expected
            }
            self.assertEqual(implemented, expected, f"{adapter.name()} missing methods")

    def test_adapter_name_is_stable_string(self):
        self.assertEqual(_make_claude().name(), "claude-code")
        self.assertEqual(_make_codex().name(), "codex")


class TestIsCurrentPerRuntime(unittest.TestCase):
    """Each adapter must positively identify its own runtime + reject others."""

    _CLAUDE_KEYS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
                    "CLAUDE_PROJECT_DIR", "CLAUDE_SESSION_ID")
    _CODEX_KEYS = ("CODEX_HOME", "CODEX_CLI", "CODEX_PROJECT_DIR",
                   "CODEX_SESSION_ID", "CODEX_THREAD_ID")

    def setUp(self):
        # Snapshot env so we can clean up after ourselves. CLAUDE/CODEX
        # signals and the binary probe are mutated together; restoring
        # only one would make subsequent tests flaky.
        self._env_backup = os.environ.copy()

    def tearDown(self):
        # Restore exactly the env we saw at setUp; don't touch PATH we
        # didn't record.
        for k in list(os.environ):
            if k not in self._env_backup:
                os.environ.pop(k, None)
        for k, v in self._env_backup.items():
            os.environ[k] = v

    def test_claude_detects_when_only_claude_signals_present(self):
        for k in self._CODEX_KEYS:
            os.environ.pop(k, None)
        os.environ["CLAUDECODE"] = "1"
        if shutil.which("claude") is None:
            self.skipTest("claude binary not on PATH in this env")
        self.assertTrue(_make_claude().is_current())
        self.assertFalse(_make_codex().is_current())

    def test_codex_detects_when_only_codex_signals_present(self):
        for k in self._CLAUDE_KEYS:
            os.environ.pop(k, None)
        os.environ["CODEX_CLI"] = "1"
        if shutil.which("codex") is None:
            self.skipTest("codex binary not on PATH in this env")
        self.assertTrue(_make_codex().is_current())
        self.assertFalse(_make_claude().is_current())

    def test_neither_adapter_matches_in_clean_env(self):
        for k in self._CLAUDE_KEYS + self._CODEX_KEYS:
            os.environ.pop(k, None)
        # Both adapters require BOTH an env signal AND the binary on PATH.
        # With no env signal, both must return False — even if the binary
        # happens to be installed.
        self.assertFalse(_make_claude().is_current())
        self.assertFalse(_make_codex().is_current())


class TestTokenLogNormalization(unittest.TestCase):
    """Both adapters must produce a TokenLog with non-negative int fields."""

    def _write_claude_sessions(self, root: Path, identifier: str, lines):
        path = root / ".claude" / "sessions" / f"{identifier}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_codex_sessions(self, root: Path, identifier: str, lines):
        path = root / ".codex" / "sessions" / f"{identifier}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_claude_read_token_log_returns_token_log(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_claude_sessions(root, "7d", [
                '{"type":"assistant","message":{"usage":{"input_tokens":10,"output_tokens":5,'
                '"cache_read_input_tokens":2,"cache_creation_input_tokens":1}}}',
                '{"type":"user"}',  # non-assistant ignored
                '{"type":"assistant","message":{"usage":{"input_tokens":3,"output_tokens":7,'
                '"cache_read_input_tokens":1,"cache_creation_input_tokens":0}}}',
            ])
            adapter = _make_claude(project_root=root)
            log = adapter.read_token_log("7d")
            self.assertIsInstance(log, TokenLog)
            self.assertEqual(log.window, "7d")
            self.assertEqual(log.input_tokens, 13)
            self.assertEqual(log.output_tokens, 12)
            self.assertEqual(log.cache_read_tokens, 3)
            self.assertEqual(log.cache_creation_tokens, 1)

    def test_claude_read_token_log_handles_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            adapter = _make_claude(project_root=Path(td))
            log = adapter.read_token_log("nonexistent-window")
            self.assertEqual(log, TokenLog(window="nonexistent-window",
                                          input_tokens=0, output_tokens=0))

    def test_claude_read_token_log_clamps_negative_numbers(self):
        """Negative tokens are not a real Claude signal; clamp to 0."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_claude_sessions(root, "1d", [
                '{"type":"assistant","message":{"usage":{"input_tokens":-50,"output_tokens":7}}}',
            ])
            adapter = _make_claude(project_root=root)
            log = adapter.read_token_log("1d")
            self.assertEqual(log.input_tokens, 0)
            self.assertEqual(log.output_tokens, 7)

    def test_codex_read_token_log_returns_token_log(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_codex_sessions(root, "7d", [
                '{"type":"event_msg","payload":{"type":"token_count","info":'
                '{"total_token_usage":{"input_tokens":100,"cached_input_tokens":30,'
                '"output_tokens":40,"reasoning_output_tokens":5}}}}',
            ])
            adapter = _make_codex(project_root=root)
            log = adapter.read_token_log("7d")
            self.assertIsInstance(log, TokenLog)
            # input - cached = 70, output + reasoning = 45, cached = 30
            self.assertEqual(log.input_tokens, 70)
            self.assertEqual(log.output_tokens, 45)
            self.assertEqual(log.cache_read_tokens, 30)

    def test_both_adapters_return_same_shape_on_empty_input(self):
        """Same input (missing file) → same shape (zero TokenLog) across runtimes."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            claude_log = _make_claude(project_root=root).read_token_log("30d")
            codex_log = _make_codex(project_root=root).read_token_log("30d")
            self.assertEqual(type(claude_log), type(codex_log))
            self.assertEqual(claude_log.window, codex_log.window)
            self.assertEqual(claude_log.input_tokens, codex_log.input_tokens)
            self.assertEqual(claude_log.output_tokens, codex_log.output_tokens)


class TestSessionEventNormalization(unittest.TestCase):
    """Both adapters produce SessionEvent with frozen (session_id, event_name, timestamp)."""

    def test_claude_read_session_events_filters_malformed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / ".claude" / "session-events" / "s1.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "\n".join([
                    '{"event_name":"SessionStart","timestamp":"2026-07-21T00:00:00Z","payload":{"cwd":"/x"}}',
                    '{"event_name":"UserPromptSubmit","timestamp":"2026-07-21T00:01:00Z","payload":{"role":"user"}}',
                    '{"timestamp":"2026-07-21T00:02:00Z"}',  # no event_name → skipped
                    '{"event_name":"","timestamp":"2026-07-21T00:03:00Z","payload":{}}',  # empty → skipped
                    'not-json',  # malformed → skipped
                ]) + "\n",
                encoding="utf-8",
            )
            events = _make_claude(project_root=root).read_session_events("s1")
            self.assertEqual(len(events), 2)
            self.assertTrue(all(isinstance(e, SessionEvent) for e in events))
            self.assertEqual(events[0].event_name, "SessionStart")
            self.assertEqual(events[0].timestamp,
                             datetime(2026, 7, 21, 0, 0, 0, tzinfo=timezone.utc))
            self.assertEqual(events[0].cwd, "/x")
            self.assertEqual(events[1].role, "user")

    def test_claude_session_events_empty_on_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            events = _make_claude(project_root=Path(td)).read_session_events("nope")
            self.assertEqual(events, [])

    def test_codex_read_session_events_filters_malformed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / ".codex" / "session-events" / "s1.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "\n".join([
                    '{"type":"event_msg","payload":{"type":"session_start","timestamp":"2026-07-21T00:00:00Z"},'
                    '"timestamp":"2026-07-21T00:00:00Z"}',
                    '{"type":"event_msg","payload":{"type":"user_prompt","timestamp":"2026-07-21T00:01:00Z"}}',
                    '{"type":"unknown_record_type","payload":{}}',  # unknown type → skipped
                    'not-json',
                ]) + "\n",
                encoding="utf-8",
            )
            events = _make_codex(project_root=root).read_session_events("s1")
            self.assertEqual(len(events), 2)
            self.assertEqual([e.event_name for e in events],
                             ["session_start", "user_prompt"])

    def test_session_event_payload_is_read_only_mapping(self):
        """Payload is exposed as MappingProxyType — mutations to the
        underlying dict must not leak across SessionEvent instances."""
        e1 = SessionEvent(
            session_id="x", event_name="PreToolUse",
            timestamp=datetime(2026, 7, 21, tzinfo=timezone.utc),
            payload={"a": 1},
        )
        with self.assertRaises(TypeError):
            e1.payload["b"] = 2  # type: ignore[index]


class TestHookEventNameNormalization(unittest.TestCase):
    """PreToolUse / PostToolUse / SessionStart must map deterministically."""

    NEUTRAL = ("PreToolUse", "PostToolUse", "SessionStart",
               "SessionEnd", "UserPromptSubmit", "PermissionRequest",
               "Notification")

    def test_claude_returns_neutral_name_unchanged(self):
        adapter = _make_claude()
        for name in self.NEUTRAL:
            self.assertEqual(adapter.hook_event_name(name), name)

    def test_codex_maps_known_neutral_names(self):
        adapter = _make_codex()
        # The mapping is the canonical "Claude hook → Codex event" table.
        # Unknown neutral names pass through unchanged (defensive default).
        self.assertEqual(adapter.hook_event_name("PreToolUse"), "before_tool_use")
        self.assertEqual(adapter.hook_event_name("PostToolUse"), "after_tool_use")
        self.assertEqual(adapter.hook_event_name("SessionStart"), "session_start")
        self.assertEqual(adapter.hook_event_name("SessionEnd"), "session_end")
        self.assertEqual(adapter.hook_event_name("UserPromptSubmit"), "user_prompt_submit")
        self.assertEqual(adapter.hook_event_name("PermissionRequest"), "permission_request")
        self.assertEqual(adapter.hook_event_name("Notification"), "notification")

    def test_codex_passes_through_unknown_neutral_name(self):
        """Unknown neutral names must NOT raise; they fall through unchanged.
        This is the contract that lets future neutral events work in both
        runtimes before Codex-specific names are added."""
        adapter = _make_codex()
        self.assertEqual(adapter.hook_event_name("FutureHook"), "FutureHook")


class TestWorkspaceRoot(unittest.TestCase):
    """workspace_root priority: explicit project_root > env > cwd."""

    def test_explicit_project_root_wins(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(_make_claude(project_root=root).workspace_root(),
                             root.resolve())
            self.assertEqual(_make_codex(project_root=root).workspace_root(),
                             root.resolve())

    def test_claude_env_signal_used_when_no_injection(self):
        with tempfile.TemporaryDirectory() as td:
            env_root = Path(td)
            os.environ["CLAUDE_PROJECT_DIR"] = str(env_root)
            try:
                self.assertEqual(_make_claude().workspace_root(), env_root.resolve())
            finally:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def test_codex_env_signal_used_when_no_injection(self):
        with tempfile.TemporaryDirectory() as td:
            env_root = Path(td)
            os.environ["CODEX_PROJECT_DIR"] = str(env_root)
            try:
                self.assertEqual(_make_codex().workspace_root(), env_root.resolve())
            finally:
                os.environ.pop("CODEX_PROJECT_DIR", None)

    def test_falls_back_to_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            adapter = _make_claude(project_root=None)
            old = os.getcwd()
            try:
                os.chdir(cwd)
                self.assertEqual(adapter.workspace_root(), cwd.resolve())
            finally:
                os.chdir(old)


class TestPromptUserIdempotent(unittest.TestCase):
    """prompt_user is mockable + deterministic; unwired call raises loud."""

    def test_claude_calls_injected_callback(self):
        calls = []

        def cb(q):
            calls.append(q)
            return "yes"

        adapter = _make_claude(prompt_callback=cb)
        self.assertEqual(adapter.prompt_user("Continue?"), "yes")
        self.assertEqual(calls, ["Continue?"])

    def test_codex_calls_injected_callback(self):
        calls = []

        def cb(q):
            calls.append(q)
            return "no"

        adapter = _make_codex(prompt_callback=cb)
        self.assertEqual(adapter.prompt_user("Continue?"), "no")
        self.assertEqual(calls, ["Continue?"])

    def test_unwired_claude_prompt_raises(self):
        with self.assertRaisesRegex(RuntimeError, "prompt callback is not configured"):
            _make_claude().prompt_user("Continue?")

    def test_unwired_codex_prompt_raises(self):
        with self.assertRaisesRegex(RuntimeError, "prompt callback is not configured"):
            _make_codex().prompt_user("Continue?")

    def test_install_skill_is_mockable(self):
        seen = []

        def install(name, src):
            seen.append((name, src))

        c = _make_claude(skill_installer=install)
        x = _make_codex(skill_installer=install)
        c.install_skill("review", Path("/tmp/review"))
        x.install_skill("review", Path("/tmp/review"))
        self.assertEqual(seen, [("review", Path("/tmp/review")),
                                ("review", Path("/tmp/review"))])

    def test_unwired_install_raises(self):
        with self.assertRaisesRegex(RuntimeError, "skill installer is not configured"):
            _make_claude().install_skill("review", Path("/tmp/review"))
        with self.assertRaisesRegex(RuntimeError, "skill installer is not configured"):
            _make_codex().install_skill("review", Path("/tmp/review"))


if __name__ == "__main__":
    unittest.main()
