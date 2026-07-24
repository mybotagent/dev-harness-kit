#!/usr/bin/env python3
"""test_lcs_server.py — Phase 1.1 (issue #346) URI routing + dispatcher tests.

Pins the LCS server contract:
- URI parsing for the 8 v1 resources (worktrees, pr, branches, spend,
  sessions, hooks/coverage, interview, research/cache) plus their
  trailing-slash variants.
- Resource registry + dispatch: registry maps resource name → handler,
  server routes parsed URIs to the right handler via longest-match.
- In-memory snapshot cache with 5s TTL: repeated reads within TTL hit
  the cache, reads past TTL re-fetch.
- Partial-failure mode: handlers can return partial payloads (data
  source unavailable) without aborting the read; status reflects that.
- Error mode: malformed URIs + unknown resources raise (not silently
  default).

All tests are pure (no network, no subprocess) so the boot-path /
read-path latency targets can be asserted with a wall-clock budget.
"""
from __future__ import annotations

import sys
import time
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))

from lcs_server import (  # noqa: E402
    LCSError,
    LCSPartialError,
    LCSServer,
    ParsedURI,
    ResourceRegistry,
    parse_uri,
)


@dataclass
class _Call:
    uri: str
    parsed: ParsedURI
    segments: tuple[str, ...]


class _StubResource:
    def __init__(self, name, payload=None, *, partial_payload=None,
                 raise_exc=None, sleep_ms=0.0):
        self.name = name
        self._payload = dict(payload or {})
        self._partial = dict(partial_payload or {})
        self._raise = raise_exc
        self._sleep = sleep_ms / 1000.0
        self.calls = []

    def fetch(self, parsed):
        self.calls.append(_Call(uri="", parsed=parsed,
                                segments=parsed.path_segments))
        if self._sleep:
            time.sleep(self._sleep)
        if self._raise is not None:
            raise self._raise
        if self._partial:
            return {"status": "partial", "data": self._partial,
                    "missing": ["upstream:fixture-down"]}
        return {"status": "ok", "data": self._payload}


def _build_registry(*resources):
    reg = ResourceRegistry()
    for r in resources:
        reg.register(r)
    return reg


# ──────────────────────────────────────────────────────────────────
# URI parsing
# ──────────────────────────────────────────────────────────────────

class TestParseURI(unittest.TestCase):
    def test_collection_uri_without_trailing_slash(self):
        p = parse_uri("lcs://worktrees")
        self.assertEqual(p.path_segments, ("worktrees",))
        self.assertFalse(p.is_collection)
        self.assertEqual(p.first_segment, "worktrees")

    def test_collection_uri_with_trailing_slash(self):
        p = parse_uri("lcs://worktrees/")
        self.assertEqual(p.path_segments, ("worktrees",))
        self.assertTrue(p.is_collection)

    def test_item_uri_single_path_param(self):
        p = parse_uri("lcs://pr/29")
        self.assertEqual(p.path_segments, ("pr", "29"))

    def test_item_uri_two_path_params(self):
        # %2F is escaped "/" — must NOT split path segments.
        p = parse_uri("lcs://branches/feat%2Ffoo/slot")
        self.assertEqual(p.path_segments, ("branches", "feat/foo", "slot"))

    def test_nested_resource_keeps_segments(self):
        # Parser is dumb about nested-vs-param — that's the registry's
        # job. The parser just returns the segments as-is.
        p = parse_uri("lcs://hooks/coverage")
        self.assertEqual(p.path_segments, ("hooks", "coverage"))

    def test_deeply_nested_item_uri(self):
        p = parse_uri("lcs://interview/sess-42")
        self.assertEqual(p.path_segments, ("interview", "sess-42"))

    def test_scheme_is_case_sensitive_lcs(self):
        with self.assertRaises(LCSError):
            parse_uri("LCS://worktrees")
        with self.assertRaises(LCSError):
            parse_uri("http://worktrees")

    def test_empty_uri_rejected(self):
        with self.assertRaises(LCSError):
            parse_uri("")
        with self.assertRaises(LCSError):
            parse_uri("lcs://")

    def test_first_segment_required(self):
        with self.assertRaises(LCSError):
            parse_uri("lcs:///foo")
        with self.assertRaises(LCSError):
            parse_uri("lcs:///")


# ──────────────────────────────────────────────────────────────────
# Resource registry + dispatch (longest-match)
# ──────────────────────────────────────────────────────────────────

class TestResourceRegistry(unittest.TestCase):
    def test_register_and_get(self):
        worktrees = _StubResource("worktrees", payload={"count": 3})
        reg = _build_registry(worktrees)
        self.assertIs(reg.get("worktrees"), worktrees)
        self.assertIn("worktrees", reg)

    def test_unknown_resource_raises(self):
        reg = ResourceRegistry()
        with self.assertRaises(LCSError):
            reg.get("nonexistent")
        self.assertNotIn("nonexistent", reg)

    def test_register_duplicate_raises(self):
        worktrees = _StubResource("worktrees")
        reg = _build_registry(worktrees)
        with self.assertRaises(LCSError):
            reg.register(_StubResource("worktrees"))

    def test_register_resource_without_name_raises(self):
        class Nameless:
            def fetch(self, parsed): pass
        reg = ResourceRegistry()
        with self.assertRaises(LCSError):
            reg.register(Nameless())

    def test_nested_resource_lookup(self):
        coverage = _StubResource("hooks/coverage", payload={"covered": 5})
        reg = _build_registry(coverage)
        self.assertIs(reg.get("hooks/coverage"), coverage)
        # Parent prefix isn't registered, so it doesn't match.
        self.assertNotIn("hooks", reg)


class TestDispatch(unittest.TestCase):
    def test_dispatch_routes_to_correct_resource(self):
        worktrees = _StubResource("worktrees", payload={"count": 3})
        pr = _StubResource("pr", payload={"number": 29})
        reg = _build_registry(worktrees, pr)
        server = LCSServer(reg)
        result = server.get("lcs://worktrees")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"], {"count": 3})
        self.assertEqual(len(worktrees.calls), 1)
        result = server.get("lcs://pr/29")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"], {"number": 29})
        self.assertEqual(len(pr.calls), 1)
        self.assertEqual(pr.calls[0].segments, ("pr", "29"))

    def test_dispatch_unknown_uri_raises(self):
        server = LCSServer(ResourceRegistry())
        with self.assertRaises(LCSError):
            server.get("lcs://nope")

    def test_dispatch_passes_parsed_uri_to_handler(self):
        captured = []
        class Capture:
            name = "pr"
            def fetch(self, parsed):
                captured.append(parsed)
                return {"status": "ok", "data": {}}
        server = LCSServer(_build_registry(Capture()))
        server.get("lcs://pr/42")
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].path_segments, ("pr", "42"))

    def test_longest_match_wins_for_nested_resource(self):
        # When both "hooks" and "hooks/coverage" are registered, the
        # nested one must win for URI "lcs://hooks/coverage" — the
        # shorter match would be wrong (the handler would receive an
        # unexpected trailing segment).
        parent = _StubResource("hooks", payload={"level": "parent"})
        nested = _StubResource("hooks/coverage", payload={"level": "nested"})
        reg = _build_registry(parent, nested)
        server = LCSServer(reg)
        result = server.get("lcs://hooks/coverage")
        self.assertEqual(result["data"], {"level": "nested"})
        self.assertEqual(len(nested.calls), 1)
        self.assertEqual(len(parent.calls), 0)

    def test_handler_receives_trailing_segments_as_path_params(self):
        # Resource "interview" registered; URI lcs://interview/sess-42
        # routes to it, and the handler reads the session id from
        # parsed.path_segments[1] (the same contract as a real handler
        # would use).
        class Interview:
            name = "interview"
            def fetch(self, parsed):
                return {"status": "ok",
                        "data": {"session_id": parsed.path_segments[1]}}
        server = LCSServer(_build_registry(Interview()))
        result = server.get("lcs://interview/sess-42")
        self.assertEqual(result["data"], {"session_id": "sess-42"})


# ──────────────────────────────────────────────────────────────────
# Partial-failure + error modes
# ──────────────────────────────────────────────────────────────────

class TestPartialFailure(unittest.TestCase):
    def test_partial_status_propagates(self):
        worktrees = _StubResource("worktrees", partial_payload={"active": ["main"]})
        server = LCSServer(_build_registry(worktrees))
        result = server.get("lcs://worktrees")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["data"], {"active": ["main"]})
        self.assertIn("missing", result)
        self.assertEqual(result["missing"], ["upstream:fixture-down"])

    def test_handler_raises_LCSPartialError_becomes_partial_status(self):
        class Partial:
            name = "pr"
            def fetch(self, parsed):
                raise LCSPartialError(
                    data={"number": int(parsed.path_segments[1])},
                    missing=["upstream:gh-api-401"],
                )
        server = LCSServer(_build_registry(Partial()))
        result = server.get("lcs://pr/99")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["data"], {"number": 99})
        self.assertEqual(result["missing"], ["upstream:gh-api-401"])

    def test_handler_raises_unexpected_exception_becomes_error_status(self):
        class Boom:
            name = "pr"
            def fetch(self, parsed):
                raise RuntimeError("upstream:network-down")
        server = LCSServer(_build_registry(Boom()))
        result = server.get("lcs://pr/99")
        self.assertEqual(result["status"], "error")
        self.assertIn("upstream:network-down", result.get("error", ""))

    def test_handler_omitting_status_gets_ok_default(self):
        # Defensive default: a handler that returns a dict without
        # "status" still produces a usable response (status="ok").
        class NoStatus:
            name = "pr"
            def fetch(self, parsed):
                return {"data": {"x": 1}}
        server = LCSServer(_build_registry(NoStatus()))
        result = server.get("lcs://pr/1")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"], {"x": 1})


# ──────────────────────────────────────────────────────────────────
# In-memory snapshot cache
# ──────────────────────────────────────────────────────────────────

class TestCache(unittest.TestCase):
    def test_repeat_read_within_ttl_hits_cache(self):
        worktrees = _StubResource("worktrees", payload={"count": 3})
        server = LCSServer(_build_registry(worktrees), ttl_seconds=5.0)
        server.get("lcs://worktrees")
        server.get("lcs://worktrees")
        server.get("lcs://worktrees")
        self.assertEqual(len(worktrees.calls), 1)

    def test_read_past_ttl_refetches(self):
        worktrees = _StubResource("worktrees", payload={"count": 3})
        server = LCSServer(_build_registry(worktrees), ttl_seconds=0.05)
        server.get("lcs://worktrees")
        time.sleep(0.08)
        server.get("lcs://worktrees")
        self.assertEqual(len(worktrees.calls), 2)

    def test_cache_key_includes_full_uri(self):
        # Same handler, different path params = different cache entries.
        # We model this by registering the handler under two names so
        # both URIs route to the same handler but use distinct keys.
        pr = _StubResource("pr", payload={"number": 0})
        server = LCSServer(_build_registry(pr))
        server.get("lcs://pr/1")
        server.get("lcs://pr/2")
        self.assertEqual(len(pr.calls), 2)
        self.assertEqual(pr.calls[0].segments, ("pr", "1"))
        self.assertEqual(pr.calls[1].segments, ("pr", "2"))

    def test_cache_disabled_with_ttl_zero(self):
        worktrees = _StubResource("worktrees", payload={})
        server = LCSServer(_build_registry(worktrees), ttl_seconds=0.0)
        server.get("lcs://worktrees")
        server.get("lcs://worktrees")
        self.assertEqual(len(worktrees.calls), 2)

    def test_partial_responses_are_cached_too(self):
        worktrees = _StubResource("worktrees", partial_payload={"active": ["main"]})
        server = LCSServer(_build_registry(worktrees), ttl_seconds=5.0)
        r1 = server.get("lcs://worktrees")
        r2 = server.get("lcs://worktrees")
        self.assertEqual(r1["status"], "partial")
        self.assertEqual(r2["status"], "partial")
        self.assertEqual(len(worktrees.calls), 1)

    def test_invalidate_uri_drops_entry(self):
        worktrees = _StubResource("worktrees", payload={})
        server = LCSServer(_build_registry(worktrees))
        server.get("lcs://worktrees")
        server.invalidate("lcs://worktrees")
        server.get("lcs://worktrees")
        self.assertEqual(len(worktrees.calls), 2)

    def test_invalidate_none_clears_all(self):
        a = _StubResource("a", payload={})
        b = _StubResource("b", payload={})
        server = LCSServer(_build_registry(a, b))
        server.get("lcs://a")
        server.get("lcs://b")
        server.invalidate()
        server.get("lcs://a")
        server.get("lcs://b")
        self.assertEqual(len(a.calls), 2)
        self.assertEqual(len(b.calls), 2)


# ──────────────────────────────────────────────────────────────────
# Latency budgets (Phase 1.1 acceptance: boot <500ms, read p99 <10ms)
# ──────────────────────────────────────────────────────────────────

class TestLatencyBudgets(unittest.TestCase):
    def test_read_p99_under_10ms(self):
        worktrees = _StubResource("worktrees", payload={"count": 3})
        server = LCSServer(_build_registry(worktrees))
        server.get("lcs://worktrees")  # warm up
        timings = []
        for _ in range(100):
            t0 = time.perf_counter()
            server.get("lcs://worktrees")
            timings.append((time.perf_counter() - t0) * 1000)
        timings.sort()
        p99 = timings[98]
        self.assertLess(p99, 10.0, f"read p99 was {p99:.3f}ms (target <10ms)")

    def test_initial_construction_under_500ms(self):
        t0 = time.perf_counter()
        LCSServer(ResourceRegistry())
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(elapsed_ms, 500.0, f"boot took {elapsed_ms:.3f}ms")


if __name__ == "__main__":
    unittest.main()
