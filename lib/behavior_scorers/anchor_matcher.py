"""Match communication notes to hand-picked relative quality tiers."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def jaccard_similarity(left: str, right: str) -> float:
    """Return token-set Jaccard similarity, with two empty notes matching."""
    a, b = _tokens(left), _tokens(right)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if a | b else 0.0


def _read_anchor_file(path: Path) -> list[dict[str, str]]:
    """Read the small, intentionally regular anchor YAML without dependencies."""
    text = path.read_text(encoding="utf-8")
    anchors: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_hand_off = False
    hand_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("  - id:"):
            if current is not None:
                current["hand_off"] = "\n".join(hand_lines).strip()
                anchors.append(current)
            current = {"id": line.split(":", 1)[1].strip()}
            hand_lines = []
            in_hand_off = False
        elif current is not None and line.startswith("    tier:"):
            current["tier"] = line.split(":", 1)[1].strip()
        elif current is not None and line.startswith("    hand_off:"):
            in_hand_off = True
        elif current is not None and line.startswith("    rationale:"):
            in_hand_off = False
        elif in_hand_off and line.startswith("      "):
            hand_lines.append(line[6:])
    if current is not None:
        current["hand_off"] = "\n".join(hand_lines).strip()
        anchors.append(current)
    return anchors


def load_anchors(anchors: Iterable[Mapping[str, Any]] | str | Path) -> list[Mapping[str, Any]]:
    if isinstance(anchors, (str, Path)):
        return _read_anchor_file(Path(anchors))
    return list(anchors)


def match_anchor(note: str, anchors: Iterable[Mapping[str, Any]] | str | Path) -> dict[str, Any]:
    """Return the nearest anchor's tier, similarity, and id."""
    candidates = load_anchors(anchors)
    if not candidates:
        raise ValueError("at least one anchor is required")
    best: tuple[float, Mapping[str, Any]] | None = None
    for anchor in candidates:
        content = str(anchor.get("hand_off", ""))
        similarity = jaccard_similarity(note, content)
        if best is None or similarity > best[0]:
            best = (similarity, anchor)
    assert best is not None
    similarity, anchor = best
    return {
        "matched_tier": str(anchor.get("tier", "bronze")),
        "similarity": similarity,
        "anchor_id": str(anchor.get("id", "")),
    }


# Short alias for callers that treat matching as a verb.
match = match_anchor

__all__ = ["jaccard_similarity", "load_anchors", "match", "match_anchor"]
