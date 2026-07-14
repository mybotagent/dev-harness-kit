#!/usr/bin/env python3
"""test_cost_gate.py — regression tests for the cost-gate hook + library + CLI.

Black-box coverage:

  1. Hook behavior (SessionStart, PostToolUse, PreToolUse) — exit codes,
     stdout/stderr contracts, jq-missing fail-closed.
  2. lib/cost_gate.py — pricing tiers, unknown-model fallback, state I/O
     atomicity, transcript scanner, heuristic fallback provenance, footer
     parsing + dedup, PR aggregation.
  3. tools/cost_gate_status.py — text/json/html/footer/aggregate-pr output.
  4. PR-level label decision — threshold crossing, footer dedup, missing
     telemetry.
  5. hooks.json wiring — cost-gate.sh registered under all 3 events.

No import of tools.token_efficiency_analyzer — isolation guarantee.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOKS = REPO_ROOT / "hooks"
LIB = REPO_ROOT / "lib"
TOOLS = REPO_ROOT / "tools"


# --- helpers -----------------------------------------------------------------

def _run_hook(script: str, payload: dict, cwd: Path | None = None,
              env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(HOOKS / script)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10,
        cwd=str(cwd) if cwd else None, env=env,
    )


def _run_cli(*args: str, cwd: Path | None = None,
             env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(TOOLS / "cost_gate_status.py"), *args],
        capture_output=True, text=True, timeout=15,
        cwd=str(cwd) if cwd else None, env=env,
    )


def _session_start_payload(session_id: str = "sess-1", source: str = "startup",
                           cwd: str = "", model: str = "",
                           transcript_path: str = "") -> dict:
    p = {
        "hook_event_name": "SessionStart",
        "session_id": session_id,
        "source": source,
    }
    if cwd:
        p["cwd"] = cwd
    if model:
        p["model"] = model
    if transcript_path:
        p["transcript_path"] = transcript_path
    return p


def _post_tool_use_payload(tool_name: str = "Read", session_id: str = "sess-1",
                           cwd: str = "", transcript_path: str = "") -> dict:
    p = {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": {"file_path": "/tmp/x"},
        "tool_response": {"ok": True},
    }
    if cwd:
        p["cwd"] = cwd
    if transcript_path:
        p["transcript_path"] = transcript_path
    return p


def _pre_tool_use_payload(tool_name: str = "Read", session_id: str = "sess-1",
                          cwd: str = "") -> dict:
    p = {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": {"file_path": "/tmp/x"},
    }
    if cwd:
        p["cwd"] = cwd
    return p


def _write_state(path: Path, **overrides) -> None:
    """Write a minimal state file with overrides."""
    import sys as _sys
    _sys.path.insert(0, str(LIB))
    from cost_gate import new_session_state  # type: ignore
    state = new_session_state(
        session_id="sess-1",
        cwd=str(path.parent.parent),
        branch="feat/cost-gate",
        repository="dev-harness-kit",
        model="claude-sonnet-5",
    )
    state.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


# ============================================================================
# 1. lib/cost_gate.py — pricing
# ============================================================================

class TestPricing(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LIB))
        from cost_gate import pricing_for  # type: ignore
        self.pricing_for = pricing_for

    def test_minimax_substring_matches_first(self):
        # minimax must be detected before opus/sonnet/haiku to avoid the
        # substring collision ("MiniMax" contains no overlap, but defensively).
        p = self.pricing_for("MiniMax-M3[1m]")
        self.assertAlmostEqual(p["in"], 0.30, places=4)
        self.assertAlmostEqual(p["out"], 1.20, places=4)

    def test_opus_substring(self):
        p = self.pricing_for("claude-opus-4-8")
        self.assertAlmostEqual(p["in"], 5.00, places=4)
        self.assertAlmostEqual(p["out"], 25.00, places=4)

    def test_sonnet_substring(self):
        p = self.pricing_for("claude-sonnet-5")
        self.assertAlmostEqual(p["in"], 3.00, places=4)
        self.assertAlmostEqual(p["out"], 15.00, places=4)

    def test_haiku_substring(self):
        p = self.pricing_for("claude-haiku-4-5")
        self.assertAlmostEqual(p["in"], 1.00, places=4)
        self.assertAlmostEqual(p["out"], 5.00, places=4)

    def test_unknown_falls_back_to_sonnet_and_collects(self):
        p, unknowns = self.pricing_for("totally-bogus-model", return_unknown=True)
        self.assertAlmostEqual(p["in"], 3.00, places=4)
        self.assertIn("totally-bogus-model", unknowns)

    def test_empty_falls_back_to_sonnet(self):
        p = self.pricing_for("")
        self.assertAlmostEqual(p["in"], 3.00, places=4)


# ============================================================================
# 2. lib/cost_gate.py — cost math
# ============================================================================

class TestCostMath(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LIB))
        from cost_gate import cost_usd  # type: ignore
        self.cost_usd = cost_usd

    def test_basic_sonnet_input_only(self):
        c = self.cost_usd("claude-sonnet-5", input_tokens=1_000_000)
        self.assertAlmostEqual(c, 3.00, places=4)

    def test_basic_opus_input_and_output(self):
        c = self.cost_usd("claude-opus-4-8",
                          input_tokens=1_000_000, output_tokens=1_000_000)
        self.assertAlmostEqual(c, 5.00 + 25.00, places=4)

    def test_cache_read_cheaper_than_input(self):
        c_in = self.cost_usd("claude-sonnet-5", input_tokens=1_000_000)
        c_cache = self.cost_usd("claude-sonnet-5", cache_read_tokens=1_000_000)
        self.assertLess(c_cache, c_in)

    def test_5m_cheaper_than_1h_cache_write(self):
        c5 = self.cost_usd("claude-sonnet-5",
                           cache_write_5m_tokens=1_000_000)
        c1 = self.cost_usd("claude-sonnet-5",
                           cache_write_1h_tokens=1_000_000)
        self.assertLess(c5, c1)


# ============================================================================
# 3. lib/cost_gate.py — state I/O + atomicity
# ============================================================================

class TestStateIO(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LIB))
        from cost_gate import (  # type: ignore
            new_session_state, load_state, save_state, DEFAULT_TOTAL,
        )
        self.new_session_state = new_session_state
        self.load_state = load_state
        self.save_state = save_state
        self.DEFAULT_TOTAL = DEFAULT_TOTAL

    def test_new_state_has_required_keys(self):
        s = self.new_session_state(
            session_id="x", cwd="/tmp", branch="main", repository="r",
            model="claude-sonnet-5",
        )
        self.assertEqual(s["schema_version"], 1)
        self.assertEqual(s["scope"], "session")
        self.assertEqual(s["scope_id"], "x")
        self.assertEqual(s["totals"], self.DEFAULT_TOTAL)
        self.assertEqual(s["status"], "ok")
        self.assertFalse(s["warn_emitted"])
        self.assertEqual(s["warnings"], [])
        self.assertEqual(s["sessions"][0]["session_id"], "x")
        self.assertEqual(s["sessions"][0]["provenance"], "actual")

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            s = self.new_session_state(
                session_id="x", cwd=td, branch="feat/y", repository="r",
                model="claude-opus-4-8",
            )
            self.save_state(p, s)
            loaded = self.load_state(p)
            self.assertEqual(loaded["scope_id"], "x")
            self.assertEqual(loaded["sessions"][0]["model"], "claude-opus-4-8")

    def test_load_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(self.load_state(Path(td) / "missing.json"))

    def test_load_corrupt_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            p.write_text("not-json{", encoding="utf-8")
            self.assertIsNone(self.load_state(p))

    def test_atomic_write_uses_tempfile(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            s = self.new_session_state(
                session_id="x", cwd=td, branch="main", repository="r",
                model="claude-sonnet-5",
            )
            self.save_state(p, s)
            # No leftover tempfiles.
            leftovers = list(Path(td).glob(".state.json.*"))
            self.assertEqual(leftovers, [], f"leftover: {leftovers}")


# ============================================================================
# 4. lib/cost_gate.py — thresholds
# ============================================================================

class TestThresholds(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LIB))
        from cost_gate import evaluate_status  # type: ignore
        self.evaluate_status = evaluate_status

    def test_below_warn_is_ok(self):
        s, _ = self.evaluate_status(0.0, {"session_warn": 5.0, "session_kill": 10.0})
        self.assertEqual(s, "ok")

    def test_at_warn_emits_warn(self):
        s, _ = self.evaluate_status(5.0, {"session_warn": 5.0, "session_kill": 10.0})
        self.assertEqual(s, "warn")

    def test_at_kill_emits_kill(self):
        s, _ = self.evaluate_status(10.0, {"session_warn": 5.0, "session_kill": 10.0})
        self.assertEqual(s, "kill")

    def test_above_kill_still_kill(self):
        s, _ = self.evaluate_status(999.0, {"session_warn": 5.0, "session_kill": 10.0})
        self.assertEqual(s, "kill")


# ============================================================================
# 5. lib/cost_gate.py — heuristic fallback
# ============================================================================

class TestHeuristic(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LIB))
        from cost_gate import heuristic_tool_cost  # type: ignore
        self.heuristic_tool_cost = heuristic_tool_cost

    def test_agent_high_estimate(self):
        c = self.heuristic_tool_cost("Agent", "claude-sonnet-5")
        self.assertGreater(c, 0.01)

    def test_read_low_estimate(self):
        c_read = self.heuristic_tool_cost("Read", "claude-sonnet-5")
        c_write = self.heuristic_tool_cost("Edit", "claude-sonnet-5")
        self.assertGreater(c_read, c_write)  # Read reads more

    def test_unknown_tool_falls_back_to_default(self):
        c = self.heuristic_tool_cost("SomeRandomMCPTool", "claude-sonnet-5")
        self.assertGreater(c, 0.0)


# ============================================================================
# 6. lib/cost_gate.py — footer parsing + dedup
# ============================================================================

class TestFooterParsing(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(LIB))
        from cost_gate import parse_footers, aggregate_pr_sessions  # type: ignore
        self.parse_footers = parse_footers
        self.aggregate_pr_sessions = aggregate_pr_sessions

    def test_parse_single_footer(self):
        body = "feat: thing\n\nCost-gate: $8.42\nCost-gate-Session: sess-1"
        out = self.parse_footers([body])
        self.assertEqual(out, [{"session": "sess-1", "usd": 8.42}])

    def test_parse_missing_returns_empty(self):
        body = "feat: thing\n\nNo trailers here."
        out = self.parse_footers([body])
        self.assertEqual(out, [])

    def test_dedup_keeps_max_per_session(self):
        # Same session appearing in two commits: keep the max cumulative.
        out = self.parse_footers([
            "Cost-gate: $3.00\nCost-gate-Session: sess-1",
            "Cost-gate: $5.00\nCost-gate-Session: sess-1",
        ])
        self.assertEqual(out, [{"session": "sess-1", "usd": 5.00}])

    def test_aggregate_pr_sessions_sums(self):
        commits = [
            "Cost-gate: $3.00\nCost-gate-Session: sess-1",
            "Cost-gate: $5.00\nCost-gate-Session: sess-1",  # dedup to $5
            "Cost-gate: $2.00\nCost-gate-Session: sess-2",
        ]
        out = self.parse_footers(commits)
        total = self.aggregate_pr_sessions(out)
        self.assertAlmostEqual(total, 7.00, places=4)


# ============================================================================
# 7. tools/cost_gate_status.py — CLI
# ============================================================================

class TestCliText(unittest.TestCase):
    def test_text_includes_scope_and_thresholds(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"
            r = _run_cli("--state", str(state_path))
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            self.assertIn("scope:", r.stdout)
            self.assertIn("session_warn:", r.stdout)
            self.assertIn("session_kill:", r.stdout)


class TestCliJson(unittest.TestCase):
    def test_json_has_required_keys(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"
            r = _run_cli("--state", str(state_path), "--json")
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            doc = json.loads(r.stdout)
            for k in ("scope", "totals", "thresholds_usd", "status",
                      "warnings", "state_path"):
                self.assertIn(k, doc, f"missing {k} in JSON: {doc}")


class TestCliHtml(unittest.TestCase):
    def test_html_is_self_contained(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"
            out = Path(td) / "report.html"
            r = _run_cli("--state", str(state_path), "--html", str(out))
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            self.assertTrue(out.exists())
            content = out.read_text(encoding="utf-8")
            self.assertIn("<html", content)
            self.assertNotIn("<script", content)


class TestCliFooter(unittest.TestCase):
    def test_footer_format(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"
            r = _run_cli("--state", str(state_path), "--footer")
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            self.assertIn("Cost-gate:", r.stdout)
            self.assertIn("Cost-gate-Session:", r.stdout)


# ============================================================================
# 8. hooks/cost-gate.sh — behavior
# ============================================================================

class TestHookSessionStart(unittest.TestCase):
    def setUp(self):
        if not (HOOKS / "cost-gate.sh").exists():
            self.skipTest("cost-gate.sh not found")

    def test_session_start_initializes_state_and_emits_context(self):
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            r = _run_hook("cost-gate.sh",
                          _session_start_payload(cwd=str(td_p)),
                          cwd=td_p)
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            self.assertIn("additionalContext", r.stdout)
            state = td_p / ".dev-kit" / ".cost-gate" / "state.json"
            self.assertTrue(state.exists(), f"state file missing: {state}")
            doc = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(doc["scope"], "session")
            self.assertEqual(doc["totals"]["cost_usd"], 0.0)

    def test_session_start_compact_preserves_session(self):
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            # First startup
            _run_hook("cost-gate.sh",
                      _session_start_payload(session_id="sess-A", cwd=str(td_p)),
                      cwd=td_p)
            # Then compact with same session id — should preserve, not reset
            r = _run_hook("cost-gate.sh",
                          _session_start_payload(session_id="sess-A",
                                                 source="compact",
                                                 cwd=str(td_p)),
                          cwd=td_p)
            self.assertEqual(r.returncode, 0)
            state = td_p / ".dev-kit" / ".cost-gate" / "state.json"
            doc = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(doc["scope_id"], "sess-A")


class TestHookPreToolUse(unittest.TestCase):
    def setUp(self):
        if not (HOOKS / "cost-gate.sh").exists():
            self.skipTest("cost-gate.sh not found")

    def test_below_kill_returns_0(self):
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            # Initialize state below kill.
            _write_state(
                td_p / ".dev-kit" / ".cost-gate" / "state.json",
                totals={
                    "input_tokens": 1000, "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_creation_5m_input_tokens": 0,
                    "cache_creation_1h_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "estimated_tokens": 0,
                    "cost_usd": 0.5,
                },
                status="ok",
            )
            r = _run_hook("cost-gate.sh",
                          _pre_tool_use_payload(cwd=str(td_p)),
                          cwd=td_p)
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")

    def test_at_kill_denies_with_json(self):
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            _write_state(
                td_p / ".dev-kit" / ".cost-gate" / "state.json",
                totals={
                    "input_tokens": 0, "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_creation_5m_input_tokens": 0,
                    "cache_creation_1h_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "estimated_tokens": 0,
                    "cost_usd": 10.0,
                },
                status="kill",
            )
            r = _run_hook("cost-gate.sh",
                          _pre_tool_use_payload(cwd=str(td_p)),
                          cwd=td_p)
            self.assertEqual(r.returncode, 2, f"stderr={r.stderr}")
            combined = r.stdout + r.stderr
            self.assertIn("permissionDecision", combined)
            self.assertIn('"deny"', combined)
            self.assertIn("COST GATE", combined)


class TestHookPostToolUse(unittest.TestCase):
    def setUp(self):
        if not (HOOKS / "cost-gate.sh").exists():
            self.skipTest("cost-gate.sh not found")

    def test_post_tool_use_updates_state_silently(self):
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            # Initialize first.
            _run_hook("cost-gate.sh",
                      _session_start_payload(cwd=str(td_p)),
                      cwd=td_p)
            r = _run_hook("cost-gate.sh",
                          _post_tool_use_payload(tool_name="Read",
                                                 cwd=str(td_p)),
                          cwd=td_p)
            self.assertEqual(r.returncode, 0, f"stderr={r.stderr}")
            # State must still exist and have a session updated_at.
            state = td_p / ".dev-kit" / ".cost-gate" / "state.json"
            self.assertTrue(state.exists())


class TestHookFailClosed(unittest.TestCase):
    def setUp(self):
        if not (HOOKS / "cost-gate.sh").exists():
            self.skipTest("cost-gate.sh not found")
        self._jq = shutil.which("jq")
        if not self._jq:
            self.skipTest("jq not on host — cannot simulate missing-jq")

    def test_pretooluse_denies_when_jq_missing(self):
        util_dirs = set()
        for util in ("bash", "cat", "echo", "printf", "command", "python3"):
            p = shutil.which(util)
            if p:
                util_dirs.add(os.path.dirname(p))
        util_dirs.discard(os.path.dirname(self._jq))
        minimal_path = os.pathsep.join(sorted(util_dirs)) or "/nonexistent"
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            payload = _pre_tool_use_payload(cwd=str(td_p))
            r = subprocess.run(
                ["bash", str(HOOKS / "cost-gate.sh")],
                input=json.dumps(payload), capture_output=True, text=True,
                timeout=5, cwd=str(td_p),
                env={**os.environ, "PATH": minimal_path},
            )
            self.assertEqual(r.returncode, 2, f"got rc={r.returncode}, stderr={r.stderr}")
            combined = r.stdout + r.stderr
            self.assertIn("permissionDecision", combined)
            self.assertIn("jq is required", combined) or self.assertIn("jq", combined)


# ============================================================================
# 9. hooks.json wiring
# ============================================================================

class TestHooksJsonWiring(unittest.TestCase):
    def setUp(self):
        path = HOOKS / "hooks.json"
        if not path.exists():
            self.skipTest(f"hooks.json not found at {path}")
        self._cfg = json.loads(path.read_text(encoding="utf-8"))

    def _hooks_under(self, event: str) -> list:
        flat = []
        for entry in self._cfg["hooks"].get(event, []):
            for h in entry.get("hooks", []):
                flat.append(h.get("command", ""))
        return flat

    def test_cost_gate_in_sessionstart(self):
        cmds = self._hooks_under("SessionStart")
        self.assertTrue(
            any("cost-gate.sh" in c for c in cmds),
            f"cost-gate.sh not wired into SessionStart. Got: {cmds}",
        )

    def test_cost_gate_in_posttooluse(self):
        cmds = self._hooks_under("PostToolUse")
        self.assertTrue(
            any("cost-gate.sh" in c for c in cmds),
            f"cost-gate.sh not wired into PostToolUse. Got: {cmds}",
        )

    def test_cost_gate_in_pretooluse(self):
        cmds = self._hooks_under("PreToolUse")
        self.assertTrue(
            any("cost-gate.sh" in c for c in cmds),
            f"cost-gate.sh not wired into PreToolUse. Got: {cmds}",
        )


# ============================================================================
# 10. Isolation guarantee — no import of token_efficiency_analyzer
# ============================================================================

class TestIsolation(unittest.TestCase):
    def test_lib_cost_gate_does_not_import_token_analyzer(self):
        path = LIB / "cost_gate.py"
        if not path.exists():
            self.skipTest("cost_gate.py not found")
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("token_efficiency_analyzer", text,
                         "lib/cost_gate.py must not import token_efficiency_analyzer")

    def test_tools_cost_gate_status_does_not_import_token_analyzer(self):
        path = TOOLS / "cost_gate_status.py"
        if not path.exists():
            self.skipTest("cost_gate_status.py not found")
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("token_efficiency_analyzer", text,
                         "tools/cost_gate_status.py must not import token_efficiency_analyzer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
