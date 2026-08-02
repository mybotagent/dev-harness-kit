> [← Skills index](README.md) · [Project README](../../README.md)

# `code-viz`

**Category:** `audit` · **Alpha:** `state` · **Invocation:** `/dev-kit:code-viz` (human-invoked)

`code-viz` is a **generic** plugin-architecture visualizer: it walks **any target repo** (Claude Code plugin, MCP server, microservice, monorepo, framework) and emits one self-contained HTML page with **multi-level views** + **a domain pillar map**. All classification is filename/path heuristic — no hardcoded skill names, pipeline stages, or module roles.

**Header**: stat tiles per surface (`39 skills · 2 commands · 14 hooks · 7 GH actions · 26 lib · 2 bin · 21 tools · 0 MCP`) **+** stat tiles per domain pillar (`Skill=127 · Test=290 · Storage=196 · LLM=158 · Build=67 · Hook=58 · Security=17 · DB=14 · Cloud=1`).

**Then** 4 inventory tables: skills (with `pillars` column), commands, hook scripts (event × matcher × script), GitHub Actions (file / triggers / jobs).

**Then** 6 abstraction levels + 1 cross-cutting pillar map (= 8+ Mermaid diagrams, click each to expand):

| # | Level | Diagrams |
|---|---|---|
| 0 | **L0 Architecture overview** | Layered topology: user → skill frontmatter → Claude events → `lib/` + `tools/` + `bin/` → external (GH Actions, MCP, CLI) → back to user |
| 1 | **L1 Code level** | Directory tree (`flowchart LR`) + extension breakdown |
| 2 | **L2 Skill level** | Skill relationship graph + **per-skill workflow diagrams** for the top N (default 12) user-invocable skills (parsed `[N/M] LABEL → description` cycle from each `SKILL.md` body, falls back to `## Behavior` numbered lists, falls back to 1-node "linear" diagram) |
| 3 | **L3 Hook event** | Claude event × matcher × script matrix (PreToolUse / PostToolUse / SessionStart / Stop / UserPromptSubmit) |
| 4 | **L4 Tools and Library layer** | `bin/` + `tools/` + `lib/` module inventory (each as a `flowchart LR` rooted at the directory) |
| 5 | **L5 External tools** | GitHub Actions triggers-to-jobs + MCP servers (from `.mcp.json` + `.claude/settings.json` + `.codex/settings.json`) + third-party CLI invocations (auto-detected from `subprocess.run` patterns) |
| - | **Cross-cutting — Domain pillar map** | Which files fall under **DB · Cloud · API · MCP · Skill · Hook · Network · Security · Build · Test · Storage · LLM** |

## When to use it

- User types `/dev-kit:code-viz` and wants a **generic** plugin-architecture overview, not repo-specific.
- User wants **multi-level views** (architecture → code → skill → hook → tools → external).
- User wants diagrams **classified by domain pillar** (DB / Cloud / API / MCP / Skill / Hook / Network / Security / Build / Test / Storage / LLM).
- User wants **per-skill workflow extraction** + drop-in PNG screenshots for a README.

## Iron Law flags

- `--target DIR` (default `$PWD`)
- `--out PATH` (default `/tmp/code-viz.html`)
- `--screenshots DIR` (optional; export each `pre.mermaid` as a PNG into DIR)
- `--top-skills N` (default 12, max 25 — how many user-invocable skills get a per-skill workflow diagram)
- `--strict` (treat any validation failure as a hard error — non-zero exit)

Read-only walk + new HTML in `/tmp` + optional PNGs.

## Generic by design (not repo-specific)

- **All classification is filename/path heuristic** via the embedded `PILLAR_PATTERNS` dict. No hardcoded skill names, pipeline stages, or module roles. Works on any plugin/repo.
- **Surfaces are optional**. Missing `skills/`, `hooks/`, `.github/`, `lib/`, etc. → section gracefully omitted, not crashed.
- **Domain pillars are keyword-matched** against each discovered path. A file matches DB if its name contains `db|sql|mongo|redis|postgres|sqlite|orm`; matches Cloud if it contains `aws|gcp|azure|k8s|docker|lambda|s3`; etc.
- **Per-skill workflow** parses `[N/M] LABEL → description` patterns from each `SKILL.md` body. Falls back to `## Cycle` / `## Behavior` numbered lists. Falls back to a 1-node "linear, no phases" diagram if nothing matches.

## Output

```text
[code-viz] target=<abs path>
[code-viz] discovered: 39 skills, 2 commands, 14 hooks, 7 GH workflows, 26 lib, 2 bin, 21 tools, 0 MCP
[code-viz] pillar map: Skill=127 Test=290 Storage=196 LLM=158 general=107 Build=67 Hook=58 Security=17 DB=14 Cloud=1
[code-viz] wrote /tmp/code-viz.html (X bytes, E mermaid diagrams)
[code-viz] exported N PNGs into <screenshots dir>
[code-viz] validation: 0 'Syntax error in text' | E/E svgs rendered | 0 pageerror | modal click OK
open /tmp/code-viz.html
```

## How it works

A single `python3 << 'PY' ... PY` heredoc embedded in `SKILL.md` (no `bin/`, `tools/`, or `lib/` companion needed):

1. **Walk** target recursively — collect all files, classify by directory + extension.
2. **Map** every discovered path to domain pillars via `PILLAR_PATTERNS`.
3. **Parse** optional surfaces: `skills/*/SKILL.md` (frontmatter + body), `commands/*.md`, `hooks/hooks.json`, `.github/workflows/*.yml`, `lib/*.py`, `bin/*.py`, `tools/*.py`, `.mcp.json`, `.claude/settings.json`, `.codex/settings.json`.
4. **Infer relationships** by scanning every `SKILL.md` + `commands/*.md` body for `/skill:<name>` / `/dev-kit:<name>` refs.
5. **Extract cycles** from each `user_invocable: true` skill body — top N get a `flowchart LR` per-skill workflow diagram.
6. **Emit** `/tmp/code-viz.html` with stat tiles (surface + pillar), 4 inventory tables, 8+ diagrams (click-to-expand modal at natural viewBox size), CSS-variable light + dark theme, `theme: 'base'` + `themeVariables` for high-contrast Mermaid text, `@media print` for clean ⌘P → PDF.
7. **(Optional)** Export one PNG per diagram via `--screenshots DIR`.
8. **Validate** via Playwright headless — `body_syntax_error=False`, all `<pre class="mermaid">` produced an `<svg>`, no `pageerror`, click-to-expand modal opens. Hard-fail exit 1 on any failure.

## Mermaid pitfalls (already burned into the validator)

- `<br/>` inside flowchart node shape labels — flaky in v10.9.1; use `\n` or `·`.
- `<n>`-style placeholders (e.g. `<name>`) — interpreted as HTML; use `[N]` or just text.
- `:` inside `stateDiagram-v2` transition labels (e.g. `lib/foo.py:130`) — `:` is the separator. **Replace with `line N` form.** Flowchart edge labels handle `:` fine.
- JS post-render sizing — Mermaid's async render loses the race. CSS-only with `!important` is more reliable.
- Raw `on:` in YAML GH-Actions — `yaml.safe_load` parses the bare key `on` as Python boolean `True`; always read via `data.get(True, data.get('on'))`.
- Unthemed Mermaid in dark mode — default theme paints light fills that disappear against a dark page; force `theme: 'base'` + explicit `themeVariables.primaryTextColor`.
- Long body snippets in node labels — keep labels ≤ 60 chars; strip backticks / arrows / quotes before interpolation.

## Hand-off

After `[code-viz] validation: 0 syntax-error / E/E svgs / modal click OK`, open `file:///tmp/code-viz.html`. Each diagram card has a `cursor: zoom-in` + `click to expand` hint; clicking shows the diagram at its natural `viewBox` size (the modal scrolls vertically if the diagram is taller than the viewport). Press `Escape` or click outside the card to close. Use the sticky top-nav to jump between levels.

For README inclusion: pass `--screenshots docs/diagrams` and the skill writes one PNG per diagram (`diagram-00.png` … `diagram-NN.png`) — reference those with `![](docs/diagrams/diagram-NN.png)`. The pillar tiles in the header show at a glance which domain pillars the target spans.



## Update history

- **v3 (current)** — Strategy F (domain-content extraction): parses `## Categories` / `## Dimensions` / `## Audit areas` / `## Checks` sections with bolded-bullet items. Captures security's OWASP A01–A10, inspect's 8 dims, etc. Skills with no extractable workflow are listed as text chips in a "no explicit workflow" section, not visualized.
- **v2** — Generic multi-level + pillar map (6 abstraction levels + 1 cross-cutting).
- **v1** — Directory visualizer (file counts + extension tables).
