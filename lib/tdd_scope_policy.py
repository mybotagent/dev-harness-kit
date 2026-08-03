#!/usr/bin/env python3
"""Deterministic first-pass policy for deciding whether TDD is relevant."""
from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath


class Decision(str, Enum):
    EXEMPT = "exempt"
    REQUIRED = "required"
    JUDGE = "judge"


_EXEMPT_SEGMENTS = {"docs", "tools", "scripts", "bin", "hooks", "fixtures", "eval", "tests"}
_CORE_SEGMENTS = {"lib", "utils", "services", "domain"}
_EXEMPT_SUFFIXES = {".md", ".mdx", ".txt", ".rst", ".adoc", ".html", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".sh"}


def classify_path(path: str) -> Decision:
    """Classify a repository-relative or absolute target path.

    Rules handle obvious maintenance work and known core-code roots. Only
    unknown paths are deferred to an LLM judge.
    """
    normalized = path.replace("\\", "/")
    pure = PurePosixPath(normalized)
    segments = set(pure.parts)
    name = pure.name
    if segments & _EXEMPT_SEGMENTS or name.startswith(("test_", "test.")):
        return Decision.EXEMPT
    if pure.suffix.lower() in _EXEMPT_SUFFIXES:
        return Decision.EXEMPT
    if "app" in segments and "api" in segments:
        return Decision.REQUIRED
    if segments & _CORE_SEGMENTS or "src" in segments:
        return Decision.REQUIRED
    return Decision.JUDGE


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m lib.tdd_scope_policy <path>")
    print(classify_path(sys.argv[1]).value)
