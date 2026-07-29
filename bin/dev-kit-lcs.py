#!/usr/bin/env python3
"""dev-kit-lcs.py — CLI driver for the Live Context Server (Phase 1.2, issue #347).

Thin launcher wrapping ``lib.lcs_server``. Two surfaces:

  User surface  --list-resources, --describe <name>
                 for terminal-friendly introspection from a human operator.

  Agent surface --get <uri>, --serve
                 for programmatic access from an agent session.
                 ``--serve`` runs a JSON-RPC loop on stdio (MCP-compatible
                 framing: one JSON object per line) until EOF or SIGTERM.

Why a CLI driver (not just an import):
- ``--serve`` lets MCP clients spawn the server as a subprocess without
  embedding the Python runtime — the MCP wire spec is stdio-based.
- ``--list-resources`` / ``--describe`` give humans a discoverability
  surface without writing Python.
- Graceful shutdown on SIGTERM/SIGINT matters for the MCP integration:
  the parent process may terminate us at any time, and we must not
  leave the registry in a half-initialized state.

Resource registration:
- The six production handlers (worktrees, branches, pr, sessions, spend,
  valuations) are registered in the default CLI registry.
- ``DEV_KIT_LCS_DEMO=1`` adds a built-in ``demo`` resource for transport
  regression tests and ad-hoc local debugging.

Exit codes:
  0  success (resource fetched / listed / described)
  1  unknown subcommand or invalid arguments
  2  URI parse error or unknown resource
  3  handler raised an exception
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path

# Make ``import lcs_server`` resolve without an install step. Mirror
# the rest of the bin/ scripts: add the repo's lib/ to sys.path.
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "lib"))

from lcs_resources.branches import BranchesResource  # noqa: E402
from lcs_resources.pr import PRResource  # noqa: E402
from lcs_resources.sessions import SessionsResource  # noqa: E402
from lcs_resources.spend import SpendResource  # noqa: E402
from lcs_resources.valuations import ValuationsResource  # noqa: E402
from lcs_resources.worktrees import WorktreesResource  # noqa: E402
from lcs_server import (  # noqa: E402
    LCSError,
    LCSServer,
    ResourceRegistry,
)

# ──────────────────────────────────────────────────────────────────
# Built-in demo resource (DEV_KIT_LCS_DEMO=1)
# ──────────────────────────────────────────────────────────────────

class _DemoResource:
    """Trivial ``demo`` resource used for testing + ad-hoc debugging.

    Returns ``{"status": "ok", "data": {"echo": <segment>, "args": [...]}}``
    so the test suite can verify wire-format round-trips without
    needing a real upstream resource.
    """

    name = "demo"

    def fetch(self, parsed):
        return {
            "status": "ok",
            "data": {
                "first_segment": parsed.first_segment,
                "path_segments": list(parsed.path_segments),
                "is_collection": parsed.is_collection,
            },
        }


# ──────────────────────────────────────────────────────────────────
# Registered vs reserved route registry (Gap 4, issue #455)
# ──────────────────────────────────────────────────────────────────

# Canonical URI form for every production resource registered by
# ``build_default_registry``. The left column is what an operator
# types; the right column is the resource name the registry walks
# against. ``worktrees`` is the only collection-form resource here —
# the others are item-with-param URIs.
REGISTERED_ROUTE_FORMS: dict[str, str] = {
    "worktrees": "lcs://worktrees",
    "branches":  "lcs://branches/<name>",
    "pr":        "lcs://pr/<n>",
    "sessions":  "lcs://sessions/<id>",
    "spend":     "lcs://spend/<window>",
    "valuations": "lcs://valuations/<plan-id>",
}

# URIs advertised in skills/lcs/SKILL.md but NOT registered in
# ``build_default_registry``. ``--list-routes`` surfaces them under
# "reserved (not implemented)" so operators can distinguish a
# documented-but-unwired URI from a registered one. The list is the
# single source of truth for the SKILL.md reserved section; update
# both together.
RESERVED_ROUTES: tuple[str, ...] = (
    "lcs://hooks/coverage",
    "lcs://interview/<step>",
    "lcs://research/cache",
)


def build_default_registry() -> ResourceRegistry:
    """Build the default registry for the repository containing the CLI."""
    repo_root = Path.cwd()
    logs_root = repo_root / "logs"
    registry = ResourceRegistry()
    registry.register(WorktreesResource(repo_root))
    registry.register(BranchesResource(repo_root))
    registry.register(PRResource(repo_root))
    registry.register(SessionsResource(logs_root))
    registry.register(SpendResource(logs_root))
    registry.register(ValuationsResource(repo_root))
    if os.environ.get("DEV_KIT_LCS_DEMO") == "1":
        registry.register(_DemoResource())
    return registry


# ──────────────────────────────────────────────────────────────────
# User surface
# ──────────────────────────────────────────────────────────────────

def cmd_list_resources(server: LCSServer) -> int:
    """Print a human-readable table of registered resources."""
    registry = server._registry  # noqa: SLF001 — CLI is the registry's user
    if len(registry) == 0:
        print("(no resources registered)")
        return 0
    for name in sorted(registry._by_name):  # noqa: SLF001
        handler = registry._by_name[name]  # noqa: SLF001
        print(f"  {name:32s}  {type(handler).__module__}.{type(handler).__name__}")
    return 0


def cmd_list_routes(server: LCSServer) -> int:
    """Print the registered-vs-reserved split for the LCS URI namespace.

    Registered routes list each live resource alongside its canonical
    URI form, or a generic path form when no canonical template is
    defined. Reserved routes are documented in ``skills/lcs/SKILL.md``
    but are not wired into the default registry; calling them returns
    exit 2. Surfacing them here makes that gap visible from the CLI
    rather than as an exit-code surprise.
    """
    registry = server._registry  # noqa: SLF001 — CLI is the registry's user

    # Registration order is stable, and iterating the live registry keeps
    # optional/debug resources discoverable. Unmapped resources get an
    # explicit generic form instead of disappearing from the listing.
    print("registered:")
    for resource_name in registry._by_name:  # noqa: SLF001
        uri = REGISTERED_ROUTE_FORMS.get(
            resource_name, f"lcs://{resource_name}/<path>",
        )
        print(f"  {uri:32s}{resource_name}")

    # Reserved section: always emits the same set so the listing is
    # deterministic regardless of which production resources are
    # currently registered.
    print("reserved (not implemented):")
    for uri in RESERVED_ROUTES:
        print(f"  {uri}")
    return 0


def cmd_describe(server: LCSServer, name: str) -> int:
    """Print details about one resource."""
    registry = server._registry  # noqa: SLF001
    if name not in registry:
        print(f"error: unknown resource {name!r}", file=sys.stderr)
        print(f"  known: {sorted(registry._by_name)}", file=sys.stderr)  # noqa: SLF001
        return 2
    handler = registry.get(name)
    print(json.dumps({
        "name": handler.name,
        "class": f"{type(handler).__module__}.{type(handler).__name__}",
    }, indent=2))
    return 0


# ──────────────────────────────────────────────────────────────────
# Agent surface
# ──────────────────────────────────────────────────────────────────

def cmd_get(server: LCSServer, uri: str) -> int:
    """Fetch a URI and print the JSON payload to stdout."""
    try:
        payload = server.get(uri)
    except LCSError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}),
              file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2))
    status = payload.get("status")
    if status == "error":
        return 3
    return 0


def cmd_serve(server: LCSServer) -> int:
    """Run a JSON-RPC loop on stdio.

    Wire format (MCP-compatible, simplified): one JSON object per line
    on stdin, one JSON object per line on stdout. Requests MUST have
    ``{"id": <int|str>, "method": <str>, "params": {...}}``; responses
    are ``{"id": ..., "result": ...}`` or ``{"id": ..., "error": ...}``.
    Notifications (no ``id``) are accepted and produce no response.

    Supported methods:
      - ``lcs.get``     params={"uri": "lcs://..."} → returns payload
      - ``lcs.list``    params={} → returns ["resource", "names"]
      - ``lcs.describe`` params={"name": "..."} → returns descriptor dict
    """
    shutdown = {"flag": False}

    def _set_shutdown(signum, frame):  # noqa: ARG001 — signal handler
        shutdown["flag"] = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _set_shutdown)
        except (ValueError, OSError):
            # Not in main thread / not supported on this platform —
            # skip silently. The read loop below also exits on EOF.
            pass

    registry = server._registry  # noqa: SLF001

    for line in sys.stdin:
        if shutdown["flag"]:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({"error": f"parse: {exc}"}) + "\n")
            sys.stdout.flush()
            continue
        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}
        try:
            if method == "lcs.get":
                result = server.get(params["uri"])
            elif method == "lcs.list":
                result = sorted(registry._by_name)  # noqa: SLF001
            elif method == "lcs.describe":
                if params["name"] not in registry:
                    raise LCSError(f"unknown resource {params['name']!r}")
                h = registry.get(params["name"])
                result = {"name": h.name,
                          "class": f"{type(h).__module__}.{type(h).__name__}"}
            else:
                raise LCSError(f"unknown method {method!r}")
        except LCSError as exc:
            if req_id is not None:
                sys.stdout.write(json.dumps(
                    {"id": req_id, "error": str(exc)}
                ) + "\n")
                sys.stdout.flush()
            continue
        except Exception as exc:  # noqa: BLE001
            if req_id is not None:
                sys.stdout.write(json.dumps(
                    {"id": req_id, "error": f"{type(exc).__name__}: {exc}"}
                ) + "\n")
                sys.stdout.flush()
            continue
        if req_id is not None:
            sys.stdout.write(json.dumps(
                {"id": req_id, "result": result}
            ) + "\n")
            sys.stdout.flush()
    return 0


# ──────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dev-kit-lcs",
        description="Live Context Server CLI (Phase 1.2).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list-resources", action="store_true",
                       help="list all registered LCS resources (user surface)")
    group.add_argument("--list-routes", action="store_true",
                       help="print registered + reserved LCS URI routes (user surface)")
    group.add_argument("--describe", metavar="NAME",
                       help="describe one resource (agent surface)")
    group.add_argument("--get", metavar="URI",
                       help="fetch a resource by URI (agent surface)")
    group.add_argument("--serve", action="store_true",
                       help="run JSON-RPC loop on stdio (MCP wire)")
    args = parser.parse_args(argv)

    server = LCSServer(build_default_registry())

    if args.list_resources:
        return cmd_list_resources(server)
    if args.list_routes:
        return cmd_list_routes(server)
    if args.describe is not None:
        return cmd_describe(server, args.describe)
    if args.get is not None:
        return cmd_get(server, args.get)
    if args.serve:
        return cmd_serve(server)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
