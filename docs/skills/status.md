> [← Skills index](README.md) · [Project README](../../README.md)

# `status`

**Category:** `status` · **Alpha:** `state` · **Invocation:** `/dev-kit:status` (human-invoked)

`status` is a read-only Human-Out-of-The-Loop (HOTL) visualization: it shows the current stage's loop progress, cumulative cycles, the drift/eval score, and the hand-off pointer on one screen, so the user can see where the harness stands without digging through state files.

## When to use it

- The user types `@dev-kit status` (or `/dev-kit:status`) to check current stage progress.

## How it works

The skill is strictly read-only: `allowed-tools` is `Read Grep`, and `Bash`, `Edit`, and `Write` are all disallowed. It reads the harness state and reports, on one screen: the current stage plus loop progress, the cumulative number of cycles run, the drift/eval score, and the next hand-off pointer. It never pushes notifications — it only reports on explicit user invocation, never proactively.

## Usage

```bash
/dev-kit:status
```

No flags — 0-arg, read-only status view.

## Output

A single-screen text summary: current stage, cumulative cycles, drift score, and the hand-off pointer to the next stage/skill.

## Related

- [ci-doctor](ci-doctor.md) — a narrower, CI-specific readiness check, as distinct from this whole-harness stage view.
- `CLAUDE.md` §2 (Active Stage) and §5 (Hand-off Pointer) — the state this skill visualizes.

---
*Source: [`skills/status/SKILL.md`](../../skills/status/SKILL.md)*
