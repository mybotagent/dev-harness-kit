---
paths:
  - "tools/token_efficiency_analyzer.py"
  - "tools/**/pricing*.py"
  - "tools/**/*pricing*.json"
---

# Token pricing rules (dev-harness-kit)

These rules govern how token-pricing data is sourced, cited, and updated.
They apply to every constant that bills tokens — the `PRICING` dict,
`--pricing-override` JSON shape, and any future pricing loader.

## Iron Laws

1. **Pricing comes from official provider docs, never from memory.**
   Anthropic / OpenAI / MiniMax publish rate sheets and revise them
   without notice. A constant copied from training data is an unpaid
   guess — the day after the provider ships a new tier it is wrong.
   The `PRICING` dict, the `--pricing-override` JSON file, and the
   skill-body pricing tables MUST each carry an inline citation to the
   page where the number was read (URL + ISO-8601 fetch date).
2. **Re-verify before every release.** A `bump` version PR that ships a
   pricing-rate change without a fresh official-source quote is a
   silent misbilling. The PR description for any change to
   `tools/token_efficiency_analyzer.py:PRICING` or to skill-body pricing
   tables MUST include "pricing re-verified against <URL> on <YYYY-MM-DD>"
   with the link to the live page, not a Wayback snapshot.
3. **Unknown model ids are a signal, not noise.** When a captured session
   shows a model id that does not match any row in `PRICING`, the
   analyzer emits `WARN: unknown model '<id>' ...` to stderr. Triage
   these the same week they appear: read the provider's current rate
   sheet, add the row, add a test, ship the same PR. Leaving an unknown
   model on the floor means we silently bill it at sonnet default.

## Mandatory workflow (any pricing change)

1. Open the provider's official page (URLs in the citation table below).
2. Confirm the rate you want to edit. For multi-tier families
   (e.g. gpt-5.6-sol/terra/luna) confirm **every** tier — a partial
   update silently misroutes whichever tier you forgot.
3. Edit `tools/token_efficiency_analyzer.py:PRICING` AND its inline
   citation comment block AND its `pricing_for()` matcher tuple —
   the matcher order matters when a shorter key is a substring of a
   longer one (see `gpt-5` vs `gpt-5.6-*` lesson below).
4. Add a `TestPricingFor` case that pins the new routing
   (e.g. `assertEqual(pricing_for("gpt-5.6-sol"), PRICING["gpt-5.6-sol"])`)
   AND a case that asserts the new id is NOT collected as unknown.
5. Quote the official-source URL and the run's exit code + test count
   in the PR body.

## Official sources (cite the page, not the API response)

When updating the table below, do not delete an old URL — supersede it
with the new one and a "superseded <YYYY-MM-DD>" note. A reviewer
should always be able to walk back the history of a rate.

| Provider | URL | Models tracked | Re-verify cadence |
|---|---|---|---|
| Anthropic | `https://platform.claude.com/docs/en/docs/about-claude/pricing` | opus / sonnet / haiku | every release |
| OpenAI    | `https://developers.openai.com/api/docs/pricing` (consolidated) and `https://developers.openai.com/api/docs/models/<model>` (per-model) | gpt-5-codex / gpt-5.* / gpt-4.1 / gpt-4o / o3 / o4-mini / gpt-realtime-2.* / gpt-image-2.* | every release |
| MiniMax   | `https://platform.minimax.io/docs/guides/pricing-paygo` | MiniMax-M3 / MiniMax-M2.7 | every release |
| Anthropic cache-TTL contract | same as Anthropic pricing page; the multipliers 5m = 1.25× input, 1h = 2.0× input are documented there | n/a (universal) | every release |

OpenAI notes (carried forward — DO NOT delete without confirming the
new URL still exists and lists the same families):

- The consolidated pricing page lives at `https://developers.openai.com/api/docs/pricing`
  (the legacy `https://openai.com/api/pricing/` redirects to a marketing
  page that omits long-context / batch / flex columns).
- Per-model cards at `https://developers.openai.com/api/docs/models/<model>`
  list context-window, modalities, and the long-context rate.
- OpenAI has a single cached-input discount (~50 % of base input) and
  no separate TTL for cache writes — both `cache_write_5m` and
  `cache_write_1h` columns in `PRICING` mirror base input pricing.

Anthropic notes:

- 5-minute cache-write is 1.25 × base input; 1-hour cache-write is 2.0 ×.
- Cache-read is 0.10 × base input (cheap; the lever for prompt-cache ROI).

MiniMax notes:

- MiniMax publishes only one cache-write rate (single TTL). Mirror it
  into both `cache_write_5m` and `cache_write_1h` columns in `PRICING`.

## Lessons we already paid for

- **`gpt-5` is a substring of `gpt-5.6-*`.** Putting the shorter key
  first in the matcher silently stole every 5.6-* id at 4× cheaper
  legacy pricing. Longest-prefix-first is mandatory when sharing a
  hierarchical namespace.
- **Capture-side filtering can strip token metadata before storage.**
  If the analyzer reports `model = ""` and zero tokens for sessions
  from a provider, the fix is upstream in the capture script (e.g.
  `tools/save_log.py:_codex_has_event_text` keeps only conversation
  text and drops `payload.info.model` / `payload.info.token_usage`).
  The analyzer cannot recover data that was never written.

## Forbidden patterns

- ❌ Hardcoding a rate from training-data memory in the PR description
  without an inline URL citation in the `PRICING` docstring.
- ❌ Editing `PRICING` without editing the matcher order too (or vice
  versa) — every rate change is also an ordering decision.
- ❌ Shipping a `pricing-override` JSON in the repo without a date
  stamp and a `superseded-by <URL+date>` pointer.
- ❌ Adding a new tier without adding a `TestPricingFor` case that
  pins the routing.

## Related

- `tools/token_efficiency_analyzer.py` — the `PRICING` dict and the
  `pricing_for()` matcher live here.
- `tests/test_token_efficiency_analyzer.py:TestPricingFor` — every new
  tier or matcher reorder needs a case here.
- `/dev-kit:token-analyzer` — consumes these rates to bill sessions.
- `rules/session-hygiene.md` — Iron Law #5 (match the model to the
  task) is the spend-side counterpart to this cost-side rule.
