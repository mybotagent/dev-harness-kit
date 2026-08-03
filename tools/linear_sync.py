#!/usr/bin/env python3
"""tools/linear_sync.py — Optional Linear auto-sync for Claude Code tasks.

Triggered by `hooks/linear-autosync.sh` on every Edit|Write|MultiEdit
so that work happening in Claude Code is reflected in the user's
Linear workspace without requiring a manual `/dev-kit:linear` call.
Gated by configuration (non-blocking; users without Linear
configured are unaffected).

# Activation

In priority order (first match wins):

1. `LINEAR_API_KEY` env var present  → enabled.
2. `.dev-kit/.enabled.json` has `mcp.linear` ∈ {`auto`, `on`}  → enabled.
3. otherwise  → no-op (exit 0).

When enabled, `LINEAR_TEAM_ID` and `LINEAR_PROJECT_NAME` env vars
override the auto-detected team / project. The project name defaults
to the canonical repository name (per #539: "A repository whose
Linear project name differs from its canonical repository name gets
a project named exactly after the repository.").

# Task context

The current task is derived from `.dev-kit/hand-off/linear.json`.
That file is the resume hint, not the authorization gate (per
#539: "Existing handoff files are hints only; their presence never
proves that the current task is already registered."). A new task
(e.g. branch change, fresh prompt) replaces the handoff before
this script decides whether to create or update an issue.

# Reconciliation contract

For the full reconciliation rules see `skills/linear/SKILL.md`.
This script's reduced contract:

  1. Find or create the project named after the repository.
  2. Search open issues in that project for a scope match.
  3. Create a new issue when no match exists or the match is stale.
  4. Update an existing issue when the scope still matches.
  5. Write `.dev-kit/hand-off/linear.json` with the result.

# Non-blocking contract

Per #539: "Linear failures are non-blocking for implicit workflow
calls." This script never raises. All failures are reported on
stderr and the exit code is always 0, so a flaky network or
misconfigured token never blocks a real edit.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# Linear API endpoint (https://developers.linear.app/docs/graphql/working-with-the-graphql-api).
_LINEAR_API_URL = "https://api.linear.app/graphql"
_HANDOFF_DIR = Path(".dev-kit") / "hand-off" / "linear"
_CONFIG_REL = Path(".dev-kit") / "linear-config.json"
_ENV_FILE_REL = Path(".dev-kit") / ".env.linear"
_ENABLED_REL = Path(".dev-kit") / ".enabled.json"
_SKIP_MARKERS = ("/", "#", "!", "?", "ls ", "cat ", "grep ", "git status")


def _load_env_file(repo: Path) -> None:
    """Load `KEY=VALUE` pairs from `.dev-kit/.env.linear` into os.environ.

    The file is untracked (`.dev-kit/` is in `.gitignore`) and is a
    fallback for users who do not want `LINEAR_API_KEY` in their
    shell rc-file. Existing env vars win — the file only fills in
    missing values. Values may be quoted with single or double
    quotes; trailing comments (`# ...`) are stripped.
    """
    path = repo / _ENV_FILE_REL
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[key] = value


def _repo_root() -> Path:
    """Return the repository root, falling back to cwd."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return Path(out.decode("utf-8", "ignore").strip() or ".").resolve()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return Path.cwd().resolve()


def _enabled() -> bool:
    """Return True iff Linear auto-sync is configured on for the current worktree.

    Precedence:
      1. Per-worktree `.dev-kit/linear-config.json` (set by `linear on`).
      2. Env var `LINEAR_API_KEY` (presence = enabled). Falls back to
         `.dev-kit/.env.linear` (untracked) if not in the shell env.
      3. Legacy `.dev-kit/.enabled.json:mcp.linear` ∈ {`auto`, `on`}.

    Returns True iff at least one of (1), (2), (3) is enabled AND
    the API key is reachable.
    """
    repo = _repo_root()
    _load_env_file(repo)
    cfg = _read_worktree_config(repo)
    if cfg is not None:
        if not cfg.get("enabled", True):
            return False
        # Worktree config explicitly enables — but still need the API key.
        return bool(os.environ.get("LINEAR_API_KEY", "").strip())
    if os.environ.get("LINEAR_API_KEY", "").strip():
        return True
    enabled_path = repo / _ENABLED_REL
    if not enabled_path.is_file():
        return False
    try:
        legacy = json.loads(enabled_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    mcp = legacy.get("mcp") if isinstance(legacy, dict) else None
    if not isinstance(mcp, dict):
        return False
    state = str(mcp.get("linear", "off")).lower()
    return state in ("auto", "on")


def _read_worktree_config(repo: Path) -> dict[str, Any] | None:
    """Read the per-worktree Linear config at `.dev-kit/linear-config.json`.

    Returns the parsed dict, or `None` if the file is missing / invalid.
    A worktree that has never run `linear on|off|setup` returns None,
    and the sync falls back to env var + legacy `.enabled.json`.
    """
    path = repo / _CONFIG_REL
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_worktree_config(repo: Path, payload: dict[str, Any]) -> Path:
    path = repo / _CONFIG_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def _project_name_override(repo: Path) -> str:
    """Return the user-set project name override, or empty string.

    Resolution order:
      1. `LINEAR_PROJECT_NAME` env var.
      2. `project_name` field of `.dev-kit/linear-config.json`.
    The repo basename is the final fallback in `sync()`.
    """
    env = os.environ.get("LINEAR_PROJECT_NAME", "").strip()
    if env:
        return env
    cfg = _read_worktree_config(repo)
    if cfg is None:
        return ""
    return str(cfg.get("project_name", "")).strip()


def _team_id_override(repo: Path) -> str:
    env = os.environ.get("LINEAR_TEAM_ID", "").strip()
    if env:
        return env
    cfg = _read_worktree_config(repo)
    if cfg is None:
        return ""
    return str(cfg.get("team_id", "")).strip()


def _notes_override(repo: Path) -> str:
    """Return operator-written notes from `.dev-kit/linear-config.json`.

    The `notes` field is free-form Markdown that the operator can
    write per worktree to capture context that the auto-generated
    body cannot derive (narrative, reasoning, follow-up TODOs,
    anything in Korean the operator wants pinned to the issue).
    """
    env = os.environ.get("LINEAR_NOTES", "").strip()
    if env:
        return env
    cfg = _read_worktree_config(repo)
    if cfg is None:
        return ""
    return str(cfg.get("notes", "")).rstrip()


def _should_skip_prompt(prompt: str) -> bool:
    """Filter read-only / non-task prompts (per #539: no Linear for
    inspect / review / security / code-viz unless explicit)."""
    s = prompt.strip().lower()
    if not s:
        return True
    if any(s.startswith(m) for m in _SKIP_MARKERS):
        return True
    # Explicit registration keyword always passes.
    if "/dev-kit:linear" in s or "register in linear" in s:
        return False
    # Heuristic: needs at least one verb that looks like work.
    work_verbs = (
        "implement", "build", "fix", "refactor", "add", "create",
        "update", "remove", "delete", "ship", "migrate", "wire",
        "integrate", "sync", "register", "track",
    )
    return not any(re.search(rf"\b{v}\b", s) for v in work_verbs)


def _read_handoff(repo: Path) -> dict[str, Any] | None:
    path = _handoff_path(repo)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_handoff(repo: Path, payload: dict[str, Any]) -> None:
    path = _handoff_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _main_repo_root(repo: Path) -> Path:
    """Return the main checkout's path, even from inside a linked worktree.

    Discriminator + resolution:
      - `git rev-parse --git-common-dir` returns the main .git/ from
        any worktree of the same repo.
      - `dirname` of that path is the main checkout.
      - In a non-worktree (or single-worktree) repo, the current
        `repo` is the main checkout; return it unchanged.
    """
    try:
        common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(repo), stderr=subprocess.DEVNULL, timeout=2,
        ).decode("utf-8", "ignore").strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return repo
    if not common:
        return repo
    # `git rev-parse --git-common-dir` returns a path that may be
    # relative to the worktree root. Resolve it against the worktree.
    p = Path(common)
    if not p.is_absolute():
        p = (repo / p).resolve()
    return p.parent


def _repo_name(repo: Path) -> str:
    """Canonical repository name = main-checkout basename.

    A worktree at `.worktrees/fix-xxx/` returns the main checkout's
    directory name (e.g. `dev-harness-kit`), NOT the worktree's own
    basename. This is the name Linear projects follow per #539
    ("A repository whose Linear project name differs from its
    canonical repository name gets a project named exactly after the
    repository").
    """
    name = _main_repo_root(repo).name
    if name.startswith(".") and len(name) > 1:
        name = name[1:]
    return name or "repository"


def _current_branch(repo: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo), stderr=subprocess.DEVNULL, timeout=2,
        )
        return out.decode("utf-8", "ignore").strip() or "(detached)"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return "(unknown)"


def _is_main_checkout(repo: Path) -> bool:
    """Return True iff ``repo`` is the main checkout (not a linked worktree).

    Discriminator: ``git rev-parse --git-dir`` returns the main
    checkout's .git/ for the main checkout, and a per-worktree path
    under .git/worktrees/<name>/ for any linked worktree. This is the
    same discriminator used by ``hooks/lib/worktree-detect.sh`` so the
    two rule-paths cannot drift.
    """
    try:
        git_dir = subprocess.check_output(
            ["git", "rev-parse", "--git-dir"],
            cwd=str(repo), stderr=subprocess.DEVNULL, timeout=2,
        ).decode("utf-8", "ignore").strip()
        git_common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(repo), stderr=subprocess.DEVNULL, timeout=2,
        ).decode("utf-8", "ignore").strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False
    if not git_dir or not git_common:
        return False
    return Path(git_dir).resolve() == Path(git_common).resolve()


def _worktree_slug(repo: Path) -> str:
    """Stable, filesystem-safe identifier for the current worktree.

    Main checkout → ``main``. Linked worktree → the trailing path
    segment (e.g. ``fix-linear-autosync-prompt-source``). Falls back
    to a slugified absolute path when neither matches.
    """
    if _is_main_checkout(repo):
        return "main"
    name = repo.name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return cleaned or "worktree"


def _handoff_path(repo: Path) -> Path:
    """Per-worktree handoff path under ``.dev-kit/hand-off/linear/``.

    Each worktree (and the main checkout) gets its own JSON file, so
    two parallel sessions in two worktrees never share or overwrite
    each other's reconciliation state.
    """
    return repo / _HANDOFF_DIR / f"{_worktree_slug(repo)}.json"


def _latest_commit_subject(repo: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=str(repo), stderr=subprocess.DEVNULL, timeout=2,
        )
        return out.decode("utf-8", "ignore").strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _resolve_prompt(repo: Path) -> str:
    """Return a non-empty task description for the current worktree.

    Sources, in priority order:
      1. The active hand-off (``prompt`` field) — set by a prior
         explicit ``/dev-kit:linear`` call or a previous auto-sync round.
      2. The most recent commit subject on the current branch.
      3. The branch name itself (e.g. ``fix/linear-autosync-prompt-source``).

    Without this fallback the script would silently bail on a fresh
    session because nothing populates the hand-off before the first
    Edit|Write fires.
    """
    handoff_prompt = str((_read_handoff(repo) or {}).get("prompt", "")).strip()
    if handoff_prompt:
        return handoff_prompt
    commit_subject = _latest_commit_subject(repo)
    if commit_subject:
        return commit_subject
    return _current_branch(repo)


def _linear_query(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Execute a Linear GraphQL request and return the `data` payload.

    Raises `RuntimeError` on transport / API failures; the caller
    is responsible for translating that into a non-blocking no-op.
    """
    api_key = os.environ.get("LINEAR_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("LINEAR_API_KEY not set")
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        _LINEAR_API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore") if exc.fp else ""
        raise RuntimeError(f"linear http {exc.code}: {body[:300] or exc.reason}") from exc
    if "errors" in payload and payload["errors"]:
        first = payload["errors"][0]
        raise RuntimeError(f"linear graphql: {first.get('message', 'unknown')}")
    return payload.get("data") or {}


def _scope_key(prompt: str, branch: str) -> str:
    """Hash-free scope key for matching an issue to a task.

    Two prompts that share the same scope key map to the same issue.
    Key = `<branch>:: <first 12 words of the prompt, lowercased, alpha-num only>`.
    """
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", prompt.lower()).strip()
    head = " ".join(cleaned.split()[:12])
    return f"{branch}::{head}"


def _resolve_team_id() -> str:
    """Return the team id to use, auto-detecting the first available
    team when the user has not pinned one via env or worktree config.
    Caches the lookup in a module-level variable so subsequent calls
    in the same `sync()` invocation don't re-query."""
    global _TEAM_ID_CACHE
    if _TEAM_ID_CACHE is not None:
        return _TEAM_ID_CACHE
    repo = _repo_root()
    cached = _team_id_override(repo)
    if cached:
        _TEAM_ID_CACHE = cached
        return cached
    data = _linear_query(
        "query { viewer { teams { nodes { id name key } } } }",
        {},
    )
    teams = ((data.get("viewer") or {}).get("teams") or {}).get("nodes") or []
    if not teams:
        raise RuntimeError("linear: no teams visible to this API key")
    _TEAM_ID_CACHE = str(teams[0]["id"])
    return _TEAM_ID_CACHE


_TEAM_ID_CACHE: str | None = None


def _find_or_create_project(repo: Path, team_id: str | None) -> str:
    """Return the project id, creating it if needed."""
    project_name = _project_name_override(repo) or _repo_name(repo)
    query = (
        "query($name: String!) {"
        "  projects(filter: { name: { eq: $name } }, first: 1) {"
        "    nodes { id name }"
        "  }"
        "}"
    )
    data = _linear_query(query, {"name": project_name})
    nodes = (data.get("projects") or {}).get("nodes") or []
    if nodes:
        return str(nodes[0]["id"])
    resolved_team = team_id or _resolve_team_id()
    mutation = (
        "mutation($name: String!, $teamId: String!) {"
        "  projectCreate(input: { name: $name, teamIds: [$teamId] }) {"
        "    project { id }"
        "  }"
        "}"
    )
    data = _linear_query(mutation, {"name": project_name, "teamId": resolved_team})
    return str(data["projectCreate"]["project"]["id"])


def _find_issue(project_id: str, scope_key: str) -> str | None:
    """Return the issue id whose description starts with `scope_key`."""
    query = (
        "query($projectId: ID!) {"
        "  issues(filter: { project: { id: { eq: $projectId } } }, first: 50) {"
        "    nodes { id description }"
        "  }"
        "}"
    )
    data = _linear_query(query, {"projectId": project_id})
    for node in (data.get("issues") or {}).get("nodes") or []:
        desc = str(node.get("description") or "")
        if desc.startswith(f"<!-- scope:{scope_key} -->"):
            return str(node["id"])
    return None


def _create_issue(project_id: str, team_id: str, title: str, body: str, scope_key: str) -> str:
    # Linear's `IssueCreateInput.{teamId, projectId}` are both `String`
    # (NOT `ID!` as in the `issues(filter:)` input). Match the schema.
    mutation = (
        "mutation($teamId: String!, $projectId: String, $title: String!, $body: String!) {"
        "  issueCreate(input: {"
        "    teamId: $teamId"
        "    projectId: $projectId"
        "    title: $title"
        "    description: $body"
        "  }) { issue { id identifier } }"
        "}"
    )
    full_body = f"<!-- scope:{scope_key} -->\n{body}"
    data = _linear_query(mutation, {
        "teamId": team_id,
        "projectId": project_id,
        "title": title,
        "body": full_body,
    })
    issue = data["issueCreate"]["issue"]
    return f"{issue['identifier']} ({issue['id']})"


def _update_issue(issue_ref: str, body: str, project_id: str | None = None) -> None:
    """Update the issue's description (and optionally its project).

    `IssueUpdateInput` is `String!`-typed for the issue id and the
    project id, just like `IssueCreateInput`. Keep these in sync.
    """
    issue_id = issue_ref.split(" ", 1)[-1].strip("()")
    if project_id is not None:
        mutation = (
            "mutation($id: String!, $body: String!, $projectId: String) {"
            "  issueUpdate(id: $id, input: { description: $body, projectId: $projectId }) {"
            "    issue { id identifier project { name } }"
            "  }"
            "}"
        )
        _linear_query(mutation, {"id": issue_id, "body": body, "projectId": project_id})
        return
    mutation = (
        "mutation($id: String!, $body: String!) {"
        "  issueUpdate(id: $id, input: { description: $body }) {"
        "    issue { id }"
        "  }"
        "}"
    )
    _linear_query(mutation, {"id": issue_id, "body": body})


def _summarize_prompt(prompt: str) -> str:
    s = re.sub(r"\s+", " ", prompt.strip())
    return s[:160] + ("…" if len(s) > 160 else "")


def _last_commit_info(repo: Path) -> dict[str, str]:
    """Return short hash + subject + author + relative date for HEAD."""
    info = {"sha": "", "short": "", "subject": "", "author": "", "date": ""}
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%H%n%h%n%s%n%an%n%ar"],
            cwd=str(repo), stderr=subprocess.DEVNULL, timeout=2,
        ).decode("utf-8", "ignore")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return info
    parts = out.split("\n", 4)
    if len(parts) >= 5:
        info["sha"], info["short"], info["subject"], info["author"], info["date"] = parts
    return info


def _changed_files_since(repo: Path, base: str = "origin/main") -> list[tuple[str, int, int]]:
    """Return ``[(path, added, removed), ...]`` for files changed
    since ``base``. Falls back to the empty list if `base` is missing
    or `git` is unavailable. The list is capped at 20 files to keep
    the Linear description under the 64 KiB limit."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--numstat", f"{base}...HEAD"],
            cwd=str(repo), stderr=subprocess.DEVNULL, timeout=2,
        ).decode("utf-8", "ignore")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return []
    rows: list[tuple[str, int, int]] = []
    for line in out.splitlines():
        try:
            added, removed, path = line.split("\t", 2)
        except ValueError:
            continue
        try:
            rows.append((path, int(added or "0"), int(removed or "0")))
        except ValueError:
            rows.append((path, 0, 0))
        if len(rows) >= 20:
            break
    return rows


def _extract_acceptance_criteria(prompt: str, commit_body: str) -> list[str]:
    """Pull `- [ ] …` items out of the commit body or the prompt.

    Order of preference:
      1. Lines from the commit body that look like checkboxes.
      2. Same pattern from the user prompt.
    Each line is returned trimmed; the leading `- [ ] ` is stripped.
    """
    pat = re.compile(r"^[\s>*\-+]*\[[ xX]\]\s+(.+)$")
    found: list[str] = []
    for source in (commit_body, prompt):
        for raw in source.splitlines():
            m = pat.match(raw.strip())
            if m:
                item = m.group(1).strip()
                if item and item not in found:
                    found.append(item)
    return found[:10]


def _commit_body(repo: Path) -> str:
    """Return the body of the latest commit (subject line excluded)."""
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%b"],
            cwd=str(repo), stderr=subprocess.DEVNULL, timeout=2,
        ).decode("utf-8", "ignore").strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return out


def _detect_pr(repo: Path) -> dict[str, str] | None:
    """Auto-detect the GitHub PR for the current branch via `gh`.

    Returns a dict with `url`, `number`, `title`, `state` when a PR
    exists, or `None` when `gh` is missing, the user is not
    authenticated, or there is no PR for the branch. The function
    fails closed: any exception becomes a no-op so auto-sync never
    blocks on a missing CLI.
    """
    try:
        out = subprocess.check_output(
            [
                "gh", "pr", "view", "--json",
                "url,number,title,state,isDraft",
            ],
            cwd=str(repo), stderr=subprocess.DEVNULL, timeout=5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not data.get("url"):
        return None
    return {
        "url": str(data.get("url", "")),
        "number": str(data.get("number", "")),
        "title": str(data.get("title", "")),
        "state": str(data.get("state", "")),
        "draft": "true" if data.get("isDraft") else "false",
    }


def _build_issue_body(*, prompt: str, branch: str, repo: Path, scope: str) -> str:
    """Build a structured Markdown body for the Linear issue.

    Sections, in order: Summary, Context, Files changed, Acceptance
    criteria, Test plan, Related. The scope marker is the first
    line so `_find_issue()` can detect reuse by prefix match.
    """
    summary = _summarize_prompt(prompt)
    commit = _last_commit_info(repo)
    files = _changed_files_since(repo)
    criteria = _extract_acceptance_criteria(_commit_body(repo), prompt)
    pr = _detect_pr(repo)
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    sections: list[str] = [f"<!-- scope:{scope} -->"]

    sections.append("## Summary")
    sections.append(summary)

    sections.append("## Context")
    sections.append(f"- **Branch:** `{branch}`")
    sections.append(f"- **Worktree:** `{repo}`")
    if commit["short"]:
        sections.append(
            f"- **Last commit:** `{commit['short']}` — {commit['subject']}"
        )
        if commit["author"] or commit["date"]:
            sections.append(
                f"  - author: {commit['author']} · {commit['date']}"
            )
    sections.append(f"- **Auto-synced at:** {timestamp}")

    if files:
        sections.append("## Files changed")
        sections.append("| path | + | - |")
        sections.append("|---|---:|---:|")
        for path, added, removed in files:
            sections.append(f"| `{path}` | {added} | {removed} |")

    if criteria:
        sections.append("## Acceptance criteria")
        for item in criteria:
            sections.append(f"- [ ] {item}")

    sections.append("## Test plan")
    sections.append(
        "_Updated automatically by `tools/linear_sync.py`. "
        "Run the suite and paste the exit code + test count here._"
    )

    notes = _notes_override(repo)
    if notes:
        sections.append("## Notes")
        sections.append(notes)

    sections.append("## Related")
    sections.append("- Branch: `" + branch + "`")
    if commit["sha"]:
        sections.append(f"- Commit: `{commit['sha']}`")
    if pr and pr.get("url"):
        state_badge = ""
        if pr["state"].lower() == "merged":
            state_badge = " (merged)"
        elif pr["state"].lower() == "closed":
            state_badge = " (closed)"
        elif pr["draft"] == "true":
            state_badge = " (draft)"
        elif pr["state"]:
            state_badge = f" ({pr['state'].lower()})"
        sections.append(f"- PR: [#{pr['number']}{state_badge}]({pr['url']}) — {pr['title']}")

    sections.append(f"_Last updated: {timestamp}_")
    return "\n\n".join(sections) + "\n"


def sync() -> int:
    """Entry point. Returns 0 always (non-blocking contract)."""
    if not _enabled():
        if os.environ.get("LINEAR_DEBUG", "").strip() == "1":
            print("linear_sync: disabled (no LINEAR_API_KEY, mcp.linear off)", file=sys.stderr)
        return 0
    repo = _repo_root()
    prompt = _resolve_prompt(repo)
    if not prompt or _should_skip_prompt(prompt):
        if os.environ.get("LINEAR_DEBUG", "").strip() == "1":
            print(f"linear_sync: skipped (prompt={prompt!r})", file=sys.stderr)
        return 0
    branch = _current_branch(repo)
    scope = _scope_key(prompt, branch)
    handoff = _read_handoff(repo) or {}
    try:
        team_id = _team_id_override(repo) or None
        project_id = _find_or_create_project(repo, team_id)
        existing = _find_issue(project_id, scope)
        summary = _summarize_prompt(prompt)
        body = _build_issue_body(prompt=prompt, branch=branch, repo=repo, scope=scope)
        if existing:
            _update_issue(existing, body)
            issue_ref = handoff.get("issue") or existing
            action = "updated"
        else:
            title = f"[{branch}] {summary}"[:250]
            resolved_team = team_id or _resolve_team_id()
            issue_ref = _create_issue(project_id, resolved_team, title, body, scope)
            action = "created"
        _write_handoff(repo, {
            "issue": issue_ref,
            "project": _project_name_override(repo) or _repo_name(repo),
            "branch": branch,
            "prompt": prompt,
            "scope": scope,
            "action": action,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        if os.environ.get("LINEAR_DEBUG", "").strip() == "1":
            print(f"linear_sync: {action} {issue_ref} (scope={scope})", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 — non-blocking per #539 design.
        print(f"linear_sync: skipped ({exc.__class__.__name__}: {exc})", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Subcommands: setup|on|off|project-name|status|sync.

    Default (no args, or `sync`) runs the auto-sync once and returns
    its exit code. All other subcommands manipulate the per-worktree
    `.dev-kit/linear-config.json` and exit 0 on success.
    """
    if argv is None:
        argv = sys.argv[1:]
    repo = _repo_root()
    _load_env_file(repo)
    if not argv or argv[0] == "sync":
        return sync()
    cmd, rest = argv[0], argv[1:]
    if cmd == "status":
        cfg = _read_worktree_config(repo)
        env_key = bool(os.environ.get("LINEAR_API_KEY", "").strip())
        env_file = (repo / _ENV_FILE_REL).is_file()
        project = _project_name_override(repo) or _repo_name(repo)
        team = _team_id_override(repo)
        print(json.dumps({
            "worktree": str(repo),
            "slug": _worktree_slug(repo),
            "config": cfg,
            "linear_api_key_set": env_key,
            "env_file_present": env_file,
            "resolved_project": project,
            "resolved_team_id": team or None,
        }, indent=2, sort_keys=True))
        return 0
    if cmd == "on":
        existing = _read_worktree_config(repo) or {}
        path = _write_worktree_config(repo, {
            "enabled": True,
            "project_name": existing.get("project_name", ""),
            "team_id": existing.get("team_id", ""),
            "set_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        print(f"linear: on (worktree={_worktree_slug(repo)} config={path})")
        return 0
    if cmd == "off":
        existing = _read_worktree_config(repo) or {}
        path = _write_worktree_config(repo, {
            "enabled": False,
            "project_name": existing.get("project_name", ""),
            "team_id": existing.get("team_id", ""),
            "set_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        print(f"linear: off (worktree={_worktree_slug(repo)} config={path})")
        return 0
    if cmd == "project-name":
        if not rest:
            current = _project_name_override(repo) or _repo_name(repo)
            print(f"linear: project-name={current} (set with: linear project-name <name>)")
            return 0
        existing = _read_worktree_config(repo) or {}
        name = " ".join(rest).strip()
        path = _write_worktree_config(repo, {
            "enabled": existing.get("enabled", True),
            "project_name": name,
            "team_id": existing.get("team_id", ""),
            "set_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        print(f"linear: project-name={name} (config={path})")
        return 0
    if cmd == "setup":
        # Print the recommended setup steps. The script never reads or
        # writes the API key itself — that stays in the env.
        print("linear: setup checklist")
        print("  Option A — shell env (recommended for shared machines):")
        print("    1. export LINEAR_API_KEY=<your-token>   # required, env-only")
        print(f"    2. cd {repo}")
        print("    3. python3 tools/linear_sync.py on")
        print("    4. python3 tools/linear_sync.py project-name <name>   # optional")
        print()
        print("  Option B — per-worktree env file (recommended for solo dev):")
        print(f"    1. Add to {repo / _ENV_FILE_REL} (untracked, .gitignore'd):")
        print("         LINEAR_API_KEY=<your-token>")
        print("    2. python3 tools/linear_sync.py on")
        print("    3. python3 tools/linear_sync.py project-name <name>   # optional")
        env_key = bool(os.environ.get("LINEAR_API_KEY", "").strip())
        env_file = (repo / _ENV_FILE_REL).is_file()
        print()
        print(f"  LINEAR_API_KEY set: {env_key}")
        print(f"  .dev-kit/.env.linear present: {env_file}")
        cfg = _read_worktree_config(repo)
        print(f"  worktree config: {cfg or '(none — defaults to env-only)'}")
        return 0
    print(f"linear: unknown command {cmd!r} (try: setup|on|off|project-name|status|sync)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
