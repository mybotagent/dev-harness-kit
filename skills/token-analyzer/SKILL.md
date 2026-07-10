---
name: token-analyzer
category: audit
description: 0-arg token-efficiency dashboard. Runs tools/token_efficiency_analyzer.py over logs/{claude-code,codex}/*.jsonl to produce one self-contained HTML report -- 4-dim session scoring, 6 anti-pattern warnings, USD savings estimate.
when_to_use: |
  - User types /dev-kit:token-analyzer
  - User wants to know where token spend is going in their Claude Code / Codex sessions
  - User suspects prefix misalignment, redundant Read, or model overspec patterns
  - Pre-release FinOps review of session-level cost
allowed-tools: Read Bash
disallowed-tools: Write Edit
model: haiku
user-invocable: true
---

# /dev-kit:token-analyzer -- token efficiency dashboard

Generate a self-contained HTML dashboard that turns the JSONL session
transcripts captured by `/dev-kit:log` into a per-repository, last-N-days
view of token spend, session efficiency, and anti-patterns. Distinct
human action ("see the spend picture") with a distinct artifact (a
single `.html` file), so it earns its own skill rather than an
`--html` flag on another command.

**Why a separate skill, not a `--html` flag on `/dev-kit:log`**:
`/dev-kit:log` toggles transcript capture (on/off/status/setup); the
analyzer consumes those transcripts. They are different stages of the
same pipeline -- capture vs. analyze -- so the user expects distinct
slash commands.

## What it does

1. Confirm transcripts exist under `logs/claude-code/` and/or
   `logs/codex/`. If neither exists, point the user at
   `/dev-kit:log setup` + `/dev-kit:log on` to enable capture first.
2. Detect the repo name from the most common `cwd` basename in the
   captured sessions (or accept `--repo <name>` to override).
3. Invoke `tools/token_efficiency_analyzer.py --repo <name> --days 30`
   and capture its `[ok] sessions=N  files_scanned=M  total_cost=$
   ...  estimated_savings=$...` summary line.
4. Echo the summary + the output HTML path to the user. Do not try
   to read the HTML back into the conversation -- it is a binary-ish
   artifact best opened in a browser.

The skill is read-only (`disallowed-tools: Write Edit`); the Python
CLI writes the file directly, mirroring how `/dev-kit:report` keeps
the skill body pure and lets the driver handle I/O.

## Flags

The CLI accepts:

| Flag | Default | Purpose |
|---|---|---|
| `--repo <name>` | (required unless auto-detected from cwd) | Matches `Path(cwd).name` |
| `--days <n>` | `30` | Look-back window |
| `--logs-dir <path>` | `./logs` | Root for `claude-code/` + `codex/` subdirs |
| `--out <path>` | `token-dashboard-<repo>-<days>d.html` | Output HTML path |

If the user did not pass `--repo`, derive it from the most common
basename of `cwd` in the captured sessions and confirm with the user
before running.

## Output

One HTML file (default name `token-dashboard-<repo>-30d.html`).
Self-contained: inline `<style>`, no `<script>`, no external assets.
Dark-mode aware. Safe to email, archive, or open from `file://`.

Sections (rendered by `tools/token_efficiency_analyzer.py:render_dashboard`):

- **Overview**: 4 metric tiles -- active sessions, total cost, avg
  score, avg cache hit ratio
- **Cost & Token Distribution**: cost by repo (share bar) + cost by
  tool (share bar, with yellow banner if `Read` is #1)
- **Sessions**: per-session row -- model, start time, input/output/
  cache-hit/cost, score pill, warning chips
- **Actionable Insights & Estimated Savings**: USD savings callout
  (green gradient) + deduplicated warning blocks

## Scoring rubric (4 dimensions, 0-100 weighted)

| Dim | Weight | Formula | Penalizes |
|---|---:|---|---|
| Cache Utilization | 0.35 | `cache_read / (input + cache_read) * 100` | prefix misalignment |
| Output Density | 0.25 | `min(100, output / total_input * 400)` | read-only sessions |
| Read Redundancy | 0.20 | `max(0, 100 - (max_repeat_reads - 1) * 12.5)` | cartography failure |
| Tool Economy | 0.20 | `max(0, 100 - tools_per_1k_out * 2)` | tool thrashing |

Total = `0.35*cache + 0.25*density + 0.20*redundancy + 0.20*economy`.

## Warning triggers (6 anti-patterns)

Each trigger has the exact emoji-prefixed message from the prompt;
rendered verbatim in the dashboard.

| Code | Condition | Fix |
|---|---|---|
| `CACHE_HIT_LOW` | `cache_hit < 50%` | move volatile data to prompt tail; don't switch models mid-session |
| `READ_HEAVY` | `Read` >= 40% of tool cost | pin large files once; build a cartography |
| `HEAVY_CONTEXT` | `total_input > 500K` in one session | delegate to sub-agents; run `/compact` |
| `MODEL_OVERSPEC` | Opus + density score < 20 | downgrade to Sonnet / Haiku |
| `WRITE_NOT_REUSED` | `cache_write > 50K` AND `cache_read < 2*cache_write` | only put re-readable data in front of prompt |
| `REPEATED_USER_MSG` | any user message text appears >= 2x | drop finished sub-tasks from context |

## Estimated savings (USD)

Conservative reclaim model -- only the cache-miss penalty + duplicate-read
waste, not the entire bill. Target = 70% cache hit + 0 duplicate reads.

- **Cache-miss delta**: shift tokens from billable input into
  `cache_read` until the session hits 70%. Saved = `shifted *
  (input_price - cache_read_price)`.
- **Duplicate-read delta**: `2K tokens * (n - 1)` per file read > 1x,
  at base input price.

Per-tool cost column is imputed from `n_calls * 2K_tokens *
input_price` (heuristic, not a billing-API call).

## Iron Law

**Quote the summary line in your reply, not a paraphrase.** The CLI
prints `[ok] sessions=N files_scanned=M total_cost=$X.XX
estimated_savings=$Y.YY` on success; copy that line verbatim into
the conversation so the user can audit the numbers without opening
the HTML. Do not claim "done" or "passed" without that line.

## Hand-off

Previous: `/dev-kit:log setup` + `/dev-kit:log on` (captures the
transcripts this skill consumes).

If `logs/claude-code/` is empty, refuse to run and tell the user to
enable capture first. Re-run at any time -- the analyzer re-reads
disk, no caching, so a fresh log shows up on the next invocation.

## Related

- `tools/token_efficiency_analyzer.py` -- the CLI driver (782 lines,
  stdlib only, py_compile-verified)
- `fixtures/make_fixture.py` -- generates 6 synthetic JSONL files
  (one per warning trigger) for regression
- `/dev-kit:log` -- captures the input this skill consumes

Next: open the output HTML in a browser, or share the file path
with the user.