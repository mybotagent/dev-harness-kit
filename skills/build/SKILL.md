---
name: build
category: build
description: 0-arg. Per-step sub-agent delegation + self-fix loop (MUST-36~38). Uses harness-runner engine. TDD + verify + debug integrated.
when_to_use: |
  - User types /dev-kit:build
  - After plan+design (PRD.md + phases/<name>/ exist)
  - After /dev-kit:ci-setup has written .dev-kit/ci-config.json (REQUIRED — refuse if marker missing or ci_setup_version < "0.1.0")
allowed-tools: Read Write Bash Glob Grep Agent
disallowed-tools: WebFetch
model: opus
disable-model-invocation: false
---

# /dev-kit:build — Step-by-Step Implementation

## Iron Law
**Sub-agent self-fix, single user interrupt, only proceed to next step on AC pass.**
**Pre-flight gate: refuse to start if `.dev-kit/ci-config.json` is absent OR `ci_setup_version` < `0.1.0`. Run `/dev-kit:ci-setup` (or `/dev-kit:ci-setup --force` to refresh stale templates) first.**

## Behavior

1. Harness-runner engine (`lib/execute.py`) auto-invoked.
2. `phases/<name>/index.json` sequential (or `--parallel N` concurrent).
3. Each step = 1 sub-agent (MUST-36):
   - Worktree isolation (MUST-38)
   - AC delegation + 5-field loop semantics (MUST-15)
   - Self-fix loop (MUST-37): lint / test / browser access
   - 3 cycles max (MUST-NOT-9, 10)
4. On PASS, advance to next step automatically. On 3x FAIL, build↔debug hand-off auto.

## Hook integration (Stage B)

| Hook | Mode |
|---|---|
| tdd-guard | ON (when methodology=tdd) |
| bash-guard | ON |
| secret-scan | ON (PostToolUse) |
| slop-detector | ON |
| stop-verify | ON |

## Output

- `phases/<name>/step<N>-output.json` per step (exit code + stdout + stderr + duration)
- `.dev-kit/hand-off/build→review.md` auto
- 2-commit protocol: `feat(scope): step N — <name>` + `chore(scope): step N output`

## Next step

`/dev-kit:review` (3-dim) + `/dev-kit:security` (10-dim) then `/dev-kit:ship`.