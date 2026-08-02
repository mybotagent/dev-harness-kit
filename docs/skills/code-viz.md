> [← Skills index](README.md) · [Project README](../../README.md)

# `code-viz`

**Category:** `audit` · **Alpha:** `state` · **Invocation:** `/dev-kit:code-viz` (human-invoked)

`code-viz` is a read-only plugin-architecture visualizer: it parses the **plugin surface** of a target directory (skills, commands, hooks, GitHub Actions, lib modules) and emits one self-contained HTML page with **stat tiles** (counts per surface), **inventory tables** (every entity it parsed), and **7 Mermaid diagrams** covering architecture, pipeline, skill relationships, per-stage workflow, hook event matrix, GH Actions triggers, and library layer. Pass `--screenshots DIR` to additionally export one PNG per diagram — drop those straight into a README. The emitted HTML is validated by a Playwright-headless subprocess that asserts no `"Syntax error in text"` appears anywhere in the rendered body, every `<pre class="mermaid">` produced a real `<svg>`, and the click-to-expand modal opens — so the artifact is verified end-to-end before the skill reports success.

## When to use it

- The user types `/dev-kit:code-viz` and wants architecture / workflow / relationship diagrams, not just file counts.
- The user wants to embed diagrams in a README — use `--screenshots docs/diagrams` to get one PNG per diagram, ready to drop in.
- The user wants a shareable single-file artifact of a plugin's architecture (the `/tmp/code-viz.html` artifact opens with no server required).

## What it emits

**Top of page**: stat tiles — `N skills · M commands · K hooks · J GH actions · L lib modules`.

**Then** 4 inventory tables: skills (name / category / alpha / model / user-invocable), commands (name / category / alpha), hook scripts (event × matcher × script), GitHub Actions (file / triggers / jobs).

**Then** 7 Mermaid diagrams:

| # | Diagram | Source |
|---|---|---|
| 0 | **Architecture overview** — `flowchart TB` layered topology (user → skill frontmatter → Claude events → `lib/` → shell scripts → GH Actions → back to user) | hand-authored |
| 1 | **dev-kit pipeline** — `flowchart LR` of the canonical stage chain (`bootstrap → plan → ci-setup → build → review → security → ship`) | hand-authored |
| 2 | **Skill relationship graph** — `flowchart LR` derived by scanning every `SKILL.md` + `commands/*.md` body for `/dev-kit:<name>` references | parsed |
| 3 | **build stage sequence** — `sequenceDiagram` of one step inside `/dev-kit:build` (worktree cut → sub-agent spawn → exit code persist → 2-commit protocol → hand-off) | hand-authored |
| 4 | **Hook event matrix** — `flowchart TD` grouped by Claude event (PreToolUse / PostToolUse / SessionStart / UserPromptSubmit / Stop), each matcher + script as a child node | parsed from `hooks/hooks.json` |
| 5 | **GitHub Actions triggers** — `flowchart LR` of `on:` events → workflow files → jobs | parsed from `.github/workflows/*.yml` |
| 6 | **Library layer** — `flowchart LR` of `lib/*.py` modules annotated with their known role (runner / worktree / ci-setup / state codec / atomic writer / etc.) | `lib/*.py` walk + role map |

## How it works

A single `python3 << 'PY' ... PY` heredoc embedded in `SKILL.md` (no `bin/`, `tools/`, or `lib/` companion needed) runs the full pipeline:

1. **Parse** the plugin surface:
   - `skills/*/SKILL.md` → frontmatter (`name`, `category`, `alpha`, `model`, `user_invocable`) + body for `/dev-kit:` ref harvesting.
   - `commands/*.md` → frontmatter + body for `/dev-kit:` ref harvesting.
   - `hooks/hooks.json` → events × matchers × scripts.
   - `.github/workflows/*.yml` → `on:` triggers + jobs (note: `yaml.safe_load` parses the bare key `on` as Python boolean `True`; the parser reads via `data.get(True, data.get('on'))`).
   - `lib/*.py` → module list (excludes `__init__.py`).
2. **Infer** relationships: scan every skill + command body for `/dev-kit:([a-z0-9-]+)` and emit an edge from source → target when the target is a known skill name.
3. **Emit** `/tmp/code-viz.html` (default; override with `--out PATH`) — a single self-contained HTML document with embedded Mermaid via the `mermaid@10.9.1` CDN, stat tiles, `<section class="card">` per diagram, sticky top-nav with anchors, and a click-to-expand `.mermaid-modal` overlay at natural viewBox size with `ESC` / backdrop / close-button close handlers. CSS variables drive both light and dark themes; Mermaid is initialized with `theme: 'base'` + explicit `themeVariables` so node text stays readable in both modes.
4. **(Optional) Export PNGs** when `--screenshots DIR` is set: a second Playwright pass screenshots each `pre.mermaid` element as `diagram-00.png` … `diagram-NN.png` in DIR. Drop straight into a README.
5. **Validate** by `subprocess.run(['python3', '-c', f'''…'''])` — the validator opens `file:///tmp/code-viz.html` in headless Chromium, captures console errors and `body.innerText`, and writes real labels (`body_syntax_error=`, `blocks=`, `svgs=`, `pageerrors=`, `modal_open=`) that the parent script parses. Hard-fail exit 1 if any validator label is wrong; the parent then prints `[code-viz]` report lines and exits 0.

The skill is intentionally hermetic — no setup hooks fire, no MCP server is required, no `lib/` companion module needs importing. The heredoc reuses the same Playwright + Mermaid pattern documented in `feedback-diagram-size-by-content.md` and `feedback-html-browser-validation.md` (no `<br/>` in flowchart labels, no `<n>`-style placeholders, no `:` inside `stateDiagram-v2` transition labels; use `\n` for line breaks inside node labels). `@media print` rules hide nav and modal and unclip diagrams so ⌘P → Save as PDF produces a clean README-ready PDF.

## What it does *not* do

- It does **not** modify the target — read-only walk; the only filesystem writes are the new HTML in `/tmp/` and (if requested) the PNGs in `--screenshots DIR`.
- It does **not** include a separate HTML emitter library — the heredoc is the emitter.
- It does **not** run an LLM pass on the plugin surface — all parsing is regex/glob/`yaml.safe_load`/`json.loads` (no LLM call inside the skill body).
- It does **not** generate per-skill workflow diagrams (only the most complex stage — `build` — gets a sequence diagram; other skills are listed in the inventory table).

## Hand-off

After `[code-viz] validation: 0 syntax-error / 7/7 svgs / modal click OK`, open `file:///tmp/code-viz.html`. Each diagram card has a `cursor: zoom-in` + `click to expand` hint; clicking shows the diagram at its natural `viewBox` size (the modal scrolls vertically if the diagram is taller than the viewport). Press `Escape` or click outside the card to close. Use the sticky top-nav to jump between sections.

For README embedding: pass `--screenshots docs/diagrams` and the skill writes one PNG per diagram (`diagram-00.png` … `diagram-06.png`) — reference those with `![](docs/diagrams/diagram-01.png)` (or copy-paste the Mermaid source blocks directly if your README renderer supports `mermaid` fenced code blocks).