"""research_cache resource — ``lcs://research/cache``.

Phase 1.10 (issue #355) v1 stub. The canonical URI is the collection
form, which returns an empty envelope — the four fields Phase 5 will
populate from ``research_engine`` are pre-declared so downstream
callers can pin to the shape now:

  lcs://research/cache/
      → {"status": "ok", "data": {
              "query_hash":    None,
              "sources":       [],
              "citations":     [],
              "retrieved_at":  None,
          }}

  lcs://research/cache/<sub>
      → LCSPartialError(data={}, missing=["unknown sub-resource <sub> (v1 stub)"])

The ``sub-segment`` form is reserved for Phase 5 (e.g. ``<sub>`` might
become a query hash key, or a per-source bucket). In v1 every sub is
unknown; raising ``LCSPartialError`` lets the LCS server surface
``status="partial"`` to the caller without crashing the read path.

Why a nested resource name ("research/cache") and not a flat "research":
- The longest-match resolver in ``lcs_server._resolve_resource`` joins
  segments with "/", so ``research/cache`` lets future siblings
  (``research/index``, ``research/queries``) live under the same top-
  level namespace without clobbering each other.
- The slash in the resource name is allowed by the registry since
  lookup is by exact string, not by single-segment match.
"""
from __future__ import annotations

from pathlib import Path

from lcs_server import LCSPartialError, ParsedURI, Resource

NAME = "research/cache"

# Canonical stub payload. Stable keys + empty defaults so callers can
# pin to the shape before Phase 5 fills it in.
_STUB_PAYLOAD: dict = {
    "query_hash": None,
    "sources": [],
    "citations": [],
    "retrieved_at": None,
}


class ResearchCacheResource(Resource):
    """LCS resource for ``lcs://research/cache[/<sub>]`` (v1 stub)."""

    name = NAME

    def __init__(self, project_root: Path) -> None:
        # ``project_root`` is kept for signature symmetry with the other
        # resources (sessions, worktrees, branches) so Phase 5 can adopt
        # it without churning the registry call site. v1 has no use for
        # the path — the canonical payload is empty.
        self._project_root = project_root

    def fetch(self, parsed: ParsedURI) -> dict:
        # Sub-segment handling — v1 reports the first extra segment only.
        #
        # ``parsed.path_segments`` for the resource ``research/cache`` is
        # structured as: ``["research", "cache", <sub>, ...]``. For a v1
        # stub we surface a single ``LCSPartialError`` carrying the first
        # sub-segment label; any deeper path (e.g. ``cache/foo/bar``)
        # intentionally collapses to ``foo`` because every sub-resource
        # is unknown until Phase 5 wires up real handlers. The full
        # multi-segment reporting is deferred so the error envelope
        # shape stays stable across the Phase 1.x to Phase 5 transition.
        sub = parsed.path_segments[2] if len(parsed.path_segments) > 2 else ""
        if sub:
            raise LCSPartialError(
                data={},
                missing=[f"unknown sub-resource {sub} (v1 stub)"],
            )
        return {"status": "ok", "data": dict(_STUB_PAYLOAD)}
