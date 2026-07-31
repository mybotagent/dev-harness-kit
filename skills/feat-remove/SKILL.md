---
name: feat-remove
category: build
description: DEPRECATED. Use /dev-kit:prune --target <feature> instead.
when_to_use: |
  - User types /dev-kit:feat-remove <feature> (legacy alias)
  - New code should call /dev-kit:prune --target <feature> directly
alpha: state
disable-model-invocation: true
user-invocable: true
---
> [← Skills index](../../README.md)

## Deprecated

`/dev-kit:feat-remove <feature>` is an alias for `/dev-kit:prune --target <feature>`.
The prune skill now owns the single-feature deletion flow (sweep → dependents → report → verify).
See `skills/prune/SKILL.md` for the full pipeline.
