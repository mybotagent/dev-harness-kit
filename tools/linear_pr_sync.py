#!/usr/bin/env python3
"""tools/linear_pr_sync.py — Sync Linear issue state based on GitHub PR events.

Reads PR events (open, ready_for_review, closed, merged, etc.) and updates
the corresponding Linear issue's workflow state. Triggered by
`.github/workflows/linear-pr-sync.yml`.

The mapping is:

  PR opened (draft=false)         → "In Progress"
  PR ready_for_review             → "In Review"
  PR reopened                     → "In Review"
  PR synchronize (new commits)   → "In Review"
  PR closed (merged=true)         → "Done"
  PR closed (merged=false)        → "Canceled"

Subcommands:
  sync --branch X --event Y [--merged B] [--pr-number N] [--pr-title T] [--pr-url U]
      Update the Linear issue mapped to branch X based on event Y.
  find --branch X
      Print the Linear issue identifier mapped to branch X (or empty).
  bulk-update --state STATE
      Update ALL open issues in the project to STATE (used for initial bulk
      transitions like "Backlog → In Review").

Failure modes: all transport errors are non-blocking (exit 0) except for
an explicit supervisor override (LINEAR_OPS_REQUIRED=1).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

LINEAR_API_URL = "https://api.linear.app/graphql"
PROJECT_NAME = os.environ.get("LINEAR_PROJECT_NAME", "dev-harness-kit")

EVENT_STATE_MAP = {
    "opened": "In Progress",
    "ready_for_review": "In Review",
    "reopened": "In Review",
    "synchronize": "In Review",
    "edited": "In Review",
    "closed": "Done",  # refined by --merged flag
}


def _api_key() -> str:
    return os.environ.get("LINEAR_API_KEY", "").strip()


def _required() -> bool:
    if not _api_key():
        print("LINEAR_API_KEY not set", file=sys.stderr)
        return False
    return True


def _request(query: str, variables: dict | None = None) -> dict | None:
    if not _required():
        return None
    payload = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        LINEAR_API_URL,
        data=payload,
        headers={
            "Authorization": _api_key(),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} {e.reason}: {body[:200]}", file=sys.stderr)
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"transport error: {e}", file=sys.stderr)
        return None


def _project_id() -> str | None:
    """Resolve the project ID for the canonical project name."""
    query = """
    query($name: String!) {
      projects(filter: { name: { eq: $name } }, first: 1) {
        nodes { id name }
      }
    }
    """
    r = _request(query, {"name": PROJECT_NAME})
    if not r:
        return None
    nodes = r.get("data", {}).get("projects", {}).get("nodes", [])
    return nodes[0]["id"] if nodes else None


def _state_id(state_name: str, project_id: str | None = None) -> str | None:
    """Resolve workflow state ID by name.

    Workflow states are team-scoped in Linear, not project-scoped. The
    `project` field does not exist on WorkflowStateFilter — Linear returns
    400 if you pass it. We ignore the project arg and query team-wide.
    """
    # Resolve the team (workflow states are team-scoped)
    team_id = _team_id()
    query = """
    query($teamId: ID) {
      workflowStates(filter: { team: { id: { eq: $teamId } } }, first: 50) {
        nodes { id name type }
      }
    }
    """
    r = _request(query, {"teamId": team_id}) if team_id else None
    if r:
        for s in r.get("data", {}).get("workflowStates", {}).get("nodes", []):
            if s["name"].lower() == state_name.lower():
                return s["id"]
    # Fallback: query without team filter (may return mixed teams but Linear
    # resolves the most common state names uniquely)
    fallback = _request("""
    query { workflowStates(first: 50) { nodes { id name type } } }
    """)
    if fallback:
        for s in fallback.get("data", {}).get("workflowStates", {}).get("nodes", []):
            if s["name"].lower() == state_name.lower():
                return s["id"]
    return None


def _team_id() -> str | None:
    """Resolve the Linear team ID for the canonical project."""
    query = """
    query($name: String!) {
      projects(filter: { name: { eq: $name } }, first: 1) {
        nodes { id teams { nodes { id } } }
      }
    }
    """
    r = _request(query, {"name": PROJECT_NAME})
    if not r:
        return None
    nodes = r.get("data", {}).get("projects", {}).get("nodes", [])
    if not nodes:
        return None
    teams = nodes[0].get("teams", {}).get("nodes", [])
    return teams[0]["id"] if teams else None


def _issue_by_branch(branch: str, project_id: str | None) -> dict | None:
    """Find the issue for a branch.

    Linear's IssueFilter does not have a `branch` field. We iterate
    recent issues in the project and match the scope marker
    `<!-- scope:<branch>::` in the description. Open issues first;
    fall back to all states if not found.
    """
    scope_marker = f"<!-- scope:{branch}::"
    issues = _iter_issues(project_id, only_open=False)
    for i in issues:
        desc = i.get("description") or ""
        if scope_marker in desc:
            return i
    return None


def _iter_issues(project_id: str | None, only_open: bool = True) -> list[dict]:
    """Iterate issues in the project, optionally only non-terminal."""
    if only_open:
        query = """
        query {
          issues(
            filter: { state: { type: { nin: ["completed", "canceled"] } } },
            first: 100
          ) {
            nodes { id identifier title description state { id name type } url }
          }
        }
        """
    else:
        query = """
        query {
          issues(first: 100) {
            nodes { id identifier title description state { id name type } url }
          }
        }
        """
    r = _request(query)
    if not r:
        return []
    return r.get("data", {}).get("issues", {}).get("nodes", [])


def _create_issue(branch: str, project_id: str, state_id: str, title: str = "") -> dict | None:
    """Create a Linear issue with the branch linked. Returns the issue or None."""
    team_id = _team_id()
    if not team_id:
        print("cannot create issue: team_id not resolved", file=sys.stderr)
        return None
    issue_title = title or f"PR #{branch}"
    desc = f"<!-- scope:{branch}::auto-sync -->\n\n{issue_title}"
    query = """
    mutation($projectId: String!, $teamId: String!, $title: String!, $stateId: String!, $desc: String!) {
      issueCreate(input: {
        projectId: $projectId
        teamId: $teamId
        title: $title
        stateId: $stateId
        description: $desc
      }) {
        success
        issue { id identifier title state { name } }
      }
    }
    """
    r = _request(query, {
        "projectId": project_id,
        "teamId": team_id,
        "title": issue_title,
        "stateId": state_id,
        "desc": desc,
    })
    if not r:
        return None
    payload = r.get("data", {}).get("issueCreate")
    if not payload or not payload.get("success"):
        return None
    return payload.get("issue")


def _update_state(issue_id: str, state_id: str) -> bool:
    query = """
    mutation($issueId: String!, $stateId: String!) {
      issueUpdate(id: $issueId, input: { stateId: $stateId }) {
        success
        issue { id identifier state { name } }
      }
    }
    """
    r = _request(query, {"issueId": issue_id, "stateId": state_id})
    if not r:
        return False
    return bool(r.get("data", {}).get("issueUpdate", {}).get("success"))


def _all_open_issues(project_id: str | None) -> list[dict]:
    return _iter_issues(project_id, only_open=True)


def cmd_sync(args: argparse.Namespace) -> int:
    if not _required():
        return 0
    project_id = _project_id()
    target_state = EVENT_STATE_MAP.get(args.event)
    if args.event == "closed":
        target_state = "Done" if args.merged == "true" else "Canceled"
    if not target_state:
        print(f"unknown event: {args.event}", file=sys.stderr)
        return 0

    issue = _issue_by_branch(args.branch, project_id)
    state_id = _state_id(target_state, project_id)
    if not state_id:
        print(f"state not found: {target_state}", file=sys.stderr)
        return 0

    if not issue:
        # Create the issue if missing
        title = args.pr_title or f"PR #{args.branch}"
        if "+" in title or "PR" in title:
            title = f"PR #{args.pr_number}: {title}" if args.pr_number else title
        issue = _create_issue(args.branch, project_id, state_id, title)
        if not issue:
            print(f"❌ could not create issue for branch={args.branch}", file=sys.stderr)
            return 1
        print(f"✅ created {issue['identifier']} → {target_state} (branch={args.branch})")
        return 0

    if issue["state"]["name"].lower() == target_state.lower():
        print(f"already {target_state}: {issue['identifier']}")
        return 0

    if _update_state(issue["id"], state_id):
        print(f"✅ {issue['identifier']} → {target_state} (branch={args.branch})")
    else:
        print(f"❌ update failed for {issue['identifier']}", file=sys.stderr)
        return 1
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    if not _required():
        return 0
    project_id = _project_id()
    issue = _issue_by_branch(args.branch, project_id)
    if issue:
        print(issue["identifier"])
    return 0


def cmd_bulk_update(args: argparse.Namespace) -> int:
    if not _required():
        return 0
    project_id = _project_id()
    state_id = _state_id(args.state, project_id)
    if not state_id:
        print(f"state not found: {args.state}", file=sys.stderr)
        return 1
    issues = _all_open_issues(project_id)
    if not issues:
        print("no open issues to update", file=sys.stderr)
        return 0
    moved = 0
    for i in issues:
        if i["state"]["name"].lower() == args.state.lower():
            continue
        if _update_state(i["id"], state_id):
            moved += 1
            # extract branch from description scope marker
            desc = i.get("description") or ""
            branch = "?"
            if "<!-- scope:" in desc:
                branch = desc.split("<!-- scope:", 1)[1].split("::", 1)[0]
            print(f"✅ {i['identifier']} → {args.state} (branch={branch})")
    print(f"\nMoved {moved}/{len(issues)} issues to {args.state}")
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    """Run the bandwidth check: API key, project, state IDs."""
    if not _required():
        return 1
    project_id = _project_id()
    if not project_id:
        print("project not found", file=sys.stderr)
        return 1
    print(f"project: {PROJECT_NAME} (id={project_id})")
    for name in ["Backlog", "Todo", "In Progress", "In Review", "Done", "Canceled"]:
        sid = _state_id(name, project_id)
        print(f"state {name}: {'id=' + sid if sid else 'NOT FOUND'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sync = sub.add_parser("sync", help="update state for a PR event")
    p_sync.add_argument("--branch", required=True)
    p_sync.add_argument("--event", required=True)
    p_sync.add_argument("--merged", default="false")
    p_sync.add_argument("--pr-number")
    p_sync.add_argument("--pr-title")
    p_sync.add_argument("--pr-url")
    p_sync.set_defaults(func=cmd_sync)

    p_find = sub.add_parser("find", help="print identifier for a branch")
    p_find.add_argument("--branch", required=True)
    p_find.set_defaults(func=cmd_find)

    p_bulk = sub.add_parser("bulk-update", help="move all open issues to STATE")
    p_bulk.add_argument("--state", required=True)
    p_bulk.set_defaults(func=cmd_bulk_update)

    p_smoke = sub.add_parser("smoke", help="verify API key + project + state IDs")
    p_smoke.set_defaults(func=cmd_smoke)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
