"""hooks_coverage resource — ``lcs://hooks/coverage``.

Exposes the project's hook landscape as a normalized JSON snapshot.

The resource merges events from ``.claude/hooks.json`` and
``.codex/hooks.json`` and surfaces ``hooks/*.sh`` filenames as matchers.
Deterministic sort order lets callers diff the result across pulls:

  lcs://hooks/coverage
      → {"status": "ok|partial",
         "data": {
             "events": ["PreToolUse", "SessionStart", ...],   # sorted union
             "matchers": ["acp-tier-assert.sh", "tdd-guard.sh", ...],  # sorted
         }}

What we read:
- ``<repo_root>/.claude/hooks.json`` — Claude Code hook manifest. The
  top-level ``hooks`` object maps event names (``PreToolUse``,
  ``SessionStart``, ``Stop``, ...) to a list of matcher blocks.
- ``<repo_root>/.codex/hooks.json`` — Codex hook manifest. Same
  ``{event: [blocks]}`` shape.
- ``<repo_root>/hooks/*.sh`` — handler scripts shipped by the plugin.
  Listed by filename only (no path component, no recursive walk).

Why two manifests plus a hooks/ directory:
- ``.claude/hooks.json`` and ``.codex/hooks.json`` describe *what the
  runtime fires*. Each runtime has its own file because the field
  schema differs in places (``_loghooks_managed`` is Codex-only).
- ``hooks/*.sh`` describes *what the plugin actually ships*. These are
  the handlers referenced by ``bash ${CLAUDE_PLUGIN_ROOT}/hooks/<name>.sh``
  in the manifest. Listing them as ``matchers`` lets an agent see
  "these are the scripts wired up" without re-parsing every block.

Failure mode:
- A *missing* manifest is reported under ``missing`` as ``no <path>``.
- A *malformed* manifest is reported under ``missing`` as
  ``malformed <path>: <reason>``.
- If BOTH manifests are absent (no runtime hook config in the repo),
  we return ``status="ok"`` with empty ``events`` — that's the "no
  configuration at all" case, not an error. Handlers in ``hooks/``
  still appear under ``matchers`` because they're a separate, optional
  surface.
- If at least one manifest is present and a sibling manifest is
  missing or malformed, we raise :class:`LCSPartialError` so the LCS
  server surfaces ``status="partial"``. The readable subset is
  preserved under ``data`` so a partial response still tells the
  agent what works.
- This matches the Phase 1.1 server contract — a partially configured
  project is flagged, but a project that hasn't started wiring hooks
  is treated as a clean baseline.
"""
from __future__ import annotations

import json
from pathlib import Path

from lcs_server import LCSPartialError, ParsedURI, Resource

# Module-level: registering this resource with a registry is the
# consumer's job (see ``build_default_registry`` in the LCS CLI).
NAME = "hooks/coverage"

# Manifest paths, relative to repo_root, that we attempt to merge.
_CLAUDE_MANIFEST = Path(".claude") / "hooks.json"
_CODEX_MANIFEST = Path(".codex") / "hooks.json"

# Handler directory, relative to repo_root.
_HANDLERS_DIR = Path("hooks")


def _read_events(path: Path, rel: str) -> tuple[set[str] | None, str | None]:
    """Return ``(events, error_token)``.

    - ``(set, None)`` — manifest read OK; ``events`` is the set of event
      names declared under the top-level ``hooks`` dict.
    - ``(None, "no <rel>")`` — file does not exist.
    - ``(None, "malformed <rel>: <reason>")`` — file exists but failed to
      parse as JSON, or its shape doesn't match the expected
      ``{"hooks": {...}}`` schema.

    Anything else (``OSError``, ``UnicodeDecodeError``, top-level not a
    dict, ``hooks`` not a dict) is treated as malformed so the partial
    envelope carries a single, uniform error shape.
    """
    if not path.is_file():
        return None, f"no {rel}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        reason = getattr(exc, "msg", None) or str(exc)
        return None, f"malformed {rel}: {reason}"
    if not isinstance(payload, dict):
        return None, f"malformed {rel}: top-level not an object"
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        return set()
    return {k for k in hooks if isinstance(k, str)}, None


def _list_handlers(repo_root: Path) -> list[str]:
    """Sorted list of ``*.sh`` filenames in ``<repo_root>/hooks/``.

    Returns ``[]`` when the directory is absent. Non-``.sh`` files
    (``hooks.json``, ``README.md``, nested subdirs) are excluded; only
    top-level handler scripts at the directory root are returned. We
    intentionally do not recurse — the plugin layout puts every
    handler script flat in ``hooks/``.
    """
    handlers_dir = repo_root / _HANDLERS_DIR
    if not handlers_dir.is_dir():
        return []
    return sorted(p.name for p in handlers_dir.glob("*.sh"))


class HooksCoverageResource(Resource):
    """LCS resource for ``lcs://hooks/coverage``.

    The constructor takes a ``repo_root`` — the directory that contains
    ``.claude/``, ``.codex/``, and ``hooks/`` as siblings. In the
    dev-harness-kit project that is the repository root; in a
    consumer's project it is wherever the two manifests and the
    handlers directory live.
    """

    name = NAME

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def fetch(self, parsed: ParsedURI) -> dict:
        # Short-circuit: neither runtime has shipped a manifest. This
        # is the "no hook config at all" case — not an error, just an
        # empty baseline. Handlers under hooks/ may still be present;
        # we surface them as matchers even without any manifest.
        claude_present = (self._repo_root / _CLAUDE_MANIFEST).is_file()
        codex_present = (self._repo_root / _CODEX_MANIFEST).is_file()
        if not claude_present and not codex_present:
            return {
                "status": "ok",
                "data": {
                    "events": [],
                    "matchers": _list_handlers(self._repo_root),
                },
            }

        events: set[str] = set()
        missing: list[str] = []

        for rel in (_CLAUDE_MANIFEST, _CODEX_MANIFEST):
            abs_path = self._repo_root / rel
            found, err = _read_events(abs_path, rel.as_posix())
            if err is not None:
                missing.append(err)
                continue
            if found:
                events.update(found)

        data = {
            "events": sorted(events),
            "matchers": _list_handlers(self._repo_root),
        }

        if missing:
            raise LCSPartialError(data=data, missing=missing)

        return {"status": "ok", "data": data}
