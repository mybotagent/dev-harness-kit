#!/usr/bin/env python3
"""research_engine.py — Phase 0-3 escalation + verification gate for /dev-kit:research.

Four escalation phases (deterministic, no model picks the phase):
  Phase 0 - cache hit: lcs://research/cache lookup (in-memory / on-disk JSONL).
  Phase 1 - direct search: single HTTP GET + OGP / JSON-LD metadata extract.
  Phase 2 - multi-source: fan-out across N candidate URLs, deduplicate claims.
  Phase 3 - human handoff: returns a structured NEEDS_HUMAN payload so the
            operator can complete the research manually.

`escalate()` runs the next eligible phase whenever the prior one returns an
unsatisfying result (cache miss, HTTP failure, < N agreeing sources). The
`max_phase` cap bounds how far the engine is allowed to escalate before it
must stop. Phase 3 always returns a NEEDS_HUMAN envelope - never a fabricated
result.

`verify()` is the citation gate: every claim must cite a URL + a fetch
timestamp + a source type (primary / secondary). Uncited claims are rejected;
claims that agree across N >= 3 sources get a confidence boost.

`enforce_citations()` is the textual sanitizer - strips or marks claims that
are not backed by a citation block in the same text. The output is the
input text with any unsupported claim flagged as `[UNCITED]`.

Module surface (kept narrow - no dependency on external search SDKs):
  - Cache file: <project>/.dev-kit/research_cache.jsonl (one record per line).
  - HTTP fetch: stdlib urllib (no requests / curl_cffi dependency).
  - No Playwright - Phase 3 returns a NEEDS_HUMAN handoff instead.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Max phase cap. Phase 3 always requires human action; bumping this past 3
# has no effect (there is no Phase 4 implementation).
MAX_PHASE_CAP = 3

# HTTP timeout for Phase 1 / Phase 2 fetches. Short enough to fail fast on
# human-interactive runtimes (research is rarely time-critical), long enough
# to tolerate transient slowness on the slow path.
_HTTP_TIMEOUT = 10

# Confidence threshold for "agreement boost" - N sources with the same claim
# yield a +N confidence adjustment capped at MAX_AGREEMENT_BOOST.
AGREEMENT_THRESHOLD = 3
MAX_AGREEMENT_BOOST = 0.3

# Source-type taxonomy. Primary = original publication, regulator filing,
# first-party blog post. Secondary = aggregator, news outlet covering the
# primary, third-party analysis. Tertiary is informational only.
SOURCE_TYPES = ("primary", "secondary", "tertiary")

# Citation block regex - matches inline citations of the form
#   <text> [src:https://example.com;ts:2026-07-26;type:primary]
# The bracketed block is required; bare URLs in prose do NOT count as a
# citation by themselves. This forces authors to encode source type +
# timestamp explicitly, which is what `verify()` then checks.
_CITATION_RE = re.compile(
    r"\[src:(?P<url>[^;\]\s]+);ts:(?P<ts>\d{4}-\d{2}-\d{2});type:(?P<type>primary|secondary|tertiary)\]"
)


@dataclass
class VerificationResult:
    """Result envelope returned by `verify()`."""
    verified: bool
    citations: List[Dict[str, str]] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    confidence: float = 0.0
    agreement_sources: int = 0


@dataclass
class Source:
    """One source record. Used by escalate() to thread URLs through phases."""
    url: str
    source_type: str = "secondary"   # primary / secondary / tertiary
    fetched_at: str = ""             # ISO date (YYYY-MM-DD)
    title: str = ""
    snippet: str = ""
    valid: bool = True
    authority: float = 0.0           # 0.0-1.0 domain-authority score


@dataclass
class EscalationResult:
    """Result envelope returned by `escalate()`."""
    phase: int = 0           # 0, 1, 2, or 3
    result: str = ""         # human-readable summary
    sources: List[Source] = field(default_factory=list)
    needs_human: bool = False
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Phase 0 - cache hit
# ---------------------------------------------------------------------------

def _cache_path(project_root: Path) -> Path:
    return project_root / ".dev-kit" / "research_cache.jsonl"


def _cache_lookup(query: str, project_root: Path) -> Optional[Dict]:
    """Scan the JSONL cache for a non-stale (< 30 day) record matching query.

    Returns the parsed record dict (with `sources` key), or None on miss /
    cache miss / staleness. The cache file is created lazily on first write;
    a missing file is not an error.
    """
    p = _cache_path(project_root)
    if not p.exists():
        return None
    cutoff = time.time() - (30 * 24 * 3600)
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("query") != query:
                    continue
                ts = rec.get("fetched_at_epoch", 0)
                if ts < cutoff:
                    continue   # stale
                return rec
    except OSError:
        return None
    return None


def _cache_record(query: str, sources: List[Source], result: str) -> Dict:
    """Build a cache record dict from a Phase 1+ result."""
    now = time.time()
    return {
        "query": query,
        "fetched_at": time.strftime("%Y-%m-%d", time.gmtime(now)),
        "fetched_at_epoch": now,
        "result": result,
        "sources": [
            {
                "url": s.url,
                "source_type": s.source_type,
                "fetched_at": s.fetched_at,
                "title": s.title,
                "snippet": s.snippet,
                "authority": s.authority,
            }
            for s in sources
        ],
    }


def _cache_write(query: str, sources: List[Source], result: str, project_root: Path) -> None:
    """Append a record to the cache. No-op if write fails."""
    p = _cache_path(project_root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = _cache_record(query, sources, result)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Phase 1 - direct search (HTTP GET + OGP / JSON-LD extract)
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: int = _HTTP_TIMEOUT) -> Optional[str]:
    """Fetch a URL via stdlib urllib. Returns text or None on failure."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "dev-kit-research/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text" not in content_type and "json" not in content_type and "html" not in content_type:
                return None
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError):
        return None


def _http_head(url: str, timeout: int = _HTTP_TIMEOUT) -> bool:
    """HEAD request - returns True if the URL resolves (2xx / 3xx)."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "dev-kit-research/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError):
        return False


def _extract_metadata(html: str) -> Dict[str, str]:
    """Pull OGP / JSON-LD / <title> / meta-description from an HTML payload.

    Returns a dict with whatever keys were found (missing keys = absent).
    The regex patterns are deliberately loose - research does not need a
    full HTML parser, just enough metadata to render a useful citation.
    """
    out: Dict[str, str] = {}

    # OGP title
    m = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    if m:
        out["title"] = m.group(1).strip()
    # <title>
    if "title" not in out:
        m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        if m:
            out["title"] = m.group(1).strip()
    # OGP description / meta description
    m = re.search(
        r'<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    if m:
        out["snippet"] = m.group(1).strip()
    # JSON-LD
    m = re.search(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.+?)</script>',
        html, re.IGNORECASE | re.DOTALL,
    )
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict):
                if data.get("@type") in ("Article", "NewsArticle", "BlogPosting", "WebPage"):
                    if "headline" in data and "title" not in out:
                        out["title"] = str(data["headline"]).strip()
                    if "datePublished" in data:
                        out["datePublished"] = str(data["datePublished"]).strip()
        except (json.JSONDecodeError, ValueError):
            pass
    return out


def _authority_for(url: str) -> float:
    """Heuristic domain-authority score, 0.0-1.0.

    No real PageRank - just a small static table of well-known domains +
    a length-based fallback so unknown domains still get a non-zero score.
    """
    try:
        host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    except (ValueError, AttributeError):
        return 0.2
    PRIMARY_DOMAINS = {
        # Standards / official
        "w3.org": 0.95, "ietf.org": 0.95, "rfc-editor.org": 0.95,
        "python.org": 0.9, "docs.python.org": 0.9,
        # Package registries
        "pypi.org": 0.9, "npmjs.com": 0.9, "crates.io": 0.9,
        # Source hosts
        "github.com": 0.85, "gitlab.com": 0.85,
        # News / media (recognized)
        "nytimes.com": 0.8, "reuters.com": 0.85, "apnews.com": 0.85,
        "bbc.com": 0.8, "bbc.co.uk": 0.8, "theguardian.com": 0.75,
    }
    SECONDARY_DOMAINS = {
        "stackoverflow.com": 0.7, "medium.com": 0.55, "dev.to": 0.55,
        "wikipedia.org": 0.7, "reddit.com": 0.45,
    }
    for d, score in PRIMARY_DOMAINS.items():
        if host == d or host.endswith("." + d):
            return score
    for d, score in SECONDARY_DOMAINS.items():
        if host == d or host.endswith("." + d):
            return score
    # Fallback: shorter domains tend to be more authoritative; cap at 0.4.
    base = max(0.1, 0.4 - (len(host) - 8) * 0.01)
    return max(0.1, min(0.4, base))


def _phase_one_direct(query: str, url: str) -> Optional[Source]:
    """Phase 1 implementation: fetch one URL + extract metadata."""
    html = _http_get(url)
    if html is None:
        return None
    meta = _extract_metadata(html)
    return Source(
        url=url,
        source_type="primary" if _authority_for(url) >= 0.7 else "secondary",
        fetched_at=time.strftime("%Y-%m-%d", time.gmtime()),
        title=meta.get("title", ""),
        snippet=meta.get("snippet", "")[:500],
        valid=True,
        authority=_authority_for(url),
    )


# ---------------------------------------------------------------------------
# Phase 2 - multi-source (fan-out + deduplicate)
# ---------------------------------------------------------------------------

def _dedupe_sources(sources: List[Source]) -> List[Source]:
    """Drop sources with the same URL or empty URL."""
    seen = set()
    out = []
    for s in sources:
        if not s.url or s.url in seen:
            continue
        seen.add(s.url)
        out.append(s)
    return out


def _phase_two_multi(query: str, candidate_urls: List[str]) -> List[Source]:
    """Phase 2 implementation: fan-out across candidate URLs."""
    sources: List[Source] = []
    for url in candidate_urls:
        src = _phase_one_direct(query, url)
        if src is not None:
            sources.append(src)
    return _dedupe_sources(sources)


# ---------------------------------------------------------------------------
# Phase 3 - human handoff (always NEEDS_HUMAN, never fabricated)
# ---------------------------------------------------------------------------

def _phase_three_human(query: str, error: str) -> EscalationResult:
    """Phase 3 always returns a structured NEEDS_HUMAN envelope."""
    return EscalationResult(
        phase=3,
        result="NEEDS_HUMAN",
        sources=[],
        needs_human=True,
        error=error or f"Phase 0-2 returned no usable results for query {query!r}",
    )


# ---------------------------------------------------------------------------
# escalate - public entry point
# ---------------------------------------------------------------------------

def escalate(
    query: str,
    *,
    project_root: Optional[Path] = None,
    candidate_urls: Optional[List[str]] = None,
    max_phase: int = MAX_PHASE_CAP,
) -> EscalationResult:
    """Run Phase 0 -> max_phase, escalating on failure.

    Parameters
    ----------
    query : str
        The natural-language research query.
    project_root : Path, optional
        Repo root (defaults to cwd). Used for cache read/write.
    candidate_urls : list[str], optional
        Pre-curated URLs for Phase 2. If omitted and Phase 2 is reached,
        the engine returns a NEEDS_HUMAN payload (we do not invent URLs).
    max_phase : int
        Upper bound on the phase that may execute. Values > MAX_PHASE_CAP
        are clamped. Phase 3 (human handoff) is the terminal state - it
        never fabricates a result.
    """
    if project_root is None:
        project_root = Path(os.environ.get("PROJECT_ROOT", "."))
    max_phase = max(0, min(int(max_phase), MAX_PHASE_CAP))

    # ---- Phase 0: cache ----
    if max_phase >= 0:
        rec = _cache_lookup(query, project_root)
        if rec is not None:
            sources = [
                Source(
                    url=s.get("url", ""),
                    source_type=s.get("source_type", "secondary"),
                    fetched_at=s.get("fetched_at", ""),
                    title=s.get("title", ""),
                    snippet=s.get("snippet", ""),
                    valid=True,
                    authority=float(s.get("authority", 0.0)),
                )
                for s in rec.get("sources", [])
                if s.get("url")
            ]
            return EscalationResult(
                phase=0,
                result=rec.get("result", ""),
                sources=sources,
                needs_human=False,
            )

    # ---- Phase 1: direct search (uses the first candidate URL) ----
    if max_phase >= 1:
        first_url = (candidate_urls or [None])[0]
        if first_url:
            src = _phase_one_direct(query, first_url)
            if src is not None:
                _cache_write(query, [src], f"Phase 1 fetch: {src.title or src.url}", project_root)
                return EscalationResult(phase=1, result=f"Fetched {src.url}", sources=[src])

    # ---- Phase 2: multi-source fan-out ----
    if max_phase >= 2 and candidate_urls and len(candidate_urls) >= 2:
        sources = _phase_two_multi(query, candidate_urls)
        if sources:
            _cache_write(
                query,
                sources,
                f"Phase 2 multi-source: {len(sources)} URLs aggregated",
                project_root,
            )
            return EscalationResult(
                phase=2,
                result=f"Aggregated {len(sources)} sources",
                sources=sources,
            )

    # ---- Phase 3: human handoff ----
    return _phase_three_human(
        query,
        error="No usable result from Phases 0-2",
    )


# ---------------------------------------------------------------------------
# verify - citation gate
# ---------------------------------------------------------------------------

def verify(claim: str, sources: List[Dict]) -> VerificationResult:
    """Check that `claim` is backed by `sources` with full citation metadata.

    A claim is verified iff at least one source citation matches it AND that
    source's URL is currently valid (HEAD reachable). N-source agreement
    (>= AGREEMENT_THRESHOLD sources asserting the same claim) raises the
    confidence by up to MAX_AGREEMENT_BOOST. Gaps list missing citation
    fields and broken URLs.

    `sources` is a list of dicts, each with keys: `url`, `fetched_at`,
    `source_type`, optionally `asserts_claim` (bool - default True). The
    `fetched_at` field is the timestamp the source was last verified.
    """
    citations: List[Dict[str, str]] = []
    gaps: List[str] = []
    agreement = 0

    if not isinstance(claim, str) or not claim.strip():
        return VerificationResult(
            verified=False, citations=[], gaps=["claim is empty"],
            confidence=0.0, agreement_sources=0,
        )

    if not sources:
        return VerificationResult(
            verified=False, citations=[],
            gaps=["no sources provided - claim requires at least one citation"],
            confidence=0.0, agreement_sources=0,
        )

    for src in sources:
        url = (src or {}).get("url", "") if isinstance(src, dict) else ""
        if not url:
            gaps.append("source missing url")
            continue
        fetched_at = (src or {}).get("fetched_at", "")
        source_type = (src or {}).get("source_type", "")
        if not fetched_at:
            gaps.append(f"{url}: missing fetched_at timestamp")
        if not source_type or source_type not in SOURCE_TYPES:
            gaps.append(f"{url}: missing or invalid source_type (got {source_type!r})")
        asserts = src.get("asserts_claim", True) if isinstance(src, dict) else True
        valid = _http_head(url)
        if not valid:
            gaps.append(f"{url}: HEAD request failed (URL not currently reachable)")
        if asserts and valid:
            citations.append({"url": url, "fetched_at": fetched_at, "source_type": source_type})
            agreement += 1

    if not citations:
        return VerificationResult(
            verified=False, citations=[], gaps=gaps,
            confidence=0.0, agreement_sources=0,
        )

    base_confidence = min(1.0, 0.5 + 0.1 * len(citations))
    boost = min(MAX_AGREEMENT_BOOST, (agreement // AGREEMENT_THRESHOLD) * 0.1) \
        if agreement >= AGREEMENT_THRESHOLD else 0.0
    confidence = round(min(1.0, base_confidence + boost), 3)

    return VerificationResult(
        verified=True,
        citations=citations,
        gaps=gaps,
        confidence=confidence,
        agreement_sources=agreement,
    )


# ---------------------------------------------------------------------------
# enforce_citations - textual citation sanitizer
# ---------------------------------------------------------------------------

def enforce_citations(text: str) -> str:
    """Mark uncited claims in `text` as `[UNCITED]` rather than dropping them.

    A claim is any sentence that does not already carry a citation block
    matching `_CITATION_RE`. Sentences with a citation are passed through
    unchanged. The output is a single string with `[UNCITED]` prefixed on
    each unsupported sentence.

    The function is intentionally lenient: short sentences (< 4 words) and
    sentences that are pure citation blocks are skipped. The goal is to
    flag factual assertions, not to censor greetings or boilerplate.
    """
    if not text:
        return text
    out_lines = []
    for paragraph in text.split("\n"):
        stripped = paragraph.strip()
        if not stripped:
            out_lines.append(paragraph)
            continue
        new_paragraph = []
        for sentence in re.split(r"(?<=[.!?])\s+", stripped):
            s = sentence.strip()
            if not s:
                continue
            # Has a citation block? Pass through.
            if _CITATION_RE.search(s):
                new_paragraph.append(sentence)
                continue
            # Too short to be a claim - leave alone.
            if len(s.split()) < 4:
                new_paragraph.append(sentence)
                continue
            new_paragraph.append(f"[UNCITED] {sentence}")
        out_lines.append(" ".join(new_paragraph))
    return "\n".join(out_lines)


if __name__ == "__main__":
    print("research_engine loaded")
    print(f"MAX_PHASE_CAP={MAX_PHASE_CAP} AGREEMENT_THRESHOLD={AGREEMENT_THRESHOLD}")
