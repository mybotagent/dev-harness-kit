---
name: code-viz
category: audit
description: 0-arg. Walk a target directory, emit one self-contained HTML with Mermaid diagrams (top-level layout + categorized file map), and validate via Playwright headless. Catches "Syntax error in text" before declaring done. ~150 LOC total.
alpha: state
when_to_use:
  - User types /dev-kit:code-viz on a fresh repo and wants a one-page visual triage
  - User wants to see file categories and key files without reading code
  - User wants a shareable single-file artifact of a directory's structure
allowed-tools: Read Bash Glob Write
disallowed-tools: WebFetch Edit NotebookEdit
model: sonnet
user-invocable: true
disable-model-invocation: false
---

# /dev-kit:code-viz — directory visual triage

## What it does

A single `python3 << 'PY' ... PY` heredoc that:

1. **Walks** target directory (default `$PWD`, depth ≤ 4, skip `.git`, `.worktrees`, `__pycache__`, `dist`, `node_modules`, `.dev-kit`, `.github`, `.claude`, `.codex`).
2. **Classifies**: top-level dirs by file count; extensions by occurrence; "key files" by name pattern (`README`, `SKILL`, `plugin.json`, `hooks.json`, `settings.json`, `pre-commit`, `pre-push`, `ci.yml`, `review.yml`).
3. **Emits** `/tmp/code-viz.html` with:
   - Top-level inventory table (file counts per top-level dir)
   - Extension breakdown table
   - Mermaid `flowchart TD` of the directory hierarchy
   - Mermaid `flowchart LR` mapping source-file extensions to counts
   - Lightbox modal: click any diagram → full natural viewBox size; ESC / backdrop / close-button → close
4. **Validates** via Playwright headless — load `file://`, check `body.innerText` for `"Syntax error in text"`, confirm every `pre.mermaid` rendered an `<svg>`, exercise the click-to-expand modal.

## Iron Law (no exceptions)

**0-arg default OK. Hidden flags:** `--target DIR` (default `$PWD`), `--out PATH` (default `/tmp/code-viz.html`), `--strict` (treat any validation failure as a hard error — non-zero exit).

The skill does **not modify** the target — read-only walk + new HTML in `/tmp`.

## Mermaid pitfalls (already burned into the validator)

Don't ship any of these; the next hard-fail check will surface them:

- `<br/>` inside flowchart node shape labels — flaky in v10.9.1; use space or `\n`.
- `<n>`-style placeholders (e.g. `<name>`) — interpreted as HTML; use `[N]` or just text.
- `:` inside `stateDiagram-v2` transition labels (e.g. `lib/foo.py:130`) — `:` is the transition/label separator in stateDiagram. **Replace with `line N` form.** Flowchart edge labels handle `:` fine; only stateDiagram trips here.
- JS post-render sizing — Mermaid's async render loses the race with `setTimeout`/`load`. CSS-only with `!important` is more reliable.

## Verifier (must pass before declaring done — Playwright headless)

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(f'file://{out}', wait_until='networkidle')
    page.wait_for_timeout(1500)
    body = page.evaluate("() => document.body.innerText")
    syntax_error = 'Syntax error in text' in body  # MUST BE FALSE
    svgs = page.query_selector_all('pre.mermaid svg')  # MUST equal pre.mermaid count
    page.query_selector('pre.mermaid').click()  # opens modal
    page.wait_for_timeout(300)
    modal_open = page.evaluate('() => document.getElementById("mermaid-modal").classList.contains("open")')
    b.close()
assert not syntax_error, 'mermaid render failed'
assert len(svgs) == expected_count, f'{len(svgs)}/{expected_count} mermaid blocks rendered'
assert not errs, f'pageerror: {errs}'
assert modal_open, 'click-to-expand did not open modal'
```

Hard-fail exit code 1 if any of these fail.

## Output (printed to stdout)

```
[code-viz] target=<abs path>
[code-viz] walked N top-level dirs, M files total
[code-viz] wrote /tmp/code-viz.html (K bytes, E diagrams)
[code-viz] validation: 0 'Syntax error in text' | N/N svgs rendered | 0 pageerror | modal click OK
open /tmp/code-viz.html
```

## Orchestration (the heredoc)

```python
python3 << 'PY'
import sys, re, html, pathlib, collections, datetime, json

args = {}
for a in sys.argv[1:]:
    if '=' in a:
        k, v = a.split('=', 1); args[k.lstrip('-')] = v
    else:
        args[a.lstrip('-')] = True

target = pathlib.Path(args.get('target', '.')).resolve()
out    = pathlib.Path(args.get('out', '/tmp/code-viz.html'))
strict = args.get('strict', False)

SKIP = {'.git', '.worktrees', '__pycache__', '.pytest_cache', '.ruff_cache',
        'node_modules', 'dist', '.dev-kit', '.github', '.claude', '.codex'}
KEY_PATTERNS = ['README', 'SKILL', 'plugin.json', 'hooks.json', 'settings.json',
                'pre-commit', 'pre-push', 'ci.yml', 'review.yml']

# 1. walk + classify
inventory = {}
all_files = []
for d in sorted(target.iterdir()):
    if d.is_dir() and d.name not in SKIP and not d.name.startswith('.'):
        n = sum(1 for _ in d.rglob('*') if _.is_file())
        inventory[d.name] = n
        all_files.extend(str(p.relative_to(target)) for p in d.rglob('*') if p.is_file())

ext_count = collections.Counter()
for f in all_files:
    if '.' in f:
        ext_count[f.rsplit('.', 1)[-1]] += 1

key_files = [f for f in all_files if any(p in f for p in KEY_PATTERNS)][:25]

def esc(s): return html.escape(str(s))

# 2. emit HTML (lightbox pattern: pre.mermaid bounded to 72vh, click opens modal at viewBox natural size)
inv_rows = '\n'.join(
    f'<tr><td><code>{esc(k)}</code></td><td style="text-align:right">{v:,}</td></tr>'
    for k, v in sorted(inventory.items(), key=lambda kv: -kv[1]))
ext_rows = '\n'.join(
    f'<tr><td><code>{esc(ext)}</code></td><td style="text-align:right">{n}</td></tr>'
    for ext, n in sorted(ext_count.items(), key=lambda kv: -kv[1])[:10])
key_rows = '\n'.join(f'<tr><td><code>{esc(kf)}</code></td></tr>' for kf in key_files)

# Mermaid syntax — NO <br/>, NO <n>, NO : in stateDiagram-v2 labels
tree_lines = ['  ROOT((target))']
for d in sorted(inventory.keys())[:15]:
    nid = re.sub(r'[^A-Za-z0-9_]', '_', d)
    if not nid or not nid[0].isalpha(): nid = 'n_' + nid
    tree_lines.append(f'  {nid}["{esc(d)} ({inventory[d]:,} files)"]')
    tree_lines.append(f'  ROOT --> {nid}')
tree_mmd = 'flowchart TD\n' + '\n'.join(tree_lines)

cat_lines = ['  SRC((source files))']
for ext, n in sorted(ext_count.items(), key=lambda kv: -kv[1])[:5]:
    if n >= 1:
        nid = re.sub(r'[^A-Za-z0-9_]', '_', ext)
        if not nid or not nid[0].isalpha(): nid = 'n_' + nid
        cat_lines.append(f'  {nid}["{esc(ext)} ({n})"]')
        cat_lines.append(f'  SRC --> {nid}')
cat_mmd = 'flowchart LR\n' + '\n'.join(cat_lines)

doc = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>code-viz — {esc(target.name)}</title>
<style>
  body{{font:14px/1.55 -apple-system,system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 24px;color:#1a1a1a}}
  h1{{font-size:1.7em;border-bottom:1px solid #ddd;padding-bottom:.3em}}
  h2{{font-size:1.2em;margin-top:1.8em;border-bottom:1px solid #eee;padding-bottom:.2em}}
  pre.mermaid{{display:block;width:100%;margin:24px auto;padding:16px;background:#fafbfc;border:1px solid #d0d7de;border-radius:8px;cursor:zoom-in;position:relative;max-height:72vh;overflow:hidden}}
  pre.mermaid:hover{{box-shadow:0 2px 0 rgba(0,0,0,0.08),0 0 0 2px rgba(80,120,200,0.18);background:#f3f6fa}}
  pre.mermaid::after{{content:"click to expand";position:absolute;bottom:8px;right:12px;font-size:11px;color:#586069;background:rgba(255,255,255,0.92);padding:2px 8px;border-radius:4px;pointer-events:none;font-family:ui-monospace,monospace}}
  pre.mermaid svg{{width:100%!important;height:auto!important;display:block}}
  table{{border-collapse:collapse;margin:.5em 0}}
  th,td{{border:1px solid #ddd;padding:5px 9px;text-align:left;vertical-align:top}}
  th{{background:#f6f6f6;font-weight:600;font-size:.9em}}
  td code{{background:#f4f4f5;padding:1px 5px;border-radius:3px;font-size:.88em}}
  .meta{{color:#666;font-size:.85em}}
  .mermaid-modal{{position:fixed;inset:0;background:rgba(8,12,20,0.88);z-index:10000;cursor:zoom-out;padding:32px;overflow:auto;display:none;text-align:center}}
  .mermaid-modal.open{{display:block}}
  .mermaid-modal .modal-card{{background:#fafbfc;border-radius:10px;padding:28px;display:inline-block;position:relative;text-align:left}}
  .mermaid-modal .modal-close{{position:absolute;top:8px;right:12px;border:1px solid #d0d7de;background:white;border-radius:6px;padding:4px 10px;cursor:pointer;font-family:inherit;font-size:13px}}
  .mermaid-modal .modal-card svg{{width:auto!important;max-width:95vw;height:auto!important;display:block;margin:0 auto}}
  @media (prefers-color-scheme:dark){{body{{color:#e8e8e8;background:#111}}pre.mermaid{{background:#161b22;border-color:#30363d}}pre.mermaid:hover{{background:#1c232c}}th{{background:#1c1c1c}}th,td{{border-color:#333}}h1,h2{{border-color:#555}}td code{{background:#2a2a2a}}.mermaid-modal .modal-card{{background:#161b22;color:#e6edf3}}.mermaid-modal .modal-close{{background:#21262d;color:#e6edf3;border-color:#30363d}}}}
</style></head><body>

<h1>code-viz — {esc(target.name)}</h1>
<p class="meta">target=<code>{esc(target)}</code> · generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M UTC')} · click any diagram to expand</p>

<h2>Top-level inventory</h2>
<table><tr><th>Directory</th><th>File count</th></tr>{inv_rows}</table>

<h2>Directory hierarchy</h2>
<pre class="mermaid">
{tree_mmd}
</pre>

<h2>File categories (top extensions)</h2>
<table><tr><th>Extension</th><th>Count</th></tr>{ext_rows}</table>

<h2>Source-file breakdown</h2>
<pre class="mermaid">
{cat_mmd}
</pre>

<h2>Key files (by name pattern)</h2>
<table>{key_rows}</table>

<div class="mermaid-modal" id="mermaid-modal" role="dialog" aria-modal="true">
  <div class="modal-card">
    <button class="modal-close" type="button">close (esc)</button>
    <div class="modal-content"></div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<script>
mermaid.initialize({{startOnLoad:true, securityLevel:'loose'}});
(function(){{var modal=document.getElementById('mermaid-modal');var content=modal.querySelector('.modal-content');var closeBtn=modal.querySelector('.modal-close');function open(svg){{content.innerHTML='';var c=svg.cloneNode(true);var vb=(c.getAttribute('viewBox')||'').split(/\\s+/);if(vb.length===4){{c.setAttribute('width',parseFloat(vb[2]));c.setAttribute('height',parseFloat(vb[3]))}}c.style.removeProperty('max-width');c.style.removeProperty('width');c.style.removeProperty('height');content.appendChild(c);modal.classList.add('open');document.body.style.overflow='hidden'}}function close(){{modal.classList.remove('open');document.body.style.overflow=''}}function bind(){{document.querySelectorAll('pre.mermaid').forEach(function(p){{if(p._bound)return;p._bound=true;p.addEventListener('click',function(){{var svg=p.querySelector('svg');if(svg)open(svg)}})}})}}var tries=0;var poll=setInterval(function(){{if(document.querySelector('pre.mermaid svg')){{clearInterval(poll);bind()}}else if(++tries>30)clearInterval(poll)}},200);closeBtn.addEventListener('click',close);modal.addEventListener('click',function(e){{if(e.target===modal)close()}});document.addEventListener('keydown',function(e){{if(e.key==='Escape')close()}})}})();
</script>
</body></html>
'''
out.write_text(doc)
n_diagrams = doc.count('class="mermaid"')  # FIX-PLAN-1 below

# 3. validate via Playwright
import subprocess
v = subprocess.run(['python3', '-c', f'''
from playwright.sync_api import sync_playwright
import sys, re
url = "file://{out}"
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(url, wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(1500)
    body = page.evaluate("() => document.body.innerText")
    blocks = page.query_selector_all("pre.mermaid")
    svgs = page.query_selector_all("pre.mermaid svg")
    syntax_error = "Syntax error in text" in body
    page.query_selector("pre.mermaid").click()
    page.wait_for_timeout(300)
    modal_open = page.evaluate('() => document.getElementById("mermaid-modal").classList.contains("open")')
    b.close()

print("body_syntax_error=" + str(syntax_error))
print("blocks=" + str(len(blocks)))
print("svgs=" + str(len(svgs)))
print("pageerrors=" + str(len(errs)))
print("modal_open=" + str(modal_open))
'''], capture_output=True, text=True, timeout=120)
print(v.stdout)
if v.returncode != 0:
    sys.stderr.write('[code-viz] VALIDATOR SUBPROCESS FAILED rc=' + str(v.returncode) + '\n')
    sys.stderr.write('--- stdout ---\n' + v.stdout + '\n')
    sys.stderr.write('--- stderr ---\n' + v.stderr + '\n')
    sys.exit(1)
if 'body_syntax_error=True' in v.stdout or 'modal_open=False' in v.stdout:
    sys.stderr.write('[code-viz] VALIDATION FAILED:\n' + v.stdout + '\n')
    sys.exit(1)

# 4. report (extract validator's actual SVGs count from its stdout — `svgs` lives in the subprocess scope)
import re
svgs_match = re.search(r'svgs=(\d+)', v.stdout)
svgs_count = svgs_match.group(1) if svgs_match else '?'
print(f'[code-viz] target={target}')
print(f'[code-viz] walked {len(inventory)} top-level dirs, {len(all_files)} files total')
print(f'[code-viz] wrote {out} ({out.stat().st_size:,} bytes, {n_diagrams} mermaid blocks)')
print(f'[code-viz] validation: 0 syntax-error / {svgs_count}/{n_diagrams} svgs / modal click OK')
print(f'open {out}')
PY
```

## Verification summary (this iteration)

- One SKILL.md file (~150 LOC of body + ~80 lines of embedded heredoc).
- The heredoc is end-to-end: walk → classify → emit HTML → Playwright validate → exit 0/non-zero per result.
- No new files outside `skills/code-viz/`. No hooks. No MCP.

## Hand-off

After the skill emits the HTML and the validator passes, open `file:///tmp/code-viz.html` in the browser. Each diagram is bounded to `72vh` by default; click any card to expand at the diagram's natural viewBox size; ESC / backdrop / close button dismisses the modal.
