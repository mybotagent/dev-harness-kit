#!/usr/bin/env python3
"""cost_gate_status.py — CLI + hook driver for the cost-gate subsystem.

Invoked by hooks/cost-gate.sh (driven by hook JSON on stdin) and by the
human-use /dev-kit:cost-gate skill (driven by CLI flags). Does not import
or share state with the post-hoc dashboard (different files, different
pricing table).

Modes (mutually exclusive):
  (default)        text status summary
  --json           machine-readable JSON to stdout
  --html PATH      write self-contained HTML report to PATH
  --footer         print two-line git-trailer block for commit messages
  --aggregate-pr   read PR commit bodies (stdin) + aggregate (test helper)

Hook modes (driven by stdin JSON):
  --hook-session-start
  --hook-post-tool-use
  --hook-pre-tool-use

Threshold overrides (env): DEV_KIT_COST_WARN_USD, DEV_KIT_COST_KILL_USD,
DEV_KIT_PR_COST_FLAG_USD. State path override (env): DEV_KIT_COST_GATE_STATE.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Resolve lib/ for cost_gate imports.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_LIB_DIR = _REPO_ROOT / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import cost_gate as cg  # noqa: E402
from atomic import now_iso  # noqa: E402


def _state_path(explicit: Optional[str], cwd: str) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("DEV_KIT_COST_GATE_STATE")
    if env:
        return Path(env)
    return cg.default_state_path(cwd)


def _detect_repo(cwd: str) -> Tuple[str, str]:
    """Best-effort git (repository, branch) detection; empty on failure."""
    repo = ""
    branch = ""
    try:
        cp = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if cp.returncode == 0:
            toplevel = cp.stdout.strip()
            repo = Path(toplevel).name
        cp = subprocess.run(
            ["git", "-C", cwd, "symbolic-ref", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if cp.returncode == 0:
            branch = cp.stdout.strip()
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        pass
    return repo, branch


# ---------------------------------------------------------------------------
# Hook modes
# ---------------------------------------------------------------------------

def _emit_session_start(payload: Dict[str, Any]) -> int:
    """SessionStart: initialize state, emit additionalContext, exit 0."""
    cwd = payload.get("cwd") or os.getcwd()
    sid = payload.get("session_id") or "unknown"
    source = payload.get("source") or "startup"
    model = payload.get("model") or ""
    transcript = payload.get("transcript_path") or ""
    repo, branch = _detect_repo(cwd)
    state_path = _state_path(None, cwd)
    state = cg.load_state(state_path)
    thresholds = cg.resolve_thresholds()
    if state is None or source == "startup" or not state.get("scope_id"):
        state = cg.new_session_state(
            session_id=sid, cwd=cwd, branch=branch or "unknown",
            repository=repo or "unknown", model=model,
            transcript_path=transcript, thresholds=thresholds,
        )
    else:
        # resume / clear / compact: keep state, refresh cursor + timestamps.
        state["cursor"]["transcript_path"] = transcript or state["cursor"].get("transcript_path", "")
        for s in state.get("sessions", []):
            if s.get("session_id") == sid:
                s["updated_at"] = now_iso()
                if model:
                    s["model"] = model
    cg.save_state(state_path, state)
    cost = float((state.get("totals") or {}).get("cost_usd", 0.0))
    warn = thresholds["session_warn"]
    ctx = (
        f"cost-gate: session initialized\n"
        f"  state: {state_path}\n"
        f"  warn: ${warn:.2f}  kill: ${thresholds['session_kill']:.2f}\n"
        f"  current: ${cost:.2f} (status={state.get('status', 'ok')})"
    )
    out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}
    sys.stdout.write(json.dumps(out))
    sys.stdout.write("\n")
    return 0


def _scan_transcript_delta(state: Dict[str, Any]) -> None:
    """Apply any new transcript usage to the running ledger."""
    cur = (state.get("cursor") or {})
    tpath = cur.get("transcript_path") or ""
    offset = int(cur.get("byte_offset") or 0)
    seen = list(cur.get("seen_ids") or [])
    scan = cg.scan_transcript(tpath, offset, seen)
    if scan.new_records == 0:
        return
    totals = state.setdefault("totals", dict(cg.DEFAULT_TOTAL))
    totals["input_tokens"] = totals.get("input_tokens", 0) + scan.delta_input
    totals["output_tokens"] = totals.get("output_tokens", 0) + scan.delta_output
    totals["cache_read_input_tokens"] = totals.get("cache_read_input_tokens", 0) + scan.delta_cache_read
    totals["cache_creation_input_tokens"] = totals.get("cache_creation_input_tokens", 0) + (
        scan.delta_cache_write_5m + scan.delta_cache_write_1h
    )
    totals["cache_creation_5m_input_tokens"] = totals.get("cache_creation_5m_input_tokens", 0) + scan.delta_cache_write_5m
    totals["cache_creation_1h_input_tokens"] = totals.get("cache_creation_1h_input_tokens", 0) + scan.delta_cache_write_1h
    model_for_cost = scan.model or (state.get("sessions") or [{}])[0].get("model") or "claude-sonnet-5"
    delta_cost = cg.cost_usd(
        model_for_cost,
        input_tokens=scan.delta_input,
        output_tokens=scan.delta_output,
        cache_write_5m_tokens=scan.delta_cache_write_5m,
        cache_write_1h_tokens=scan.delta_cache_write_1h,
        cache_read_tokens=scan.delta_cache_read,
    )
    totals["cost_usd"] = float(totals.get("cost_usd", 0.0)) + delta_cost
    # Update per-session ledger.
    sessions = state.setdefault("sessions", [])
    if sessions:
        sessions[0]["usage"] = dict(totals)
        sessions[0]["cost_usd"] = totals["cost_usd"]
        sessions[0]["updated_at"] = now_iso()
    # Advance cursor.
    state["cursor"]["byte_offset"] = offset + (os.path.getsize(tpath) - offset if os.path.exists(tpath) else 0)
    # Cap seen_ids to last 1000 to bound growth.
    new_seen = list(set(seen) | set())
    state["cursor"]["seen_ids"] = new_seen[-1000:]


def _emit_post_tool_use(payload: Dict[str, Any]) -> int:
    """PostToolUse: scan transcript, update ledger, emit context on first warn."""
    cwd = payload.get("cwd") or os.getcwd()
    sid = payload.get("session_id") or "unknown"
    tool_name = payload.get("tool_name") or ""
    transcript = payload.get("transcript_path") or ""
    state_path = _state_path(None, cwd)
    state = cg.load_state(state_path)
    if state is None:
        # Initialize minimally so we have a place to write.
        repo, branch = _detect_repo(cwd)
        state = cg.new_session_state(
            session_id=sid, cwd=cwd, branch=branch or "unknown",
            repository=repo or "unknown", model="",
            transcript_path=transcript, thresholds=cg.resolve_thresholds(),
        )
    if transcript and not state["cursor"].get("transcript_path"):
        state["cursor"]["transcript_path"] = transcript
    _scan_transcript_delta(state)
    # Fallback heuristic if transcript yielded nothing.
    totals = state.get("totals") or {}
    if totals.get("input_tokens", 0) == 0 and totals.get("output_tokens", 0) == 0:
        # No real usage — apply heuristic for this tool call.
        model = (state.get("sessions") or [{}])[0].get("model") or "claude-sonnet-5"
        hc = cg.heuristic_tool_cost(tool_name, model)
        totals["cost_usd"] = float(totals.get("cost_usd", 0.0)) + hc
        totals["estimated_tokens"] = totals.get("estimated_tokens", 0) + 3000
        sessions = state.get("sessions", [])
        if sessions:
            sessions[0]["provenance"] = "estimated"
            sessions[0]["cost_usd"] = totals["cost_usd"]
            sessions[0]["updated_at"] = now_iso()
    # Threshold + status.
    thresholds = state.get("thresholds_usd") or cg.resolve_thresholds()
    status, reasons = cg.evaluate_status(float(totals.get("cost_usd", 0.0)), thresholds)
    state["status"] = status
    state["warnings"] = list(reasons)
    cg.save_state(state_path, state)
    # First-warn crossing emits additionalContext; otherwise silent.
    cost = float(totals.get("cost_usd", 0.0))
    if status in ("warn", "kill") and not state.get("warn_emitted", False):
        state["warn_emitted"] = True
        cg.save_state(state_path, state)
        ctx = (
            f"cost-gate WARN: ${cost:.2f} "
            f"(warn ${thresholds['session_warn']:.2f}, "
            f"kill ${thresholds['session_kill']:.2f})"
        )
        out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}
        sys.stdout.write(json.dumps(out))
        sys.stdout.write("\n")
    return 0


def _emit_pre_tool_use(payload: Dict[str, Any]) -> int:
    """PreToolUse: advisory only — emit additionalContext when cost is high.

    The historical deny-on-kill branch was removed (cost-gate is now
    warn-only). The hook still loads state and emits an additionalContext
    line for high-cost sessions so operators get visibility, but it never
    blocks the tool call.
    """
    cwd = payload.get("cwd") or os.getcwd()
    state_path = _state_path(None, cwd)
    state = cg.load_state(state_path)
    if state is None:
        return 0
    cost = float((state.get("totals") or {}).get("cost_usd", 0.0))
    thresholds = state.get("thresholds_usd") or cg.resolve_thresholds()
    status, reasons = cg.evaluate_status(cost, thresholds)
    if status != "warn":
        return 0
    msg = (
        f"cost-gate advisory: session cost ${cost:.2f} "
        f"(warn ${thresholds['session_warn']:.2f}, "
        f"kill ${thresholds['session_kill']:.2f}). "
        f"No tool block is issued — gate is advisory only."
    )
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": msg}}
    sys.stdout.write(json.dumps(out))
    sys.stdout.write("\n")
    return 0


# ---------------------------------------------------------------------------
# CLI modes
# ---------------------------------------------------------------------------

def _cli_text(args: argparse.Namespace) -> int:
    state_path = _state_path(args.state, os.getcwd())
    state = cg.load_state(state_path)
    if state is None:
        thresholds = cg.resolve_thresholds()
        state = cg.new_session_state(
            session_id="ephemeral", cwd=str(state_path.parent.parent),
            branch="unknown", repository="unknown", model="",
            thresholds=thresholds,
        )
        state["warnings"] = ["no state file — showing defaults"]
    sys.stdout.write(cg.format_text(state, state_path) + "\n")
    return 0


def _cli_json(args: argparse.Namespace) -> int:
    state_path = _state_path(args.state, os.getcwd())
    state = cg.load_state(state_path)
    if state is None:
        thresholds = cg.resolve_thresholds()
        state = cg.new_session_state(
            session_id="ephemeral", cwd=str(state_path.parent.parent),
            branch="unknown", repository="unknown", model="",
            thresholds=thresholds,
        )
    sys.stdout.write(cg.format_json(state, state_path) + "\n")
    return 0


def _cli_html(args: argparse.Namespace) -> int:
    state_path = _state_path(args.state, os.getcwd())
    state = cg.load_state(state_path)
    if state is None:
        thresholds = cg.resolve_thresholds()
        state = cg.new_session_state(
            session_id="ephemeral", cwd=str(state_path.parent.parent),
            branch="unknown", repository="unknown", model="",
            thresholds=thresholds,
        )
    out_path = Path(args.html)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(cg.format_html(state, state_path), encoding="utf-8")
    sys.stdout.write(f"wrote {out_path}\n")
    return 0


def _cli_footer(args: argparse.Namespace) -> int:
    state_path = _state_path(args.state, os.getcwd())
    state = cg.load_state(state_path)
    if state is None:
        thresholds = cg.resolve_thresholds()
        state = cg.new_session_state(
            session_id="ephemeral", cwd=str(state_path.parent.parent),
            branch="unknown", repository="unknown", model="",
            thresholds=thresholds,
        )
    sys.stdout.write(cg.format_footer(state) + "\n")
    return 0


def _cli_aggregate_pr(args: argparse.Namespace) -> int:
    """Read commit bodies from --bodies-file (one per line) and aggregate."""
    bodies_path = Path(args.bodies_file)
    bodies = [ln for ln in bodies_path.read_text(encoding="utf-8").splitlines() if ln]
    records = cg.parse_footers(bodies)
    total = cg.aggregate_pr_sessions(records)
    th = cg.resolve_thresholds()
    decision = {
        "total_usd": round(total, 4),
        "threshold_usd": th["pr_flag"],
        "apply_cost_flag": total >= th["pr_flag"],
        "sessions": sorted({r["session"] for r in records}),
        "missing_telemetry": not records,
    }
    sys.stdout.write(json.dumps(decision, indent=2, sort_keys=True) + "\n")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(prog="cost_gate_status")
    p.add_argument("--state", help="Path to state.json (default: $CWD/.dev-kit/.cost-gate/state.json)")
    p.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    p.add_argument("--html", metavar="PATH", help="Write self-contained HTML report")
    p.add_argument("--footer", action="store_true", help="Emit two-line git-trailer block")
    p.add_argument("--aggregate-pr", action="store_true", help="Aggregate PR commit trailers")
    p.add_argument("--bodies-file", help="(with --aggregate-pr) file with one commit body per line")
    # Hook modes — mutually exclusive; reading stdin JSON.
    p.add_argument("--hook-session-start", action="store_true")
    p.add_argument("--hook-post-tool-use", action="store_true")
    p.add_argument("--hook-pre-tool-use", action="store_true")
    args = p.parse_args()

    # Hook modes — read JSON from stdin.
    if args.hook_session_start or args.hook_post_tool_use or args.hook_pre_tool_use:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError as e:
            sys.stderr.write(f"cost_gate: bad JSON on stdin: {e}\n")
            return 0
        if args.hook_session_start:
            return _emit_session_start(payload)
        if args.hook_post_tool_use:
            return _emit_post_tool_use(payload)
        if args.hook_pre_tool_use:
            return _emit_pre_tool_use(payload)

    if args.aggregate_pr:
        if not args.bodies_file:
            sys.stderr.write("--aggregate-pr requires --bodies-file\n")
            return 2
        return _cli_aggregate_pr(args)
    if args.html:
        return _cli_html(args)
    if args.json:
        return _cli_json(args)
    if args.footer:
        return _cli_footer(args)
    return _cli_text(args)


if __name__ == "__main__":
    sys.exit(main())
