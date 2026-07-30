# /dev-kit:llm-refresh — Skill README

> Refresh the vendor-tracked pricing and model registry under
> `docs/llm-info/<provider>.json` from each provider's official pricing
> page. Slash command: `/dev-kit:llm-refresh`.

## What this skill does

Fetches the official public pricing page for each tracked LLM provider
(Anthropic, OpenAI, MiniMax, DeepSeek) via `WebFetch`, extracts the current
token-pricing table (LLM-based, not a per-vendor regex parser), and writes
the result into `docs/llm-info/<provider>.json`. The same JSON is the
single source of truth consumed by:

- `lib/cost_gate.py` (drives `/dev-kit:cost-gate`)
- `tools/token_efficiency_analyzer.py` (drives `/dev-kit:token-analyzer`)
- any future consumer that bills Claude/OpenAI/MiniMax/DeepSeek tokens

`docs/llm-info/<provider>.json` values are always **USD per million
tokens**. The MiniMax file used to publish in CNY; values were
pre-converted at FX 7.00 during the initial bootstrap and the original
CNY rate is recorded in each row's `notes` field.

## File layout

```
skills/llm-refresh/
├── SKILL.md                 # slash command frontmatter + body
├── README.md                # this file
├── agents/
│   └── openai.yaml          # Codex dual-publish interface
└── scripts/
    └── refresh.py           # the single executable entry point
```

The four `docs/llm-info/<provider>.json` files it produces are tracked
separately:

```
docs/llm-info/
├── README.md
├── sources.json             # provider registry {url, currency}
├── claude.json
├── codex.json
├── minimax.json
└── deepseek.json
```

## Invocation

### Slash command (human)

```
/dev-kit:llm-refresh             # refresh every provider
/dev-kit:llm-refresh --provider claude    # one provider
/dev-kit:llm-refresh --check             # diff only; do not write
/dev-kit:llm-refresh --json              # machine-readable summary
```

### Direct CLI (debug + scripts)

`refresh.py` does not fetch or parse anything itself — it validates a JSON
payload on stdin, diffs it against the committed file, and atomically
writes. Extraction is `WebFetch`, driven by `SKILL.md`'s Body.

```bash
# from the repo root — payload is the WebFetch-extracted model array
echo '{"models": [...]}' | python3 skills/llm-refresh/scripts/refresh.py --provider codex --check
echo '{"models": [...]}' | python3 skills/llm-refresh/scripts/refresh.py --provider codex --json
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | up to date (with `--check`) OR write succeeded |
| 1 | `--check` saw a diff (no write happened) |
| 2 | stdin payload failed schema validation |
| 3 | usage error (unknown provider id, missing `sources.json`, empty/bad stdin JSON) |

## Trust model

- **User-initiated, never auto.** No cron, no CI workflow re-runs
  the refresh. The user runs the skill manually after seeing a vendor
  announcement. Same explicit-intent pattern as `bin/set-provider.sh`.
- **No silent overwrites.** The script diffs the extracted payload
  against the existing file (ignoring the `fetched_at` stamp) and reports
  "no change" when equal. Atomic writes only happen on a real diff, via
  `lib/atomic.atomic_write_json`.
- **Bad schema is loud, not silent.** `refresh.py` raises on a missing key,
  non-numeric price, negative price, or empty `models` list and exits 2.
  That catches a malformed extraction; it does NOT catch a wrong-but
  well-typed number (e.g. right shape, wrong currency) — that's what the
  `git diff` review in step 5 below is for. A prior hand-rolled parser
  produced exactly that failure mode (MiniMax CNY prices mislabeled as
  USD) and it passed every automated check because the JSON was
  well-formed; only diff review catches it.
- **WebFetch is used deliberately.** Extraction reads an arbitrary,
  vendor-controlled page layout — the kind of task an LLM adapts to and a
  regex/HTML-table parser breaks on the first redesign. See SKILL.md
  "What it does" for the incident that motivated this.

## How to add a new provider

1. Append one row to `docs/llm-info/sources.json` — no parser code needed:
   ```json
   {
     "id": "<provider_id>",
     "label": "<Human name>",
     "url": "https://vendor.example.com/pricing",
     "currency": "USD"
   }
   ```
2. Run the skill (or `WebFetch` the URL by hand with the extraction prompt
   in `SKILL.md`'s Body), review the printed diff, and commit
   `docs/llm-info/<provider_id>.json`.

## How to handle a vendor price change

1. Run the skill with `--check` for that provider — preview the diff
   without writing (see "Direct CLI" above for the exact pipeline).
2. Compare the diff to the vendor's published change. Confirm only
   the expected prices moved, and the currency is what you expect.
3. Drop `--check` to write the file.
4. `git diff docs/llm-info/<id>.json` — sanity-check the JSON against the
   live vendor page, not just against valid-JSON-shape.
5. `git add docs/llm-info/<id>.json` + commit. The PR description
   must include "pricing re-verified against <URL> on <YYYY-MM-DD>"
   per `rules/token-pricing.md`.

## Re-verify cadence

`rules/token-pricing.md` requires a fresh re-verification before
**every release** (the `/dev-kit:bump` flow). For day-to-day work,
re-run on:

- Vendor announcement of a price change
- Vendor announcement of a new model row
- A drift warning surfaced by `/dev-kit:token-analyzer` ("unknown model")

## Related files

- `docs/llm-info/` — the JSON SSOT this skill maintains.
- `lib/llm_pricing.py` — the consumer that reads `docs/llm-info/*.json`.
- `lib/cost_gate.py` — pricing consumer for `/dev-kit:cost-gate`.
- `tools/token_efficiency_analyzer.py` — pricing consumer for `/dev-kit:token-analyzer`.
- `rules/token-pricing.md` — Iron Laws that govern every rate change
  (citation rule, no-pricing-from-memory, etc.).
- `tests/test_llm_pricing.py` — loader contract tests (cross-consumer
  parity between `cost_gate` and the analyzer).
- `tests/test_llm_refresh.py` — schema + script CLI contract tests.

## Why this skill exists

Without `docs/llm-info/`, both `lib/cost_gate.py` and
`tools/token_efficiency_analyzer.py` would carry their own inline
`PRICING` dict that drifts independently from each other and from
the vendor. This skill is the single edit point. The skill is intentionally
slow, explicit, and human-gated so a silent misbilling is impossible.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
