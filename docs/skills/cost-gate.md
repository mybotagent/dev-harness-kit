> [← Skills index](README.md) · [Project README](../../README.md)

# `cost-gate`

**Category:** `audit` · **Alpha:** `enforcement` · **Invocation:** `/dev-kit:cost-gate` (human-invoked)

`cost-gate` is a read-only, live cost measurement for the current session. It exists because `/dev-kit:token-analyzer` is post-hoc over historical JSONL logs, while a user mid-session needs to know the running cost before it crosses the warn threshold — and needs the exact git-trailer text to attach to a commit so the PR-level cost aggregator can pick it up.

## When to use it

- The user types `/dev-kit:cost-gate`.
- The user wants to know the running session's cost before it hits the warn threshold.
- The user is about to commit on a PR branch and needs the Cost-gate trailer.
- The user wants visibility into per-session spend without leaving the terminal.

## How it works

The skill reads the live state file at `$CWD/.dev-kit/.cost-gate/state.json` (overridable via `DEV_KIT_COST_GATE_STATE`), and deterministically checks the running cost against two thresholds — session warn (`DEV_KIT_COST_WARN_USD`, default $5) and PR flag (`DEV_KIT_PR_COST_FLAG_USD`, default $20) — printing `ok` or `warn` status in plain text. It then emits the exact two-line git-trailer block a user can paste into a commit message:

```
Cost-gate: $8.42
Cost-gate-Session: <session-id>
```

The skill itself is read-only (`disallowed-tools: Write Edit`); the underlying CLI, `tools/cost_gate_status.py`, also writes nothing on its own — there is no cost hook, and the gate never blocks a tool call. This is deliberately a separate skill from `/dev-kit:token-analyzer` rather than a flag on it: token-analyzer consumes captured JSONL transcripts for a multi-session, multi-day dashboard, while cost-gate reads the live ledger for the running session and emits the trailer block the PR workflow needs — different stages of the same pipeline (preemptive live vs. post-hoc historical), each meriting its own slash command.

## Usage

```bash
/dev-kit:cost-gate [--state PATH] [--json] [--html PATH] [--footer] [--aggregate-pr --bodies-file PATH]
```

| Flag | Default | Purpose |
|---|---|---|
| `--state PATH` | `$CWD/.dev-kit/.cost-gate/state.json` | State file location |
| `--json` | _(off)_ | Machine-readable JSON to stdout |
| `--html PATH` | _(off)_ | Self-contained HTML status (no JS) |
| `--footer` | _(off)_ | Two-line git trailer for commit messages |
| `--aggregate-pr --bodies-file PATH` | _(off)_ | Aggregate Cost-gate trailers across PR commits |

Threshold overrides (env): `DEV_KIT_COST_WARN_USD`, `DEV_KIT_PR_COST_FLAG_USD`. Defaults: session warn $5, PR flag $20.

## Output

```
scope: session  scope_id: sess-abc
status: warn    cost_usd: $5.42
sessions: 1  actual=1  estimated=0
input=12450  output=2100  cache_read=89000
session_warn: $5.00  pr_flag: $20.00
warnings: ['cost $5.42 >= warn $5.00']
state_path: /Users/.../dev-harness-kit/.dev-kit/.cost-gate/state.json
```

The trailer block printed by `--footer` is the input the PR-level cost flag (`.github/workflows/cost-flag.yml`) aggregates. On a PR branch, append it to the commit body:

```bash
git commit -m "feat: thing" -m "$(python3 tools/cost_gate_status.py --footer)"
```

The aggregator dedupes repeated `Cost-gate-Session` snapshots by keeping the maximum cumulative value per session, and applies a `cost-flag` label when cumulative cost exceeds $20.

## Iron Laws

- Read-only: the skill never modifies state; the CLI prints, it does not write.
- No blocking: the cost-gate is observed only — there is no hook and no `session_kill` threshold; it cannot deny a tool call.
- Quote the summary line: the CLI prints `scope=... status=... cost_usd=...` on success; copy it verbatim so the user can audit without re-running.
- Stdout vs stderr contract: the status summary goes to stdout. This skill never emits a deny JSON or non-zero exit code for high cost.

## Related

- `tools/cost_gate_status.py` — CLI driver (stdlib-only).
- `lib/cost_gate.py` — pricing table, transcript scanner, threshold evaluation, footer parsing, PR aggregation; independent of `tools/token_efficiency_analyzer.py`.
- `.github/workflows/cost-flag.yml` — PR-level aggregator that applies the `cost-flag` label above $20 cumulative.
- [token-analyzer](token-analyzer.md) — the post-hoc, multi-session counterpart to this live gate.

---
*Source: [`skills/cost-gate/SKILL.md`](../../skills/cost-gate/SKILL.md)*
