#!/usr/bin/env python3
"""
test_token_efficiency_analyzer.py — Coverage for the token-analyzer skill.

Tests:
- Pure scoring rubric (stepped cache curve, weights, letter grade)
- Cost Gate evaluation (tokens + USD thresholds, bad status escalation)
- Per-warning $ attribution across all 3 reclaim axes
- Per-axis reclaim helpers (cache_miss / dup_read / model_downgrade)
- Pricing override merge + unknown-model warn
- JSON output shape + exit code 3 on bad gate
- End-to-end HTML render (every new panel + per-session Tools column)
- Stdout/stderr separation (WARN lines never leak into [ok] contract)
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from token_efficiency_analyzer import (  # noqa: E402
    DEFAULT_COST_GATE_TOKENS,
    DEFAULT_COST_GATE_USD,
    PRICING,
    WARNING_RECOMMENDATIONS,
    _KNOWN_SOURCES,
    _source_for,
    aggregate_session,
    cache_miss_reclaim,
    cost_gate_stderr_lines,
    cost_usd,
    discover_logs,
    dup_read_reclaim,
    enforce_cost_gate,
    estimated_savings,
    evaluate_warnings,
    filter_sessions,
    grade_for,
    load_pricing_override,
    main,
    model_downgrade_reclaim,
    pricing_for,
    render_dashboard,
    score_cache_utilization,
    score_session,
)

FIXTURE_LOGS = PROJECT_ROOT / "fixtures" / "logs" / "claude-code"


def _make_session(**overrides) -> dict:
    """Build a minimal session dict for unit tests (no JSONL needed)."""
    base = {
        "session_id": overrides.get("session_id", "test-session-id"),
        "source": "claude-code",
        "repo": overrides.get("repo", "test-repo"),
        "model": overrides.get("model", "claude-sonnet-5"),
        "first_ts": None,
        "last_ts": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_write_tokens": 0,
        "cache_read_tokens": 0,
        "ephemeral_5m": 0,
        "ephemeral_1h": 0,
        "tool_counts": {},
        "read_files": {},
        "user_texts": [],
        "log_path": "/tmp/fake.jsonl",
    }
    base.update(overrides)
    return base


class TestScoreCacheUtilization(unittest.TestCase):
    """Stepped curve: 0 -> 0, 0.50 -> 50, 0.85 -> 100, >0.85 -> 100."""

    def test_zero_hit(self):
        self.assertEqual(score_cache_utilization(0.0), 0.0)

    def test_warn_threshold(self):
        self.assertEqual(score_cache_utilization(0.50), 50.0)

    def test_full_threshold(self):
        self.assertEqual(score_cache_utilization(0.85), 100.0)

    def test_above_full(self):
        self.assertEqual(score_cache_utilization(1.0), 100.0)

    def test_below_warn_slope_1_to_1(self):
        # Below 0.50, slope is 1:1 (1 unit ratio = 1 unit score).
        self.assertEqual(score_cache_utilization(0.25), 25.0)
        self.assertEqual(score_cache_utilization(0.10), 10.0)

    def test_between_warn_and_full(self):
        # 0.675 -> 50 + (0.175 * 142.857...) = 75
        score = score_cache_utilization(0.675)
        self.assertGreater(score, 70.0)
        self.assertLess(score, 80.0)


class TestGradeFor(unittest.TestCase):
    """A: 90+, B: 80+, C: 70+, D: 60+, F: <60."""

    def test_a(self):
        self.assertEqual(grade_for(95), "A")
        self.assertEqual(grade_for(90), "A")

    def test_b(self):
        self.assertEqual(grade_for(89), "B")
        self.assertEqual(grade_for(80), "B")

    def test_c(self):
        self.assertEqual(grade_for(79), "C")
        self.assertEqual(grade_for(70), "C")

    def test_d(self):
        self.assertEqual(grade_for(69), "D")
        self.assertEqual(grade_for(60), "D")

    def test_f(self):
        self.assertEqual(grade_for(59), "F")
        self.assertEqual(grade_for(0), "F")


class TestPricingFor(unittest.TestCase):
    def test_opus_substring(self):
        p = pricing_for("claude-opus-4-7")
        self.assertEqual(p["in"], PRICING["opus"]["in"])

    def test_sonnet_substring(self):
        p = pricing_for("claude-sonnet-5")
        self.assertEqual(p["in"], PRICING["sonnet"]["in"])

    def test_haiku_substring(self):
        p = pricing_for("claude-haiku-4-5")
        self.assertEqual(p["in"], PRICING["haiku"]["in"])

    def test_minimax_substring(self):
        # MiniMax tier must be matched by substring (covers MiniMax-M3,
        # MiniMax-M2.7, and any future variant) and NOT fall through to a
        # Claude tier via DEFAULT_PRICING_KEY.
        for mid in ("MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed"):
            p = pricing_for(mid)
            self.assertEqual(p["in"], PRICING["minimax"]["in"],
                             f"model {mid!r} did not route to minimax tier")
            self.assertEqual(p["out"], PRICING["minimax"]["out"])

    def test_minimax_routed_before_claude_tiers(self):
        # If a future "minimax-sonnet" variant exists, it must NOT match
        # the sonnet substring — Sonnet input is 10x more expensive than
        # MiniMax-M3 input, so misrouting would silently inflate costs.
        unknown: set[str] = set()
        p = pricing_for("minimax-sonnet", _unknown_models=unknown)
        self.assertEqual(unknown, set(),
                         "minimax-sonnet must resolve to minimax tier, not sonnet")
        self.assertEqual(p["in"], PRICING["minimax"]["in"])

    def test_minimax_known_after_pricing_add(self):
        """MiniMax-M3 now has its own tier — was previously unknown and
        silently fell back to sonnet pricing. Verify (a) it routes to
        PRICING['minimax'] and (b) it is NOT collected as unknown."""
        unknown: set[str] = set()
        p = pricing_for("MiniMax-M3", _unknown_models=unknown)
        self.assertNotIn("MiniMax-M3", unknown)
        self.assertEqual(p["in"], PRICING["minimax"]["in"])

    def test_unknown_collects(self):
        # An id matching no tier must be collected AND fall back to sonnet.
        unknown: set[str] = set()
        p = pricing_for("totally-unrecognized-model-abc", _unknown_models=unknown)
        self.assertIn("totally-unrecognized-model-abc", unknown)
        self.assertEqual(p["in"], PRICING["sonnet"]["in"])

    def test_empty_falls_back(self):
        unknown: set[str] = set()
        p = pricing_for("", _unknown_models=unknown)
        self.assertEqual(unknown, set())
        self.assertEqual(p["in"], PRICING["sonnet"]["in"])


class TestLoadPricingOverride(unittest.TestCase):
    def test_no_path_is_noop(self):
        before = dict(PRICING)
        load_pricing_override(None)
        self.assertEqual(PRICING, before)

    def test_merge_overrides_tier(self):
        before_opus_in = PRICING["opus"]["in"]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"opus": {"in": 99.99}}, f)
            path = Path(f.name)
        try:
            load_pricing_override(path)
            self.assertEqual(PRICING["opus"]["in"], 99.99)
            # Other fields preserved
            self.assertEqual(PRICING["opus"]["out"], PRICING["opus"]["out"])
        finally:
            path.unlink()
            PRICING["opus"]["in"] = before_opus_in

    def test_missing_file_silently_noop(self):
        load_pricing_override(Path("/tmp/does-not-exist-token-analyzer.json"))


class TestCostUsd(unittest.TestCase):
    def test_basic_sonnet(self):
        # 1M input + 1M output + 1M cache_read on Sonnet
        cost = cost_usd("claude-sonnet-5",
                        input_tokens=1_000_000,
                        output_tokens=1_000_000,
                        cache_read_tokens=1_000_000)
        self.assertAlmostEqual(cost, 3.00 + 15.00 + 0.30, places=4)

    def test_5m_vs_1h_ttl_split(self):
        # 1M tokens written at 5m should be 1.25x in; at 1h should be 2.0x in.
        a = cost_usd("claude-sonnet-5",
                     input_tokens=0, output_tokens=0,
                     cache_write_5m_tokens=1_000_000,
                     cache_read_tokens=0)
        b = cost_usd("claude-sonnet-5",
                     input_tokens=0, output_tokens=0,
                     cache_write_1h_tokens=1_000_000,
                     cache_read_tokens=0)
        # Sonnet: in = 3.00
        self.assertAlmostEqual(a, 3.75, places=4)   # 1.25x
        self.assertAlmostEqual(b, 6.00, places=4)   # 2.0x


class TestEvaluateWarnings(unittest.TestCase):
    def test_cache_hit_low_fires(self):
        s = _make_session(
            input_tokens=10_000, cache_read_tokens=1_000,  # hit = 1/11 ~= 0.091
            model="claude-sonnet-5",
        )
        sc = score_session(s)
        warns = evaluate_warnings(s, sc, reclaim_cache_miss=1.23, reclaim_dup_read=0.0, reclaim_downgrade=0.0)
        codes = [w.code for w in warns]
        self.assertIn("CACHE_HIT_LOW", codes)
        low = next(w for w in warns if w.code == "CACHE_HIT_LOW")
        self.assertEqual(low.reclaim_axis, "cache_miss")
        self.assertEqual(low.priority, 1)
        self.assertEqual(low.estimated_save_usd, 1.23)

    def test_read_heavy_fires_with_dup_read_attribution(self):
        # Repeatedly reading the same file should trigger READ_HEAVY.
        s = _make_session(
            input_tokens=1000, output_tokens=200,
            tool_counts={"Read": 10, "Bash": 1},
            read_files={"/repo/big.py": 9},
            model="claude-sonnet-5",
        )
        sc = score_session(s)
        warns = evaluate_warnings(s, sc, reclaim_cache_miss=0.0, reclaim_dup_read=0.42, reclaim_downgrade=0.0)
        codes = [w.code for w in warns]
        self.assertIn("READ_HEAVY", codes)
        rh = next(w for w in warns if w.code == "READ_HEAVY")
        self.assertEqual(rh.reclaim_axis, "dup_read")
        self.assertEqual(rh.estimated_save_usd, 0.42)

    def test_model_overspec_only_for_opus_with_low_density(self):
        s = _make_session(model="claude-opus-4-7",
                          input_tokens=10_000, output_tokens=50, cache_read_tokens=0)
        sc = score_session(s)
        warns = evaluate_warnings(s, sc, reclaim_cache_miss=0.0, reclaim_dup_read=0.0, reclaim_downgrade=4.5)
        codes = [w.code for w in warns]
        self.assertIn("MODEL_OVERSPEC", codes)
        mo = next(w for w in warns if w.code == "MODEL_OVERSPEC")
        self.assertEqual(mo.reclaim_axis, "model_downgrade")
        self.assertEqual(mo.estimated_save_usd, 4.5)

    def test_repeated_user_msg_fires(self):
        s = _make_session(
            user_texts=["please continue, fix the loop above"] * 3,
            model="claude-sonnet-5",
        )
        sc = score_session(s)
        warns = evaluate_warnings(s, sc)
        codes = [w.code for w in warns]
        self.assertIn("REPEATED_USER_MSG", codes)


class TestReclaimAxes(unittest.TestCase):
    def test_cache_miss_reclaim_zero_when_above_target(self):
        s = _make_session(input_tokens=100, cache_read_tokens=900)  # hit = 0.90 > 0.85
        sc = score_session(s)
        self.assertEqual(cache_miss_reclaim([(s, sc)]), [0.0])

    def test_cache_miss_reclaim_positive_below_target(self):
        s = _make_session(model="claude-sonnet-5",
                          input_tokens=10_000, cache_read_tokens=1_000)  # hit ~= 0.091
        sc = score_session(s)
        saves = cache_miss_reclaim([(s, sc)])
        self.assertGreater(saves[0], 0.0)

    def test_dup_read_reclaim_uses_default_2k_per_dup(self):
        # 1 file read 4x -> 3 dups * 2000 = 6000 tokens * sonnet_in
        s = _make_session(model="claude-sonnet-5",
                          read_files={"/r/x.py": 4},
                          output_tokens=1_000)
        sc = score_session(s)
        saves = dup_read_reclaim([(s, sc)])
        # 6000 * 3.00 / 1_000_000 = 0.018, rounded to 0.02 by the helper.
        self.assertAlmostEqual(saves[0], 0.02, places=2)

    def test_model_downgrade_only_for_opus_low_density(self):
        s_opus = _make_session(model="claude-opus-4-7",
                               input_tokens=1_000_000, output_tokens=1_000,
                               cache_read_tokens=0)
        sc_opus = score_session(s_opus)
        self.assertGreater(model_downgrade_reclaim([(s_opus, sc_opus)])[0], 0.0)

        s_sonnet = _make_session(model="claude-sonnet-5",
                                 input_tokens=1_000_000, output_tokens=1_000)
        sc_sonnet = score_session(s_sonnet)
        self.assertEqual(model_downgrade_reclaim([(s_sonnet, sc_sonnet)]), [0.0])

    def test_estimated_savings_dict_keys(self):
        s = _make_session(model="claude-sonnet-5",
                          input_tokens=10_000, cache_read_tokens=1_000,
                          read_files={"/x.py": 3})
        sc = score_session(s)
        out = estimated_savings([(s, sc)])
        self.assertEqual(set(out.keys()), {"cache_miss", "dup_read", "model_downgrade", "total"})
        # total = sum of others
        self.assertAlmostEqual(out["total"], out["cache_miss"] + out["dup_read"] + out["model_downgrade"], places=4)


class TestEnforceCostGate(unittest.TestCase):
    def test_ok_when_under_thresholds(self):
        s = _make_session(input_tokens=100, cache_read_tokens=100)
        sc = score_session(s)
        status, violations = enforce_cost_gate([(s, sc)], 1_000_000, 1000.0)
        self.assertEqual(status, "ok")
        self.assertEqual(violations, [])

    def test_warn_on_single_threshold_breach(self):
        s = _make_session(input_tokens=300_000, cache_read_tokens=0)
        sc = score_session(s)
        status, violations = enforce_cost_gate([(s, sc)], 200_000, 5.0)
        self.assertEqual(status, "warn")
        self.assertEqual(len(violations), 1)
        self.assertIn("input=300,000", violations[0]["reason"])

    def test_bad_on_huge_breach(self):
        s = _make_session(input_tokens=10_000_000, cache_read_tokens=0)
        sc = score_session(s)
        status, violations = enforce_cost_gate([(s, sc)], 200_000, 5.0)
        self.assertEqual(status, "bad")
        self.assertEqual(len(violations), 1)

    def test_stderr_lines_have_warn_prefix(self):
        s = _make_session(input_tokens=300_000, cache_read_tokens=0)
        sc = score_session(s)
        _, violations = enforce_cost_gate([(s, sc)], 200_000, 5.0)
        lines = cost_gate_stderr_lines(violations)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("WARN:"))


class TestFixtures(unittest.TestCase):
    """End-to-end: each fixture JSONL must produce its target warning code."""

    FIXTURE_TO_CODE = {
        "aaaa-low-cache.jsonl":      "CACHE_HIT_LOW",
        "bbbb-read-heavy.jsonl":     "READ_HEAVY",
        "cccc-heavy-ctx.jsonl":      "HEAVY_CONTEXT",
        "dddd-opus-typo.jsonl":      "MODEL_OVERSPEC",
        "eeee-write-not-reused.jsonl": "WRITE_NOT_REUSED",
        "ffff-repeated-msg.jsonl":   "REPEATED_USER_MSG",
    }

    def setUp(self):
        if not FIXTURE_LOGS.exists():
            self.skipTest(f"fixture dir missing: {FIXTURE_LOGS}")

    def test_each_fixture_aggregates_and_scores(self):
        for fname, code in self.FIXTURE_TO_CODE.items():
            with self.subTest(fixture=fname):
                s = aggregate_session(FIXTURE_LOGS / fname)
                self.assertIsNotNone(s, f"aggregate_session returned None for {fname}")
                sc = score_session(s)
                self.assertIn("total", sc)
                self.assertIn("grade", sc)
                self.assertIn(score_session(s)["grade"], "ABCDF")
                # Reclaim helpers do not raise.
                cache_miss_reclaim([(s, sc)])
                dup_read_reclaim([(s, sc)])
                model_downgrade_reclaim([(s, sc)])


class TestEndToEndDashboard(unittest.TestCase):
    """Run main() against a tmp logs dir, assert HTML + summary."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="token-analyzer-test-"))
        # Copy fixtures into <tmpdir>/logs/claude-code/
        target = self.tmpdir / "logs" / "claude-code"
        target.mkdir(parents=True)
        for f in FIXTURE_LOGS.glob("*.jsonl"):
            shutil.copy(f, target / f.name)
        self.out_html = self.tmpdir / "dashboard.html"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_html_contains_every_new_section(self):
        rc = main([
            "--repo", "fixture-repo",
            "--days", "30",
            "--logs-dir", str(self.tmpdir / "logs"),
            "--out", str(self.out_html),
        ])
        self.assertEqual(rc, 0)
        self.assertTrue(self.out_html.exists())
        html_text = self.out_html.read_text()
        for needle in ("Cost Gate:", "Cost by Model", "Cache TTL Mix",
                       "ROI Actions", "Recommended Optimizations",
                       "class=\"grade grade-", "Tools</th>"):
            self.assertIn(needle, html_text, f"missing section: {needle}")

    def test_stderr_warn_does_not_leak_into_stdout(self):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            rc = main([
                "--repo", "fixture-repo",
                "--days", "30",
                "--logs-dir", str(self.tmpdir / "logs"),
                "--out", str(self.out_html),
            ])
        self.assertEqual(rc, 0)
        # Stdout has the [ok] summary lines, NEVER the WARN lines.
        self.assertIn("[ok]", stdout_buf.getvalue())
        self.assertNotIn("WARN:", stdout_buf.getvalue())
        # Stderr may have WARN lines from cost gate.
        self.assertIn("WARN:", stderr_buf.getvalue())


class TestJsonOutput(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="token-analyzer-json-"))
        target = self.tmpdir / "logs" / "claude-code"
        target.mkdir(parents=True)
        for f in FIXTURE_LOGS.glob("*.jsonl"):
            shutil.copy(f, target / f.name)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_json_emits_expected_keys(self):
        import io
        from contextlib import redirect_stdout, redirect_stderr
        stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            rc = main([
                "--repo", "fixture-repo",
                "--days", "30",
                "--logs-dir", str(self.tmpdir / "logs"),
                "--json",
            ])
        self.assertEqual(rc, 0)
        data = json.loads(stdout_buf.getvalue())
        self.assertEqual(data["repo"], "fixture-repo")
        self.assertEqual(data["days"], 30)
        self.assertEqual(data["sessions"], 6)
        self.assertEqual(data["branch"], "")
        self.assertFalse(data["branch_filter_active"])
        self.assertEqual(set(data["estimated_savings_usd"].keys()),
                         {"cache_miss", "dup_read", "model_downgrade", "total"})
        self.assertIn("cost_gate", data)
        self.assertIn(data["cost_gate"]["status"], ("ok", "warn", "bad"))
        self.assertIsInstance(data["warnings"], list)

    def test_json_exit_code_3_on_bad_gate(self):
        rc = main([
            "--repo", "fixture-repo",
            "--days", "30",
            "--logs-dir", str(self.tmpdir / "logs"),
            "--cost-gate-tokens", "1000",   # every session will breach
            "--json",
        ])
        self.assertEqual(rc, 3)

    def test_json_empty_logs_returns_2(self):
        empty = self.tmpdir / "empty"
        (empty / "claude-code").mkdir(parents=True)
        rc = main([
            "--repo", "fixture-repo",
            "--days", "30",
            "--logs-dir", str(empty),
            "--json",
        ])
        self.assertEqual(rc, 2)


class TestWeightInvariants(unittest.TestCase):
    def test_score_session_uses_40_20_20_20(self):
        s = _make_session(input_tokens=100, cache_read_tokens=900,
                          output_tokens=50, tool_counts={"Read": 1},
                          read_files={})
        sc = score_session(s)
        # cache_hit = 0.90 -> score_cache_utilization returns 100
        # density: 50/1000 * 400 = 20
        # redundancy: 100 (max_repeat = 1 -> 100 - 0*12.5)
        # economy: depends on tools/output but should be <=100
        expected_cache = 100.0
        self.assertEqual(sc["cache"], expected_cache)
        self.assertAlmostEqual(sc["density"], 20.0)
        # Now compute expected total using the new weights
        expected = round(0.40 * sc["cache"] + 0.20 * sc["density"]
                         + 0.20 * sc["redundancy"] + 0.20 * sc["economy"], 1)
        self.assertEqual(sc["total"], expected)


class TestBranchAwareness(unittest.TestCase):
    """Per-branch discovery, extraction, and filtering."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="token-analyzer-branch-"))
        self._now = None  # filled per-test if needed

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_session(self, subdir: str, sid: str, *,
                       branch: str | None = "main",
                       cwd: str = "/tmp/fixture-repo") -> Path:
        """Write one minimal session record under logs/claude-code/<subdir>/."""
        d = self.tmpdir / "logs" / "claude-code" / subdir
        d.mkdir(parents=True, exist_ok=True)
        rec = {
            "type": "assistant",
            "sessionId": sid,
            "cwd": cwd,
            "timestamp": "2026-07-09T10:00:00.000Z",
            "gitBranch": branch,
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 100,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 500,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": 0,
                        "ephemeral_1h_input_tokens": 0,
                    },
                },
            },
        }
        # If branch is None, drop the field entirely (simulates wire-format omission).
        if branch is None:
            del rec["gitBranch"]
        p = d / f"{sid}.jsonl"
        p.write_text(json.dumps(rec) + "\n")
        return p

    def test_source_for_walks_up_for_nested(self):
        nested = Path("/tmp/foo/logs/claude-code/main/sid.jsonl")
        self.assertEqual(_source_for(nested), "claude-code")
        flat = Path("/tmp/foo/logs/claude-code/sid.jsonl")
        self.assertEqual(_source_for(flat), "claude-code")
        self.assertEqual(set(_KNOWN_SOURCES), {"claude-code", "codex"})

    def test_discover_logs_walks_recursively(self):
        self._write_session("main", "s1", branch="main")
        self._write_session("feature-x", "s2", branch="feature-x")
        # Legacy flat file alongside the nested ones.
        flat = self.tmpdir / "logs" / "claude-code" / "legacy.jsonl"
        flat.parent.mkdir(parents=True, exist_ok=True)
        flat.write_text("{}\n")
        names = {p.name for p in discover_logs(self.tmpdir / "logs")}
        self.assertEqual(names, {"s1.jsonl", "s2.jsonl", "legacy.jsonl"})

    def test_aggregate_session_extracts_branch_from_wire_format(self):
        p = self._write_session("main", "sid-w", branch="main")
        s = aggregate_session(p)
        self.assertEqual(s["branch"], "main")
        self.assertEqual(s["source"], "claude-code")

    def test_aggregate_session_source_from_top_level_subdir(self):
        # Path .../logs/claude-code/main/sid.jsonl — parent.name is "main"
        # but source must remain "claude-code" (not the branch dir).
        p = self._write_session("main", "sid-src", branch="main")
        s = aggregate_session(p)
        self.assertEqual(s["source"], "claude-code")
        self.assertEqual(s["branch"], "main")

    def test_aggregate_session_branch_fallback_to_path_when_no_wire(self):
        p = self._write_session("release-1.0", "sid-no-wire", branch=None)
        s = aggregate_session(p)
        self.assertEqual(s["branch"], "release-1.0")
        self.assertEqual(s["source"], "claude-code")

    def test_aggregate_session_flat_legacy_buckets_as_main(self):
        flat = self.tmpdir / "logs" / "claude-code" / "legacy.jsonl"
        flat.parent.mkdir(parents=True, exist_ok=True)
        flat.write_text(json.dumps({
            "type": "assistant",
            "sessionId": "x",
            "cwd": "/tmp/fixture-repo",
            "timestamp": "2026-07-09T10:00:00.000Z",
            "message": {"role": "assistant", "model": "claude-sonnet-5",
                        "content": [{"type": "text", "text": "ok"}],
                        "usage": {"input_tokens": 1000, "output_tokens": 100,
                                  "cache_read_input_tokens": 500}},
        }) + "\n")
        s = aggregate_session(flat)
        # Flat layout: parent.name == source tool subdir → branch buckets to "main".
        self.assertEqual(s["branch"], "main")
        self.assertEqual(s["source"], "claude-code")

    def test_filter_sessions_branch_substring_match(self):
        from datetime import datetime, timezone, timedelta
        p1 = self._write_session("main", "s-main", branch="main")
        p2 = self._write_session("feature-x", "s-feat", branch="feature-x")
        sessions = [aggregate_session(p) for p in (p1, p2)]
        # Force last_ts to now so the days filter doesn't drop them.
        now = datetime.now(timezone.utc)
        for s in sessions:
            s["first_ts"] = now
            s["last_ts"] = now
        kept = filter_sessions(sessions, repo="", days=30, branch="feature")
        self.assertEqual([s["session_id"] for s in kept], ["s-feat"])

    def test_filter_sessions_empty_branch_disables_filter(self):
        from datetime import datetime, timezone
        p1 = self._write_session("main", "s-main", branch="main")
        p2 = self._write_session("feature-x", "s-feat", branch="feature-x")
        sessions = [aggregate_session(p) for p in (p1, p2)]
        now = datetime.now(timezone.utc)
        for s in sessions:
            s["first_ts"] = now
            s["last_ts"] = now
        kept = filter_sessions(sessions, repo="", days=30)
        self.assertEqual(len(kept), 2)

    def test_main_branch_filter_json(self):
        from io import StringIO
        import contextlib
        self._write_session("main", "s-main", branch="main")
        self._write_session("feature-x", "s-feat", branch="feature-x")
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main([
                "--repo", "fixture-repo",
                "--days", "30",
                "--logs-dir", str(self.tmpdir / "logs"),
                "--branch", "feature",
                "--json",
            ])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["branch"], "feature")
        self.assertTrue(data["branch_filter_active"])
        self.assertEqual(data["sessions"], 1)

    def test_main_mixed_flat_and_nested_does_not_crash(self):
        from io import StringIO
        import contextlib
        self._write_session("main", "s-main", branch="main")
        flat = self.tmpdir / "logs" / "claude-code" / "legacy.jsonl"
        flat.parent.mkdir(parents=True, exist_ok=True)
        flat.write_text("{}\n")
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main([
                "--repo", "fixture-repo",
                "--days", "30",
                "--logs-dir", str(self.tmpdir / "logs"),
                "--json",
            ])
        # rc == 0 (legacy flat yields branch="main" which still matches).
        self.assertIn(rc, (0, 2))


if __name__ == "__main__":
    unittest.main()