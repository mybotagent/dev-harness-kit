#!/usr/bin/env python3
"""cost_gate_status.py — read-only CLI for cost measurement.

Driven by the human-use /dev-kit:cost-gate skill. Pure measurement /
display; there is no hook driver, no SessionStart / PostToolUse / PreToolUse
mode. Cost is observed only — this CLI never blocks tool calls.

Modes (mutually exclusive):
  (default)        text status summary
  --json           machine-readable JSON to stdout
  --html PATH      write self-contained HTML report to PATH
  --footer         print two-line git-trailer block for commit messages
  --aggregate-pr   read PR commit bodies (stdin) + aggregate (test helper)

Threshold overrides (env): DEV_KIT_COST_WARN_USD,
DEV_KIT_PR_COST_FLAG_USD. State path override (env):
DEV_KIT_COST_GATE_STATE.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Resolve lib/ for cost_gate imports.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_LIB_DIR = _REPO_ROOT / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import cost_gate as cg  # noqa: E402


def _state_path(explicit: Optional[str], cwd: str) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("DEV_KIT_COST_GATE_STATE")
    if env:
        return Path(env)
    return cg.default_state_path(cwd)


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
    args = p.parse_args()

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
