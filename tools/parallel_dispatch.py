#!/usr/bin/env python3
"""parallel_dispatch.py — Multi-agent fan-out + dedupe + verifier + synthesize (issue #177).

The canonical multi-agent fan-out pattern is duplicated across
`/dev-kit:security` (10-dim A01-A10), `/dev-kit:eval` (3-dim), and
`/dev-kit:inspect` (8-dim). Each skill issues N parallel `Agent` calls
inside ONE assistant message, then dedupes by file+line+theme, then runs
a verifier pass, then synthesizes the final report.

This module extracts the fan-out + dedupe + verifier + synthesize
boilerplate so each skill can route through it. All agents share the same
read-only evidence corpus; no worktrees; no overlap risk because no writes.

`/dev-kit:review` keeps its inline pattern as the canonical reference.

SSOT: this file. Skill bodies (security/eval/inspect) call
`fanout_and_synthesize(...)` from their own SKILL.md instructions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence


@dataclass
class Finding:
    """One finding produced by a dimension agent.

    Fields match the dedupe key (file + line + theme). Theme is free-text
    so a finding can be categorized by the model.
    """
    file: str
    line: int
    theme: str
    severity: str = "MED"
    detail: str = ""


@dataclass
class SynthesisResult:
    """The full output of `fanout_and_synthesize`."""
    dimensions: List[str]
    findings: List[Finding] = field(default_factory=list)
    verified: List[Finding] = field(default_factory=list)
    rejected: List[Finding] = field(default_factory=list)
    synthesis: str = ""


def _dedupe_key(f: Finding) -> tuple[str, int, str]:
    return (f.file, f.line, f.theme)


def dedupe_findings(findings: Sequence[Finding]) -> List[Finding]:
    """Collapse findings on (file, line, theme). First occurrence wins."""
    seen: Dict[tuple[str, int, str], Finding] = {}
    for f in findings:
        k = _dedupe_key(f)
        if k not in seen:
            seen[k] = f
    return list(seen.values())


def fanout_and_synthesize(
    dimensions: Sequence[str],
    evidence: Sequence[Path],
    synthesize_prompt: str,
    *,
    dimension_agent: Optional[Callable[[str, Sequence[Path]], List[Finding]]] = None,
    verifier: Optional[Callable[[List[Finding]], List[Finding]]] = None,
    synthesize: Optional[Callable[[List[Finding], List[Finding]], str]] = None,
) -> SynthesisResult:
    """Run N dimension agents in parallel, dedupe, verifier pass, synthesize.

    Args:
        dimensions: ordered dimension labels (e.g. ["A01", ..., "A10"]).
        evidence: read-only file paths shared by all agents. The Agent tool
            is responsible for issuing parallel calls; this function
            encapsulates the dedupe + verifier + synthesize pipeline.
        dimension_agent: optional callable (dim, evidence) -> [Finding].
            When None, fanout is a no-op (callers wire their own Agent calls
            inside one assistant message; the helper still dedupes +
            verifies + synthesizes the raw results they pass in).
        verifier: optional callable ([Finding]) -> [Finding] (verified only).
            When None, all deduped findings are treated as verified.
        synthesize: optional callable (verified, rejected) -> str.
            When None, returns a default JSON summary.

    Returns:
        SynthesisResult with the deduped + verified findings and the
        synthesis text. The synthesis text is the body of the final
        report emitted by the calling skill.
    """
    raw: List[Finding] = []
    if dimension_agent is not None:
        for dim in dimensions:
            raw.extend(dimension_agent(dim, evidence))
    deduped = dedupe_findings(raw)
    if verifier is not None:
        verified = verifier(deduped)
        rejected = [f for f in deduped if f not in verified]
    else:
        verified = deduped
        rejected = []
    if synthesize is not None:
        synthesis_text = synthesize(verified, rejected)
    else:
        synthesis_text = json.dumps(
            {
                "dimensions": list(dimensions),
                "verified_count": len(verified),
                "rejected_count": len(rejected),
                "verified": [f.__dict__ for f in verified],
                "rejected": [f.__dict__ for f in rejected],
            },
            indent=2,
        )
    return SynthesisResult(
        dimensions=list(dimensions),
        findings=deduped,
        verified=verified,
        rejected=rejected,
        synthesis=synthesis_text,
    )
