> [← Skills index](README.md) · [Project README](../../README.md)

# `llm-refresh`

**Category:** `shortcuts` · **Alpha:** `analysis` · **Invocation:** `/dev-kit:llm-refresh` (human-invoked)

Refreshes `docs/llm-info/<provider>.json` — the pricing/model registry for the
four tracked LLM providers (Claude/Anthropic, OpenAI Codex/API, MiniMax,
DeepSeek) — from each vendor's official public pricing page. It is the only
mechanism intended to mutate those JSON files; hand edits are explicitly
discouraged (see `docs/llm-info/README.md`). Updates are explicit,
diff-visible, and user-committed, mirroring the trust model of
`bin/set-provider.sh` — nothing is silently rewritten.

## When to use it

- You ask to update or sync Claude/Codex/MiniMax/DeepSeek pricing or model lists.
- On a quarterly cadence, or before quoting prices in a plan or cost-gate config.
- After a vendor publishes a new model or price change.

## How it works

1. From the project root, run `python3 skills/llm-refresh/scripts/refresh.py`.
   Add `--provider claude` (or `codex`, `minimax`, `deepseek`) to refresh a
   single provider, or `--check` to preview without writing.
2. The script prints one line per provider:
   - `[<id>] no change` — the vendor page matches the registry; nothing to do.
   - `[<id>] wrote <path> (<N> models)` — file updated; review the diff.
   - `[<id>] FAIL: <reason>` — fetch or parser failed; investigate before
     trusting the unchanged file.
3. Exit codes are sentinel-friendly: `0` ok, `1` `--check` saw a diff, `2`
   fetch/parse fail, `3` usage error — safe to pair `--check` with CI.
4. After a successful run, you review the `git diff` and commit yourself:

   ```bash
   git diff docs/llm-info/<id>.json
   git add docs/llm-info/<id>.json
   git commit -m "chore(llm-info): refresh <provider> pricing snapshot"
   ```

**Trust model:** the SKILL.md body has `WebFetch` in `disallowed-tools` —
network access is delegated to `refresh.py`'s `urllib.request.urlopen` call
(the same pattern as `lib/llm_judge.py`), never done inline by the model.
There is no automation: no cron, no GitHub Action refreshes the file, so a
stale registry is an intentional, isolated failure mode rather than a silent
drift into the README. Writes only happen on a real diff, via
`lib/atomic.py:atomic_write_json`.

## Usage

```bash
/dev-kit:llm-refresh [--provider claude|codex|minimax|deepseek] [--check]
```

## Rules

- **Read-only on the skill side.** `Edit` and `Write` are disallowed in
  frontmatter; all mutation happens in `refresh.py` via `Bash`.
- **No model delegation.** `Agent` is disallowed so the refresh stays
  deterministic — you see the diff, not a sub-agent's interpretation.
- **One hand-off.** No automated next skill — you commit manually so the
  refresh always lands behind a reviewable PR.

## Files installed

| Path | Purpose |
|---|---|
| `skills/llm-refresh/SKILL.md` | This skill's definition |
| `skills/llm-refresh/scripts/refresh.py` | Fetch + parse + diff + atomic-write CLI |
| `skills/llm-refresh/agents/openai.yaml` | Codex-side interface (Codex reuses this same SKILL.md) |
| `docs/llm-info/sources.json` | Provider registry (`id → {url, parser, currency}`) |
| `docs/llm-info/{claude,codex,minimax,deepseek}.json` | SSOT, one per provider |
| `docs/llm-info/README.md` | Pointer + "do not edit by hand" rule |
| `tests/test_llm_refresh.py` | Schema + script-behavior contracts |

## Related

- `lib/cost_gate.py` — planned future consumer of the refreshed registry
  (currently uses inline tier data; not yet wired up).
- [`cost-gate`](cost-gate.md), [`token-analyzer`](token-analyzer.md) — other
  pricing-aware skills in the audit category.

---
*Source: [`skills/llm-refresh/SKILL.md`](../../skills/llm-refresh/SKILL.md)*
