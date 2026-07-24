"""interview resource — ``lcs://interview/<step>``.

Read-only v1 stub (Phase 1.9, issue #354). Surfaces the parsed
frontmatter of ``.dev-kit/hand-off/<step>.md`` so callers can see the
5-field safety contract (safety_valve, ambiguity_score, value_score,
evidence_count, status) that Phase 6 interview_engine consumes.
frontmatter of one ``.dev-kit/hand-off/<step>.md`` file as a
normalized JSON snapshot. URI form:

  lcs://interview/<step>
      → {"status": "ok", "data": {step, safety_valve, ambiguity_score,
            value_score, evidence_count, status}}

5-field contract (frontmatter keys; missing → ``None``):
  - ``safety_valve``    int  — binary safe-to-execute flag (0|1)
  - ``ambiguity_score`` int  — 0..N, higher = more ambiguous
  - ``value_score``     float — expected ROI heuristic
  - ``evidence_count``  int  — supporting evidence count
  - ``status``          str  — one of "ok" | "held" | "blocked" | ...

Failure modes:
  - Collection form (``lcs://interview`` or ``lcs://interview/``)
    raises :class:`LCSError` — the resource is item-only.
  - Missing hand-off file → ``LCSPartialError`` →
    ``status="partial"`` with ``missing=["no hand-off <step>"]``.
  - Empty hand-off file → ``LCSPartialError`` →
    ``status="partial"`` with ``missing=["empty hand-off <step>"]``.

Filename resolution: the URI's step segment is used to construct
``.dev-kit/hand-off/<step>.md`` directly, with a dash-encoded
fallback (``/``, ``→``, ``\\``, whitespace → ``-``) when the raw
form isn't present. The first hit wins; no other filesystem probing.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from lcs_server import LCSError, LCSPartialError, ParsedURI, Resource

NAME = "interview"

# Contract fields exposed in the payload. Order is preserved in the
# returned dict (Python 3.7+ insertion-order semantics). Numeric
# fields default to None when missing so the caller can distinguish
# "not present" from "present and zero".
CONTRACT_FIELDS: tuple[str, ...] = (
    "safety_valve",
    "ambiguity_score",
    "value_score",
    "evidence_count",
    "status",
)

# Characters that don't round-trip cleanly through a filesystem
# filename. Replaced with ``-`` when generating the dash-encoded
# fallback. ``/`` and ``\\`` are path separators, ``→`` and friends
# are multi-byte Unicode that macOS / Linux file systems handle but
# Windows refuses, and whitespace makes tab-completion painful.
_DASH_RE = re.compile(r"[/\\\s→➔➜➝➞→⇒⟹]")


def _dash_encode(step: str) -> str:
    """Replace path-hostile characters in ``step`` with ``-``."""
    return _DASH_RE.sub("-", step)


def _candidate_paths(project_root: Path, step: str) -> list[Path]:
    """Build the ordered list of hand-off MD paths to try for ``step``.

    Order:
      1. Raw step id, URL-decoded a second time (parse_uri already
         decodes once — this is a belt-and-braces pass so the helper
         is safe to call from non-LCS code).
      2. Dash-encoded form (only differs from (1) when the step id
         contains a special char).

    Both candidates live under ``<project_root>/.dev-kit/hand-off/``.
    The caller picks the first one that exists.
    """
    raw = unquote(step)
    candidates: list[str] = [raw]
    dash = _dash_encode(raw)
    if dash != raw:
        candidates.append(dash)
    base = project_root / ".dev-kit" / "hand-off"
    return [base / f"{c}.md" for c in candidates]


def _parse_frontmatter(text: str) -> dict:
    """Parse the first YAML frontmatter block in ``text``.

    Recognized keys are exactly the 5 contract fields; unknown keys
    are silently dropped. Missing keys default to ``None``. Returns
    an empty dict if no valid ``---`` block is present (no opening
    fence, or no closing fence on its own line).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    # Locate closing fence (a line that is exactly "---" or "...").
    close_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() in {"---", "..."}:
            close_idx = i
            break
    if close_idx is None:
        return {}

    out: dict = {key: None for key in CONTRACT_FIELDS}
    for line in lines[1:close_idx]:
        # Scalar ``key: value`` and ``key: "value"`` shapes only.
        m = re.match(r"^\s*([A-Za-z_][\w-]*)\s*:\s*(.*?)\s*$", line)
        if not m:
            continue
        key, raw_val = m.group(1), m.group(2)
        if key not in out:
            continue
        out[key] = _coerce(key, raw_val)
    return out


def _coerce(key: str, raw: str) -> object:
    """Coerce a frontmatter scalar to its contract type.

    ``safety_valve`` / ``ambiguity_score`` / ``evidence_count`` → int.
    ``value_score`` → float.
    ``status`` → str (stripped, quotes removed).
    Falls back to the raw string if the int/float parse fails — the
    caller can still see the unexpected value in the payload.
    """
    val = raw.strip()
    # Strip matching surrounding quotes if any.
    if len(val) >= 2 and val[0] == val[-1] and val[0] in {"'", '"'}:
        val = val[1:-1]
    if key in {"safety_valve", "ambiguity_score", "evidence_count"}:
        try:
            return int(val)
        except ValueError:
            return val
    if key == "value_score":
        try:
            return float(val)
        except ValueError:
            return val
    return val


def _read_hand_off(project_root: Path, step: str) -> dict:
    """Resolve and parse the hand-off MD file for ``step``.

    Raises :class:`LCSPartialError` when no candidate path exists
    or the matched file is empty.
    """
    for path in _candidate_paths(project_root, step):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                raise LCSPartialError(
                    data={"step": step},
                    missing=[f"empty hand-off {step}"],
                )
            return _parse_frontmatter(text)
    raise LCSPartialError(
        data={"step": step},
        missing=[f"no hand-off {step}"],
    )


class InterviewResource(Resource):
    """LCS resource for ``lcs://interview/<step>``."""

    name = NAME

    def __init__(self, project_root: Path) -> None:
        # ``project_root`` is the parent of ``.dev-kit/`` — the
        # resource reads from ``<project_root>/.dev-kit/hand-off/``.
        # We keep the path as-is (no ``resolve()``) so tests using a
        # ``tempfile.TemporaryDirectory`` don't hit symlink-resolution
        # surprises on macOS where /tmp → /private/tmp.
        self._project_root = project_root

    def fetch(self, parsed: ParsedURI) -> dict:
        # Item-only: ``lcs://interview`` (collection) and
        # ``lcs://interview/`` (collection-with-trailing-slash) both
        # carry no step id and are an error, not a partial.
        if not parsed.path_segments[1:]:
            raise LCSError(
                "lcs://interview requires a step id; use lcs://interview/<step>"
            )
        step = unquote(parsed.path_segments[1])
        frontmatter = _read_hand_off(self._project_root, step)
        return {
            "status": "ok",
            "data": {
                "step": step,
                "safety_valve": frontmatter.get("safety_valve"),
                "ambiguity_score": frontmatter.get("ambiguity_score"),
                "value_score": frontmatter.get("value_score"),
                "evidence_count": frontmatter.get("evidence_count"),
                "status": frontmatter.get("status"),
            },
        }
