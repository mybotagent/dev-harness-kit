#!/usr/bin/env python3
"""test_research_engine.py — RED-first tests for lib/research_engine.py.

Covers:
  - Phase 0 cache hit / miss / staleness
  - Phase 1 direct search (HTTP fetch + OGP / JSON-LD extract)
  - Phase 2 multi-source fan-out + dedupe
  - Phase 3 human handoff (NEEDS_HUMAN envelope, never fabricated)
  - max_phase cap (clamps to 3, respects 0 = cache only)
  - verify() citation gate: missing url / timestamp / source_type
  - verify() N-source agreement (>= 3 sources -> confidence boost)
  - enforce_citations() text sanitization (UNCITED flag)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import research_engine  # noqa: E402


def _make_src(url="https://example.com", source_type="primary",
              fetched_at="2026-07-26", asserts_claim=True, **kw):
    """Helper: build a source dict the way `escalate()` / `verify()` consume."""
    out = {"url": url, "fetched_at": fetched_at, "source_type": source_type,
           "asserts_claim": asserts_claim}
    out.update(kw)
    return out


class TestPhaseEscalation(unittest.TestCase):
    """Phase 0 -> 1 -> 2 -> 3 escalation logic."""

    def test_phase_0_cache_hit(self):
        """Pre-seeded cache returns Phase 0 result."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            root.joinpath(".dev-kit").mkdir()
            rec = {
                "query": "phase 0 test",
                "fetched_at": "2026-07-26",
                "fetched_at_epoch": 9999999999,   # far future = never stale
                "result": "cached result string",
                "sources": [{
                    "url": "https://example.com",
                    "source_type": "primary",
                    "fetched_at": "2026-07-26",
                    "title": "Example",
                    "snippet": "snip",
                    "authority": 0.9,
                }],
            }
            with open(root / ".dev-kit" / "research_cache.jsonl", "w") as f:
                f.write(json.dumps(rec) + "\n")
            out = research_engine.escalate("phase 0 test", project_root=root)
            self.assertEqual(out.phase, 0)
            self.assertEqual(out.result, "cached result string")
            self.assertEqual(len(out.sources), 1)
            self.assertEqual(out.sources[0].url, "https://example.com")

    def test_phase_0_cache_miss_no_file(self):
        """No cache file -> fall through to Phase 1+."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch.object(research_engine, "_phase_one_direct", return_value=None) as m1, \
                 patch.object(research_engine, "_phase_three_human",
                              wraps=research_engine._phase_three_human) as m3:
                out = research_engine.escalate("nope", project_root=root,
                                               candidate_urls=["https://x.com"],
                                               max_phase=3)
            self.assertEqual(out.phase, 3)
            self.assertTrue(out.needs_human)
            m1.assert_called_once()
            m3.assert_called_once()

    def test_phase_0_stale_cache_skipped(self):
        """Cache older than 30 days is treated as a miss."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            root.joinpath(".dev-kit").mkdir()
            rec = {
                "query": "stale",
                "fetched_at": "2020-01-01",
                "fetched_at_epoch": 1577836800,   # 2020-01-01
                "result": "stale",
                "sources": [],
            }
            with open(root / ".dev-kit" / "research_cache.jsonl", "w") as f:
                f.write(json.dumps(rec) + "\n")
            with patch.object(research_engine, "_phase_one_direct", return_value=None) as m1, \
                 patch.object(research_engine, "_phase_three_human",
                              wraps=research_engine._phase_three_human):
                out = research_engine.escalate("stale", project_root=root,
                                               candidate_urls=["https://x.com"],
                                               max_phase=3)
            # Stale cache = miss -> Phase 1 attempted -> None -> Phase 3
            self.assertEqual(out.phase, 3)
            self.assertTrue(out.needs_human)
            m1.assert_called_once()

    def test_phase_1_direct_search(self):
        """Phase 1 returns a Source when _phase_one_direct succeeds."""
        src = research_engine.Source(
            url="https://example.com", source_type="primary",
            fetched_at="2026-07-26", title="T", snippet="S",
            valid=True, authority=0.9,
        )
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch.object(research_engine, "_phase_one_direct", return_value=src):
                out = research_engine.escalate("phase 1", project_root=root,
                                               candidate_urls=["https://example.com"],
                                               max_phase=1)
            self.assertEqual(out.phase, 1)
            self.assertEqual(len(out.sources), 1)
            self.assertEqual(out.sources[0].url, "https://example.com")
            # And the cache was written for next time.
            self.assertTrue((root / ".dev-kit" / "research_cache.jsonl").exists())

    def test_phase_2_multi_source_fanout(self):
        """Phase 2 dedupes sources across multiple URLs."""
        s1 = research_engine.Source(url="https://a.com", source_type="primary",
                                    fetched_at="2026-07-26", authority=0.9)
        s2 = research_engine.Source(url="https://b.com", source_type="secondary",
                                    fetched_at="2026-07-26", authority=0.6)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch.object(research_engine, "_phase_two_multi", return_value=[s1, s2]):
                out = research_engine.escalate("multi", project_root=root,
                                               candidate_urls=["https://a.com", "https://b.com"],
                                               max_phase=2)
            self.assertEqual(out.phase, 2)
            self.assertEqual(len(out.sources), 2)
            urls = {s.url for s in out.sources}
            self.assertEqual(urls, {"https://a.com", "https://b.com"})

    def test_phase_3_human_handoff_never_fabricates(self):
        """Phase 3 returns NEEDS_HUMAN with empty sources, even on Phase 2 success below threshold."""
        out = research_engine.escalate("anything", project_root=Path(tempfile.mkdtemp()),
                                       candidate_urls=["https://a.com"],   # only 1 -> Phase 2 not entered
                                       max_phase=3)
        self.assertEqual(out.phase, 3)
        self.assertTrue(out.needs_human)
        self.assertEqual(out.result, "NEEDS_HUMAN")
        self.assertEqual(out.sources, [])

    def test_max_phase_caps_escalation(self):
        """max_phase=0 short-circuits to Phase 0 cache only (no Phase 1 fetch)."""
        with patch.object(research_engine, "_phase_one_direct") as m1:
            out = research_engine.escalate("q", project_root=Path(tempfile.mkdtemp()),
                                           candidate_urls=["https://x.com"],
                                           max_phase=0)
        # No cache seeded -> Phase 0 miss -> max_phase=0 prevents escalation
        # -> engine returns Phase 3 (human handoff), but Phase 1 must NOT be called.
        self.assertEqual(out.phase, 3)
        self.assertTrue(out.needs_human)
        m1.assert_not_called()

    def test_max_phase_clamped_to_3(self):
        """max_phase > 3 is clamped (Phase 4+ does not exist)."""
        with patch.object(research_engine, "_phase_one_direct", return_value=None), \
             patch.object(research_engine, "_phase_three_human",
                          wraps=research_engine._phase_three_human):
            out = research_engine.escalate("q", project_root=Path(tempfile.mkdtemp()),
                                           candidate_urls=["https://x.com"],
                                           max_phase=99)
        self.assertEqual(out.phase, 3)
        self.assertTrue(out.needs_human)


class TestVerifyCitationGate(unittest.TestCase):
    """verify() enforces url + fetched_at + source_type, and HEADs each URL."""

    def test_verify_empty_claim_rejected(self):
        with patch.object(research_engine, "_http_head", return_value=True):
            out = research_engine.verify("", [_make_src()])
        self.assertFalse(out.verified)
        self.assertIn("claim is empty", out.gaps)

    def test_verify_empty_sources_rejected(self):
        with patch.object(research_engine, "_http_head", return_value=True):
            out = research_engine.verify("a real claim", [])
        self.assertFalse(out.verified)
        self.assertEqual(out.confidence, 0.0)
        self.assertIn("no sources provided", out.gaps[0])

    def test_verify_missing_url_rejected(self):
        with patch.object(research_engine, "_http_head", return_value=True):
            out = research_engine.verify("claim", [{"fetched_at": "2026-07-26",
                                                    "source_type": "primary"}])
        self.assertFalse(out.verified)
        self.assertTrue(any("missing url" in g for g in out.gaps))

    def test_verify_missing_timestamp_excludes_source(self):
        # Per the Phase 5 (issue #443) review: citation gate no longer
        # fails open. A source with missing fetched_at is excluded from
        # citations and verified=False.
        with patch.object(research_engine, "_http_head", return_value=True):
            out = research_engine.verify("claim", [_make_src(fetched_at="")])
        self.assertFalse(out.verified)
        self.assertEqual(out.citations, [])
        self.assertTrue(any("missing fetched_at" in g for g in out.gaps))

    def test_verify_invalid_source_type_excludes_source(self):
        with patch.object(research_engine, "_http_head", return_value=True):
            out = research_engine.verify("claim", [_make_src(source_type="bogus")])
        self.assertFalse(out.verified)
        self.assertEqual(out.citations, [])
        self.assertTrue(any("invalid source_type" in g for g in out.gaps))

    def test_verify_broken_url_reported_as_gap(self):
        with patch.object(research_engine, "_http_head", return_value=False):
            out = research_engine.verify("claim", [_make_src()])
        self.assertFalse(out.verified)
        self.assertTrue(any("HEAD request failed" in g for g in out.gaps))

    def test_verify_n_source_agreement_boost(self):
        """N >= 3 agreeing sources -> confidence boost."""
        with patch.object(research_engine, "_http_head", return_value=True):
            out = research_engine.verify("consensus claim", [
                _make_src(url="https://a.com"),
                _make_src(url="https://b.com"),
                _make_src(url="https://c.com"),
            ])
        self.assertTrue(out.verified)
        self.assertEqual(out.agreement_sources, 3)
        # base = 0.5 + 0.1*3 = 0.8 ; boost = +0.1 (3 // 3 * 0.1) ; total 0.9
        self.assertGreater(out.confidence, 0.8)


class TestEnforceCitations(unittest.TestCase):
    """enforce_citations() flags uncited claims."""

    def test_enforce_flags_uncited_sentence(self):
        text = "Python 3.12 added the new typing syntax. This is well documented."
        out = research_engine.enforce_citations(text)
        self.assertIn("[UNCITED]", out)
        # Both sentences are uncited (no [src:...;ts:...;type:...] block).
        self.assertEqual(out.count("[UNCITED]"), 2)

    def test_enforce_passes_cited_sentence(self):
        # Citation block on the same sentence as the claim -> no UNCITED flag.
        text = ("Python 3.12 added the new typing syntax "
                "[src:https://docs.python.org/3/whatsnew/3.12.html;ts:2026-07-26;type:primary].")
        out = research_engine.enforce_citations(text)
        self.assertNotIn("[UNCITED]", out)

    def test_enforce_short_sentence_not_flagged(self):
        """< 4 words are not treated as claims."""
        text = "Python is great."
        out = research_engine.enforce_citations(text)
        self.assertNotIn("[UNCITED]", out)

    def test_enforce_empty_text_passthrough(self):
        self.assertEqual(research_engine.enforce_citations(""), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ---- SSRF gate (Phase 5 review finding, issue #443) ----

class TestSsrfGate:
    """The _validate_url_for_ssrf helper must reject schemes other than
    http(s) and any host that resolves to a private/loopback/link-local
    address (RFC1918, 127.0.0.0/8, 169.254.0.0/16, cloud metadata, etc).
    """

    def test_rejects_ftp_scheme(self):
        from research_engine import _validate_url_for_ssrf
        assert _validate_url_for_ssrf("ftp://example.com/file") is False

    def test_rejects_file_scheme(self):
        from research_engine import _validate_url_for_ssrf
        assert _validate_url_for_ssrf("file:///etc/passwd") is False

    def test_rejects_loopback(self):
        from research_engine import _validate_url_for_ssrf
        assert _validate_url_for_ssrf("http://127.0.0.1/x") is False

    def test_rejects_metadata_service(self):
        from research_engine import _validate_url_for_ssrf
        assert _validate_url_for_ssrf("http://169.254.169.254/latest/meta-data/") is False

    def test_rejects_rfc1918(self):
        from research_engine import _validate_url_for_ssrf
        assert _validate_url_for_ssrf("http://10.0.0.1/secret") is False

    def test_rejects_link_local(self):
        from research_engine import _validate_url_for_ssrf
        assert _validate_url_for_ssrf("http://[fe80::1]/x") is False

    def test_accepts_public_https(self):
        from research_engine import _validate_url_for_ssrf
        # example.com is a public host (RFC2606 reserved for docs but
        # resolves to a public IP).
        assert _validate_url_for_ssrf("https://example.com/page") is True

    def test_rejects_malformed_url(self):
        from research_engine import _validate_url_for_ssrf
        assert _validate_url_for_ssrf("not a url") is False
        assert _validate_url_for_ssrf("") is False
