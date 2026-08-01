"""trace_log.py — append-only structured trajectory log per worktree run.

Stores per-step execution data + per-dim scores + verdict + per-dim
evidence. JSON file under `eval/transcripts/<case_id>/<UTC>.json`.

Phase 0 (issue #511): deterministic 4-dim scorers only; LLM judges come
in Phase 1. `judge_scores` is still written so the schema does not
need a v2 bump when LLM judge fields appear.

Public API:
    TraceStep     — one step in the trajectory (frozen dataclass)
    TraceLog      — full trajectory + scores + evidence (frozen dataclass)
    TraceLog.save(worktree)  — write JSON file under worktree
    TraceLog.load(path)      — read JSON file back

Backward compat: schema_version is a positive integer. New fields are
additive; never repurpose existing field names.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class TraceStep:
    """One step in the agent trajectory.

    All times are ISO-8601 UTC. `extra` carries step-specific metadata
    (file path, command, etc.) that does not fit the fixed fields.
    """

    ts: str
    skill: str
    phase: str
    model: Optional[str] = None
    prompt_hash: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    retries: int = 0
    exit_code: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TraceLog:
    """Full trajectory + scores + evidence.

    `steps` is the per-step execution log; `judge_scores` is the per-dim
    scoring output (one entry per rubric invocation); `evidence` is the
    per-dim debug data the human reviewer would need.
    """

    schema_version: int = SCHEMA_VERSION
    case_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    harness_version: str = ""
    agent: str = ""
    worktree_branch: str = ""
    worktree_path: str = ""
    steps: List[TraceStep] = field(default_factory=list)
    judge_scores: List[Dict[str, Any]] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "harness_version": self.harness_version,
            "agent": self.agent,
            "worktree_branch": self.worktree_branch,
            "worktree_path": self.worktree_path,
            "steps": [asdict(s) for s in self.steps],
            "judge_scores": list(self.judge_scores),
            "evidence": dict(self.evidence),
        }

    @classmethod
    def load(cls, path: Path) -> "TraceLog":
        """Read a JSON file back into a TraceLog.

        Unknown step fields go into `extra`; missing fields get defaults.
        Raises ValueError on schema_version mismatch (the caller can
        choose to migrate or skip).
        """
        raw = json.loads(Path(path).read_text())
        version = raw.get("schema_version", 0)
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"trace schema_version={version} != current={SCHEMA_VERSION} "
                f"(file={path}); migrate first"
            )
        steps_raw = raw.pop("steps", [])
        steps: List[TraceStep] = []
        for s in steps_raw:
            # Take `extra` (may be absent or empty) and any future
            # fields not in TraceStep's annotations; merge into a single
            # `extra` dict. Then construct with only the known fields.
            step_extra: Dict[str, Any] = dict(s.get("extra") or {})
            for k, v in s.items():
                if k == "extra":
                    continue  # already merged
                if k not in TraceStep.__annotations__:
                    step_extra[k] = v
            known = {k: v for k, v in s.items()
                     if k in TraceStep.__annotations__ and k != "extra"}
            steps.append(TraceStep(extra=step_extra, **known))
        return cls(steps=steps, **raw)

    def save(self, worktree: Path) -> Path:
        """Write the trace JSON to `worktree/eval/transcripts/<case_id>/<UTC>.json`.

        Hardens against the LLM review findings (trace path escape /
        symlink-directed writes):
        - case_id must be a single safe relative component (no `..`,
          no `/`, no leading `-`, no absolute path).
        - the parent transcript directory must resolve strictly under
          `worktree/eval/transcripts/` (containment check).
        - existing symlinks at the destination are refused; the parent
          directory is rejected if it is itself a symlink.
        - collision-safe filename: timestamp + microsecond + uuid4 suffix
          prevents same-second overwrites (the previous version had
          only second resolution).

        Returns the written path. Raises ValueError on path validation
        failure.
        """
        import uuid

        case_id = self.case_id
        if not case_id or case_id.startswith(".") or case_id.startswith("-"):
            raise ValueError(f"case_id must be a safe component: {case_id!r}")
        if "/" in case_id or "\\" in case_id or ".." in case_id:
            raise ValueError(f"case_id must not contain path separators or '..': {case_id!r}")
        if Path(case_id).is_absolute():
            raise ValueError(f"case_id must be relative: {case_id!r}")

        worktree = Path(worktree).resolve()
        transcripts_root = (worktree / "eval" / "transcripts").resolve()
        out_dir = (transcripts_root / case_id).resolve()
        try:
            out_dir.relative_to(transcripts_root)
        except ValueError as exc:
            raise ValueError(
                f"case_id resolves outside transcripts root: {out_dir}"
            ) from exc
        # Refuse symlinked parents (worktree-controlled escape vector).
        if out_dir.exists() and out_dir.is_symlink():
            raise ValueError(f"refusing to write through symlink: {out_dir}")
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        suffix = uuid.uuid4().hex[:8]
        out = out_dir / f"{ts}-{suffix}.json"
        out.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=False))
        return out


def now_utc() -> str:
    """ISO-8601 UTC timestamp string (e.g. `2026-07-31T10:00:00Z`)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
