#!/usr/bin/env python3
"""Run the local subscription CLI only for paths deferred by policy."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

STATE = ".dev-kit/.tdd-scope.json"
INSTRUCTION = (
    "Classify the request for TDD. Return JSON only with keys "
    "tdd_required (boolean), confidence (number), reason (string). "
    "False means documentation, configuration, one-off script, formatting, "
    "typo, or simple maintenance. True means core behavior, API, business "
    "logic, security, data handling, or meaningful refactoring.\nRequest: "
)


def _parse(raw: str) -> dict:
    for text in (raw, json.loads(raw).get("result", "") if raw.startswith("{") else ""):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            continue
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("tdd_required"), bool):
            return {"tdd_required": value["tdd_required"], "confidence": float(value.get("confidence", 0)), "reason": str(value.get("reason", ""))}
    raise ValueError("invalid TDD judge response")


def evaluate(prompt: str, root: Path) -> dict:
    try:
        result = subprocess.run(
            ["claude", "-p", "--output-format", "json", "--permission-mode", "plan", INSTRUCTION + prompt],
            capture_output=True, text=True, timeout=45,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "claude judge failed")
        decision = _parse(result.stdout)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        decision = {"tdd_required": True, "confidence": 0.0, "reason": f"judge unavailable: {exc}"}
    path = root / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n")
    return decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.prompt, args.root.resolve()), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
