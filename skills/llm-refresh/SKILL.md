---
name: llm-refresh
category: shortcuts
description: Refresh docs/llm-info/<provider>.json from each vendor's official pricing page via WebFetch extraction. Diff-then-commit; manual like set-provider.sh.
alpha: analysis
when_to_use:
  - User types /dev-kit:llm-refresh
  - User asks to update / sync Claude/Codex/MiniMax/DeepSeek pricing or model lists
  - Quarterly cadence or before quoting prices in a plan or cost-gate config
  - After a vendor publishes a new model or price change
allowed-tools: Read Bash WebFetch
disallowed-tools: Write Edit Agent
model: sonnet
disable-model-invocation: false
user-invocable: true
---
> [← Skills index](../../README.md)

# /dev-kit:llm-refresh — LLM pricing & model registry refresh

## What it does

Fetches each provider's official public pricing page via `WebFetch`, extracts
the current token-pricing table into a normalized payload, and writes it to
`docs/llm-info/<provider>.json`. The four tracked providers are defined in
`docs/llm-info/sources.json` — Claude/Anthropic, OpenAI Codex/API, MiniMax,
DeepSeek. The skill is the only mechanism that mutates those JSON files; hand
edits are explicitly discouraged (see `docs/llm-info/README.md`).

Updates are **explicit, diff-visible, and user-committed** — same trust model as
`bin/set-provider.sh`. Nothing here auto-commits.

A prior version of this skill hand-rolled a regex/HTML-table parser per
provider. The first live vendor layout change broke two of the four parsers
outright and, worse, silently mislabeled MiniMax's raw CNY prices as USD in
the committed JSON — a wrong number, not a loud failure. Bespoke per-vendor
scraping is exactly the kind of harness engineering an LLM extraction step
makes unnecessary: reading "price per token for each model" off an arbitrary
page is what the model is good at, and it adapts to layout changes for free.

## Body

For each provider in `docs/llm-info/sources.json`:

1. `WebFetch` the provider's `url` with this extraction prompt (fill in the
   provider label):

   ```
   Extract the current LLM API token-pricing table from this page into a
   strict JSON array (no markdown, no commentary, no surrounding text) where
   each element has EXACTLY these keys:
     id                     kebab-case slug, e.g. "claude-sonnet-5"
     display_name           string, the vendor's own model name
     context_window         integer, max context in tokens
     input_price_per_mtok   number, USD per 1,000,000 input tokens
     output_price_per_mtok  number, USD per 1,000,000 output tokens
     deprecated             boolean
     notes                  string, <=200 chars

   Only include the LLM API token-pricing table — ignore consumer
   subscription plans, TTS/voice pricing, and unrelated product tiers.
   If the page prices in a non-USD currency, convert to USD using the
   currently published FX rate and record the original value + rate used
   in `notes`. Return ONLY the JSON array.
   ```

2. Pipe the returned JSON array into `refresh.py` via stdin (wrap it as
   `{"models": [...]}` if not already):

   ```bash
   python3 skills/llm-refresh/scripts/refresh.py --provider claude --check <<'JSON'
   {"models": [ ...extracted array... ]}
   JSON
   ```

   Add `--json` for a machine-readable summary. Drop `--check` once the diff
   looks right to actually write the file.

3. The script prints one of three lines per provider:

   - `[<id>] no change` — extracted payload matches the registry (compared
     ignoring the `fetched_at` timestamp); nothing to do.
   - `[<id>] wrote <path> (<N> models)` — file updated; review the diff.
   - `[<id>] FAIL: <reason>` — the extracted JSON failed schema validation
     (missing key, non-numeric price, negative price, empty list). This is
     the deterministic backstop against a bad extraction — it does not
     catch a wrong-but-well-typed number, which is why step 4 still applies.

4. Exit codes are sentinel-friendly (0=ok, 1=`--check` saw a diff, 2=payload
   failed validation, 3=usage error). After a successful run, the user reviews
   the `git diff` **and sanity-checks the numbers against the vendor page**
   before committing:

   ```bash
   git diff docs/llm-info/<id>.json   # sanity check — this is the real gate
   git add docs/llm-info/<id>.json
   git commit -m "chore(llm-info): refresh <provider> pricing snapshot"
   ```

## Trust model

- **Extraction is LLM-based, validation is not.** `WebFetch` reads the page
  and produces the JSON payload; `refresh.py` only validates schema (types,
  required keys, non-negative prices), diffs against the committed file, and
  performs the atomic write. The model's reading of the page is not
  automatically trusted — the printed diff is what the user checks against
  the vendor page before committing, same gate that caught the previous
  parser's CNY/USD bug.
- **No automation.** No cron, no GitHub Action refreshes the file. If a vendor
  changes prices and the user does not run the skill, the registry drifts from
  reality — that is intentional. The README does not contain vendor numbers, so
  the worst case is a stale-but-isolated JSON file.
- **No silent overwrites.** The script diffs the extracted payload against the
  existing file (ignoring the `fetched_at` stamp) and reports "no change" when
  equal. Atomic writes only happen on a real diff, via
  `lib/atomic.py:atomic_write_json`.

## Rules

- **READ-ONLY on the SKILL side.** `Edit` and `Write` are disallowed. The only
  file mutation is `refresh.py`'s atomic write, invoked via `Bash` with the
  extracted JSON on stdin — never write the JSON to a file with the `Write`
  tool first.
- **No model delegation.** `Agent` is disallowed — the assistant running this
  skill does its own extraction and review; it does not fan out to a
  sub-agent whose interpretation would be harder to audit.
- **One hand-off.** No automated next skill. The user commits manually so the
  refresh always lands behind a reviewable PR.

## Files installed

| Path | Purpose |
|---|---|
| `skills/llm-refresh/SKILL.md` | This file |
| `skills/llm-refresh/scripts/refresh.py` | Validate (stdin JSON) + diff + atomic-write CLI. No fetching or parsing — that's `WebFetch`, driven by this file's Body. |
| `skills/llm-refresh/agents/openai.yaml` | Codex-side `interface` (no separate Codex skill body — Codex reuses this same SKILL.md via `.codex-plugin/plugin.json:skills = "./skills/"`) |
| `docs/llm-info/sources.json` | Provider registry (id → `{url, currency}`) |
| `docs/llm-info/{claude,codex,minimax,deepseek}.json` | SSOT, one per provider |
| `docs/llm-info/README.md` | Pointer + "do not edit by hand" rule |
| `tests/test_llm_refresh.py` | Schema + script-behaviour contracts |

## Next step

After committing a refreshed `docs/llm-info/<id>.json`, the next planned
consumer is `lib/cost_gate.py` (currently inline tier data). Wiring that is a
follow-up PR — this skill does not touch `lib/cost_gate.py` so the diff stays
reviewable.
