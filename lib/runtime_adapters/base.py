"""Runtime-neutral adapter contracts shared by supported CLI runtimes."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class TokenLog:
    """Normalized token usage for one requested time window."""

    window: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """Normalized event emitted during one runtime session."""

    session_id: str
    event_name: str
    timestamp: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@runtime_checkable
class RuntimeAdapter(Protocol):
    """Interface implemented once for each supported agent runtime."""

    def name(self) -> str:
        """Return the stable runtime name.

        Example: ``adapter.name() == "claude-code"``.
        """
        ...

    def is_current(self) -> bool:
        """Return whether this adapter matches the running environment.

        Example: ``adapter.is_current()`` before selecting an adapter.
        """
        ...

    def read_token_log(self, window: str) -> TokenLog:
        """Read and normalize token usage for a time window.

        Example: ``adapter.read_token_log("7d")``.
        """
        ...

    def read_session_events(self, session_id: str) -> list[SessionEvent]:
        """Read and normalize events belonging to a session.

        Example: ``adapter.read_session_events("session-1")``.
        """
        ...

    def hook_event_name(self, neutral_name: str) -> str:
        """Map a neutral hook event to its runtime-native name.

        Example: ``PreToolUse`` maps to ``PreToolUse`` for Claude Code
        and ``before_tool_use`` for Codex.
        """
        ...

    def prompt_user(self, question: str) -> str:
        """Ask the current runtime to collect one answer from the user.

        Example: ``adapter.prompt_user("Continue?")``.
        """
        ...

    def workspace_root(self) -> Path:
        """Return the project workspace root used by this runtime.

        Example: ``adapter.workspace_root() / "CLAUDE.md"``.
        """
        ...

    def install_skill(self, skill_name: str, skill_dir: Path) -> None:
        """Install a named skill from ``skill_dir`` into this runtime.

        Example: ``adapter.install_skill("review", source_dir)``.
        """
        ...
