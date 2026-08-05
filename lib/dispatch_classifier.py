"""Dispatch-mode classifier.

Pure function: takes a list of build steps (as parsed from
`phases/<phase>/index.json`), returns a `DispatchDecision` describing
whether the steps should be executed sequentially or in parallel.

Replaces the legacy `--parallel N` argparse flag on `/dev-kit:build`.
The classifier is the single source of truth for the dispatch decision;
the build runner only branches on the verdict.

Iron Law (L5 — one answer, no option lists unless asked):
    - Default = sequential. Parallel is opt-in by evidence, not by user toggle.
    - First-match-wins priority order; a single hit at any rule yields sequential.

tmux + long-running safety:
    - Pure Python function, no I/O, no subprocess. Safe under tmux + long-running.
    - Idempotent across re-invocation within a session: byte-identical output.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class DispatchDecision:
    """The classifier's verdict.

    Attributes:
        mode: "sequential" (default) or "parallel".
        reason: One-line human-readable reason, emitted as the first line of
                the build log. Auditable so the user can see why parallelism
                was rejected.
    """
    mode: str
    reason: str


# Minimum N at which parallel is even considered. Below this threshold,
# the (N+1)x supervisor cost exceeds the wall-clock savings on real
# builds (the harness runner pays the orchestrator re-read for every
# sub-agent).
_MIN_PARALLEL_N = 4

# Vague-scope markers: if a step's preamble contains any of these, the
# scope is treated as ambiguous and the classifier falls back to
# sequential. The match is intentionally narrow — substring, not regex —
# so a step that legitimately mentions "TODO" in a comment is not
# penalized. All markers are lowercased; the haystack is lowercased before
# the substring check.
#
# NOTE: single-character markers like "?" are intentionally NOT included.
# A literal "?" appears in URLs (`?foo=bar`), ternary expressions
# (`a ? b : c`), and legitimate documentation questions, none of which
# signal ambiguous scope. Ambiguity is captured by the multi-character
# words below.
_VAGUE_SCOPE_MARKERS = (
    "todo:", "fixme:", "tbd:", "tk:", "maybe", "perhaps", "either",
)


def _has_dependency_edge(steps: list[dict]) -> bool:
    """True if any step declares an explicit or implicit dependency edge.

    Dependency sources checked:
      - `depends_on` list field (explicit, e.g. ["step1", "step3"]).
      - `consumes` string field (implicit: this step consumes another's
        artifact by name reference).

    `depends_on` is constrained to a list per the helper docstring;
    strings (or any other truthy non-list) are ignored — the contract
    is explicit about the type.
    """
    for step in steps:
        deps = step.get("depends_on")
        if isinstance(deps, list) and deps:
            return True
        if step.get("consumes"):
            return True
    return False


def _has_vague_scope(step: dict) -> bool:
    """True if the step's preamble contains a vague-scope marker.

    Looks at `preamble` (string) and `ac` (acceptance criteria list) — if
    either contains a marker, the scope is treated as ambiguous.
    """
    preamble = (step.get("preamble") or "").lower()
    ac = " ".join(step.get("ac") or []).lower()
    haystack = preamble + "\n" + ac
    return any(marker in haystack for marker in _VAGUE_SCOPE_MARKERS)


def _has_overlap(steps: list[dict]) -> bool:
    """True if two steps declare any overlapping `writes:` paths.

    Overlap triggers sequential regardless of whether each step has a
    `partition` field. Partition documents *intent* (this step owns a
    region); overlap on writes is a *factual* collision. When both
    signals disagree, the factual collision wins — the user must split
    the writes or merge the steps before parallel is safe.
    """
    n = len(steps)
    for i in range(n):
        writes_i = set(steps[i].get("writes") or [])
        if not writes_i:
            continue
        for j in range(i + 1, n):
            writes_j = set(steps[j].get("writes") or [])
            if not writes_j:
                continue
            if writes_i & writes_j:
                return True
    return False


def _has_clean_isolation(steps: list[dict]) -> bool:
    """True if every step has either an empty `writes` set or an explicit partition.

    A step with non-empty `writes` and no `partition` is treated as
    sharing the global worktree state — not clean.
    """
    for step in steps:
        writes = step.get("writes") or []
        if writes and not step.get("partition"):
            return False
    return True


def classify(steps: Iterable[dict]) -> DispatchDecision:
    """Classify a batch of build steps as sequential or parallel.

    Priority order (first match wins):
      1. Dependency edge between any pair → sequential.
      2. Any step has vague scope → sequential.
      3. Two steps share declared writes without partition → sequential.
      4. N >= 4 AND every step has clean worktree isolation → parallel.
      5. Otherwise → sequential.

    Args:
        steps: Iterable of step dicts as parsed from index.json. Each step
               may declare: `depends_on`, `consumes`, `preamble`, `ac`,
               `writes`, `partition`. None are required; missing fields
               are treated as empty.

    Returns:
        DispatchDecision with `mode` ("sequential" | "parallel") and a
        `reason` string suitable for the build log's first line.
    """
    steps_list = list(steps)
    n = len(steps_list)

    # Rule 1 — dependency edge.
    if _has_dependency_edge(steps_list):
        return DispatchDecision(
            mode="sequential",
            reason=f"sequential — {n} steps, dependency edge detected",
        )

    # Rule 2 — vague scope.
    for i, step in enumerate(steps_list):
        if _has_vague_scope(step):
            return DispatchDecision(
                mode="sequential",
                reason=f"sequential — step {step.get('step', i + 1)} has vague scope",
            )

    # Rule 3 — overlap on shared writes.
    if _has_overlap(steps_list):
        return DispatchDecision(
            mode="sequential",
            reason=f"sequential — {n} steps, overlapping writes without partition",
        )

    # Rule 4 — clean isolation AND sufficient N.
    if n >= _MIN_PARALLEL_N and _has_clean_isolation(steps_list):
        return DispatchDecision(
            mode="parallel",
            reason=f"parallel — {n} steps, clean worktree isolation",
        )

    # Rule 5 — default sequential.
    suffix = "insufficient N" if n < _MIN_PARALLEL_N else "non-clean isolation"
    return DispatchDecision(
        mode="sequential",
        reason=f"sequential — {n} steps, {suffix}",
    )
