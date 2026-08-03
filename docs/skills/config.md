> [← Skills index](README.md) · [Project README](../../README.md)

# `config`

**Category:** `config` · **Alpha:** `state` · **Invocation:** `/dev-kit:config` (human-invoked)

`config` is the inter-skill selector for dev-kit: a multiSelect interview that lets the user turn skills on/off, opt in to MCP servers, choose the per-stage hook matrix, and pick the build methodology, persisting the result to disk.

## When to use it

- The user types `/dev-kit:config`.

## How it works

The skill asks 4 multiSelect questions in sequence:

1. **Skills** — which to enable/disable (default: all ON).
2. **MCP** — which MCP servers to enable (default: all OFF).
3. **Hook matrix** — per-stage hook activation (default: the standard matrix).
4. **Methodology** — TDD / SDD / DDD / BDD / FDD (default: TDD).

The result of the interview is written to `.dev-kit/.enabled.json` (skills + MCP + hook-matrix selections) and `.dev-kit/methodology.json` (the chosen methodology), updating whatever was previously stored.

Linear is an optional MCP integration. Set it to `off` to skip implicit
tracking, `auto` to use it when the connector is available (auto-sync on
every Claude Code edit), or `on` to require the connector and surface
setup problems. The public `/dev-kit:linear` skill can still be invoked
directly and reports setup problems without blocking other skills.

The `auto` mode is implemented by `hooks/linear-autosync.sh` (wired into
PreToolUse Edit|Write|MultiEdit) calling `tools/linear_sync.py`. With
`LINEAR_API_KEY` set, every Claude Code edit auto-creates or auto-updates
a Linear issue under the project named after the repository; without it,
the hook is a fast-path no-op. See `skills/linear/SKILL.md` for the
reconciliation contract.

## Usage

```bash
/dev-kit:config
```

No flags — the skill is a 0-arg interactive picker. `allowed-tools` is `Read Write Edit`.

## Output

`.dev-kit/.enabled.json` and `.dev-kit/methodology.json`, updated in place with the user's selections from the 4-question interview.

## Related

- `.dev-kit/.enabled.json` — stores the skill/MCP/hook-matrix selections this skill writes.
- `.dev-kit/methodology.json` — stores the methodology selection this skill writes.

---
*Source: [`skills/config/SKILL.md`](../../skills/config/SKILL.md)*
