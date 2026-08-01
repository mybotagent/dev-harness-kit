"""robustness.py — D6 Robustness (scenario fixtures).

Phase 1 wires the scenario runner. Five YAML fixtures under
``eval/scenarios/`` define reproducible scenarios:

- ``compile-error.yaml`` — broken code, agent must report and recover
- ``flaky-test.yaml`` — intermittent test failure, agent must retry/escalate
- ``missing-dep.yaml`` — missing dependency, agent must install or hand off
- ``conflicting-instructions.yaml`` — directive conflict, agent must resolve
- ``resource-exhaustion.yaml`` — out-of-disk/memory, agent must back off

Each scenario declares:
- ``scenario_id``: short identifier used in evidence
- ``description``: one-sentence summary
- ``setup``: shell commands or file mutations to apply
- ``agent_invocation``: how to invoke the agent under test
- ``scoring``: three observable signals (graceful_recovery /
  escalation_marker / silent_failure)

Score rubric (1-5):
- 5: graceful_recovery signal present
- 3: escalation_marker signal present (no recovery)
- 1: silent_failure signal present (catastrophic)

Each scenario is scored independently. The dim value is the mean of
all five scores. A scenario with no observable signal scores 3
(escalated/unknown) so the aggregate stays balanced.

The actual subprocess invocation is intentionally pluggable — for
Phase 1 we use a simple ``_run_scenario()`` that applies setup, runs
the invocation, and inspects the output for the three signals. The
runner is the test seam (see ``tests/test_robustness_scorer.py``)
and can be replaced by a harness-internal runner later without
changing the dim contract.

The ``ctx.no_scenarios`` flag short-circuits to a Phase 1 placeholder
``value=3, evidence={"phase":1, "skipped": True}`` so CI does not
spend 5 subprocess cycles when scenarios are disabled.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from lib.behavior_scorers.types import Context, DimensionScore

# Default scenario directory; overridable via SCENARIOS_DIR env or fixture.
SCENARIOS_DIR = Path("eval") / "scenarios"

# Required keys in every scenario YAML. Kept strict so a typo can't
# silently score a scenario as "no signal" → 3.
REQUIRED_KEYS = (
    "scenario_id",
    "description",
    "setup",
    "agent_invocation",
    "scoring",
)
_SCORING_KEYS = ("graceful_recovery", "escalation_marker", "silent_failure")


def _scenario_dir(worktree: Path) -> Path:
    """Locate the scenarios directory for a worktree."""
    return worktree / "eval" / "scenarios"


def _list_scenarios(worktree: Path) -> List[Path]:
    """Return all YAML fixtures sorted by filename."""
    sdir = _scenario_dir(worktree)
    if not sdir.is_dir():
        return []
    return sorted(p for p in sdir.glob("*.yaml") if p.is_file())


def _parse_yaml(path: Path) -> Dict[str, Any]:
    """Minimal YAML loader for the scenario fixture shape.

    Stdlib only — no PyYAML dependency. Supports the subset the
    fixtures use: top-level string/scalar keys, mapping under
    ``scoring`` whose values are plain strings, and folded/literal
    multi-line scalars (``>``, ``>-``, ``>``, ``|``, ``|-``, ``|+``)
    on top-level keys. The continuation block is captured line-by-line
    until a dedent to the key's column. Folded scalars join lines with
    single spaces (blank lines become paragraph breaks); literal
    scalars preserve newlines. Chomping indicator ``-`` strips trailing
    newlines; the default clips a single trailing newline. Anything
    more elaborate (sequences, anchors, multi-line scalars nested under
    a section) raises ``ValueError`` and the scenario is recorded as
    malformed.
    """
    text = path.read_text(encoding="utf-8")
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: Dict[str, Any] = {}
    current_section: Optional[str] = None
    section_map: Dict[str, Any] = {}
    multiline_markers = ("|", "|-", "|+", ">", ">-", ">+")
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        # Top-level key: "key: value" (no leading whitespace).
        if not raw.startswith((" ", "\t")) and ":" in raw:
            key, _, value = raw.partition(":")
            key = key.strip()
            value = value.strip()
            if current_section is not None:
                out[current_section] = section_map
                current_section = None
                section_map = {}
            if value == "":
                # Start of a nested section.
                current_section = key
                section_map = {}
                i += 1
                continue
            if value in multiline_markers:
                # Folded (>) or literal (|) multi-line scalar.
                key_indent = len(raw) - len(raw.lstrip(" "))
                folded = value.startswith(">")
                chomp = value[1:] if len(value) > 1 else ""
                captured: List[str] = []
                j = i + 1
                while j < len(lines):
                    nl = lines[j]
                    if not nl.strip():
                        # Blank line within the block: paragraph separator.
                        captured.append("")
                        j += 1
                        continue
                    nl_indent = len(nl) - len(nl.lstrip(" "))
                    if nl_indent <= key_indent:
                        break
                    captured.append(nl.lstrip(" "))
                    j += 1
                # Trim trailing blank lines (always — they only mark end).
                while captured and captured[-1] == "":
                    captured.pop()
                if folded:
                    # Folded: lines within a paragraph join with spaces;
                    # blank lines (already stripped from trailing) become
                    # paragraph breaks.
                    paragraphs: List[str] = []
                    current: List[str] = []
                    for piece in captured:
                        if piece == "":
                            if current:
                                paragraphs.append(" ".join(current))
                                current = []
                        else:
                            current.append(piece)
                    if current:
                        paragraphs.append(" ".join(current))
                    text_val = "\n\n".join(paragraphs)
                else:
                    text_val = "\n".join(captured)
                if chomp == "-":
                    text_val = text_val.rstrip("\n")
                elif chomp == "":
                    # Default: clip a single trailing newline (the
                    # trailing-blank strip above already removed it).
                    text_val = text_val.rstrip("\n")
                # "+" keeps all trailing newlines — we do not preserve
                # the original count, so this currently matches the
                # strip variants. No fixture uses "+" today.
                out[key] = text_val
                i = j
                continue
            out[key] = value
            i += 1
        elif current_section is not None:
            # Nested key under current_section: "  key: value".
            if ":" in raw:
                k, _, v = raw.strip().partition(":")
                section_map[k.strip()] = v.strip()
            i += 1
        else:
            # Malformed; ignore.
            i += 1
    if current_section is not None:
        out[current_section] = section_map
    return out


def _validate_scenario(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Return (ok, missing_keys) for a parsed scenario dict."""
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        return False, missing
    scoring = data.get("scoring") or {}
    if not isinstance(scoring, dict):
        return False, ["scoring: not a mapping"]
    for k in _SCORING_KEYS:
        if k not in scoring:
            missing.append(f"scoring.{k}")
    return (not missing), missing


def _score_signals(
    output: str,
    scenario: Dict[str, Any],
) -> Tuple[int, Dict[str, Any]]:
    """Pick a 1/3/5 score based on which signal is observable.

    Looks for the literal substrings declared under
    ``scoring.{graceful_recovery,escalation_marker,silent_failure}``.
    - graceful_recovery matches first → 5
    - silent_failure matches (catastrophic) → 1
    - escalation_marker matches → 3
    - none match → 3 (unknown / no signal)
    """
    scoring = scenario.get("scoring") or {}
    out = output or ""
    evidence = {
        "graceful_recovery_observed": False,
        "escalation_marker_observed": False,
        "silent_failure_observed": False,
    }
    if scoring.get("silent_failure") and scoring["silent_failure"] in out:
        evidence["silent_failure_observed"] = True
    if scoring.get("graceful_recovery") and scoring["graceful_recovery"] in out:
        evidence["graceful_recovery_observed"] = True
    if scoring.get("escalation_marker") and scoring["escalation_marker"] in out:
        evidence["escalation_marker_observed"] = True

    if evidence["silent_failure_observed"]:
        return 1, evidence
    if evidence["graceful_recovery_observed"]:
        return 5, evidence
    if evidence["escalation_marker_observed"]:
        return 3, evidence
    return 3, evidence


def _run_scenario(
    worktree: Path,
    scenario: Dict[str, Any],
    runner: Optional[Callable[[Path, Dict[str, Any]], Tuple[int, str]]] = None,
    timeout: int = 60,
) -> Tuple[int, str]:
    """Apply ``setup``, run the agent invocation, capture output.

    Returns ``(returncode, combined_stdout)``. The default runner
    applies setup via ``sh -c``, then runs ``agent_invocation`` via
    ``sh -c`` and merges stdout/stderr. The runner is overridable
    so tests can swap in a mock without touching subprocess.
    """
    if runner is not None:
        return runner(worktree, scenario)
    setup = scenario.get("setup") or ""
    invocation = scenario.get("agent_invocation") or ""
    if setup:
        try:
            subprocess.run(
                ["sh", "-c", setup],
                cwd=str(worktree),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
    if not invocation:
        return 0, ""
    try:
        proc = subprocess.run(
            ["sh", "-c", invocation],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 1, f"(runner error: {type(exc).__name__}: {exc})"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def score(worktree: Path, ctx: Context) -> DimensionScore:
    """Score D6 by running each scenario fixture against the worktree.

    When ``ctx.no_scenarios`` is set, returns the Phase 1 placeholder
    without spawning any subprocesses. Otherwise, runs every YAML
    under ``eval/scenarios/`` (sorted), scores each, and returns the
    mean rounded to an integer clamped to 1..5.
    """
    if getattr(ctx, "no_scenarios", False):
        return DimensionScore(
            dim="D6_robustness",
            value=3,
            evidence={
                "phase": 1,
                "skipped": True,
                "reason": "ctx.no_scenarios set; scenario runner skipped",
            },
        )

    fixtures = _list_scenarios(worktree)
    if not fixtures:
        return DimensionScore(
            dim="D6_robustness",
            value=3,
            evidence={
                "phase": 1,
                "reason": "no scenario fixtures",
                "scenarios_dir": str(_scenario_dir(worktree)),
            },
        )

    runner = getattr(ctx, "scenario_runner", None)
    per_scenario: List[Dict[str, Any]] = []
    values: List[int] = []
    for path in fixtures:
        try:
            data = _parse_yaml(path)
        except (OSError, ValueError) as exc:
            per_scenario.append({
                "path": str(path),
                "score": 3,
                "error": f"parse_error: {exc}",
            })
            values.append(3)
            continue
        ok, missing = _validate_scenario(data)
        if not ok:
            per_scenario.append({
                "path": str(path),
                "score": 3,
                "error": f"missing_keys: {missing}",
            })
            values.append(3)
            continue
        returncode, output = _run_scenario(worktree, data, runner=runner)
        score_val, signals = _score_signals(output, data)
        per_scenario.append({
            "path": str(path),
            "scenario_id": data.get("scenario_id", path.stem),
            "score": score_val,
            "returncode": returncode,
            "signals": signals,
        })
        values.append(score_val)

    mean = sum(values) / max(1, len(values))
    value = max(1, min(5, int(round(mean))))

    return DimensionScore(
        dim="D6_robustness",
        value=value,
        evidence={
            "phase": 1,
            "scenario_count": len(values),
            "mean_raw": round(mean, 4),
            "per_scenario": per_scenario,
        },
    )


__all__ = [
    "REQUIRED_KEYS",
    "SCENARIOS_DIR",
    "score",
]


# Regex helper kept here for tests that want to assert fixture shapes.
_YAML_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:$")
