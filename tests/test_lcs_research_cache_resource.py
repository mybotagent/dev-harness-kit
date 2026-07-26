#!/usr/bin/env python3
"""test_lcs_research_cache_resource.py — Phase 1.10 (issue #355) research cache resource.

Pins the ``lcs://research/cache`` contract for the v1 stub:
- Collection form returns ``status="ok"`` with the empty stub payload
  (query_hash=None, sources=[], citations=[], retrieved_at=None).
- Item form (sub-segment) raises ``LCSPartialError`` listing the unknown
  sub-resource so the server surfaces ``status="partial"``.
- The registered resource name is the nested ``research/cache`` so the
  server's longest-match resolver routes both ``lcs://research/cache``
  and ``lcs://research/cache/`` to it.
- v1 is intentionally empty — Phase 5 will populate via research_engine.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))

from lcs_resources.research_cache import ResearchCacheResource  # noqa: E402
from lcs_server import (  # noqa: E402
    LCSPartialError,
    LCSServer,
    ResourceRegistry,
    parse_uri,
)


class TestResearchCacheResourceFetch(unittest.TestCase):
    """The handler's pure fetch() pinned to the v1 stub contract."""

    def test_collection_form_empty_stub(self):
        resource = ResearchCacheResource(Path("/tmp"))
        parsed = parse_uri("lcs://research/cache")
        result = resource.fetch(parsed)
        self.assertEqual(result["status"], "ok")
        data = result["data"]
        self.assertEqual(data["query_hash"], None)
        self.assertEqual(data["sources"], [])
        self.assertEqual(data["citations"], [])
        self.assertEqual(data["retrieved_at"], None)

    def test_collection_form_trailing_slash(self):
        """Trailing slash is the canonical collection form; same payload."""
        resource = ResearchCacheResource(Path("/tmp"))
        parsed = parse_uri("lcs://research/cache/")
        result = resource.fetch(parsed)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["query_hash"], None)
        self.assertEqual(result["data"]["sources"], [])
        self.assertEqual(result["data"]["citations"], [])
        self.assertEqual(result["data"]["retrieved_at"], None)

    def test_unknown_sub_segment_partial(self):
        resource = ResearchCacheResource(Path("/tmp"))
        parsed = parse_uri("lcs://research/cache/foo")
        with self.assertRaises(LCSPartialError) as cm:
            resource.fetch(parsed)
        exc = cm.exception
        self.assertEqual(exc.data, {})
        self.assertEqual(exc.missing, ["unknown sub-resource foo (v1 stub)"])

    def test_payload_shape_stable(self):
        """The data dict must contain exactly these 4 keys, default-empty."""
        resource = ResearchCacheResource(Path("/tmp"))
        parsed = parse_uri("lcs://research/cache")
        data = resource.fetch(parsed)["data"]
        self.assertEqual(
            set(data.keys()),
            {"query_hash", "sources", "citations", "retrieved_at"},
        )
        # Empty defaults on the stub.
        self.assertIsNone(data["query_hash"])
        self.assertEqual(data["sources"], [])
        self.assertEqual(data["citations"], [])
        self.assertEqual(data["retrieved_at"], None)


class TestResearchCacheThroughLCSServer(unittest.TestCase):
    """End-to-end through the LCSServer dispatcher + cache."""

    def test_uri_routes_through_lcs_server(self):
        registry = ResourceRegistry()
        registry.register(ResearchCacheResource(Path("/tmp")))
        server = LCSServer(registry, ttl_seconds=0)  # disable cache

        result = server.get("lcs://research/cache")
        self.assertEqual(result["status"], "ok")
        data = result["data"]
        self.assertEqual(data["query_hash"], None)
        self.assertEqual(data["sources"], [])
        self.assertEqual(data["citations"], [])
        self.assertEqual(data["retrieved_at"], None)

    def test_sub_segment_yields_partial_envelope(self):
        """Server wraps LCSPartialError into status='partial' envelope."""
        registry = ResourceRegistry()
        registry.register(ResearchCacheResource(Path("/tmp")))
        server = LCSServer(registry, ttl_seconds=0)

        result = server.get("lcs://research/cache/foo")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["data"], {})
        self.assertEqual(result["missing"], ["unknown sub-resource foo (v1 stub)"])


if __name__ == "__main__":
    unittest.main()
