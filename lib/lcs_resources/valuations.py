"""valuations resource — ``lcs://valuations/<plan-id>``.

Phase 4 (issue #373) build no-go gate. /dev-kit:valuate writes the
decision envelope here; /dev-kit:build reads it before dispatching
to the runner and refuses to proceed on non-`proceed` verdicts.

Single URI form:
  lcs://valuations/<plan-id>/
      → {"status": "ok"|"partial"|"error", "data": {"plan_id": ...,
        "decision": "proceed"|"revise"|"hold"|"kill", "rationale": str,
        "blocking_findings": list, "scores": dict, "persisted_at": str}}

Source: <project>/.dev-kit/valuations/<plan-id>.json (one envelope per
plan). Missing envelope -> partial; the build gate treats partial as
"hold" and refuses to proceed.

Failure mode: a read or JSON parse error returns status=error with
``missing=[str(exc)]`` so the LCS server can surface it. The
build gate's contract is "proceed on `decision == proceed` and
`status in (ok, partial-with-valid-decision)`", so an error envelope
also halts the build (fail-closed).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from lcs_server import LCSPartialError, ParsedURI, Resource

NAME = "valuations"


def _path(project_root: Path) -> Path:
    return project_root / ".dev-kit" / "valuations"


class ValuationsResource(Resource):
    """LCS resource for ``lcs://valuations/<plan-id>``."""

    name = NAME

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def fetch(self, parsed: ParsedURI) -> dict:
        # lcs://valuations/<plan-id>/
        if not parsed.path_segments[1:]:
            return {
                "status": "ok",
                "data": {
                    "plan_ids": [
                        p.stem for p in _path(self._repo_root).glob("*.json")
                    ],
                },
            }
        plan_id = unquote(parsed.path_segments[1])
        p = _path(self._repo_root) / f"{plan_id}.json"
        if not p.exists():
            return {
                "status": "partial",
                "data": None,
                "missing": [f"no valuation envelope for plan_id={plan_id!r}"],
            }
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {
                "status": "error",
                "data": None,
                "missing": [f"valuation envelope read/parse failed: {exc}"],
            }
        return {"status": "ok", "data": data}

    def write(self, plan_id: str, envelope: dict, project_root: Optional[Path] = None) -> dict:
        """Persist an envelope. The build runner calls this from
        /dev-kit:valuate to seed the lookup the gate reads.

        ``envelope`` must be the canonical shape produced by
        ``lib/valuation_engine.decision_persists_to_lcs`` plus a
        ``scores`` sub-dict. This method is a thin convenience for
        the CLI and tests; the runtime LCS server has its own
        write path.
        """
        root = project_root or self._repo_root
        d = _path(root)
        d.mkdir(parents=True, exist_ok=True)
        envelope = {**envelope, "persisted_at": datetime.now(timezone.utc).isoformat()}
        (d / f"{plan_id}.json").write_text(json.dumps(envelope, indent=2), encoding="utf-8")
        return {"status": "ok", "data": envelope}
