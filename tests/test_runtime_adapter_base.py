#!/usr/bin/env python3
"""Contract tests for the runtime-neutral adapter interface."""
from __future__ import annotations

import dataclasses
import inspect
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import get_type_hints

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.runtime_adapters.base import (  # noqa: E402
    RuntimeAdapter,
    SessionEvent,
    TokenLog,
)


class CompleteAdapter:
    def name(self) -> str:
        return "test"

    def is_current(self) -> bool:
        return True

    def read_token_log(self, window: str) -> TokenLog:
        return TokenLog(window=window, input_tokens=1, output_tokens=2)

    def read_session_events(self, session_id: str) -> list[SessionEvent]:
        return []

    def hook_event_name(self, neutral_name: str) -> str:
        return neutral_name

    def prompt_user(self, question: str) -> str:
        return question

    def workspace_root(self) -> Path:
        return PROJECT_ROOT

    def install_skill(self, skill_name: str, skill_dir: Path) -> None:
        return None


class IncompleteAdapter:
    def name(self) -> str:
        return "incomplete"


class TestRuntimeAdapterBase(unittest.TestCase):
    def test_records_are_importable_and_constructible(self):
        log = TokenLog(window="day", input_tokens=3, output_tokens=4)
        event = SessionEvent(
            session_id="session-1",
            event_name="SessionStart",
            timestamp=datetime.now(timezone.utc),
        )
        self.assertEqual(log.input_tokens, 3)
        self.assertEqual(event.event_name, "SessionStart")

    def test_records_are_frozen_and_slotted(self):
        log = TokenLog(window="day", input_tokens=3, output_tokens=4)
        event = SessionEvent(
            session_id="session-1",
            event_name="SessionStart",
            timestamp=datetime.now(timezone.utc),
        )
        self.assertTrue(dataclasses.is_dataclass(log))
        self.assertTrue(dataclasses.is_dataclass(event))
        self.assertIsInstance(log.__slots__, tuple)
        self.assertIsInstance(event.__slots__, tuple)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            log.input_tokens = 5
        with self.assertRaises(dataclasses.FrozenInstanceError):
            event.event_name = "Stop"

    def test_session_event_payload_defaults_to_immutable_empty_mapping(self):
        event = SessionEvent(
            session_id="session-1",
            event_name="SessionStart",
            timestamp=datetime.now(timezone.utc),
        )
        self.assertEqual(dict(event.payload), {})
        with self.assertRaises(TypeError):
            event.payload["key"] = "value"

    def test_protocol_accepts_complete_structural_implementation(self):
        self.assertIsInstance(CompleteAdapter(), RuntimeAdapter)
        self.assertNotIsInstance(IncompleteAdapter(), RuntimeAdapter)

    def test_protocol_has_eight_documented_methods(self):
        expected = {
            "name",
            "is_current",
            "read_token_log",
            "read_session_events",
            "hook_event_name",
            "prompt_user",
            "workspace_root",
            "install_skill",
        }
        methods = {
            name for name, member in inspect.getmembers(RuntimeAdapter)
            if callable(member) and not name.startswith("_")
        }
        self.assertEqual(methods, expected)
        for name in expected:
            doc = inspect.getdoc(getattr(RuntimeAdapter, name))
            self.assertTrue(doc, name)
            self.assertIn("Example:", doc, name)

    def test_protocol_signatures_match_portability_contract(self):
        hints = get_type_hints(RuntimeAdapter)
        self.assertEqual(hints, {})
        self.assertEqual(list(inspect.signature(RuntimeAdapter.read_token_log).parameters), ["self", "window"])
        self.assertEqual(
            list(inspect.signature(RuntimeAdapter.read_session_events).parameters),
            ["self", "session_id"],
        )
        self.assertEqual(
            list(inspect.signature(RuntimeAdapter.hook_event_name).parameters),
            ["self", "neutral_name"],
        )
        self.assertEqual(
            list(inspect.signature(RuntimeAdapter.install_skill).parameters),
            ["self", "skill_name", "skill_dir"],
        )


if __name__ == "__main__":
    unittest.main()
