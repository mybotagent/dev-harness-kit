#!/usr/bin/env python3
"""Token efficiency analyzer for AI agent (Claude Code / Codex) session logs.

Reads JSONL session transcripts under ``<logs_dir>/<source>/<session>.jsonl``
(default: ``./logs/{claude-code,codex}``), aggregates per-session token and
tool usage for a given repository over the last N days, scores each session
0-100 against four dimensions (Cache Utilization, Output Density, Read
Redundancy, Tool Economy), fires anti-pattern warnings, and emits a single
self-contained HTML dashboard with embedded CSS.

Usage::

    python tools/token_efficiency_analyzer.py --repo "my-project" --days 30

Stdlib only (``json``, ``html``, ``os``, ``sys``, ``collections``, ``argparse``,
``datetime``, ``pathlib``, ``statistics``).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean


# ---------------------------------------------------------------------------
# Pricing model (USD per 1M tokens).
#
# Cache *write* is ~25% pricier than base input (one-time priming premium).
# Cache *read* is ~10% of base input (recovers the miss on subsequent turns).
# These match Anthropic's published rates for the Claude 4.x family at the
# time of writing. ``pricing_for()`` matches the model id substring so any
# variant (claude-opus-4-7, claude-sonnet-5, claude-haiku-4-5, ...) resolves.
# ---------------------------------------------------------------------------
PRICING: dict[str, dict[str, float]] = {
    "opus":   {"in": 15.00, "out": 75.00, "cache_write": 18.75, "cache_read": 1.50},
    "sonnet": {"in":  3.00, "out": 15.00, "cache_write":  3.75, "cache_read": 0.30},
    "haiku":  {"in":  0.80, "out":  4.00, "cache_write":  1.00, "cache_read": 0.08},
}
DEFAULT_PRICING_KEY = "sonnet"


def pricing_for(model_id: str) -> dict[str, float]:
    """Pick the pricing row whose key appears in the model id (case-insensitive)."""
    if not model_id:
        return PRICING[DEFAULT_PRICING_KEY]
    mid = model_id.lower()
    for key in ("opus", "sonnet", "haiku"):
        if key in mid:
            return PRICING[key]
    return PRICING[DEFAULT_PRICING_KEY]


def cost_usd(model_id: str, *, input_tokens: int, output_tokens: int,
             cache_write_tokens: int, cache_read_tokens: int) -> float:
    """Dollar cost of one assistant turn.

    ``input_tokens`` is the *non-cached* input (what the cache missed on).
    Cached input is billed separately under cache_read. The cache *write*
    surcharge reflects the 25% premium on the first turn that primes the
    cache prefix.
    """
    p = pricing_for(model_id)
    return (
        input_tokens         * p["in"]          / 1_000_000
        + output_tokens      * p["out"]         / 1_000_000
        + cache_write_tokens * p["cache_write"] / 1_000_000
        + cache_read_tokens  * p["cache_read"]  / 1_000_000
    )


# ---------------------------------------------------------------------------
# Log discovery + session aggregation
# ---------------------------------------------------------------------------

def discover_logs(logs_dir: Path) -> list[Path]:
    """Return every .jsonl under ``<logs_dir>/<source>/*``."""
    if not logs_dir.exists():
        return []
    out: list[Path] = []
    for sub in ("claude-code", "codex"):
        d = logs_dir / sub
        if d.exists():
            out.extend(sorted(d.glob("*.jsonl")))
    return out


def parse_iso(ts: str) -> datetime | None:
    """Best-effort ISO-8601 parser; returns None on failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def repo_from_cwd(cwd: str | None) -> str:
    """Derive a repo label from the working directory's basename."""
    if not cwd:
        return ""
    return Path(cwd).name


def aggregate_session(path: Path) -> dict | None:
    """Walk one JSONL file once and return per-session aggregates, or None."""
    session_id: str | None = None
    repo = ""
    source = path.parent.name
    models: Counter[str] = Counter()
    input_tokens = 0
    output_tokens = 0
    cache_write_tokens = 0
    cache_read_tokens = 0
    ephemeral_5m = 0
    ephemeral_1h = 0
    tool_counts: Counter[str] = Counter()
    read_files: Counter[str] = Counter()
    user_texts: list[str] = []
    first_ts: datetime | None = None
    last_ts: datetime | None = None

    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = parse_iso(rec.get("timestamp") or "")
                if ts is not None:
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts

                if session_id is None:
                    session_id = rec.get("sessionId") or rec.get("session_id") or path.stem
                if not repo:
                    repo = repo_from_cwd(rec.get("cwd"))

                msg = rec.get("message") or {}
                rec_type = rec.get("type")

                if rec_type == "assistant":
                    m = msg.get("model")
                    if m:
                        models[m] += 1
                    u = msg.get("usage") or {}
                    # input_tokens = non-cached input (cache missed)
                    input_tokens       += int(u.get("input_tokens") or 0)
                    output_tokens      += int(u.get("output_tokens") or 0)
                    cache_write_tokens += int(u.get("cache_creation_input_tokens") or 0)
                    cache_read_tokens  += int(u.get("cache_read_input_tokens") or 0)
                    cc = u.get("cache_creation") or {}
                    ephemeral_5m += int(cc.get("ephemeral_5m_input_tokens") or 0)
                    ephemeral_1h += int(cc.get("ephemeral_1h_input_tokens") or 0)

                    for blk in (msg.get("content") or []):
                        if not isinstance(blk, dict):
                            continue
                        if blk.get("type") == "tool_use":
                            name = blk.get("name") or "?"
                            tool_counts[name] += 1
                            if name == "Read":
                                inp = blk.get("input") or {}
                                fp = inp.get("file_path") or inp.get("path") or ""
                                if fp:
                                    read_files[fp] += 1

                elif rec_type == "user":
                    c = msg.get("content")
                    if isinstance(c, str):
                        if c.strip():
                            user_texts.append(c.strip())
                    elif isinstance(c, list):
                        parts: list[str] = []
                        for blk in c:
                            if isinstance(blk, dict) and blk.get("type") == "text":
                                t = blk.get("text")
                                if isinstance(t, str):
                                    parts.append(t)
                        joined = "\n".join(parts).strip()
                        if joined:
                            user_texts.append(joined)

    except OSError:
        return None

    if session_id is None:
        return None

    return {
        "session_id": session_id,
        "source": source,
        "repo": repo or path.stem.split("__")[0],
        "model": models.most_common(1)[0][0] if models else "",
        "first_ts": first_ts,
        "last_ts": last_ts,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_write_tokens": cache_write_tokens,
        "cache_read_tokens": cache_read_tokens,
        "ephemeral_5m": ephemeral_5m,
        "ephemeral_1h": ephemeral_1h,
        "tool_counts": tool_counts,
        "read_files": read_files,
        "user_texts": user_texts,
        "log_path": str(path),
    }


# ---------------------------------------------------------------------------
# Scoring rubric (per session, 0-100 weighted)
#
# Weights: cache 0.35, density 0.25, redundancy 0.20, economy 0.20.
# Total is the weighted sum; each dim is reported alongside.
# ---------------------------------------------------------------------------

def score_session(s: dict) -> dict:
    """Apply the 4-dim rubric. Returns a dict of dim scores + a weighted total.

    Cache Utilization (weight 0.35)
        cache_read / (input + cache_read). Low ratio = critical penalty
        because the prompt prefix is misaligned and we keep re-priming.
        A perfectly cached session scores 100; a session that never hits
        cache scores 0.

    Output Density (weight 0.25)
        output / (input + cache_read). Sessions that only read without ever
        producing artifacts score near 0; sessions that ship a lot of output
        relative to input score high.

    Read Redundancy (weight 0.20)
        Penalty scales with the worst repeated file read (max count of any
        single file in read_files). Reading the same 5000-line file 8 times
        is a cartography failure.

    Tool Economy (weight 0.20)
        tool_calls per 1K output tokens. Excess calls for thin output = wasted
        spend (often a confused agent thrashing).
    """
    total_input = s["input_tokens"] + s["cache_read_tokens"]
    cache_hit = (s["cache_read_tokens"] / total_input) if total_input else 0.0
    s_cache = round(min(100.0, cache_hit * 100.0), 1)

    out_density = s["output_tokens"] / total_input if total_input else 0.0
    # Map density: 0 -> 0, 0.10 -> 50, 0.25+ -> 100 (cap)
    s_density = round(min(100.0, max(0.0, out_density) * 400.0), 1)

    max_repeat = max(s["read_files"].values(), default=0)
    # 1 reread ok, 5+ is bad; cap at 0 score for >= 10.
    s_redundancy = round(max(0.0, 100.0 - (max_repeat - 1) * 12.5), 1)

    total_tools = sum(s["tool_counts"].values())
    tools_per_1k_out = total_tools / max(1.0, s["output_tokens"] / 1000.0)
    # 0 tools/1k -> 100; 50+ tools/1k -> 0
    s_economy = round(max(0.0, 100.0 - tools_per_1k_out * 2.0), 1)

    total = round(
        0.35 * s_cache
        + 0.25 * s_density
        + 0.20 * s_redundancy
        + 0.20 * s_economy,
        1,
    )
    return {
        "cache": s_cache,
        "density": s_density,
        "redundancy": s_redundancy,
        "economy": s_economy,
        "total": total,
        "cache_hit_ratio": cache_hit,
        "max_repeat_reads": max_repeat,
        "tools_per_1k_out": tools_per_1k_out,
    }


# ---------------------------------------------------------------------------
# Warning engine (anti-pattern detection).
#
# Each trigger maps to one of the messages from the meta-prompt. Messages
# are prefixed with the emoji already; we keep them intact so the dashboard
# can render them verbatim.
# ---------------------------------------------------------------------------

def evaluate_warnings(s: dict, score: dict) -> list[dict]:
    """Return a list of {level, code, message} dicts."""
    warnings: list[dict] = []
    total_input = s["input_tokens"] + s["cache_read_tokens"]
    cache_hit = score["cache_hit_ratio"]

    # 1. Cache hit < 50% — prefix misalignment suspected.
    if total_input > 0 and cache_hit < 0.50:
        warnings.append({
            "level": "critical",
            "code": "CACHE_HIT_LOW",
            "message": (
                "🚨 캐시 적중률 50% 미만: 프리픽스(Prefix) 정렬이 깨졌을 "
                "확률이 높습니다. 자주 변하는 데이터(날짜, 시간 등)는 프롬프트 "
                "맨 뒤로 빼고, 세션 중간에 모델이나 CLAUDE.md를 변경하지 마세요. "
                "한 토큰만 엇갈려도 전체 캐시가 무효화됩니다."
            ),
        })

    # 2. Read tool cost >= 40% of total tool-imputed cost.
    #
    # We impute tool cost as: ``n_calls * 2K_tokens * base_input_price``.
    # This is a heuristic proxy for "context the tool surfaces back to the
    # model," not a billing-API call. Real Anthropic billing does not
    # break out per-tool spend, so this is the best approximation.
    tool_costs: dict[str, float] = {}
    for name, n in s["tool_counts"].items():
        tool_costs[name] = n * 2000 * pricing_for(s["model"])["in"] / 1_000_000
    total_tool_cost = sum(tool_costs.values()) or 1.0
    read_share = tool_costs.get("Read", 0.0) / total_tool_cost
    if read_share >= 0.40 and s["tool_counts"].get("Read", 0) > 0:
        warnings.append({
            "level": "critical",
            "code": "READ_HEAVY",
            "message": (
                "🚨 대용량 파일 Turn Read 의심: 파일을 반복해서 읽고 있습니다. "
                "큰 파일은 한 번 읽어 캐시에 고정(Pin)하고, 아키텍처 지도"
                "(Cartography)를 만들어 에이전트가 진입점을 바로 찾게 하세요."
            ),
        })

    # 3. Context growth > 500K (one session accumulating a lot of input).
    if total_input > 500_000:
        warnings.append({
            "level": "warn",
            "code": "HEAVY_CONTEXT",
            "message": (
                "💡 무거운 탐색 위임 권고: 무거운 탐색은 Sub-agent에게 위임하고, "
                "메인 세션에는 요약본만 넘기세요. 장기 세션의 경우 /compact "
                "명령으로 적시에 컨텍스트를 압축해야 합니다."
            ),
        })

    # 4. Opus on low-density simple work.
    is_opus = "opus" in (s["model"] or "").lower()
    if is_opus and score["density"] < 20.0 and s["output_tokens"] > 0:
        warnings.append({
            "level": "warn",
            "code": "MODEL_OVERSPEC",
            "message": (
                "💡 모델 오버스펙: 단순 타이포 수정이나 간단한 로직에는 작업 "
                "성격에 맞춰 하위 모델(Sonnet/Haiku)로 다운그레이드 하세요."
            ),
        })

    # 5. Cache writes high but reads < 2 per write on average.
    writes = s["cache_write_tokens"]
    if writes > 50_000 and s["cache_read_tokens"] < 2 * writes:
        warnings.append({
            "level": "critical",
            "code": "WRITE_NOT_REUSED",
            "message": (
                "🚨 비효율적 프리픽스 캐싱: 첫 호출(Write)은 25% 더 비쌉니다. "
                "5분 안에 2~3번 이상 재사용되지 않을 데이터는 캐시 앞단에 "
                "두지 마세요."
            ),
        })

    # 6. Repeated user messages (same text appears >= 2 times).
    repeats = [t for t, n in Counter(s["user_texts"]).items() if n >= 2 and len(t) > 5]
    if repeats:
        warnings.append({
            "level": "critical",
            "code": "REPEATED_USER_MSG",
            "message": (
                "🚨 안티패턴 감지: 막힐 때마다 세션을 새로 파거나, 이미 캐시된 "
                "컨텍스트를 유저 메시지로 반복 주입하지 마세요. 끝난 작업의 "
                "노드는 컨텍스트에서 즉시 제거하세요."
            ),
        })

    return warnings


# ---------------------------------------------------------------------------
# Estimated savings.
#
# Conservative model: for each session, compute the *delta* between the actual
# cost and an "optimized" cost assuming (a) cache hit >= 70% (good prefix
# alignment) and (b) zero duplicate reads (cartography in place).
#
# The cache-hit delta is computed by *shifting* tokens from the billable input
# bucket into the cache_read bucket until the target hit ratio is reached.
# The cost saved is ``shifted * (input_price - cache_read_price)`` — i.e. the
# difference between paying full input price and paying the much smaller
# cache_read price for those tokens.
#
# The redundancy delta is computed per duplicate read above 1, assuming each
# duplicate reads ~2K tokens of context that would otherwise be cached.
#
# This intentionally leaves the model room — we only reclaim the cache-miss
# penalty + the duplicate-read penalty, not the entire spend.
# ---------------------------------------------------------------------------

def estimated_savings(sessions: list[dict], scored: list[tuple[dict, dict]]) -> float:
    """USD saved if all sessions ran at 70% cache hit + 0 duplicate reads."""
    if not scored:
        return 0.0
    total_saved = 0.0
    for s, sc in scored:
        model = s["model"]
        target_hit = 0.70
        current_hit = sc["cache_hit_ratio"]
        total_input = s["input_tokens"] + s["cache_read_tokens"]
        if current_hit < target_hit and total_input > 0:
            shift = (target_hit - current_hit) * total_input
            p = pricing_for(model)
            total_saved += shift * (p["in"] - p["cache_read"]) / 1_000_000
        # Redundancy savings: each duplicate Read above 1 is ~2K token waste.
        dup_tokens = sum(max(0, n - 1) for n in s["read_files"].values()) * 2000
        total_saved += dup_tokens * pricing_for(model)["in"] / 1_000_000
    return round(total_saved, 2)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_sessions(sessions: list[dict], repo: str, days: int) -> list[dict]:
    """Keep sessions whose derived repo matches ``repo`` AND last_ts within ``days``."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[dict] = []
    for s in sessions:
        if repo and repo not in (s["repo"] or ""):
            continue
        last = s["last_ts"]
        if last is None:
            continue
        if last < cutoff:
            continue
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# HTML rendering (single self-contained file, embedded CSS, no JS, no deps)
# ---------------------------------------------------------------------------

CSS = """
:root {
  --bg: #0e1117;
  --panel: #161b22;
  --panel-2: #1c232c;
  --text: #e6edf3;
  --muted: #8b95a7;
  --accent: #58a6ff;
  --good: #3fb950;
  --warn: #d29922;
  --bad: #f85149;
  --border: #30363d;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
}
.wrap { max-width: 1180px; margin: 0 auto; padding: 32px 24px; }
h1 { margin: 0 0 8px 0; font-size: 28px; letter-spacing: -0.02em; }
.subtitle { color: var(--muted); margin-bottom: 28px; }
.grid { display: grid; gap: 16px; }
.cols-4 { grid-template-columns: repeat(4, 1fr); }
.cols-2 { grid-template-columns: 1fr 1fr; }
@media (max-width: 900px) {
  .cols-4 { grid-template-columns: repeat(2, 1fr); }
  .cols-2 { grid-template-columns: 1fr; }
}
.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 18px 20px;
}
.metric .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; }
.metric .value { font-size: 26px; font-weight: 600; margin-top: 4px; }
.metric .delta { font-size: 12px; color: var(--muted); margin-top: 2px; }
.section-title { font-size: 16px; font-weight: 600; margin: 28px 0 12px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 500; font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; }
tr:last-child td { border-bottom: none; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 500; margin-right: 4px; }
.pill-good { background: rgba(63,185,80,0.15); color: var(--good); }
.pill-warn { background: rgba(210,153,34,0.15); color: var(--warn); }
.pill-bad  { background: rgba(248,81,73,0.15); color: var(--bad); }
.bar { height: 8px; background: var(--panel-2); border-radius: 4px; overflow: hidden; }
.bar > span { display: block; height: 100%; background: var(--accent); }
.warning {
  border-left: 3px solid var(--bad);
  background: rgba(248,81,73,0.06);
  padding: 14px 16px;
  border-radius: 6px;
  margin: 10px 0;
  font-size: 13px;
  white-space: pre-wrap;
}
.warning.warn { border-left-color: var(--warn); background: rgba(210,153,34,0.06); }
.savings {
  background: linear-gradient(135deg, rgba(63,185,80,0.10), rgba(88,166,255,0.10));
  border: 1px solid rgba(63,185,80,0.35);
  border-radius: 10px;
  padding: 22px 26px;
  margin: 18px 0 6px;
}
.savings .big { font-size: 32px; font-weight: 700; color: var(--good); }
.muted { color: var(--muted); }
.footer { color: var(--muted); font-size: 12px; margin-top: 36px; text-align: center; }
code { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; }
"""

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Token Efficiency Dashboard — {repo}</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <h1>Token Efficiency Dashboard</h1>
  <div class="subtitle">{repo} · last {days} days · {session_count} active sessions · generated {generated_at}</div>

  <div class="section-title">Overview</div>
  <div class="grid cols-4">
    <div class="panel metric"><div class="label">Active Sessions</div><div class="value">{session_count}</div><div class="delta">{repos_named} distinct repo labels</div></div>
    <div class="panel metric"><div class="label">Total Cost</div><div class="value">${total_cost:.2f}</div><div class="delta">{total_tokens:,} tokens processed</div></div>
    <div class="panel metric"><div class="label">Avg Score</div><div class="value">{avg_score:.1f}<span class="muted" style="font-size:14px">/100</span></div><div class="delta">cache {avg_cache:.0f} · density {avg_density:.0f} · redundancy {avg_redundancy:.0f} · economy {avg_economy:.0f}</div></div>
    <div class="panel metric"><div class="label">Cache Hit Ratio</div><div class="value">{avg_cache_hit:.0%}</div><div class="delta">cache_read / total_input</div></div>
  </div>

  <div class="section-title">Cost &amp; Token Distribution</div>
  <div class="grid cols-2">
    <div class="panel">
      <div style="font-weight:600;margin-bottom:10px">Cost by Repository</div>
      <table>
        <thead><tr><th>Repo</th><th style="text-align:right">Sessions</th><th style="text-align:right">Cost</th><th style="width:30%">Share</th></tr></thead>
        <tbody>{repo_rows}</tbody>
      </table>
    </div>
    <div class="panel">
      <div style="font-weight:600;margin-bottom:10px">Cost by Tool</div>
      <table>
        <thead><tr><th>Tool</th><th style="text-align:right">Calls</th><th style="text-align:right">Est. Cost</th><th style="width:30%">Share</th></tr></thead>
        <tbody>{tool_rows}</tbody>
      </table>
      {read_warning_html}
    </div>
  </div>

  <div class="section-title">Sessions</div>
  <div class="panel" style="overflow-x:auto">
    <table>
      <thead><tr>
        <th>Session</th><th>Model</th><th>Started</th>
        <th style="text-align:right">Input</th><th style="text-align:right">Output</th>
        <th style="text-align:right">Cache Hit</th><th style="text-align:right">Cost</th>
        <th style="text-align:right">Score</th><th>Warnings</th>
      </tr></thead>
      <tbody>{session_rows}</tbody>
    </table>
  </div>

  <div class="section-title">Actionable Insights &amp; Estimated Savings</div>
  <div class="savings">
    <div class="muted" style="font-size:12px;text-transform:uppercase;letter-spacing:0.06em">Estimated Savings if Recommendations Applied</div>
    <div class="big">${estimated_savings:.2f}</div>
    <div class="muted" style="margin-top:6px">Reclaimable from cache-miss penalty + duplicate-read waste across the {session_count} sessions.</div>
  </div>
  <div>{warnings_html}</div>

  <div class="footer">Computed by tools/token_efficiency_analyzer.py · stdlib only · no external assets</div>
</div>
</body>
</html>
"""


def render_dashboard(repo: str, days: int, sessions: list[dict],
                     scored: list[tuple[dict, dict]],
                     warnings_per_session: list[list[dict]],
                     estimated: float) -> str:
    """Compose the HTML dashboard. Inputs are pre-filtered to ``repo``+``days``."""

    session_costs: list[float] = []
    for s, _ in scored:
        session_costs.append(cost_usd(
            s["model"],
            input_tokens=s["input_tokens"],
            output_tokens=s["output_tokens"],
            cache_write_tokens=s["cache_write_tokens"],
            cache_read_tokens=s["cache_read_tokens"],
        ))
    total_cost = sum(session_costs)
    total_tokens = sum(
        s["input_tokens"] + s["output_tokens"]
        + s["cache_write_tokens"] + s["cache_read_tokens"]
        for s, _ in scored
    )

    avg_score = mean(sc["total"] for _, sc in scored) if scored else 0.0
    avg_cache = mean(sc["cache"] for _, sc in scored) if scored else 0.0
    avg_density = mean(sc["density"] for _, sc in scored) if scored else 0.0
    avg_redundancy = mean(sc["redundancy"] for _, sc in scored) if scored else 0.0
    avg_economy = mean(sc["economy"] for _, sc in scored) if scored else 0.0
    avg_cache_hit = mean(sc["cache_hit_ratio"] for _, sc in scored) if scored else 0.0

    # Cost by repo
    repo_costs: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for (s, _), c in zip(scored, session_costs):
        repo_costs[s["repo"]][0] += 1
        repo_costs[s["repo"]][1] += c
    repo_rows_html = "".join(
        f"<tr><td>{html.escape(rr)}</td><td style='text-align:right'>{int(repo_costs[rr][0])}</td>"
        f"<td style='text-align:right'>${repo_costs[rr][1]:.2f}</td>"
        f"<td><div class='bar'><span style='width:{(repo_costs[rr][1] / total_cost * 100) if total_cost else 0:.1f}%'></span></div></td></tr>"
        for rr in sorted(repo_costs, key=lambda k: -repo_costs[k][1])
    )

    # Cost by tool (imputed — see evaluate_warnings comment for the heuristic)
    tool_costs: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for s, _ in scored:
        for name, n in s["tool_counts"].items():
            est = n * 2000 * pricing_for(s["model"])["in"] / 1_000_000
            tool_costs[name][0] += n
            tool_costs[name][1] += est
    total_tool_cost = sum(c[1] for c in tool_costs.values()) or 1.0
    sorted_tools = sorted(tool_costs.items(), key=lambda kv: -kv[1][1])
    tool_rows_html = "".join(
        f"<tr><td>{html.escape(name)}</td><td style='text-align:right'>{int(calls)}</td>"
        f"<td style='text-align:right'>${cost:.2f}</td>"
        f"<td><div class='bar'><span style='width:{(cost / total_tool_cost * 100):.1f}%'></span></div></td></tr>"
        for name, (calls, cost) in sorted_tools
    )
    read_warning_html = ""
    if sorted_tools and sorted_tools[0][0] == "Read":
        read_warning_html = (
            '<div class="warning warn" style="margin-top:12px">'
            '🚨 Read 툴이 툴 비용 1위입니다 — 대용량 파일 반복 읽기를 의심하세요.'
            '</div>'
        )

    # Session rows
    session_rows_parts: list[str] = []
    for idx, ((s, sc), cost) in enumerate(zip(scored, session_costs)):
        total_in = s["input_tokens"] + s["cache_read_tokens"]
        hit = sc["cache_hit_ratio"]
        started = s["first_ts"].strftime("%Y-%m-%d %H:%M") if s["first_ts"] else "—"
        score = sc["total"]
        pill_cls = "pill-good" if score >= 75 else ("pill-warn" if score >= 50 else "pill-bad")
        warns = warnings_per_session[idx]
        warn_chips = " ".join(
            f"<span class='pill {'pill-bad' if w['level']=='critical' else 'pill-warn'}'>{html.escape(w['code'])}</span>"
            for w in warns
        ) or "<span class='muted'>—</span>"
        session_rows_parts.append(
            f"<tr><td><code>{html.escape(s['session_id'][:8])}</code></td>"
            f"<td>{html.escape(s['model'] or '?')}</td>"
            f"<td class='muted'>{html.escape(started)}</td>"
            f"<td style='text-align:right'>{s['input_tokens']:,}</td>"
            f"<td style='text-align:right'>{s['output_tokens']:,}</td>"
            f"<td style='text-align:right'>{hit:.0%}</td>"
            f"<td style='text-align:right'>${cost:.2f}</td>"
            f"<td style='text-align:right'><span class='pill {pill_cls}'>{score:.0f}</span></td>"
            f"<td>{warn_chips}</td></tr>"
        )
    session_rows_html = "\n".join(session_rows_parts) or "<tr><td colspan='9' class='muted'>No sessions.</td></tr>"

    # Warnings list (deduped by code)
    seen_codes: set[str] = set()
    warn_blocks: list[str] = []
    for warns in warnings_per_session:
        for w in warns:
            if w["code"] in seen_codes:
                continue
            seen_codes.add(w["code"])
            css = "warning" if w["level"] == "critical" else "warning warn"
            warn_blocks.append(f'<div class="{css}">{html.escape(w["message"])}</div>')
    warnings_html = "\n".join(warn_blocks) or '<div class="muted">No anti-patterns detected.</div>'

    return HTML_TEMPLATE.format(
        repo=html.escape(repo),
        days=days,
        session_count=len(scored),
        repos_named=len({s["repo"] for s, _ in scored}),
        total_cost=total_cost,
        total_tokens=total_tokens,
        avg_score=avg_score,
        avg_cache=avg_cache,
        avg_density=avg_density,
        avg_redundancy=avg_redundancy,
        avg_economy=avg_economy,
        avg_cache_hit=avg_cache_hit,
        repo_rows=repo_rows_html,
        tool_rows=tool_rows_html,
        read_warning_html=read_warning_html,
        session_rows=session_rows_html,
        warnings_html=warnings_html,
        estimated_savings=estimated,
        css=CSS,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Token efficiency analyzer + HTML dashboard.")
    parser.add_argument("--repo", required=True, help="Repository name to filter (matches basename of cwd).")
    parser.add_argument("--days", type=int, default=30, help="Look-back window in days (default 30).")
    parser.add_argument("--logs-dir", default="logs", help="Logs root directory (default: ./logs).")
    parser.add_argument("--out", default=None, help="Output HTML path (default: token-dashboard-<repo>-<days>d.html).")
    args = parser.parse_args(argv)

    logs_dir = Path(args.logs_dir).resolve()
    files = discover_logs(logs_dir)
    if not files:
        print(f"[error] No JSONL logs found under {logs_dir}/(claude-code|codex)/", file=sys.stderr)
        return 2

    sessions: list[dict] = []
    for p in files:
        s = aggregate_session(p)
        if s is not None:
            sessions.append(s)

    selected = filter_sessions(sessions, args.repo, args.days)
    if not selected:
        print(f"[warn] No sessions matched repo='{args.repo}' within {args.days} days.", file=sys.stderr)

    scored: list[tuple[dict, dict]] = [(s, score_session(s)) for s in selected]
    warnings_per_session = [evaluate_warnings(s, sc) for s, sc in scored]
    estimated = estimated_savings(selected, scored)

    html_out = render_dashboard(
        repo=args.repo,
        days=args.days,
        sessions=selected,
        scored=scored,
        warnings_per_session=warnings_per_session,
        estimated=estimated,
    )

    out_path = Path(args.out) if args.out else Path(f"token-dashboard-{args.repo}-{args.days}d.html")
    out_path.write_text(html_out, encoding="utf-8")

    # Console summary
    total_cost = sum(
        cost_usd(
            s["model"],
            input_tokens=s["input_tokens"],
            output_tokens=s["output_tokens"],
            cache_write_tokens=s["cache_write_tokens"],
            cache_read_tokens=s["cache_read_tokens"],
        )
        for s in selected
    )
    print(f"[ok] sessions={len(selected)}  files_scanned={len(files)}  "
          f"total_cost=${total_cost:.2f}  estimated_savings=${estimated:.2f}")
    print(f"[ok] dashboard -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())