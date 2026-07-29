"""runtime_adapters — runtime-neutral adapter surface.

Provides a single `RuntimeAdapter` Protocol with two concrete
implementations (`ClaudeCodeAdapter`, `CodexAdapter`). Downstream code
asks the package "give me the right adapter for this environment" and
only ever imports the abstract surface.

Importing this package from the project root is the supported entry point:

    from runtime_adapters import ClaudeCodeAdapter, CodexAdapter

.. note::

    This file is intentionally minimal — ~20 LOC. Per-issue acceptance
    (issue #343): the only responsibility is the re-export. Adapter
    wiring (which adapter is "current", how to detect it, etc.) lives
    in ``lib/runtime_adapters/select.py`` and is out of scope for #343.
"""
from __future__ import annotations

from .base import RuntimeAdapter, SessionEvent, TokenLog
from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter

__all__ = [
    # Abstract surface
    "RuntimeAdapter",
    "SessionEvent",
    "TokenLog",
    # Concrete adapters
    "ClaudeCodeAdapter",
    "CodexAdapter",
]
