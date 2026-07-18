"""runner.py — orchestrator that ties dimensions, evidence, and fp_filter.

The engine has one public entrypoint: `run_analysis`. Each SKILL.md
body calls it with:

  dimensions:  list of Dimension objects (or names) to engage
  mode:        one of "read-only" | "delete" | "rewrite"
  paths:       list of root paths to consider (used for scope display)
  candidates:  {dim_name: [raw json findings]} gathered by the parent
               skill's parallel Agent fan-out. Optional — when omitted,
               the engine returns an empty AnalysisResult.

The pipeline is:
  parse_candidate      → coerce raw JSON to Evidence
  deterministic_filter → drop empty-scenario / low-confidence-minor
  dedupe               → collapse identical anchors
  threshold_by_mode    → drop below floor for delete/rewrite

If `verdicts` is provided, REJECTED items are dropped before rendering.

The renderer is intentionally simple markdown — no emojis, no colors —
because the SKILL.md body wraps it in the family-specific summary the
parent skill expects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .dimensions import Dimension, resolve
from .evidence import Evidence, Severity, SEVERITY_ORDER, parse_candidate
from .fp_filter import (
    apply_verifier,
    dedupe,
    deterministic_filter,
    threshold_by_mode,
)
from .evidence import Verdict  # noqa: F401  (re-export for callers)


@dataclass
class SuggestedDiff:
    """One mutation the engine is willing to suggest for a finding."""

    file: str
    line: int
    dim: str
    command: str  # rm path / git rm path / "# rewrite: <hint>"
    reason: str


@dataclass
class AnalysisResult:
    """Immutable bag of kept findings + scope metadata."""

    dimensions: Tuple[Dimension, ...]
    mode: str
    paths: Tuple[Path, ...]
    findings: Tuple[Evidence, ...]
    kept_count: int
    filtered_count: int

    @property
    def verdict(self) -> str:
        """Block / Drift / Healthy bucket per parent skill convention."""
        if not self.findings:
            return "Healthy"
        severities = {f.severity for f in self.findings}
        if Severity.CRITICAL in severities:
            return "Critical"
        if Severity.MAJOR in severities:
            return "Major drift"
        return "Minor drift"


def run_analysis(
    dimensions: Sequence[Dimension | str],
    mode: str,
    paths: Iterable[Path | str],
    candidates: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    verdicts: Optional[Sequence[Tuple[int, Verdict, str]]] = None,
) -> AnalysisResult:
    """Deterministic engine. See module docstring for full semantics.

    Returns an AnalysisResult; never raises on empty input.
    """
    if mode not in {"read-only", "delete", "rewrite"}:
        raise ValueError(
            f"analysis mode must be one of read-only/delete/rewrite, got {mode!r}"
        )
    dims = tuple(resolve(dimensions))
    paths_t = tuple(Path(p) for p in paths)
    raw = candidates or {}

    parsed: List[Evidence] = []
    for d in dims:
        for raw_item in raw.get(d.name, []) or []:
            try:
                parsed.append(parse_candidate(dict(raw_item)))
            except (ValueError, TypeError):
                # Malformed item from a per-dim expert is dropped silently.
                # Verifier pass would catch this; deterministic mode skips it.
                continue

    pre_filter_count = len(parsed)
    filtered = deterministic_filter(parsed)
    deduped = dedupe(filtered)
    thresholded = threshold_by_mode(deduped, mode)
    if verdicts is not None:
        thresholded = apply_verifier(thresholded, verdicts)
    thresholded = _sort(thresholded)

    return AnalysisResult(
        dimensions=dims,
        mode=mode,
        paths=paths_t,
        findings=tuple(thresholded),
        kept_count=len(thresholded),
        filtered_count=pre_filter_count - len(thresholded),
    )


def _sort(items: Sequence[Evidence]) -> List[Evidence]:
    sev_index = {s: i for i, s in enumerate(SEVERITY_ORDER)}
    return sorted(
        items,
        key=lambda e: (sev_index[e.severity], e.file, e.line, e.dim),
    )


def render_markdown(result: AnalysisResult) -> str:
    """Markdown report for the kept findings. Deterministic + parent-friendly."""
    scope = ", ".join(str(p) for p in result.paths) or "(no paths)"
    out: List[str] = [
        "# Analysis Report",
        "",
        f"**Verdict:** {result.verdict}",
        f"**Mode:** {result.mode}",
        f"**Scope:** {scope}",
        f"**Dimensions:** {', '.join(d.name for d in result.dimensions)}",
        f"**Coverage:** {result.kept_count} findings kept, "
        f"{result.filtered_count} filtered as false positive / low-signal",
        "",
        "## Per-dimension summary",
        "",
        "| dim | HIGH | MED | LOW |",
        "|-----|------|-----|-----|",
    ]
    by_dim: Dict[str, List[Evidence]] = {}
    for f in result.findings:
        by_dim.setdefault(f.dim, []).append(f)

    for d in result.dimensions:
        items = by_dim.get(d.name, [])
        high = sum(1 for f in items if f.severity == Severity.CRITICAL)
        med = sum(1 for f in items if f.severity == Severity.MAJOR)
        low = sum(
            1 for f in items if f.severity in (Severity.MINOR, Severity.NIT)
        )
        out.append(f"| {d.name} | {high} | {med} | {low} |")

    out.append("")
    out.append("## Findings")
    out.append("")
    for f in result.findings:
        out.append(f"- **[{f.severity.value.upper()}] {f.title}** — "
                   f"{f.file}:{f.line} (dim: {f.dim})")
        out.append(f"  TL;DR: {f.tldr}")
        out.append(f"  Scenario: {f.failure_scenario}")
        if f.fix_hint:
            out.append(f"  Fix: {f.fix_hint}")
        out.append("")
    if not result.findings:
        out.append("(no findings)")
        out.append("")
    return "\n".join(out)


def emit_suggested_diffs(result: AnalysisResult) -> List[SuggestedDiff]:
    """Translate kept findings into mutation commands per the mode.

    - delete:    `rm <file>` / `git rm <file>` for each non-zero finding
    - rewrite:   `# rewrite: <fix_hint>` per finding
    - read-only: empty list (no mutation surfaced)
    """
    if result.mode == "read-only":
        return []
    out: List[SuggestedDiff] = []
    seen_files: set = set()
    for f in result.findings:
        if result.mode == "delete":
            if f.file in seen_files:
                continue
            seen_files.add(f.file)
            out.append(
                SuggestedDiff(
                    file=f.file,
                    line=f.line,
                    dim=f.dim,
                    command=f"git rm {f.file}",
                    reason=f.failure_scenario,
                )
            )
        elif result.mode == "rewrite":
            hint = f.fix_hint or "see scenario"
            out.append(
                SuggestedDiff(
                    file=f.file,
                    line=f.line,
                    dim=f.dim,
                    command=f"# rewrite: {hint}",
                    reason=f.failure_scenario,
                )
            )
    return out
