---
name: status
category: status
description: HOTL visualization. Current loop progress + cumulative cycles + hand-off chain + eval score on one screen.
version: 0.1.0
when_to_use: |
  - User types @dev-kit status
allowed-tools: Read Grep
disallowed-tools: Bash Edit Write
model: haiku
disable-model-invocation: false
---

# @dev-kit:status — HOTL visualization

Read-only. Current stage + cumulative cycles + drift score + hand-off pointer.

No push notifications ❌. Only on user invocation.