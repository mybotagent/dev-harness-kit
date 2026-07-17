#!/usr/bin/env python3
"""session_monitor.py -- inline arrow-key picker over all Claude Code +
Codex sessions in this repo.

Shows every session captured by ``/dev-kit:log`` (running or stopped) across
this repo's worktrees, grouped by git worktree with LIVE / IDLE / STALE
status. Pressing Enter on a session exits the picker and execs
``claude --resume <sid>`` (or ``codex resume <sid>``) with the working
directory set to that session's worktree, so the user lands back inside it.

The UI is a single-pane inline picker (arrow keys to move, Enter to
resume, ``q`` / ``Esc`` / ``Ctrl-C`` to cancel) built directly on
``termios`` + ANSI escapes -- no ``curses``, no third-party deps. The
intent is the same "pick one of N" pattern Claude Code's own
``AskUserQuestion`` uses; rendering stays inside the terminal's normal
scrollback so the user never loses their last command's output.

Stdlib only. All log parsing and worktree classification is reused from
``tools/token_efficiency_analyzer.py`` -- this module adds status
derivation, running-process detection, and the resume hand-off.

Usage::

    python3 tools/session_monitor.py            # interactive picker (real terminal)
    python3 tools/session_monitor.py --list     # non-interactive listing (previewable)
    python3 tools/session_monitor.py --days 90  # widen the capture window

The picker and the ``os.execvp`` resume hand-off both need a real TTY;
they cannot run through a non-interactive harness Bash tool. Use ``--list``
to preview inside a conversation.
"""
from __future__ import annotations

import argparse
import json
import os
import select
import subprocess
import sys
import termios
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

# When run as ``python3 tools/session_monitor.py`` the script's own dir is
# already ``sys.path[0]``; the explicit insert also covers ``import
# session_monitor`` from the test suite (which inserts ``tools/`` on the path).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import token_efficiency_analyzer as tea  # noqa: E402  (path set up above)

# A session with no running process is still "LIVE" if its most recent turn
# landed within this window -- the Stop/SessionEnd hooks fire per turn, so a
# fresh last_ts means the CLI is very likely still open.
RECENCY_WINDOW_SECONDS = 180


class Status(Enum):
    LIVE = "live"
    IDLE = "idle"
    STALE = "stale"


@dataclass
class Session:
    agg: dict
    worktree_state: str
    status: Status
    pids: list[int] = field(default_factory=list)
    wt_path: Path | None = None

    @property
    def session_id(self) -> str:
        return self.agg.get("session_id", "")

    @property
    def source(self) -> str:
        return self.agg.get("source", "claude-code")

    @property
    def worktree(self) -> str:
        return self.agg.get("worktree") or "(unknown)"

    @property
    def branch(self) -> str:
        return self.agg.get("branch") or ""

    @property
    def model(self) -> str:
        return self.agg.get("model") or "?"

    @property
    def last_ts(self):
        return self.agg.get("last_ts")

    @property
    def subagent_count(self) -> int:
        tc = self.agg.get("tool_counts") or {}
        try:
            return int(tc.get("Agent", 0))
        except Exception:
            return 0

    @property
    def log_path(self) -> str:
        return self.agg.get("log_path", "")


@dataclass
class AgentNode:
    tool_use_id: str = ""
    subagent_type: str = ""
    description: str = ""
    prompt_excerpt: str = ""
    turn_count: int = 0
    last_ts: datetime | None = None


@dataclass
class AgentGraph:
    session_id: str
    root_user_prompt: str
    nodes: list[AgentNode]


@dataclass
class WorktreeInfo:
    dirname: str
    state: str
    path: Path | None
    sessions: list[Session]
    last_commit_subject: str | None = None


@dataclass
class ResumeRequest:
    agg: dict
    wt_path: Path | None


# --------------------------------------------------------------------------
# Data collection
# --------------------------------------------------------------------------
def discover_repo_root(start: Path | None = None) -> Path:
    """Resolve the MAIN repo checkout (owner of the shared .git), even when
    invoked from inside a worktree."""
    start = (start or Path.cwd()).resolve()
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse",
             "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).parent
    except Exception:
        pass
    return start


def worktree_paths(repo_root: Path, *, runner=subprocess.run) -> dict[str, Path]:
    """Map worktree dirname (matching ``tea.worktree_from_path``) -> abs path.

    Always includes the ``(main)`` sentinel. Degrades to just ``(main)`` if
    ``git worktree list`` is unavailable."""
    paths: dict[str, Path] = {"(main)": repo_root}
    try:
        out = runner(
            ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return paths
    if out.returncode != 0:
        return paths
    for line in out.stdout.splitlines():
        if line.startswith("worktree "):
            p = Path(line[len("worktree "):].strip())
            name = tea.worktree_from_path(p)
            paths.setdefault(name, p)
    return paths


def _is_cli_process(cmd: str) -> bool:
    """True when the ps command line is a claude/codex CLI (not the desktop
    app, a Helper process, or an unrelated shell that merely mentions them)."""
    low = cmd.lower()
    if "claude.app" in low or "helper" in low or ".vscode" in low:
        return False
    toks = cmd.split()
    if not toks:
        return False
    # Only trust the executable (argv[0]) or an interpreter's script arg.
    return any(Path(t).name in ("claude", "codex") for t in toks[:2])


def _is_resume_process(cmd: str) -> bool:
    padded = " " + cmd + " "
    return " -r " in padded or "--resume" in cmd or " resume " in padded


def list_cli_processes(*, runner=subprocess.run) -> list[dict]:
    """Enumerate running claude/codex CLI processes (read-only)."""
    try:
        out = runner(["ps", "-axo", "pid=,command="],
                     capture_output=True, text=True, timeout=5)
    except Exception:
        return []
    if out.returncode != 0:
        return []
    procs: list[dict] = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid_s, cmd = parts
        if not pid_s.isdigit() or not _is_cli_process(cmd):
            continue
        procs.append({"pid": int(pid_s), "command": cmd,
                      "is_resume": _is_resume_process(cmd)})
    return procs


def pid_cwd(pid: int, *, runner=subprocess.run) -> Path | None:
    """Resolve a process's cwd via ``lsof``. None on any failure."""
    try:
        out = runner(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                     capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        if line.startswith("n"):
            return Path(line[1:])
    return None


def _worktree_for_cwd(cwd: Path, wt_paths: dict[str, Path]) -> str | None:
    """Longest-prefix match of a cwd against known worktree paths."""
    try:
        cwd = cwd.resolve()
    except Exception:
        pass
    best: str | None = None
    best_len = -1
    for name, p in wt_paths.items():
        try:
            pr = p.resolve()
        except Exception:
            pr = p
        if cwd == pr or pr in cwd.parents:
            length = len(str(pr))
            if length > best_len:
                best, best_len = name, length
    return best


def map_processes_to_worktrees(procs: list[dict], wt_paths: dict[str, Path],
                               *, runner=subprocess.run) -> dict[str, list[int]]:
    """Map each running CLI process to the worktree it is cwd'd into.

    Processes whose cwd is outside every known worktree (a different repo)
    are dropped."""
    result: dict[str, list[int]] = {}
    for proc in procs:
        cwd = pid_cwd(proc["pid"], runner=runner)
        if cwd is None:
            continue
        name = _worktree_for_cwd(cwd, wt_paths)
        if name is None:
            continue
        result.setdefault(name, []).append(proc["pid"])
    return result


def derive_status(agg: dict, worktree_state: str, now: datetime) -> Status:
    """Per-session base status: STALE (worktree merged/gone) > LIVE (recent
    turn within the recency window) > IDLE.

    Running-process attribution is applied separately by
    ``attach_live_processes`` because a process is cwd'd into a *worktree*,
    which may hold many sessions -- only the newest one is plausibly the live
    CLI, so a running PID must not blanket-mark every session in the worktree."""
    if worktree_state in tea.STALE_WORKTREE_STATES:
        return Status.STALE
    last = agg.get("last_ts")
    if last is not None:
        try:
            if (now - last).total_seconds() <= RECENCY_WINDOW_SECONDS:
                return Status.LIVE
        except Exception:
            pass
    return Status.IDLE


def attach_live_processes(sessions: list[Session],
                          pid_map: dict[str, list[int]]) -> None:
    """Attribute each worktree's running CLI PIDs to its newest non-stale
    session and mark that one LIVE. Mutates the sessions in place."""
    by_wt: dict[str, list[Session]] = {}
    for s in sessions:
        by_wt.setdefault(s.worktree, []).append(s)
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    for wt, pids in pid_map.items():
        if not pids:
            continue
        cands = [s for s in by_wt.get(wt, []) if s.status is not Status.STALE]
        if not cands:
            continue
        newest = max(cands, key=lambda s: s.last_ts or epoch)
        newest.pids = pids
        newest.status = Status.LIVE


def _enrich_branches_from_worktrees(sessions: list[Session],
                                    *, runner=subprocess.run) -> None:
    """Override each session's branch with the worktree's current HEAD
    branch. The log captures ``branch`` at save-time, which can lag the
    actual checkout (e.g. a session that started on ``main`` before the
    user moved the worktree to a feature branch). Mutates ``agg['branch']``
    in place so the picker, ``--list``, and ``--json`` all show the same
    value. Skips stale (merged/gone) worktrees and detached HEADs. Falls
    back to the log-captured branch on any ``git`` failure.
    """
    by_wt: dict[str, list[Session]] = {}
    for s in sessions:
        by_wt.setdefault(s.worktree, []).append(s)
    for sess_list in by_wt.values():
        first = sess_list[0]
        if first.worktree_state in tea.STALE_WORKTREE_STATES:
            continue
        wt_path = first.wt_path
        if wt_path is None or not Path(wt_path).is_dir():
            continue
        try:
            out = runner(
                ["git", "-C", str(wt_path), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=3,
            )
        except Exception:
            continue
        if out.returncode != 0:
            continue
        branch = out.stdout.strip()
        if not branch or branch == "HEAD":  # detached
            continue
        for s in sess_list:
            s.agg["branch"] = branch


def build_agent_graph(path: Path) -> AgentGraph:
    """Stream one session's jsonl into a parent -> sub-agent graph.

    In the main transcript, ``tool_use`` blocks with ``name == "Agent"`` are
    the spawn edges. ``isSidechain: true`` lines are the sub-agent execution
    transcripts. Sidechain lines are grouped into chains by walking
    ``parentUuid`` links; the k-th spawn is correlated to the k-th chain by
    encounter order (a documented heuristic -- the wire log does not carry the
    parent tool_use id into the sidechain). Codex logs have no sidechains and
    yield an empty node list."""
    root_prompt = ""
    nodes: list[AgentNode] = []
    chains: dict[str, dict] = {}
    order: list[str] = []
    uuid_to_root: dict[str, dict] = {}

    if not Path(path).is_file():
        return AgentGraph(session_id=Path(path).stem, root_user_prompt="", nodes=[])

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue

            if obj.get("isSidechain"):
                uuid = obj.get("uuid") or ""
                parent = obj.get("parentUuid")
                root = uuid_to_root.get(parent) if parent else None
                if root is None:
                    root = uuid or f"chain-{len(order)}"
                    order.append(root)
                    chains[root] = {"turns": 0, "last_ts": None}
                if uuid:
                    uuid_to_root[uuid] = root
                chains[root]["turns"] += 1
                ts = tea.parse_iso(obj.get("timestamp", "") or "")
                if ts and (chains[root]["last_ts"] is None
                           or ts > chains[root]["last_ts"]):
                    chains[root]["last_ts"] = ts
                continue

            typ = obj.get("type")
            msg = obj.get("message") or {}
            if not root_prompt and typ == "user":
                root_prompt = _first_user_text(msg)[:200]
            if typ == "assistant":
                content = msg.get("content")
                if isinstance(content, list):
                    for blk in content:
                        if (isinstance(blk, dict)
                                and blk.get("type") == "tool_use"
                                and blk.get("name") == "Agent"):
                            inp = blk.get("input") or {}
                            nodes.append(AgentNode(
                                tool_use_id=blk.get("id", "") or "",
                                subagent_type=(inp.get("subagent_type")
                                               or inp.get("agentType") or ""),
                                description=inp.get("description", "") or "",
                                prompt_excerpt=(inp.get("prompt", "") or "")[:200],
                            ))

    for i, node in enumerate(nodes):
        if i < len(order):
            ch = chains[order[i]]
            node.turn_count = ch["turns"]
            node.last_ts = ch["last_ts"]

    return AgentGraph(session_id=Path(path).stem,
                      root_user_prompt=root_prompt, nodes=nodes)


def _first_user_text(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text":
                return blk.get("text", "") or ""
            if isinstance(blk, str):
                return blk
    return ""


def build_resume(agg: dict, repo_root: Path,
                 wt_path: Path | None) -> tuple[Path, list[str], str | None]:
    """Return (cwd, argv, warning) for the resume hand-off."""
    sid = agg.get("session_id", "")
    source = agg.get("source", "claude-code")
    if source == "codex":
        argv = ["codex", "resume", sid]
    else:
        argv = ["claude", "--resume", sid]
    if wt_path and Path(wt_path).is_dir():
        return Path(wt_path), argv, None
    warning = (f"worktree '{agg.get('worktree', '?')}' is gone/merged; "
               f"resuming in main checkout {repo_root}")
    return repo_root, argv, warning


def collect_sessions(repo_root: Path, logs_dir: Path,
                     repo: str, days: int) -> list[dict]:
    """discover -> dedupe -> aggregate (skip None) -> date/repo filter."""
    files = tea._dedupe_by_session(tea.discover_logs(logs_dir, repo_root=repo_root))
    aggs = [a for p in files if (a := tea.aggregate_session(p)) is not None]
    return tea.filter_sessions(aggs, repo, days)


def group_by_worktree(sessions: list[Session], wt_meta: dict,
                      wt_paths: dict[str, Path]) -> list[WorktreeInfo]:
    buckets: dict[str, list[Session]] = {}
    for s in sessions:
        buckets.setdefault(s.worktree, []).append(s)

    infos: list[WorktreeInfo] = []
    for name, sess in buckets.items():
        sess.sort(key=lambda s: (s.last_ts or datetime.min.replace(
            tzinfo=timezone.utc)), reverse=True)
        state = wt_meta.get(name, {}).get("state", "unknown")
        path = wt_paths.get(name)
        for s in sess:
            s.wt_path = path
        infos.append(WorktreeInfo(dirname=name, state=state,
                                  path=path, sessions=sess))

    def _rank(info: WorktreeInfo):
        has_live = any(s.status is Status.LIVE for s in info.sessions)
        newest = max((s.last_ts for s in info.sessions if s.last_ts),
                     default=datetime.min.replace(tzinfo=timezone.utc))
        # live worktrees first, then most-recently-active
        return (0 if has_live else 1, _neg_time(newest))

    infos.sort(key=_rank)
    return infos


def _neg_time(dt: datetime) -> float:
    try:
        return -dt.timestamp()
    except Exception:
        return 0.0


def build_model(repo_root: Path, logs_dir: Path, repo: str, days: int,
                *, now: datetime | None = None,
                runner=subprocess.run) -> list[WorktreeInfo]:
    now = now or datetime.now(timezone.utc)
    aggs = collect_sessions(repo_root, logs_dir, repo, days)
    wt_meta = tea.classify_all_worktrees(repo_root, git_runner=runner)
    wt_paths = worktree_paths(repo_root, runner=runner)
    pid_map = map_processes_to_worktrees(
        list_cli_processes(runner=runner), wt_paths, runner=runner)

    sessions: list[Session] = []
    for agg in aggs:
        wt = agg.get("worktree") or "(unknown)"
        state = wt_meta.get(wt, {}).get("state", "unknown")
        sessions.append(Session(agg=agg, worktree_state=state,
                                status=derive_status(agg, state, now)))
    attach_live_processes(sessions, pid_map)
    result = group_by_worktree(sessions, wt_meta, wt_paths)
    _enrich_branches_from_worktrees(sessions, runner=runner)
    attach_last_commit_subjects(result, runner=runner)
    return result


def get_last_commit_subject(wt_path: Path, *,
                            runner=subprocess.run) -> str | None:
    """Resolve the last commit's subject line from a worktree dir.

    Returns ``None`` on any failure (no git, no commits, missing dir,
    subprocess error) so the listing never crashes. The subject line
    is read with ``%s`` so multi-line commit messages are truncated at
    the first newline — only the headline fits in a column.
    """
    if wt_path is None or not Path(wt_path).is_dir():
        return None
    try:
        out = runner(
            ["git", "-C", str(wt_path), "log", "-1", "--pretty=%s"],
            capture_output=True, text=True, timeout=3,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    subj = out.stdout.strip()
    return subj or None


def attach_last_commit_subjects(model: list[WorktreeInfo],
                                *, runner=subprocess.run) -> None:
    """Populate each WorktreeInfo's ``last_commit_subject`` field.

    Resolves the subject once per worktree dir (sessions in the same
    worktree share HEAD) and is a no-op when the path is missing or
    not a git repo. Mutates in place."""
    for w in model:
        w.last_commit_subject = get_last_commit_subject(w.path, runner=runner)


def filter_model(model: list[WorktreeInfo], pattern: str) -> list[WorktreeInfo]:
    """Substring filter (case-insensitive) against every visible session
    field: session_id, branch, model, source, log_path, worktree
    dirname, status. Empty pattern is identity. WorktreeInfo buckets
    whose sessions all fail the filter are dropped entirely."""
    pat = (pattern or "").strip().lower()
    if not pat:
        return list(model)
    out: list[WorktreeInfo] = []
    for w in model:
        kept = [s for s in w.sessions if _session_matches(s, w, pat)]
        if kept:
            out.append(WorktreeInfo(
                dirname=w.dirname, state=w.state, path=w.path,
                sessions=kept, last_commit_subject=w.last_commit_subject,
            ))
    return out


def _session_matches(s: Session, w: WorktreeInfo, pat: str) -> bool:
    haystacks = (
        s.session_id, s.branch, s.model, s.source, s.log_path,
        w.dirname, s.status.value,
    )
    return any(pat in (h or "").lower() for h in haystacks)


# Section labels for the structured listing. Order = display order, which
# also encodes priority (live work first, archived work last). Keep in sync
# with the bucket names emitted by ``group_by_state``.
STATE_SECTIONS = ("live", "merged", "gone", "unknown")


def group_by_state(model: list[WorktreeInfo]) -> list[tuple[str, list[WorktreeInfo]]]:
    """Group worktrees into state sections for the structured listing.

    Returns ``[(section_label, [WorktreeInfo...]), ...]`` in the fixed
    order ``live -> merged -> gone -> unknown``. Sections with no
    worktrees are omitted. Within a section the input ordering is
    preserved (callers like ``group_by_worktree`` already sort by
    recency, so this composes)."""
    buckets: dict[str, list[WorktreeInfo]] = {k: [] for k in STATE_SECTIONS}
    for w in model:
        buckets.setdefault(w.state, []).append(w)
    return [(k, buckets[k]) for k in STATE_SECTIONS if buckets[k]]


# --------------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------------
_GLYPH = {Status.LIVE: "●", Status.IDLE: "○", Status.STALE: "⌀"}


def _rel_time(ts: datetime | None, now: datetime | None = None) -> str:
    if ts is None:
        return "never"
    now = now or datetime.now(timezone.utc)
    try:
        secs = (now - ts).total_seconds()
    except Exception:
        return "?"
    if secs < 0:
        secs = 0
    if secs < 90:
        return f"{int(secs)}s ago"
    if secs < 5400:
        return f"{int(secs // 60)}m ago"
    if secs < 172800:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def _src_tag(source: str) -> str:
    return "cx" if source == "codex" else "cc"


def _column_header(indent: str) -> str:
    """Column-label line aligned to the STATUS/SRC/ID/MODEL/BRANCH/AGE/COMMIT
    fields shared by ``print_plain_listing`` and the inline picker.

    Field widths mirror the data rows exactly: STATUS covers glyph + status
    word (8), SRC (3), ID (9), MODEL (15), BRANCH (23), AGE right-justified
    (9), COMMIT (40, truncated). ``indent`` differs per view (4 spaces for
    ``--list``, 2 for the picker) but every column after it lines up."""
    return (f"{indent}{'STATUS':<8}{'SRC':<4}{'ID':<9}"
            f"{'MODEL':<15}{'BRANCH':<23}{'AGE':>9}  {'COMMIT':<40}")


def _commit_cell(subject: str | None) -> str:
    """Single-cell commit subject, 40-char truncated, '?' when absent."""
    if not subject:
        return "?"
    return subject[:40].ljust(40)


def print_plain_listing(model: list[WorktreeInfo], logs_dir: Path) -> None:
    """Non-interactive listing for previewing inside a conversation (--list).

    Sessions are bucketed by worktree STATE first (live -> merged -> gone
    -> unknown) so the structural picture reads top-down: active work on
    top, archived work at the bottom. Each worktree header shows the
    resolved ``last_commit_subject`` so you can see what each worktree's
    tip is without dropping into git yourself.
    """
    now = datetime.now(timezone.utc)
    total = sum(len(w.sessions) for w in model)
    if total == 0:
        print(f"[session-monitor] no sessions found under {logs_dir}")
        return
    live = sum(1 for w in model for s in w.sessions if s.status is Status.LIVE)
    sections = group_by_state(model)
    print(f"[session-monitor] {total} sessions across {len(model)} worktrees "
          f"({live} live)  logs={logs_dir}")
    for label, wts in sections:
        section_total = sum(len(w.sessions) for w in wts)
        print(f"\n── {label.upper()}  ({len(wts)} worktrees, "
              f"{section_total} sessions) " + "─" * max(0, 56 - len(label)))
        for w in wts:
            tag = f"last: \"{w.last_commit_subject}\"" if w.last_commit_subject else "last: ?"
            print(f"  ▸ {w.dirname}  [{w.state}]  ({len(w.sessions)} sessions)  {tag}")
            print(_column_header("    "))
            for s in w.sessions:
                sub = f" +{s.subagent_count}agt" if s.subagent_count else ""
                print(f"    {_GLYPH[s.status]} {s.status.value:5} "
                      f"{_src_tag(s.source):<3} {s.session_id[:8]} "
                      f"{s.model:14.14} {s.branch:22.22} "
                      f"{_rel_time(s.last_ts, now):>9}  "
                      f"{_commit_cell(w.last_commit_subject)}{sub}")


def print_json(model: list[WorktreeInfo], logs_dir: Path) -> None:
    """Machine-readable JSON for the skill-driven AskUserQuestion picker.

    Carries the full session_id, worktree abs path, and log path so the
    skill can synthesize the exact ``cd <wt> && claude --resume <sid>``
    command without re-running the tool. Stable shape: top-level keys
    ``logs_dir``, ``generated_at``, ``total_sessions``, ``live_sessions``,
    ``worktrees`` (list of worktree records with ``sessions`` list nested).
    """
    now = datetime.now(timezone.utc)
    payload = {
        "logs_dir": str(logs_dir),
        "generated_at": now.isoformat(),
        "total_sessions": sum(len(w.sessions) for w in model),
        "live_sessions": sum(1 for w in model for s in w.sessions
                             if s.status is Status.LIVE),
        "worktrees": [
            {
                "name": w.dirname,
                "state": w.state,
                "path": str(w.path) if w.path else None,
                "last_commit_subject": w.last_commit_subject,
                "has_live": any(s.status is Status.LIVE for s in w.sessions),
                "sessions": [
                    {
                        "session_id": s.session_id,
                        "source": s.source,
                        "branch": s.branch,
                        "model": s.model,
                        "status": s.status.value,
                        "last_ts": s.last_ts.isoformat() if s.last_ts else None,
                        "last_rel": _rel_time(s.last_ts, now),
                        "pids": list(s.pids),
                        "subagent_count": s.subagent_count,
                        "log_path": s.log_path,
                    }
                    for s in w.sessions
                ],
            }
            for w in model
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=False))


# --------------------------------------------------------------------------
# Inline picker (termios + ANSI)
# --------------------------------------------------------------------------
_ANSI = {
    "reset":      "\x1b[0m",
    "bold":       "\x1b[1m",
    "dim":        "\x1b[2m",
    "reverse":    "\x1b[7m",
    "hide_cur":   "\x1b[?25l",
    "show_cur":   "\x1b[?25h",
    "home":       "\x1b[H",
    "clear_eol":  "\x1b[K",
    "green":      "\x1b[32m",
    "yellow":     "\x1b[33m",
    "red":        "\x1b[31m",
    "cyan":       "\x1b[36m",
}

_STATUS_COLOR = {
    Status.LIVE: "green",
    Status.IDLE: "yellow",
    Status.STALE: "red",
}


def build_rows(model: list[WorktreeInfo], *,
               now: datetime | None = None) -> list[dict]:
    """Flatten a worktree model into header + session rows for the picker.

    Pure function -- testable without a TTY. Emits three row kinds:

    - ``"section"`` — top-level bucket label ("LIVE", "MERGED", ...) with
      no ``session`` key; not selectable.
    - ``"header"``  — per-worktree title with state + commit subject; not
      selectable.
    - ``"columns"`` — column-label row beneath each header; not selectable.
    - ``"session"`` — selectable row carrying a ``Session`` payload.

    The picker only lands its cursor on session rows (see
    ``_move_selectable``).
    """
    now = now or datetime.now(timezone.utc)
    rows: list[dict] = []
    sections = group_by_state(model)
    for label, wts in sections:
        section_total = sum(len(w.sessions) for w in wts)
        rows.append({
            "kind": "section",
            "text": (f"── {label.upper()}  ({len(wts)} worktrees, "
                     f"{section_total} sessions) " + "─" * 30),
        })
        for w in wts:
            tag = f"  last: \"{w.last_commit_subject}\"" if w.last_commit_subject else ""
            rows.append({
                "kind": "header",
                "text": (f"  ▸ {w.dirname}  [{w.state}]  "
                         f"({len(w.sessions)} sessions){tag}"),
            })
            rows.append({"kind": "columns", "text": _column_header("  ")})
            for s in w.sessions:
                sub = f" +{s.subagent_count}agt" if s.subagent_count else ""
                rows.append({
                    "kind": "session",
                    "text": (f"  {_GLYPH[s.status]} {s.status.value:5} "
                             f"{_src_tag(s.source):<3} "
                             f"{s.session_id[:8]} {s.model[:14]:14} "
                             f"{s.branch[:22]:22} "
                             f"{_rel_time(s.last_ts, now):>9}  "
                             f"{_commit_cell(w.last_commit_subject)}{sub}"),
                    "session": s,
                })
    return rows


def _selectable_indices(rows: list[dict]) -> list[int]:
    return [i for i, r in enumerate(rows) if r["kind"] == "session"]


def _move_selectable(rows: list[dict], cursor: int, delta: int) -> int:
    """Move the cursor by ``delta`` session rows, never landing on a header."""
    sel = _selectable_indices(rows)
    if not sel:
        return cursor
    if cursor in sel:
        pos = sel.index(cursor)
    else:
        # cursor was on a header; land on the nearest selectable row
        pos = len(sel)
        for j, idx in enumerate(sel):
            if idx >= cursor:
                pos = j
                break
    target = max(0, min(pos + delta, len(sel) - 1))
    return sel[target]


def _terminal_size(fallback: tuple[int, int] = (80, 24)) -> tuple[int, int]:
    try:
        return os.get_terminal_size(0)
    except OSError:
        return fallback


def _render_picker(out, rows: list[dict], cursor: int, scroll: int,
                   max_x: int, max_y: int) -> None:
    """Write the picker frame to ``out`` (one full redraw per call).

    Layout: 1 header line + body + 1 footer line. ``max_x`` and ``max_y``
    are the caller's terminal size in columns / rows; this function does
    not query the terminal itself so the same call can be unit-tested.
    """
    body_h = max(1, max_y - 2)
    sess_total = sum(1 for r in rows if r["kind"] == "session")
    wt_total = sum(1 for r in rows if r["kind"] == "header")
    head = (f" session-monitor  {sess_total} sessions / {wt_total} worktrees ")

    out.write(_ANSI["home"] + _ANSI["hide_cur"])
    out.write(_ANSI["bold"] + _ANSI["cyan"] + head.ljust(max_x) + _ANSI["reset"] + "\n")

    visible_end = min(scroll + body_h, len(rows))
    for i in range(scroll, visible_end):
        r = rows[i]
        text = r["text"][: max_x - 1]
        if r["kind"] in ("section", "header", "columns"):
            out.write(_ANSI["dim"] + text.ljust(max_x) + _ANSI["reset"] + "\n")
            continue
        color = _STATUS_COLOR.get(r["session"].status)
        prefix = _ANSI[color] if color else ""
        if i == cursor:
            out.write(_ANSI["reverse"] + prefix + text.ljust(max_x)
                      + _ANSI["reset"] + "\n")
        else:
            out.write(prefix + text.ljust(max_x) + _ANSI["reset"] + "\n")

    # pad any unused body lines so the footer ends up on the last row
    for _ in range(body_h - (visible_end - scroll)):
        out.write(_ANSI["clear_eol"] + "\n")

    footer = " ↑↓ / j k move   Enter resume   q / Esc / Ctrl-C quit "
    out.write(_ANSI["reverse"] + footer.ljust(max_x) + _ANSI["reset"])
    out.flush()


def _read_key(timeout: float = 0.5) -> bytes:
    """Read one logical keypress from stdin, with timeout.

    Resolves ``ESC [ A/B`` into single bytes ``b"\\x1b[A"`` /
    ``b"\\x1b[B"`` so the caller can match arrow keys directly. A lone
    ``ESC`` (no follow-up byte within 50 ms) is returned as-is.
    """
    rlist, _, _ = select.select([0], [], [], timeout)
    if not rlist:
        return b""
    b = os.read(0, 1)
    if b != b"\x1b":
        return b
    # ESC pressed -- peek for a follow-up byte
    rlist, _, _ = select.select([0], [], [], 0.05)
    if not rlist:
        return b"\x1b"  # lone ESC
    nxt = os.read(0, 1)
    if nxt != b"[":
        return b"\x1b" + nxt
    rlist, _, _ = select.select([0], [], [], 0.05)
    if not rlist:
        return b"\x1b["
    return b"\x1b[" + os.read(0, 1)


def pick_session(model: list[WorktreeInfo]) -> Session | None:
    """Run the inline arrow-key picker. Returns the selected Session, or
    None if the user quit (``q`` / ``Esc`` / ``Ctrl-C``). Always restores
    the original ``termios`` state on exit, even on exception.
    """
    rows = build_rows(model)
    selectable = _selectable_indices(rows)
    if not selectable:
        return None

    cursor = selectable[0]
    scroll = 0

    try:
        saved = termios.tcgetattr(0)
    except termios.error:
        saved = None

    try:
        if saved is not None:
            attrs = termios.tcgetattr(0)
            # Disable canonical mode + echo, but keep ISIG so Ctrl-C
            # still raises KeyboardInterrupt (which the outer try/except
            # catches and turns into a clean None return).
            attrs[3] &= ~(termios.ICANON | termios.ECHO)
            termios.tcsetattr(0, termios.TCSAFLUSH, attrs)

        while True:
            max_x, max_y = _terminal_size()
            # leave 1 row for the prompt below the body if it shrinks
            max_y = max(5, max_y)
            _render_picker(sys.stdout, rows, cursor, scroll, max_x, max_y)

            key = _read_key(0.5)
            if not key:
                continue

            if key in (b"\r", b"\n"):
                return rows[cursor]["session"]
            if key == b"\x1b":
                return None
            if key == b"\x1b[A" or key in (b"k", b"K"):
                cursor = _move_selectable(rows, cursor, -1)
            elif key == b"\x1b[B" or key in (b"j", b"J"):
                cursor = _move_selectable(rows, cursor, +1)
            elif key in (b"q", b"Q"):
                return None
            # ignore everything else (Tab, function keys, etc.)

            body_h = max(1, max_y - 2)
            if cursor < scroll:
                scroll = cursor
            elif cursor >= scroll + body_h:
                scroll = cursor - body_h + 1

    except KeyboardInterrupt:
        return None
    finally:
        if saved is not None:
            try:
                termios.tcsetattr(0, termios.TCSAFLUSH, saved)
            except termios.error:
                pass
        # Show cursor again and drop the picker frame so the resumed CLI
        # starts on a clean line.
        sys.stdout.write(_ANSI["show_cur"] + "\n")
        sys.stdout.flush()


# --------------------------------------------------------------------------
# CLI alias setup (--cli-setup)
# --------------------------------------------------------------------------
CLI_ALIAS_NAME = "session-monitor"
_CLI_BEGIN = "# >>> dev-harness-kit session-monitor alias >>>"
_CLI_END = "# <<< dev-harness-kit session-monitor alias <<<"


def _shell_rc(env=None) -> Path:
    """Best-effort user rc file for the current login shell: ``~/.zshrc``
    for zsh, ``~/.bashrc`` for bash, else ``~/.profile``."""
    env = env if env is not None else os.environ
    shell = env.get("SHELL", "")
    home = Path.home()
    if "zsh" in shell:
        return home / ".zshrc"
    if "bash" in shell:
        return home / ".bashrc"
    return home / ".profile"


def _alias_block(script_path: Path, python_exe: str) -> str:
    """The managed rc block (marker-wrapped) defining the alias."""
    return (f"{_CLI_BEGIN}\n"
            f"alias {CLI_ALIAS_NAME}='{python_exe} {script_path}'\n"
            f"{_CLI_END}")


def _strip_managed_block(text: str) -> str:
    """Remove any prior managed alias block plus trailing blank lines so
    re-running ``--cli-setup`` never duplicates or drifts."""
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        if line.strip() == _CLI_BEGIN:
            skipping = True
            continue
        if skipping:
            if line.strip() == _CLI_END:
                skipping = False
            continue
        out.append(line)
    while out and out[-1].strip() == "":
        out.pop()
    return "\n".join(out)


def _render_rc(existing: str, block: str) -> str:
    """Pure: rc contents with the managed block appended, replacing any
    prior copy. Idempotent -- feeding its own output back yields the same
    string. Always ends with a single trailing newline."""
    base = _strip_managed_block(existing)
    if base:
        return f"{base}\n\n{block}\n"
    return f"{block}\n"


def install_cli_alias(*, script_path: Path | None = None,
                      python_exe: str | None = None,
                      rc: Path | None = None,
                      dry_run: bool = False) -> int:
    """Install (or refresh) the ``session-monitor`` shell alias in the
    user's rc file. Idempotent via marker-wrapped managed block."""
    script_path = script_path or Path(__file__).resolve()
    python_exe = python_exe or sys.executable or "python3"
    rc = rc or _shell_rc()
    block = _alias_block(script_path, python_exe)

    if dry_run:
        print(f"[session-monitor] would write to {rc}:\n")
        print(block)
        print(f"\n[session-monitor] then activate with:  source {rc}")
        return 0

    existing = rc.read_text() if rc.exists() else ""
    verb = "refreshed" if _CLI_BEGIN in existing else "installed"
    rc.write_text(_render_rc(existing, block))
    print(f"[session-monitor] {verb} '{CLI_ALIAS_NAME}' alias in {rc}")
    print(f"  alias {CLI_ALIAS_NAME}='{python_exe} {script_path}'")
    print(f"[session-monitor] activate now:  source {rc}")
    return 0


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------
def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Inline arrow-key picker over Claude Code + Codex sessions "
                    "with worktree-aware resume.")
    p.add_argument("--logs-dir", default="",
                   help="logs root (default: <main-repo>/logs)")
    p.add_argument("--repo", default="",
                   help="filter sessions to this repo name substring")
    p.add_argument("--days", type=int, default=30,
                   help="only sessions active within N days (default 30)")
    p.add_argument("--list", action="store_true",
                   help="print a plain listing instead of the picker")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable JSON (used by the "
                        "/dev-kit:session-monitor skill's AskUserQuestion flow)")
    p.add_argument("--print-resume-command", action="store_true",
                   help="print the cwd + argv that would be exec'd on Enter, "
                        "then exit (no picker, no exec)")
    p.add_argument("--filter", metavar="PATTERN", default="",
                   help="substring filter (case-insensitive) across "
                        "session_id, branch, model, source, log_path, "
                        "worktree, status; empty = show all")
    p.add_argument("--cli-setup", action="store_true",
                   help="install a `session-monitor` shell alias into your rc "
                        "(~/.zshrc or ~/.bashrc; idempotent), then exit")
    p.add_argument("--dry-run", action="store_true",
                   help="with --cli-setup, print the alias block without "
                        "writing to the rc file")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.cli_setup:
        return install_cli_alias(dry_run=args.dry_run)

    repo_root = discover_repo_root()
    logs_dir = Path(args.logs_dir) if args.logs_dir else repo_root / "logs"

    model = build_model(repo_root, logs_dir, args.repo, args.days)

    if args.filter:
        before = sum(len(w.sessions) for w in model)
        model = filter_model(model, args.filter)
        after = sum(len(w.sessions) for w in model)
        if before and not after:
            print(f"[session-monitor] --filter {args.filter!r} matched "
                  f"0 of {before} sessions", file=sys.stderr)

    if args.list:
        print_plain_listing(model, logs_dir)
        return 0

    if args.json:
        print_json(model, logs_dir)
        return 0

    if args.print_resume_command:
        first = next((s for w in model for s in w.sessions), None)
        if first is None:
            print("[session-monitor] no sessions to resume")
            return 0
        cwd, argv, warning = build_resume(first.agg, repo_root, first.wt_path)
        if warning:
            print(f"[session-monitor] {warning}", file=sys.stderr)
        print(f"cd {cwd} && {' '.join(argv)}")
        return 0

    total = sum(len(w.sessions) for w in model)
    if total == 0:
        print(f"[session-monitor] no sessions found under {logs_dir}")
        print("  run /dev-kit:log setup && /dev-kit:log on to start capturing.")
        return 0

    if not sys.stdout.isatty() or not sys.stdin.isatty():
        print("[session-monitor] not a TTY -- run this in a real terminal, "
              "or use --list to preview.", file=sys.stderr)
        print_plain_listing(model, logs_dir)
        return 0

    sel = pick_session(model)
    if sel is None:
        return 0

    cwd, resume_argv, warning = build_resume(sel.agg, repo_root, sel.wt_path)
    if warning:
        print(f"[session-monitor] {warning}", file=sys.stderr)
    try:
        os.chdir(cwd)
        os.execvp(resume_argv[0], resume_argv)
    except FileNotFoundError:
        print(f"[session-monitor] '{resume_argv[0]}' not on PATH. Run manually:\n"
              f"  cd {cwd} && {' '.join(resume_argv)}", file=sys.stderr)
        return 127
    except OSError as exc:
        # Covers ``chdir`` failure (worktree deleted between model build and
        # exec) and any other exec-time OS error.
        print(f"[session-monitor] cannot exec: {exc}. Run manually:\n"
              f"  cd {cwd} && {' '.join(resume_argv)}", file=sys.stderr)
        return 1
    return 0  # unreachable after execvp


if __name__ == "__main__":
    raise SystemExit(main())