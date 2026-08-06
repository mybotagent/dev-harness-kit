---
name: config
category: config
description: skill + hook + methodology picker (multiSelect).
alpha: state
when_to_use: |
  - User types /dev-kit:config
allowed-tools: Read Write Edit
model: haiku
disable-model-invocation: false
---
> [← Skills index](../../README.md)

# /dev-kit:config — Inter-Skill Selector

multiSelect 3 questions:
1. Skills — which to enable/disable (default: all ON)
2. Hook matrix — per-stage hook activation (default: matrix)
3. Methodology — TDD/SDD/DDD/BDD/FDD (default: TDD)

Result → `.dev-kit/.enabled.json` + `.dev-kit/methodology.json` updated.

For Linear, choose `off` to never call it implicitly, or `auto` to use it when
the connector is available. An explicit `/dev-kit:linear` call remains
available and reports setup problems without blocking other skills.

Note: MCP integration is intentionally out of scope. See
[docs/decisions/0001-no-mcp.md](../../docs/decisions/0001-no-mcp.md).
