# Token-pricing post-mortem (moved from `rules/token-pricing.md`)

These are the lessons-learned from past pricing incidents. Kept as
historical record, not as policy — see `rules/token-pricing.md` for the
Iron Law + workflow.

## Incidents

### 1. `gpt-5` is a substring of `gpt-5.6-*`

Putting the shorter key first in the matcher silently stole every
`gpt-5.6-*` id at 4× cheaper legacy pricing. **Longest-prefix-first is
mandatory** when sharing a hierarchical namespace. The shared loader
(`lib/llm_pricing.py`) enforces this.

### 2. Two PRICING dicts drifted

`tools/token_efficiency_analyzer.py` used to have its own `PRICING`
dict AND so did `lib/cost_gate.py`. Both silently misbilled sessions
until 2026-07-17 — that's why both now go through
`lib/llm_pricing.py` as the single source of truth.

### 3. Capture-side filtering strips token metadata before storage

If the analyzer reports `model = ""` and zero tokens for sessions
from a provider, the fix is upstream in the capture script. Example:
`tools/save_log.py:_codex_has_event_text` keeps only conversation
text and drops `payload.info.model` / `payload.info.token_usage`. The
analyzer cannot recover data that was never written.

### 4. Fixtures pin parsers, not rates

A pricing rate can change monthly; a parser matching the page
structure is a contract that changes much less often. Tests under
`skills/llm-refresh/tests/fixtures/` pin the parser once and let the
rate drift until someone re-runs `/dev-kit:llm-refresh` to refresh
the JSON.
