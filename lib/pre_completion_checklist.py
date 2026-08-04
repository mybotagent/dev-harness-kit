"""Intent checks run before a completion claim is accepted.

The checklist is deliberately lightweight: it looks for evidence in the request,
diff, and changed paths rather than attempting to understand arbitrary source.
Advisory items can fail without blocking; requirements and test evidence block.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Union

CHECKLIST_ITEMS = (
    "requirements addressed",
    "docs updated",
    "edge cases flagged",
    "public APIs documented",
    "tests not skipped",
)
BLOCKING_ITEMS = {"requirements addressed", "tests not skipped"}
TextInput = Union[str, Path, None]


@dataclass(frozen=True)
class CheckResult:
    """Result of the five-item completion checklist."""

    passed: bool
    failed_items: List[str]
    blocking: bool


def _text(value: TextInput) -> str:
    if value is None:
        return ""
    if isinstance(value, Path):
        try:
            return value.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""
    return str(value)


def read_user_request(project_root: TextInput = None) -> str:
    """Read the most likely original-request hand-off, without writing state."""
    root = Path(project_root or ".")
    handoff = root / ".dev-kit" / "hand-off"
    if not handoff.is_dir():
        return ""
    files = sorted(p for p in handoff.iterdir() if p.is_file())
    preferred = [
        p for p in files
        if any(word in p.stem.lower() for word in ("request", "prompt", "user"))
    ]
    candidates = preferred or [p for p in files if p.suffix.lower() in {".md", ".txt", ".json"}]
    return "\n\n".join(_text(path) for path in candidates)


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE | re.MULTILINE) for pattern in patterns)


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text)}


def _requirements(request: str, diff: str, paths: list[str]) -> bool:
    if not diff.strip():
        return False
    if _has(diff, r"requirements?\s+(?:addressed|met|implemented)", r"implemented\s+the\s+request"):
        return True
    request_tokens = _tokens(request) - {"that", "this", "with", "from", "have", "must", "should"}
    evidence = _tokens(diff) | _tokens(" ".join(paths))
    return bool(request_tokens & evidence) or _has(request, r"\b(no|without)\s+requirements?\b")


def _docs(diff: str, paths: list[str]) -> bool:
    path_text = " ".join(paths).lower()
    return _has(
        diff,
        r"docs?\s+(?:updated|added|now|cover)",
        r"documentation\s+(?:updated|added|now)",
        r"public api.*document",
        r'(?m)^\+.*(?:^|\s)(?:documentation|readme|changelog)\b',
    ) or bool(re.search(r"(^|/)(?:readme|changelog)(?:\.|$)|(^|/)docs?(/|$)|\.(?:md|rst|txt)$", path_text))


def _edges(diff: str, request: str) -> bool:
    return _has(
        diff + "\n" + request,
        r"edge[- ]cases?\s+(?:flagged|covered|handled|tested)",
        r"(?:empty|null|missing|invalid|error|failure|exception|boundary|timeout|malformed)",
        r"validation\b",
    )


def _api_docs(diff: str, request: str, paths: list[str]) -> bool:
    text = diff + "\n" + request + "\n" + " ".join(paths)
    if _has(text, r"(?:no|without)\s+public\s+api", r"internal[- ]only", r"private\s+implementation"):
        return True
    return _has(
        text,
        r"public\s+api.*(?:document|docstring|reference)",
        r"api\s+documentation",
        r"exported?\s+(?:function|class|symbol)",
        r"(?:endpoint|interface).*document",
    )


def _tests(diff: str, paths: list[str]) -> bool:
    text = diff + "\n" + " ".join(paths)
    if _has(text, r"\btests?\s+(?:were\s+)?skipped\b", r"\btests?\s+(?:were\s+)?not run\b", r"\bskip(?:ped)?\s+tests?\b", r"pytest\s+.*--?no", r"\bxfail\b"):
        return False
    return _has(
        text,
        r"tests?\s+(?:not\s+)?skipped\s*[:=-]?",
        r"(?:tests?|pytest|unittest).*(?:passed|run|green)",
        r"test[_/].*\.(?:py|ts|js)",
    )


def check(user_request: TextInput, diff: TextInput, files: Iterable[TextInput]) -> CheckResult:
    """Evaluate checklist evidence from the request, diff, and implementation paths."""
    request_text = _text(user_request)
    diff_text = _text(diff)
    paths = [_text(path) for path in (files or [])]
    checks = (
        _requirements(request_text, diff_text, paths),
        _docs(diff_text, paths),
        _edges(diff_text, request_text),
        _api_docs(diff_text, request_text, paths),
        _tests(diff_text, paths),
    )
    failed = [item for item, passed in zip(CHECKLIST_ITEMS, checks) if not passed]
    return CheckResult(passed=not failed, failed_items=failed, blocking=bool(set(failed) & BLOCKING_ITEMS))
