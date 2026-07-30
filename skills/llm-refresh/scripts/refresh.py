#!/usr/bin/env python3
"""refresh.py — validate, diff, and atomically write one provider's
pricing payload into docs/llm-info/<provider>.json.

Usage:
    <extracted-models-json> | python3 skills/llm-refresh/scripts/refresh.py \
        --provider ID [--check] [--json] [--sources PATH]

Why this shape instead of a bespoke per-vendor parser:
    Pricing pages are owned by the vendor and their HTML/markdown structure
    drifts without notice. A prior version of this script hand-rolled one
    regex/HTML-table parser per provider; the first live vendor-layout
    change broke two of them outright and silently mislabeled a third
    provider's CNY prices as USD (wrong currency, not just a crash).
    Extraction is now done by the calling SKILL.md body via WebFetch
    (LLM-based, adapts to layout changes) — this script's only job is the
    part that must stay deterministic: schema validation, diffing against
    the committed file, and the atomic write. The user still reviews the
    printed diff and commits manually; nothing here auto-commits.

Payload on stdin (JSON): either a bare array of model objects, or
`{"models": [...], "currency": "USD"}`. Each model object must have:
    id, display_name, context_window, input_price_per_mtok,
    output_price_per_mtok, deprecated, notes
(see docs/llm-info/README.md for the full schema).

Exit codes (sentinel-style, designed for chain audits):
    0 — no change (--check) OR write succeeded OR nothing to write
    1 — --check was used AND the payload differs from the committed file
    2 — payload failed schema validation
    3 — usage error (unknown provider id, missing sources.json, bad/absent stdin JSON)
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Re-use the plugin's POSIX-atomic write helper (lib/atomic.py).
_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parents[3] / "lib"))

from atomic import atomic_write_json, now_iso  # type: ignore  # noqa: E402

EXIT_OK = 0
EXIT_DIFF = 1
EXIT_INVALID = 2
EXIT_USAGE = 3

REQUIRED_MODEL_KEYS = {
    "id", "display_name", "context_window",
    "input_price_per_mtok", "output_price_per_mtok",
    "deprecated", "notes",
}


# ---------- project root ----------

def _project_root() -> Path:
    candidate = _THIS.parents[3]
    if (candidate / ".claude-plugin" / "plugin.json").exists():
        return candidate
    cwd_candidate = Path.cwd()
    if (cwd_candidate / ".claude-plugin" / "plugin.json").exists():
        return cwd_candidate
    return candidate


# ---------- validation ----------

def validate_models(models: Any) -> List[Dict[str, Any]]:
    """Raise ValueError with an actionable message on any schema violation."""
    if not isinstance(models, list) or not models:
        raise ValueError("payload must contain a non-empty 'models' list")
    for i, m in enumerate(models):
        if not isinstance(m, dict):
            raise ValueError(f"models[{i}] must be an object")
        missing = REQUIRED_MODEL_KEYS - set(m.keys())
        if missing:
            raise ValueError(f"models[{i}] missing keys: {sorted(missing)}")
        if not isinstance(m["id"], str) or not m["id"]:
            raise ValueError(f"models[{i}].id must be a non-empty string")
        if not isinstance(m["display_name"], str) or not m["display_name"]:
            raise ValueError(f"models[{i}].display_name must be a non-empty string")
        if not isinstance(m["context_window"], int) or isinstance(m["context_window"], bool):
            raise ValueError(f"models[{i}].context_window must be an int")
        for key in ("input_price_per_mtok", "output_price_per_mtok"):
            val = m[key]
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ValueError(f"models[{i}].{key} must be a number")
            if val < 0:
                raise ValueError(f"models[{i}].{key} must be non-negative (got {val})")
        if not isinstance(m["deprecated"], bool):
            raise ValueError(f"models[{i}].deprecated must be a bool")
    return models


# ---------- IO ----------

def load_sources(root: Path, sources_path: Optional[Path] = None) -> Dict[str, Any]:
    path = sources_path or (root / "docs" / "llm-info" / "sources.json")
    if not path.exists():
        print(f"error: sources.json not found: {path}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: sources.json is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def load_existing(root: Path, provider_id: str) -> Optional[Dict[str, Any]]:
    path = root / "docs" / "llm-info" / f"{provider_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_payload(root: Path, payload: Dict[str, Any]) -> Path:
    path = root / "docs" / "llm-info" / f"{payload['provider']}.json"
    atomic_write_json(path, payload)
    return path


def _comparable(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Strip the always-changing `fetched_at` stamp so two payloads with
    identical prices compare equal regardless of when they were fetched."""
    if payload is None:
        return None
    return {k: v for k, v in payload.items() if k != "fetched_at"}


def diff_payloads(before: Optional[Dict[str, Any]], after: Dict[str, Any]) -> str:
    before_text = (
        json.dumps(before, indent=2, sort_keys=True, ensure_ascii=False) if before else ""
    )
    after_text = json.dumps(after, indent=2, sort_keys=True, ensure_ascii=False)
    diff = difflib.unified_diff(
        before_text.splitlines(),
        after_text.splitlines(),
        fromfile="before",
        tofile="after",
        lineterm="",
    )
    return "\n".join(diff)


# ---------- CLI ----------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate + diff + write one provider's pricing payload (read from stdin) into docs/llm-info/<provider>.json.",
    )
    parser.add_argument("--provider", required=True, help="Provider id from sources.json (e.g. claude).")
    parser.add_argument("--check", action="store_true", help="Diff only; never write. Exit 1 on diff.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable summary.")
    parser.add_argument("--sources", help="Override sources.json path (for testing).")
    parsed = parser.parse_args(argv)

    root = _project_root()
    sources_path = Path(parsed.sources).resolve() if parsed.sources else None
    sources = load_sources(root, sources_path)
    providers = {p["id"]: p for p in sources.get("providers", [])}

    if parsed.provider not in providers:
        known = ", ".join(sorted(providers))
        print(f"error: provider '{parsed.provider}' not in sources.json (known: {known})", file=sys.stderr)
        return EXIT_USAGE
    meta = providers[parsed.provider]

    raw_stdin = sys.stdin.read()
    if not raw_stdin.strip():
        print(
            f"error: no payload on stdin — pipe extracted model JSON, "
            f"e.g. echo '{{\"models\": [...]}}' | {Path(__file__).name} --provider {parsed.provider}",
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        extracted = json.loads(raw_stdin)
    except json.JSONDecodeError as exc:
        print(f"error: stdin is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_USAGE

    models_raw = extracted.get("models") if isinstance(extracted, dict) else extracted
    try:
        models = validate_models(models_raw)
    except ValueError as exc:
        print(f"[{parsed.provider}] FAIL: {exc}", file=sys.stderr)
        return EXIT_INVALID

    currency = (extracted.get("currency") if isinstance(extracted, dict) else None) or meta.get("currency", "USD")
    existing = load_existing(root, parsed.provider)
    OWNED_KEYS = {"provider", "label", "source_url", "fetched_at", "currency", "models"}
    payload = {
        # This script only extracts token pricing (`models`) plus the
        # metadata fields above. Anything else already in the committed
        # file (e.g. `plans`, `plans_note`) is hand-curated and out of
        # scope for WebFetch extraction — carry it forward untouched
        # rather than silently wiping it on every refresh.
        **{k: v for k, v in (existing or {}).items() if k not in OWNED_KEYS},
        "provider": parsed.provider,
        "label": meta["label"],
        "source_url": meta["url"],
        "fetched_at": now_iso(),
        "currency": currency,
        "models": models,
    }
    payload.setdefault("plans", [])

    changed = _comparable(existing) != _comparable(payload)
    target = root / "docs" / "llm-info" / f"{parsed.provider}.json"

    overall = EXIT_OK
    if parsed.check:
        if changed:
            overall = EXIT_DIFF
            if not parsed.json:
                print(f"--- {parsed.provider} (changed) ---")
                print(diff_payloads(existing, payload))
        elif not parsed.json:
            print(f"[{parsed.provider}] no change")
    elif changed:
        write_payload(root, payload)
        if not parsed.json:
            print(f"[{parsed.provider}] wrote {target} ({len(models)} models)")
    elif not parsed.json:
        print(f"[{parsed.provider}] no change")

    if parsed.json:
        summary = {
            "provider": parsed.provider,
            "changed": changed,
            "model_count": len(models),
            "fetched_at": payload["fetched_at"],
        }
        print(json.dumps({"summary": summary, "exit": overall}, indent=2, sort_keys=True, ensure_ascii=False))
    return overall


if __name__ == "__main__":
    sys.exit(main())
