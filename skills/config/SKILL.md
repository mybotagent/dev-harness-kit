---
name: config
category: config
description: skill + MCP + hook + methodology picker (multiSelect).
alpha: state
when_to_use: |
  - User types /dev-kit:config
allowed-tools: Read Write Edit
model: haiku
disable-model-invocation: false
---
> [← Skills index](../../README.md)

# /dev-kit:config — Inter-Skill Selector

multiSelect 4 questions:
1. Skills — which to enable/disable (default: all ON)
2. MCP — which to enable (default: all OFF)
3. Hook matrix — per-stage hook activation (default: matrix)
4. Methodology — TDD/SDD/DDD/BDD/FDD (default: TDD)

Result → `.dev-kit/.enabled.json` + `.dev-kit/methodology.json` updated.