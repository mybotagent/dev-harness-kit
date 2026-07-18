#!/usr/bin/env python3
"""discover_dependents.py — Phase 2 of /dev-kit:prune.

Walks the call graph of every Phase-1 deletion candidate and emits one row
per live importer / caller / runtime reference. Output is a DEPENDENTS
block that gates Phase 3 (REPORT) on per-row user ack.

Backed by `lib/analysis_core.runner.run_analysis(mode="delete", ...)` —
the same deterministic engine Phase 1 used, so scope filtering, severity
floors, dedupe, and the `deletion_proof` contract (no_importers AND
no_callers) all behave identically. The engine emits the deletion
suggestions; this script annotates them with the live dependents that
would break if the candidate were removed.

Why a separate script (vs inlining into the SKILL.md body)?
- The dependent-walk has to run AFTER Phase 1 produces candidates; it is
  stateful and would otherwise bloat the SKILL.md body.
- It needs to be testable in isolation (see
  `tests/test_prune.py::test_prune_target_runs_full_suite` and friends).
- It needs to be invokable from the SKILL.md body *and* from a manual
  repro (`python3 skills/prune/scripts/discover_dependents.py --target foo`)
  without the user having to load the skill first.

Usage:
    python3 skills/prune/scripts/discover_dependents.py --target <feat> \\
        --candidates <phase1-report.json> --out <dependents-report.md>

The output is a Markdown block (not JSON) because Phase 3 reads it
verbatim into `.dev-kit/hand-off/prune-target-report.md` and the SKILL.md
body formats it as a bullet list.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

# Make lib/ importable when this script is invoked from any cwd. The
# prune skill is shipped as a slash command; users may invoke it from
# $PROJECT_ROOT, from a worktree, or from CI where the cwd is the runner's
# workspace. Both layouts must work.
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.analysis_core.runner import (  # noqa: E402  (sys.path tweak above)
    emit_suggested_diffs,
    render_markdown,
    run_analysis,
)
from lib.analysis_core.dimensions import group  # noqa: E402


def _load_candidates(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Load Phase-1 candidate JSON.

    Expected shape (one of):

      - { "<dim>": [ {file, line, severity, confidence, ...}, ... ], ... }
      - [ {dim, file, line, ...}, ... ]   (flat list — we bucket by `dim`)

    Anything else raises ValueError; the SKILL.md body wraps the call so
    a Phase-1 failure surfaces here rather than silently passing through.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        bucket: Dict[str, List[Dict[str, Any]]] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            d = str(item.get("dim", ""))
            if not d:
                continue
            bucket.setdefault(d, []).append(dict(item))
        return bucket
    if isinstance(raw, Mapping):
        out: Dict[str, List[Dict[str, Any]]] = {}
        for k, v in raw.items():
            if not isinstance(v, list):
                continue
            out[str(k)] = [dict(x) for x in v if isinstance(x, Mapping)]
        return out
    raise ValueError(
        f"candidates file must be a JSON object or list, got {type(raw).__name__}"
    )


def _dependent_rows(
    candidates: Mapping[str, Sequence[Mapping[str, Any]]],
    target: str,
    paths: Sequence[Path],
) -> List[Dict[str, str]]:
    """Run the analysis engine and surface dependents.

    Uses `inspect` dimensions in `mode="delete"` so the engine's
    `emit_suggested_diffs` produces the same `git rm` /
    `# delete-blocked: requires no_importers AND no_callers proof`
    suggestions Phase 1 would. Any candidate whose `deletion_proof` is
    missing or incomplete gets a dependent row named "needs proof" — the
    user MUST ack before Phase 3 can render.

    A pure-refactor sweep (mode="rewrite") would skip this gate entirely;
    `mode="delete"` is the contract prune enforces.
    """
    result = run_analysis(
        dimensions=group("inspect"),
        mode="delete",
        paths=paths,
        candidates=candidates,
    )
    rows: List[Dict[str, str]] = []
    for diff in emit_suggested_diffs(result):
        rows.append({
            "file": diff.file,
            "line": str(diff.line) if diff.line is not None else "",
            "dim": diff.dim,
            "command": diff.command,
            "reason": diff.reason,
        })
    # Render once so the caller can echo the verdict header without
    # re-running the engine. Cheap; the engine is deterministic.
    rows.append({
        "file": "__report__",
        "line": "",
        "dim": "__engine__",
        "command": "verdict:" + result.verdict,
        "reason": f"target={target} kept={result.kept_count} "
                  f"filtered={result.filtered_count}",
    })
    return rows


def _render_markdown(target: str, rows: Iterable[Dict[str, str]]) -> str:
    """Render the DEPENDENTS block as Markdown.

    Bullet shape is locked to the Phase-3 renderer so a downstream
    `parse_prune_target_report.py` can split on `**File:**` /
    `**Command:**` keys without a regex pass. Each row is one bullet; the
    engine verdict line is rendered as a heading.
    """
    out: List[str] = [
        f"# DEPENDENTS — {target}",
        "",
        "Phase 2 output. Each row is a candidate + its dependent proof.",
        "Block until the user explicitly acks each row before Phase 3.",
        "",
    ]
    verdict_emitted = False
    for row in rows:
        if row["dim"] == "__engine__":
            if not verdict_emitted:
                out.append("## Verdict")
                out.append("")
                out.append(f"- {row['command']}  ({row['reason']})")
                out.append("")
                verdict_emitted = True
            continue
        out.append(f"- **File:** {row['file']}:{row['line'] or '?'}")
        out.append(f"  **Dim:** {row['dim']}")
        out.append(f"  **Command:** `{row['command']}`")
        if row["reason"]:
            out.append(f"  **Reason:** {row['reason']}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--target", required=True,
        help="Named feature to scope the dependent-walk to.",
    )
    parser.add_argument(
        "--candidates", type=Path, required=True,
        help="Phase-1 candidate JSON file (output of build-prune / inspect).",
    )
    parser.add_argument(
        "--out", type=Path, required=True,
        help="Output Markdown path (DEPENDENTS block).",
    )
    parser.add_argument(
        "--scope", action="append", default=[],
        help="Restrict scope to one or more paths. Repeatable. "
             "Defaults to the repo root when omitted.",
    )
    args = parser.parse_args(argv)

    if not args.candidates.exists():
        print(f"discover_dependents: candidates file missing: {args.candidates}",
              file=sys.stderr)
        return 2

    candidates = _load_candidates(args.candidates)
    paths = [Path(p).resolve() for p in args.scope] if args.scope else [
        _REPO_ROOT.resolve(),
    ]
    rows = _dependent_rows(candidates, args.target, paths)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(_render_markdown(args.target, rows), encoding="utf-8")
    print(f"discover_dependents: wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
