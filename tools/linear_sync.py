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
_HANDOFF_REL = Path(".dev-kit") / "hand-off" / "linear.json"
_ENABLED_REL = Path(".dev-kit") / ".enabled.json"
_SKIP_MARKERS = ("/", "#", "!", "?", "ls ", "cat ", "grep ", "git status")


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
    """Return True iff Linear auto-sync is configured on.

    Precedence: env var `LINEAR_API_KEY` wins; otherwise read
    `.dev-kit/.enabled.json` and check `mcp.linear`.
    """
    if os.environ.get("LINEAR_API_KEY", "").strip():
        return True
    enabled_path = _repo_root() / _ENABLED_REL
    if not enabled_path.is_file():
        return False
    try:
        cfg = json.loads(enabled_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    mcp = cfg.get("mcp") if isinstance(cfg, dict) else None
    if not isinstance(mcp, dict):
        return False
    state = str(mcp.get("linear", "off")).lower()
    return state in ("auto", "on")


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
    path = repo / _HANDOFF_REL
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_handoff(repo: Path, payload: dict[str, Any]) -> None:
    path = repo / _HANDOFF_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _repo_name(repo: Path) -> str:
    name = repo.name
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


def _first_prompt(repo: Path) -> str:
    """Read the first user prompt of the session from the active hand-off.

    Falls back to the previous prompt recorded in the handoff.
    """
    handoff = _read_handoff(repo) or {}
    return str(handoff.get("prompt", "")).strip()


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
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode("utf-8"))
    if "errors" in payload and payload["errors"]:
        raise RuntimeError(f"linear graphql: {payload['errors'][0].get('message', 'unknown')}")
    return payload.get("data") or {}


def _scope_key(prompt: str, branch: str) -> str:
    """Hash-free scope key for matching an issue to a task.

    Two prompts that share the same scope key map to the same issue.
    Key = `<branch>:: <first 12 words of the prompt, lowercased, alpha-num only>`.
    """
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", prompt.lower()).strip()
    head = " ".join(cleaned.split()[:12])
    return f"{branch}::{head}"


def _find_or_create_project(repo: Path, team_id: str | None) -> str:
    """Return the project id, creating it if needed."""
    project_name = os.environ.get("LINEAR_PROJECT_NAME", "").strip() or _repo_name(repo)
    query = (
        "query($name: String!, $teamId: String) {"
        "  projects(filter: { name: { eq: $name } }, first: 1) {"
        "    nodes { id name }"
        "  }"
        "}"
    )
    data = _linear_query(query, {"name": project_name, "teamId": team_id})
    nodes = (data.get("projects") or {}).get("nodes") or []
    if nodes:
        return str(nodes[0]["id"])
    mutation = (
        "mutation($name: String!, $teamId: String!) {"
        "  projectCreate(input: { name: $name, teamIds: [$teamId] }) {"
        "    project { id }"
        "  }"
        "}"
    )
    if not team_id:
        raise RuntimeError("LINEAR_TEAM_ID required to create project")
    data = _linear_query(mutation, {"name": project_name, "teamId": team_id})
    return str(data["projectCreate"]["project"]["id"])


def _find_issue(project_id: str, scope_key: str) -> str | None:
    """Return the issue id whose description starts with `scope_key`."""
    query = (
        "query($projectId: String!) {"
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


def _create_issue(project_id: str, title: str, body: str, scope_key: str) -> str:
    mutation = (
        "mutation($projectId: String!, $title: String!, $body: String!) {"
        "  issueCreate(input: { projectId: $projectId, title: $title, description: $body }) {"
        "    issue { id identifier }"
        "  }"
        "}"
    )
    full_body = f"<!-- scope:{scope_key} -->\n{body}"
    data = _linear_query(mutation, {"projectId": project_id, "title": title, "body": full_body})
    issue = data["issueCreate"]["issue"]
    return f"{issue['identifier']} ({issue['id']})"


def _update_issue(issue_ref: str, body: str) -> None:
    issue_id = issue_ref.split(" ", 1)[-1].strip("()")
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


def sync() -> int:
    """Entry point. Returns 0 always (non-blocking contract)."""
    if not _enabled():
        return 0
    repo = _repo_root()
    prompt = _first_prompt(repo)
    if not prompt or _should_skip_prompt(prompt):
        return 0
    branch = _current_branch(repo)
    scope = _scope_key(prompt, branch)
    handoff = _read_handoff(repo) or {}
    try:
        team_id = os.environ.get("LINEAR_TEAM_ID", "").strip() or None
        project_id = _find_or_create_project(repo, team_id)
        existing = _find_issue(project_id, scope)
        summary = _summarize_prompt(prompt)
        body = (
            f"Auto-synced from branch `{branch}`.\n\n"
            f"**Prompt:** {summary}\n\n"
            f"_Last updated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}_"
        )
        if existing:
            _update_issue(existing, body)
            issue_ref = handoff.get("issue") or existing
            action = "updated"
        else:
            title = f"[{branch}] {summary}"[:250]
            issue_ref = _create_issue(project_id, title, body, scope)
            action = "created"
        _write_handoff(repo, {
            "issue": issue_ref,
            "project": os.environ.get("LINEAR_PROJECT_NAME", "").strip() or _repo_name(repo),
            "branch": branch,
            "prompt": prompt,
            "scope": scope,
            "action": action,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
    except Exception as exc:  # noqa: BLE001 — non-blocking per #539 design.
        print(f"linear_sync: skipped ({exc.__class__.__name__}: {exc})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(sync())
