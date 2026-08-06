# 0001 - MCP integration is out of scope (intentional)

**Status:** Accepted (2026-08-06)
**Source:** dev-harness-kit slim-sweep review (PR-1)

## Context

The plugin has `commands/`, `skills/`, `hooks/`, `lib/`, `tools/`, `agents/` directories. It does not have an `mcp/` directory or any MCP server entry.

The `/dev-kit:config` skill lists "skill + MCP + hook + methodology picker" but only `skill` and `methodology` are wired. The MCP option in the picker is non-functional.

## Decision

This plugin does not ship an MCP server entry. This is intentional, not deferred.

## Consequences

- `/dev-kit:config` removes the MCP picker option.
- Consumer-repo integration is limited to: slash commands, hooks, and library functions.
- Future contributors should NOT add MCP support without an explicit revisit of this decision.
- The `PreCompletionChecklistMiddleware`, `cost-gate`, and `token-analyzer` continue to be delivered as slash commands + library functions.

## Revisit when

- Three or more consumer-repo requests for MCP integration land.
- The MCP spec stabilizes for plugins carrying hooks/skills bundles (not just standalone servers).
- A new plugin-wide surface (e.g. `commands/<x>.md` -> external API call) requires MCP-level wiring.
