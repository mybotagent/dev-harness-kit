> [← Skills index](README.md) · [Project README](../../README.md)

# `code-viz`

**Category:** `audit` · **Alpha:** `state` · **Invocation:** `/dev-kit:code-viz` (human-invoked)

`code-viz` is a read-only visual triage skill: walk a target directory, classify its files by directory and extension, then emit one self-contained HTML page with Mermaid diagrams (top-level inventory table, directory-hierarchy graph, source-file breakdown) sized for the loaded viewport with click-to-expand lightbox modals. The emitted HTML is validated by a Playwright-headless subprocess that asserts no `"Syntax error in text"` appears anywhere in the rendered body, every `<pre class="mermaid">` produced a real `<svg>`, and the click-to-expand modal opens — so the artifact is verified end-to-end before the skill reports success.

## When to use it

- The user types `/dev-kit:code-viz` on a fresh repo and wants a one-page visual triage.
- The user wants to see file categories and key files without reading code.
- The user wants a shareable single-file artifact of a directory's structure (the `/tmp/code-viz.html` artifact opens with no server required).

## How it works

A single `python3 << 'PY' ... PY` heredoc embedded in `SKILL.md` (no `bin/`, `tools/`, or `lib/` companion needed) runs the full pipeline:

1. **Walk** the target directory (`--target DIR`, default `$PWD`, depth ≤ 4). Skips `.git`, `.worktrees`, `__pycache__`, `.dev-kit`, `.github`, `.claude`, `.codex`, `dist`, `node_modules`.
2. **Classify** into three views: top-level directories by file count (Table 1), file extensions by occurrence (Table 2), and "key files" by name pattern (`README`, `SKILL`, `plugin.json`, `hooks.json`, `settings.json`, `pre-commit`, `pre-push`, `ci.yml`, `review.yml`) (Table 3).
3. **Emit** `/tmp/code-viz.html` (default; override with `--out PATH`) — a single self-contained HTML document with embedded Mermaid via the `mermaid@10.9.1` CDN, a `<pre class="mermaid">` per diagram (bounded to `72vh` so the artifact fits the viewport by default), a click-to-expand `.mermaid-modal` overlay at natural viewBox size with `ESC` / backdrop / close-button close handlers.
4. **Validate** by `subprocess.run(['python3', '-c', f'''…'''])` — the validator opens `file:///tmp/code-viz.html` in headless Chromium, captures console errors and `body.innerText`, and writes real labels (`body_syntax_error=`, `blocks=`, `svgs=`, `pageerrors=`, `modal_open=`) that the parent script parses. Hard-fail exit 1 if any validator label is wrong; the parent then prints `[code-viz]` report lines and exits 0.

The skill is intentionally hermetic — no setup hooks fire, no MCP server is required, no `lib/` companion module needs importing. The heredoc reuses the same Playwright + mermaid pattern documented in `feedback-diagram-size-by-content.md` and `feedback-html-browser-validation.md` (no `<br/>` in flowchart labels, no `<n>`-style placeholders, no `:` inside `stateDiagram-v2` transition labels).

## What it does *not* do

- It does **not** modify the target — read-only walk; the only filesystem write is the new HTML in `/tmp/`.
- It does **not** include a separate HTML emitter library — the heredoc is the emitter.
- It does **not** run an LLM pass on the directory contents — all classification is regex/glob (no LLM call inside the skill body).

## Hand-off

After `[code-viz] validation: 0 syntax-error / N/N svgs / modal click OK`, open `file:///tmp/code-viz.html`. Each diagram card has a `cursor: zoom-in` + `click to expand` hint; clicking shows the diagram at its natural `viewBox` size (the modal scrolls vertically if the diagram is taller than the viewport). Press `Escape` or click outside the card to close.
