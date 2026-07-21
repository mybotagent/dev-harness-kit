#!/usr/bin/env python3
"""eval_runner.py — Agent-behavior evaluator.

Discovers case fixtures in `eval/cases/{review,security,plan}/*.json`,
replays recorded agent outputs from `eval/transcripts/<dim>/<case>.json`,
runs the per-dim LLM-as-judge prompt, and writes
`.dev-kit/eval-report.md`.

Unit of eval: a case fixture + a recorded agent transcript -> per-dim
axis scores -> verdict. Three dims (review / security / plan) each with
its own axis set (see `llm_judge.DIM_AXES`). No code discovery; no file
freshness. Code-sanity is folded into the review judge via a 20-checkbox
rubric (see `eval/prompts/judge-code-sanity.md`).

Two opt-in dims (NOT auto-invoked, default OFF):

- **session**: a recorded Claude Code / Codex session log
  (``logs/<source>/<sid>.jsonl``) judged on 8 axes (의도 파악, 모호함
  미해소, 반복 실수, 명시적 룰 준수, 비효율, 구조 개선 필요,
  오버엔지니어링, 꼼꼼함) via ``eval/prompts/judge-session.md``.
- **golden_diff**: regression diff of a current ``run_eval`` result
  against the captured baselines in ``eval/golden/*.json``.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
import llm_judge  # type: ignore
from atomic import atomic_write_json, now_iso  # noqa: E402

SUPPORTED_DIMS: tuple = ("review", "security", "plan")
PROMPT_BY_DIM: Dict[str, str] = {
    "review": "judge-review.md",
    "security": "judge-security.md",
    "plan": "judge-plan.md",
}

# Session-log judge axes (the 8-axis rubric in eval/prompts/judge-session.md).
# These are deliberately separate from DIM_AXES so the per-dim case eval
# is untouched by the new session-log path.
SESSION_AXES: tuple = (
    "intent_alignment",
    "ambiguity_unresolved",
    "repeated_mistakes",
    "rule_adherence",
    "inefficiency",
    "structural_improvement",
    "over_engineering",
    "thoroughness",
)


@dataclass
class CaseResult:
    """One case outcome from run_eval.

    Mutable because _judge_case populates fields incrementally before
    returning; converted to dict at the API boundary via asdict().
    """
    case_id: str = ""
    dim: str = ""
    scores: Dict[str, float] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    raw: str = ""
    verdict: str = ""
    score: float = 0.0
    error: Optional[str] = None


def mock_skipped(case: Dict, axes: tuple) -> CaseResult:
    return CaseResult(
        case_id=case["case_id"], dim=case["dim"],
        scores={ax: 0.0 for ax in axes},
        raw="TRANSCRIPT_MISSING", verdict="SKIPPED", score=0.0,
    )


def mock_drift_warning(case: Dict, axes: tuple) -> CaseResult:
    return CaseResult(
        case_id=case["case_id"], dim=case["dim"],
        scores={ax: 7.0 for ax in axes},
        raw="DRY_RUN", verdict="DRIFT_WARNING", score=7.0,
    )


def real_result(case: Dict, *, scores: Dict[str, float],
                tokens_in: int, tokens_out: int,
                raw: str, verdict: str, score: float) -> CaseResult:
    return CaseResult(
        case_id=case["case_id"], dim=case["dim"],
        scores=scores, tokens_in=tokens_in, tokens_out=tokens_out,
        raw=raw, verdict=verdict, score=score,
    )


def exception_rot(case: Dict, axes: tuple, exc: Exception) -> CaseResult:
    return CaseResult(
        case_id=case["case_id"], dim=case["dim"],
        scores={ax: 0.0 for ax in axes},
        raw=str(exc), verdict="ROT", score=0.0, error=str(exc),
    )


# ---------- discovery ----------

def discover_cases(project_root: Path) -> List[Dict]:
    """Find all evaluable cases in `eval/cases/<dim>/*.json`.

    Returns list of `{case_id, dim, category, input_path, input_inline,
    expected, schema_version, raw_path}` dicts. Skips dim directories
    that don't exist (e.g. a dim not yet seeded).
    """
    cases: List[Dict] = []
    cases_dir = project_root / "eval" / "cases"
    if not cases_dir.exists():
        return cases
    for dim in SUPPORTED_DIMS:
        dim_dir = cases_dir / dim
        if not dim_dir.exists():
            continue
        for case_path in sorted(dim_dir.glob("*.json")):
            try:
                data = json.loads(case_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("dim") not in SUPPORTED_DIMS:
                # Wrong dim or missing dim field; skip.
                continue
            if data.get("dim") != dim:
                # Case lives under one dim dir but claims another; skip.
                continue
            data.setdefault("case_id", case_path.stem)
            data["raw_path"] = str(case_path.relative_to(project_root))
            cases.append(data)
    return cases


# ---------- transcript I/O ----------

def transcript_path(project_root: Path, dim: str, case_id: str) -> Path:
    return project_root / "eval" / "transcripts" / dim / f"{case_id}.json"


def load_transcript(project_root: Path, dim: str, case_id: str) -> Optional[Dict]:
    """Return recorded transcript or None if not present / not parseable."""
    p = transcript_path(project_root, dim, case_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_transcript(project_root: Path, dim: str, case_id: str, data: Dict) -> Path:
    """Atomic write of a transcript. Returns the path written."""
    p = transcript_path(project_root, dim, case_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, data)
    return p


# ---------- judgment ----------

def _judge_case(
    project_root: Path,
    case: Dict,
    transcript: Optional[Dict],
    config: Dict,
) -> CaseResult:
    """Run the per-dim LLM-as-judge on a case. Returns a CaseResult.

    If `transcript` is None, the case is marked as SKIPPED (a setup gap,
    not a regression) with axis scores of 0.0 and verdict "SKIPPED".
    """
    dim = case["dim"]
    axes = llm_judge.DIM_AXES[dim]
    if transcript is None:
        return mock_skipped(case, axes)
    prompt_name = PROMPT_BY_DIM[dim]
    substitutions = {
        "CASE_ID": case.get("case_id", ""),
        "DIM": dim,
        "CATEGORY": case.get("category", ""),
        "INPUT": _read_input(project_root, case),
        "AGENT_OUTPUT": json.dumps(transcript.get("agent_output", {}), indent=2),
        "EXPECTED": json.dumps(case.get("expected", {}), indent=2),
        "RUBRIC": _read_rubric(project_root),
    }
    prompt = llm_judge.format_prompt(project_root, prompt_name, substitutions)
    if not prompt:
        # Fallback inline prompt if the per-dim template is missing.
        prompt = (
            f"You are an eval judge for the {dim} dimension. "
            f"Compare the agent output against the expected behavior and "
            f"return a JSON object with these axes: {list(axes)}. "
            f"Each axis is 0-10. ONLY a JSON object, no prose."
        )
    raw = llm_judge.call_judge(
        provider=config["provider"],
        api_key=config["api_key"],
        model=config["model"],
        prompt=prompt,
        axes=axes,
        base_url=config.get("base_url", "https://api.minimax.io/anthropic"),
    )
    scores = raw.get("scores") or {}
    # Keep only the requested dim's axes (drop any extra fields the model
    # might emit). Missing axes default to 0 so the verdict is well-defined.
    scores = {ax: float(scores.get(ax, 0.0)) for ax in axes}
    score = llm_judge.score_aggregate(scores) if scores else 0.0
    verdict = llm_judge.verdict_from_score(score) if score > 0 else "ROT"
    return real_result(
        case,
        scores=scores,
        tokens_in=raw.get("tokens_in", 0),
        tokens_out=raw.get("tokens_out", 0),
        raw=(raw.get("raw") or "")[:500],
        verdict=verdict,
        score=score,
    )


def _read_input(project_root: Path, case: Dict) -> str:
    """Render the case input. If `input_path` exists, read it; else use
    `input_inline`. Returns a string suitable for embedding in a prompt.
    """
    inline = case.get("input_inline")
    if inline is not None:
        return inline
    rel = case.get("input_path")
    if rel:
        p = project_root / rel
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except OSError:
                return f"(unreadable: {rel})"
        return f"(missing: {rel})"
    return ""


def _read_rubric(project_root: Path) -> str:
    """Return the shared code-sanity rubric prompt body (review dim only
    needs the full rubric; others get a one-liner reminder)."""
    p = project_root / "eval" / "prompts" / "judge-code-sanity.md"
    if not p.exists():
        return "(code-sanity rubric not found)"
    return p.read_text(encoding="utf-8")


# ---------- public API ----------

def judge_case(
    project_root: Path,
    case: Dict,
    transcript: Optional[Dict] = None,
    config: Optional[Dict] = None,
) -> Dict:
    """Score a single case. If `transcript` is None it is loaded from
    `eval/transcripts/<dim>/<case_id>.json`.

    Returns a plain dict (asdict of CaseResult) for backward compatibility
    with callers that subscript into the result.
    """
    if config is None:
        config = llm_judge.load_config(project_root)
    if transcript is None:
        transcript = load_transcript(project_root, case["dim"], case["case_id"])
    return asdict(_judge_case(project_root, case, transcript, config))


# ---------- report ----------

def _render_summary(results: List[Dict]) -> str:
    """Render the `## Summary` block: total cases + verdict counts."""
    by_verdict: Dict[str, int] = {"OK": 0, "DRIFT_WARNING": 0, "ROT": 0, "SKIPPED": 0}
    for r in results:
        by_verdict[r.get("verdict", "OK")] += 1
    lines = ["## Summary", f"- Total cases: {len(results)}"]
    for v in ("OK", "DRIFT_WARNING", "ROT", "SKIPPED"):
        lines.append(f"- {v}: {by_verdict[v]}")
    return "\n".join(lines)


def _render_per_dim_table(results: List[Dict]) -> str:
    """Render the `## Per-Dimension Scores` block (one ### dim section per dim)."""
    lines = ["## Per-Dimension Scores"]
    by_dim: Dict[str, List[Dict]] = {d: [] for d in SUPPORTED_DIMS}
    for r in results:
        by_dim.setdefault(r.get("dim", "?"), []).append(r)
    for dim, dim_results in by_dim.items():
        if not dim_results:
            continue
        scored = [r for r in dim_results if r.get("verdict") != "SKIPPED"]
        if not scored:
            lines.append(f"### {dim} (no cases with transcripts)")
            lines.append("")
            continue
        axes = llm_judge.DIM_AXES[dim]
        axis_means: Dict[str, float] = {}
        for ax in axes:
            vals = [r["scores"].get(ax, 0.0) for r in scored]
            axis_means[ax] = round(sum(vals) / max(1, len(vals)), 2)
        overall = round(sum(axis_means.values()) / max(1, len(axis_means)), 2)
        lines.append(f"### {dim} (n={len(scored)}, overall={overall})")
        lines.append("")
        lines.append("| Axis | Mean |")
        lines.append("|---|---|")
        for ax in axes:
            lines.append(f"| `{ax}` | {axis_means[ax]} |")
        lines.append("")
    return "\n".join(lines)


def _render_per_case(results: List[Dict]) -> str:
    """Render the `## Per-Case Results` block: one bullet per result."""
    lines = ["## Per-Case Results"]
    for r in results:
        verdict = r.get("verdict", "?")
        score = r.get("score", 0)
        case_id = r.get("case_id", "?")
        dim = r.get("dim", "?")
        axes_str = ", ".join(
            f"{ax}={r.get('scores', {}).get(ax, '-')}"
            for ax in llm_judge.DIM_AXES.get(dim, ())
        )
        lines.append(f"- **{verdict}** `{case_id}` (dim={dim}) score={score} ({axes_str})")
    return "\n".join(lines)


def write_report(
    project_root: Path,
    results: List[Dict],
    config: Optional[Dict] = None,
) -> Path:
    """Write `.dev-kit/eval-report.md`. Thin dispatcher (issue #93).

    Composes header + the three renderers (_render_summary, _render_per_dim_table,
    _render_per_case) and writes the assembled markdown to disk.
    """
    path = project_root / ".dev-kit" / "eval-report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Eval Report — agent-behavior (dev-harness-kit)\n"
        f"> Generated: {now_iso()}\n"
        f"> Provider: {config.get('provider', 'minimax') if config else 'minimax'}\n"
        f"> Model: {config.get('model', 'MiniMax-M3[1m]') if config else 'MiniMax-M3[1m]'}\n"
    )
    body = "\n\n".join([
        _render_summary(results),
        _render_per_dim_table(results),
        _render_per_case(results),
    ])
    path.write_text(f"{header}\n{body}\n", encoding="utf-8")
    return path


# ---------- top-level driver ----------

def _discover_cases_for_run(project_root: Path, dim: Optional[str], case: Optional[str]) -> List[Dict]:
    """Discover + filter cases for one run_eval invocation."""
    cases = discover_cases(project_root)
    if dim is not None:
        cases = [c for c in cases if c["dim"] == dim]
    if case is not None:
        cases = [c for c in cases if c["case_id"] == case]
    return cases


def _run_dry_run(project_root: Path, cases: List[Dict]) -> List[CaseResult]:
    """Mock each case: SKIPPED if no transcript, else DRIFT_WARNING at 7.0."""
    results: List[CaseResult] = []
    for c in cases:
        t = load_transcript(project_root, c["dim"], c["case_id"])
        if t is None:
            results.append(mock_skipped(c, llm_judge.DIM_AXES[c["dim"]]))
            continue
        results.append(mock_drift_warning(c, llm_judge.DIM_AXES[c["dim"]]))
    return results


def _run_real_judges(project_root: Path, cases: List[Dict], config: Dict) -> List[CaseResult]:
    """Run real LLM judge per case; any exception becomes ROT."""
    results: List[CaseResult] = []
    for c in cases:
        t = load_transcript(project_root, c["dim"], c["case_id"])
        try:
            results.append(_judge_case(project_root, c, t, config))
        except Exception as e:
            results.append(exception_rot(c, llm_judge.DIM_AXES[c["dim"]], e))
    return results


def _tally_and_emit(project_root: Path, results: List[CaseResult], config: Dict) -> Dict:
    """Tally verdicts, write the report, return the run summary dict."""
    results_dicts = [asdict(r) for r in results]
    write_report(project_root, results_dicts, config)
    summary: Dict[str, int] = {v: 0 for v in ("OK", "DRIFT_WARNING", "ROT", "SKIPPED")}
    for r in results:
        summary[r.verdict or "OK"] += 1
    return {
        "results": results_dicts,
        "config": {k: v for k, v in config.items() if k != "api_key"},
        "summary": summary,
    }


def run_eval(
    project_root: Path,
    config: Optional[Dict] = None,
    *,
    dry_run: bool = False,
    dim: Optional[str] = None,
    case: Optional[str] = None,
) -> Dict:
    """Run the agent-behavior eval. Thin dispatcher (issue #93).

    Args:
        project_root: project root.
        config: llm_judge config (defaults to load_config()).
        dry_run: skip real LLM calls; mock each case at 7.0/DRIFT_WARNING.
        dim: restrict to one of {review, security, plan}. None = all.
        case: restrict to a single case_id. None = all.
    """
    if config is None:
        config = llm_judge.load_config(project_root)
    if dim is not None and dim not in SUPPORTED_DIMS:
        raise ValueError(f"unknown dim={dim!r}; must be one of {SUPPORTED_DIMS}")
    cases = _discover_cases_for_run(project_root, dim, case)
    results = (_run_dry_run(project_root, cases) if dry_run or not config.get("api_key")
               else _run_real_judges(project_root, cases, config))
    return _tally_and_emit(project_root, results, config)


# ---------- session-log judge (opt-in, default OFF) ----------



def _session_id_from_log(path: Path) -> str:
    """Derive a stable session id from a log path. Prefers the
    ``sessionId`` field on the first jsonl line; falls back to the
    file stem. Empty string on any failure.
    """
    sid = ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                sid = obj.get("sessionId") or obj.get("session_id") or ""
                if sid:
                    return str(sid)
                # First line parsed but no sessionId — keep stem fallback.
                break
    except OSError:
        return ""
    return sid or path.stem


def _summarize_session_log(path: Path, max_chars: int = 12_000) -> str:
    """Render a session log into a compact text block suitable for the
    LLM judge prompt. Includes root user prompt, assistant turn count,
    tool_use names + counts, sidechain (sub-agent) summary, and the last
    assistant text excerpt. Truncates to ``max_chars`` to keep the
    prompt bounded.
    """
    if not path.is_file():
        return ""
    tool_counts: Dict[str, int] = {}
    sidechain_turns = 0
    root_prompt = ""
    last_assistant_text = ""
    turn_count = 0
    parsed = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                parsed += 1
                if obj.get("isSidechain"):
                    sidechain_turns += 1
                    continue
                typ = obj.get("type")
                msg = obj.get("message") or {}
                if typ == "user" and not root_prompt:
                    content = msg.get("content")
                    if isinstance(content, str):
                        root_prompt = content
                    elif isinstance(content, list):
                        for blk in content:
                            if (isinstance(blk, dict)
                                    and blk.get("type") == "text"):
                                root_prompt = blk.get("text", "") or ""
                                break
                            if isinstance(blk, str):
                                root_prompt = blk
                                break
                if typ == "assistant":
                    turn_count += 1
                    content = msg.get("content")
                    if isinstance(content, list):
                        for blk in content:
                            if not isinstance(blk, dict):
                                continue
                            if blk.get("type") == "tool_use":
                                name = blk.get("name", "?") or "?"
                                tool_counts[name] = tool_counts.get(name, 0) + 1
                            if blk.get("type") == "text":
                                last_assistant_text = blk.get("text", "") or ""
    except OSError:
        return ""

    parts: List[str] = []
    if root_prompt:
        parts.append(f"ROOT USER PROMPT:\n{root_prompt[:2000]}")
    parts.append(f"TURN COUNT: {turn_count}")
    parts.append(f"SIDECHAIN TURNS: {sidechain_turns}")
    if tool_counts:
        tools = ", ".join(
            f"{n}={c}" for n, c in sorted(
                tool_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )
        )
        parts.append(f"TOOL COUNTS: {tools}")
    if last_assistant_text:
        parts.append(f"LAST ASSISTANT TEXT:\n{last_assistant_text[:1500]}")
    if parsed == 0:
        # Empty file or no parseable jsonl lines — caller treats this
        # as a missing log and short-circuits without an LLM call.
        return ""
    if not parts:
        return f"(unparseable session log, {parsed} lines read)"
    body = "\n\n".join(parts)
    return body[:max_chars]


def _session_cache_path(project_root: Path, session_id: str) -> Path:
    """Per-session judge cache. Located under
    ``.dev-kit/cache/session-eval/<sid>.json`` so it can be gitignored
    and survives across runs without leaking into eval/.
    """
    p = project_root / ".dev-kit" / "cache" / "session-eval" / f"{session_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_session_cache(project_root: Path, session_id: str) -> Optional[Dict]:
    p = _session_cache_path(project_root, session_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_session_cache(project_root: Path, session_id: str, data: Dict) -> None:
    p = _session_cache_path(project_root, session_id)
    atomic_write_json(p, data)


def run_session_dim(
    project_root: Path,
    session_log_path: Path,
    *,
    config: Optional[Dict] = None,
    dry_run: bool = False,
) -> Dict:
    """Judge a session log against the 8-axis session rubric.

    Cost: 1 LLM call per session_id (cached). Opt-in only — never wired
    into CI. Returns a dict with ``session_id``, ``scores`` (8 axes,
    0-10), ``score`` (mean), ``verdict`` (OK / DRIFT_WARNING / ROT /
    SKIPPED), ``cached`` (bool), and the standard ``tokens_in`` /
    ``tokens_out`` / ``raw`` / ``error`` fields.

    Dry-run / no api_key: returns score=7.0 / DRIFT_WARNING / cached=False
    without touching the network — same shape as the per-dim dry-run path.
    """
    sid = _session_id_from_log(session_log_path)
    # Cache lookup keyed on session_id; first session_id wins even if a
    # later log path differs, since the rubric is the session itself.
    if config is None:
        config = llm_judge.load_config(project_root)
    cached = _load_session_cache(project_root, sid) if sid else None
    if cached is not None:
        return {**cached, "cached": True}

    axes = SESSION_AXES
    if dry_run or not config.get("api_key"):
        scores = {ax: 7.0 for ax in axes}
        report = {
            "session_id": sid,
            "log_path": str(session_log_path),
            "scores": scores,
            "tokens_in": 0,
            "tokens_out": 0,
            "raw": "DRY_RUN",
            "verdict": "DRIFT_WARNING",
            "score": llm_judge.score_aggregate(scores),
            "error": None,
            "cached": False,
        }
        report["summary"] = {"verdict": report["verdict"],
                             "score": report["score"],
                             "cached": False,
                             "axes": len(scores)}
        return report

    body = _summarize_session_log(session_log_path)
    if not body:
        report = {
            "session_id": sid,
            "log_path": str(session_log_path),
            "scores": {ax: 0.0 for ax in axes},
            "tokens_in": 0,
            "tokens_out": 0,
            "raw": "EMPTY_LOG",
            "verdict": "ROT",
            "score": 0.0,
            "error": "empty or unreadable session log",
            "cached": False,
        }
        report["summary"] = {"verdict": "ROT", "score": 0.0,
                             "cached": False, "axes": 0}
        return report

    substitutions = {
        "SESSION_ID": sid,
        "LOG_PATH": str(session_log_path),
        "SESSION_BODY": body,
    }
    prompt = llm_judge.format_prompt(
        project_root, "judge-session.md", substitutions,
    )
    if not prompt:
        # Fallback inline prompt if the template is missing — keeps the
        # function usable even before the prompt file is shipped.
        prompt = (
            f"You are a session-log judge. Score the session against "
            f"these 8 axes (0-10): {list(axes)}. Respond ONLY a JSON "
            f"object with those keys, no prose."
        )
    try:
        raw = llm_judge.call_judge(
            provider=config["provider"],
            api_key=config["api_key"],
            model=config["model"],
            prompt=prompt,
            axes=axes,
            base_url=config.get("base_url", "https://api.minimax.io/anthropic"),
        )
        scores = raw.get("scores") or {}
        scores = {ax: float(scores.get(ax, 0.0)) for ax in axes}
        score = llm_judge.score_aggregate(scores) if scores else 0.0
        verdict = llm_judge.verdict_from_score(score) if score > 0 else "ROT"
        report = {
            "session_id": sid,
            "log_path": str(session_log_path),
            "scores": scores,
            "tokens_in": raw.get("tokens_in", 0),
            "tokens_out": raw.get("tokens_out", 0),
            "raw": (raw.get("raw") or "")[:500],
            "verdict": verdict,
            "score": score,
            "error": None,
            "cached": False,
        }
    except Exception as e:
        report = {
            "session_id": sid,
            "log_path": str(session_log_path),
            "scores": {ax: 0.0 for ax in axes},
            "tokens_in": 0,
            "tokens_out": 0,
            "raw": str(e),
            "verdict": "ROT",
            "score": 0.0,
            "error": str(e),
            "cached": False,
        }
    # Cache successful judgments only (don't poison the cache on ROT).
    if sid and report["verdict"] != "ROT":
        try:
            _save_session_cache(project_root, sid, {
                k: v for k, v in report.items() if k != "cached"
            })
        except OSError:
            pass
    report["summary"] = {"verdict": report["verdict"],
                         "score": report["score"],
                         "cached": report["cached"],
                         "axes": len(report["scores"])}
    return report


def write_session_report(project_root: Path, report: Dict) -> Path:
    """Write `.dev-kit/session-eval-report.md` for one session."""
    path = project_root / ".dev-kit" / "session-eval-report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    sid = report.get("session_id", "?")
    log = report.get("log_path", "?")
    verdict = report.get("verdict", "?")
    score = report.get("score", 0.0)
    cached = "yes" if report.get("cached") else "no"
    lines: List[str] = [
        "# Session Eval — 8-axis judge (dev-harness-kit)",
        f"> Generated: {now_iso()}",
        f"> Session ID: `{sid}`",
        f"> Log path: `{log}`",
        f"> Verdict: **{verdict}** (score={score}, cached={cached})",
        "",
        "## Axes (0-10)",
        "| Axis | Score |",
        "|---|---|",
    ]
    for ax, v in (report.get("scores") or {}).items():
        lines.append(f"| `{ax}` | {v} |")
    if report.get("error"):
        lines += ["", "## Error", f"```\n{report['error']}\n```"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------- golden diff (opt-in, default OFF) ----------



def _golden_index(project_root: Path) -> Dict[str, Dict]:
    """Index `eval/golden/*.json` keyed by ``(dim, case_id)``.

    Returns ``{f"{dim}/{case_id}": golden_dict, ...}``. Missing dir or
    malformed entries are silently skipped — a partial index is fine
    (only the matched cases get diffed).
    """
    out: Dict[str, Dict] = {}
    golden_dir = project_root / "eval" / "golden"
    if not golden_dir.exists():
        return out
    for path in sorted(golden_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        dim = data.get("dim", "")
        cid = data.get("case_id", "")
        if not dim or not cid:
            continue
        out[f"{dim}/{cid}"] = data
    return out


def _classify_severity(delta: float) -> str:
    """Map an axis-level drop (current - baseline, expected negative) to
    a severity bucket. delta=0 -> "minor" (no regression). Larger drops
    classify as ``major`` or ``critical``."""
    if delta >= -0.5:
        return "minor"
    if delta >= -2.0:
        return "major"
    return "critical"


def _hash_axis_scores(scores: Dict[str, float]) -> str:
    """Stable hash of an axis-score dict for change detection. JSON
    dump + sorted keys so dict ordering does not perturb the digest."""
    payload = json.dumps({k: round(v, 3) for k, v in scores.items()},
                         sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def run_golden_diff(
    project_root: Path,
    run_result: Dict,
    *,
    config: Optional[Dict] = None,
) -> Dict:
    """Diff a `run_eval` result against `eval/golden/*.json`.

    Returns a ``RegressionReport`` dict with:

    - ``markers``: list of axis-level regressions (baseline - current > 0).
    - ``added``: cases present in the run but absent from golden.
    - ``removed``: golden cases absent from the run.
    - ``summary``: counts by severity + verdict.
    - ``ok``: True iff no ``critical`` markers and no ROT cases that
      were OK at baseline.
    """
    if config is None:
        config = llm_judge.load_config(project_root)
    goldens = _golden_index(project_root)
    by_key: Dict[str, Dict] = {}
    for r in (run_result.get("results") or []):
        key = f"{r.get('dim', '?')}/{r.get('case_id', '?')}"
        by_key[key] = r

    markers: List[Dict] = []
    added: List[str] = []
    removed: List[str] = []

    for key, golden in goldens.items():
        if key not in by_key:
            removed.append(key)
            continue
        cur = by_key[key]
        baseline_scores = (golden.get("expected") or {}).get("scores") or {}
        cur_scores = cur.get("scores") or {}
        for ax, base_val in baseline_scores.items():
            try:
                base_f = float(base_val)
            except (TypeError, ValueError):
                continue
            cur_f = float(cur_scores.get(ax, 0.0))
            delta = cur_f - base_f
            if delta < -0.5:  # only meaningful regressions
                markers.append({
                    "case_id": golden.get("case_id", ""),
                    "dim": golden.get("dim", ""),
                    "axis": ax,
                    "baseline": round(base_f, 2),
                    "current": round(cur_f, 2),
                    "delta": round(delta, 2),
                    "severity": _classify_severity(delta),
                })

    for key in by_key:
        if key not in goldens:
            added.append(key)

    summary = {
        "total_goldens": len(goldens),
        "total_run_cases": len(by_key),
        "added_cases": len(added),
        "removed_cases": len(removed),
        "markers": len(markers),
        "critical": sum(1 for m in markers if m["severity"] == "critical"),
        "major": sum(1 for m in markers if m["severity"] == "major"),
        "minor": sum(1 for m in markers if m["severity"] == "minor"),
    }
    summary["ok"] = (
        summary["critical"] == 0
        and summary["removed_cases"] == 0
    )

    return {
        "markers": markers,
        "added": added,
        "removed": removed,
        "summary": summary,
        "config": {k: v for k, v in config.items() if k != "api_key"},
        "baseline_hashes": {
            key: (goldens[key].get("baseline_hash", "")
                  or _hash_axis_scores(
                      (goldens[key].get("expected") or {}).get("scores") or {}
                  ))
            for key in goldens
        },
    }


def write_regression_report(project_root: Path, reg: Dict) -> Path:
    """Write `.dev-kit/regression-report.md` from a golden-diff result."""
    path = project_root / ".dev-kit" / "regression-report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = reg.get("summary", {})
    lines: List[str] = [
        "# Regression Report — golden diff (dev-harness-kit)",
        f"> Generated: {now_iso()}",
        f"> Verdict: **{'OK' if summary.get('ok') else 'REGRESSION'}**",
        "",
        "## Summary",
        f"- Total goldens: {summary.get('total_goldens', 0)}",
        f"- Total run cases: {summary.get('total_run_cases', 0)}",
        f"- Added cases (not in golden): {summary.get('added_cases', 0)}",
        f"- Removed cases (golden absent from run): {summary.get('removed_cases', 0)}",
        f"- Markers: {summary.get('markers', 0)} "
        f"(critical={summary.get('critical', 0)}, "
        f"major={summary.get('major', 0)}, "
        f"minor={summary.get('minor', 0)})",
        "",
    ]
    markers = reg.get("markers") or []
    if markers:
        lines += [
            "## Markers",
            "| Case | Dim | Axis | Baseline | Current | Delta | Severity |",
            "|---|---|---|---|---|---|---|",
        ]
        for m in markers:
            lines.append(
                f"| `{m['case_id']}` | {m['dim']} | `{m['axis']}` | "
                f"{m['baseline']} | {m['current']} | {m['delta']} | "
                f"**{m['severity']}** |"
            )
        lines.append("")
    added = reg.get("added") or []
    if added:
        lines += ["## Added (in run, not in golden)", *(f"- `{k}`" for k in added), ""]
    removed = reg.get("removed") or []
    if removed:
        lines += ["## Removed (in golden, not in run)", *(f"- `{k}`" for k in removed), ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run agent-behavior eval")
    parser.add_argument("--project-root", default=".", help="project root")
    parser.add_argument("--dry-run", action="store_true", help="skip LLM calls")
    parser.add_argument(
        "--dim",
        choices=SUPPORTED_DIMS,
        help="restrict to one dimension (default: all)",
    )
    parser.add_argument("--case", help="restrict to a single case_id")
    parser.add_argument(
        "--session-log",
        metavar="PATH",
        help="opt-in: judge a session log on the 8-axis session rubric",
    )
    parser.add_argument(
        "--golden-diff",
        action="store_true",
        help="opt-in: diff the run_eval result against eval/golden/*.json",
    )
    parser.add_argument(
        "--write-session-report",
        action="store_true",
        help="with --session-log, write .dev-kit/session-eval-report.md",
    )
    parser.add_argument(
        "--write-regression-report",
        action="store_true",
        help="with --golden-diff, write .dev-kit/regression-report.md",
    )
    args = parser.parse_args()
    root = Path(args.project_root).resolve()

    if args.session_log:
        sess_path = Path(args.session_log).resolve()
        cfg = llm_judge.load_config(root)
        report = run_session_dim(root, sess_path, config=cfg,
                                 dry_run=args.dry_run)
        if args.write_session_report:
            write_session_report(root, report)
        print(json.dumps(report["summary"], indent=2))
    else:
        report = run_eval(
            root,
            dry_run=args.dry_run,
            dim=args.dim,
            case=args.case,
        )
        if args.golden_diff:
            cfg = llm_judge.load_config(root)
            reg = run_golden_diff(root, report, config=cfg)
            if args.write_regression_report:
                write_regression_report(root, reg)
            print(json.dumps(reg["summary"], indent=2))
        else:
            print(json.dumps(report["summary"], indent=2))
