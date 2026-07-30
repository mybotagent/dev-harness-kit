# docs/llm-info/ — LLM pricing & model registry (SSOT)

This directory is the **single source of truth** for LLM pricing, plans, and model availability across Claude/Anthropic, OpenAI Codex, MiniMax, and DeepSeek. Every value in every `*.json` is **verified against the vendor's own public pricing page**; refresh via `/dev-kit:llm-refresh [--provider <id>] [--check]`.

## Files

| File | Purpose |
|---|---|
| `sources.json` | Provider registry: id → `{url, currency}`. Read by `refresh.py`; `url` is what `WebFetch` extracts pricing from. |
| `claude.json` | Anthropic Claude pricing + active models + plans (USD) |
| `codex.json` | OpenAI Codex / API pricing + active models + plans (USD; ChatGPT consumer plans out of scope) |
| `minimax.json` | MiniMax pricing + active models (USD; converted from CNY @ FX 7.00 per the per-row notes) |
| `deepseek.json` | DeepSeek pricing + active models + cache-hit rate (USD) |

All values are **USD per million tokens**. The MiniMax row-level `notes` field records the original CNY rate (e.g. "Originally 2.10 / 8.40 CNY per Mtok at FX 7.00.") so the conversion is reproducible.

## Verification (initial bootstrap, 2026-07-17)

Every JSON value was hand-extracted from the vendor's official docs page during the initial bootstrap. To re-verify after a vendor changes prices, run `/dev-kit:llm-refresh` (or `--provider <id>`): it `WebFetch`es the URL recorded in `sources.json`, extracts the pricing table, and reports any drift via `refresh.py --check`. To apply, drop `--check`.

| Provider | Verified page | Currency in JSON |
|---|---|---|
| claude   | https://platform.claude.com/docs/en/about-claude/pricing | USD |
| codex    | https://developers.openai.com/api/docs/pricing            | USD |
| minimax  | https://platform.minimaxi.com/docs/guides/pricing-paygo.md| USD (converted from CNY @ FX 7.00) |
| deepseek | https://api-docs.deepseek.com/quick_start/pricing        | USD |

## Rules

- **Do not edit `*.json` by hand.** They are machine-emitted and version-controlled so a future `git diff` reveals drift from the vendor's published pricing page.
- **Refresh via the skill**: `/dev-kit:llm-refresh [--provider <id>] [--check]`.
- **Currency** is per-provider but always normalized to USD in the JSON payload. MiniMax values are pre-converted upstream at FX 7.00.
- **Deprecation** is tracked via the `models[].deprecated` flag.

## Why JSON and not the README

Pricing drifts on every vendor release cycle. Mirroring those facts into README or any Markdown document means re-editing the README every price change — and reviewing README PRs becomes a guessing game. The README, cost-gate configs, and any other consumer reference `.json` under this directory, never the numbers themselves.

## Next step

When a vendor announces a pricing or model-list change, run `/dev-kit:llm-refresh`,
review the printed diff against the live vendor page, `git add docs/llm-info/*.json`,
commit, push.

For a sanity check before committing, use `/dev-kit:llm-refresh --check` (or
`--provider <id> --check`) to see the diff without writing.
