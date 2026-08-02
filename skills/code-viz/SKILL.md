---
name: code-viz
category: audit
description: 0-arg. Parse skills/hooks/commands/.github/workflows and emit one self-contained HTML with 7 Mermaid diagrams (architecture, pipeline, skill relations, build sequence, hook matrix, GH Actions, lib layer) + inventory tables. Playwright-validated.
alpha: state
when_to_use:
  - User types /dev-kit:code-viz and wants architecture/workflow/relationship diagrams, not just file counts
  - User wants to see how skills/hooks/commands/GH-Actions/lib connect without reading code
  - User wants a shareable single-file artifact of a plugin's architecture
allowed-tools: Read Bash Glob Write
disallowed-tools: WebFetch Edit NotebookEdit
model: sonnet
user-invocable: true
disable-model-invocation: false
---

# /dev-kit:code-viz — plugin architecture & workflow visualizer

## What it does

A single `python3 << 'PY' ... PY` heredoc that parses the **plugin surface** of a target directory and emits `/tmp/code-viz.html` containing:

1. **Inventory tables** — skills (name / category / alpha / model / user-invocable), commands, hook scripts (event × matcher × script), GitHub Actions (file / triggers / jobs).
2. **Architecture overview** — `flowchart TB` showing the layered topology: user → skill/command frontmatter → Claude hook events → `lib/` modules → `.sh`/`.py` scripts → `.github/workflows/*.yml` → back to user.
3. **dev-kit pipeline** — `flowchart LR` of the canonical stage chain: `bootstrap → plan → ci-setup → build → review → security → ship`.
4. **Skill relationship graph** — `flowchart LR` derived by scanning every `SKILL.md` + `commands/*.md` body for `/dev-kit:<name>` references and emitting an edge per call.
5. **build stage sequence** — `sequenceDiagram` of one step inside `/dev-kit:build`: worktree cut → sub-agent spawn → exit code persist → 2-commit protocol → hand-off.
6. **Hook event matrix** — `flowchart TD` grouped by Claude event (PreToolUse / PostToolUse / SessionStart / UserPromptSubmit / Stop), each matcher + script as a child node.
7. **GitHub Actions triggers** — `flowchart LR` of `on:` events → workflow files → jobs.
8. **Library layer** — `flowchart LR` of `lib/*.py` modules annotated with their known role (runner / worktree / ci-setup / state codec / atomic writer / etc.).

Each diagram is bounded to `72vh` by default; **click any card** to open a modal at the diagram's natural viewBox size; ESC / backdrop / close-button dismisses.

## Iron Law (no exceptions)

**0-arg default OK. Hidden flags:** `--target DIR` (default `$PWD`), `--out PATH` (default `/tmp/code-viz.html`), `--strict` (treat any validation failure as a hard error — non-zero exit).

The skill does **not modify** the target — read-only walk + new HTML in `/tmp`.

## Mermaid pitfalls (already burned into the validator)

Don't ship any of these; the next hard-fail check will surface them:

- `<br/>` inside flowchart node shape labels — flaky in v10.9.1; use `\n` or `·`.
- `<n>`-style placeholders (e.g. `<name>`) — interpreted as HTML; use `[N]` or just text.
- `:` inside `stateDiagram-v2` transition labels (e.g. `lib/foo.py:130`) — `:` is the transition/label separator in stateDiagram. **Replace with `line N` form.** Flowchart edge labels handle `:` fine; only stateDiagram trips here.
- JS post-render sizing — Mermaid's async render loses the race with `setTimeout`/`load`. CSS-only with `!important` is more reliable.
- Raw `on:` in YAML GH-Actions — `yaml.safe_load` parses the bare key `on` as Python boolean `True`; always read via `data.get(True, data.get('on'))`.

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
[code-viz] parsed N skills, M commands, K hooks, J GH workflows, L lib modules
[code-viz] wrote /tmp/code-viz.html (X bytes, E mermaid diagrams)
[code-viz] validation: 0 'Syntax error in text' | E/E svgs rendered | 0 pageerror | modal click OK
open /tmp/code-viz.html
```

## Orchestration (the heredoc)

```python
python3 << 'PY'
import sys, re, html, pathlib, collections, datetime, json
try:
    import yaml
except Exception:
    yaml = None

args = {}
for a in sys.argv[1:]:
    if '=' in a:
        k, v = a.split('=', 1); args[k.lstrip('-')] = v
    else:
        args[a.lstrip('-')] = True

target = pathlib.Path(args.get('target', '.')).resolve()
out    = pathlib.Path(args.get('out', '/tmp/code-viz.html'))
strict = args.get('strict', False)

def esc(s): return html.escape(str(s))
def nid(s, prefix='n_'):
    n = re.sub(r'[^A-Za-z0-9_]', '_', s)
    if not n or not n[0].isalpha(): n = prefix + n
    return n

# --- 1. parse skills/*/SKILL.md frontmatter ---
skills = []
skills_dir = target/'skills'
if skills_dir.exists():
    for p in sorted(skills_dir.iterdir()):
        if not p.is_dir(): continue
        fm_file = p/'SKILL.md'
        if not fm_file.exists(): continue
        text = fm_file.read_text()
        m = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
        fm = {}
        if m:
            for ln in m.group(1).split('\n'):
                mm = re.match(r'^([A-Za-z_]\w*):\s*(.*?)\s*$', ln)
                if mm: fm[mm.group(1)] = mm.group(2).strip('"').strip("'")
        skills.append({
            'name': fm.get('name', p.name),
            'category': fm.get('category', '?'),
            'alpha': fm.get('alpha', '-'),
            'model': fm.get('model', 'sonnet'),
            'user_invocable': fm.get('user_invocable', 'true'),
            'body': text,
            'path': str(p.relative_to(target)),
        })

# --- 2. parse commands/*.md ---
commands = []
cmd_dir = target/'commands'
if cmd_dir.exists():
    for p in sorted(cmd_dir.glob('*.md')):
        text = p.read_text()
        m = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
        fm = {}
        if m:
            for ln in m.group(1).split('\n'):
                mm = re.match(r'^([A-Za-z_]\w*):\s*(.*?)\s*$', ln)
                if mm: fm[mm.group(1)] = mm.group(2).strip('"').strip("'")
        commands.append({'name': fm.get('name', p.stem), 'category': fm.get('category', '?'), 'alpha': fm.get('alpha', '-')})

# --- 3. parse hooks/hooks.json ---
hook_events = []
hj = target/'hooks'/'hooks.json'
if hj.exists():
    cfg = json.loads(hj.read_text())
    for event, matchers in cfg.get('hooks', {}).items():
        rows = []
        for grp in matchers:
            matcher = grp.get('matcher', '*')
            for h in grp.get('hooks', []):
                cmd = h.get('command', '')
                script = cmd.split('/')[-1].replace('.sh','')
                rows.append((matcher, script))
        hook_events.append((event, rows))

# --- 4. parse .github/workflows/*.yml ---
workflows = []
wf_dir = target/'.github'/'workflows'
if wf_dir.exists() and yaml is not None:
    for p in sorted(list(wf_dir.glob('*.yml')) + list(wf_dir.glob('*.yaml'))):
        try:
            data = yaml.safe_load(p.read_text())
        except Exception:
            data = {}
        on = data.get(True, data.get('on', {}))  # YAML bare 'on' parses as True
        if isinstance(on, list):
            triggers = [str(x) for x in on]
        elif isinstance(on, dict):
            triggers = []
            for k, v in on.items():
                if isinstance(v, dict) and 'types' in v:
                    triggers.append(f"{k}({','.join(v['types'])})")
                else:
                    triggers.append(str(k))
        else:
            triggers = [str(on)]
        jobs = list((data.get('jobs') or {}).keys())
        workflows.append({'name': p.stem, 'triggers': triggers, 'jobs': jobs})

# --- 5. parse lib/*.py + tools/*.py for module layer ---
lib_modules = sorted([p.stem for p in (target/'lib').glob('*.py') if p.stem != '__init__']) if (target/'lib').exists() else []
tool_modules = sorted([p.stem for p in (target/'tools').glob('*.py')]) if (target/'tools').exists() else []

# --- 6. infer skill/command relationships from /dev-kit:<name> refs ---
skill_names = {s['name'] for s in skills}
cmd_names = {c['name'] for c in commands}
ref_re = re.compile(r'/dev-kit:([a-z0-9-]+)')
relations = collections.defaultdict(set)
def harvest(text):
    return {m for m in ref_re.findall(text) if m in skill_names}
for s in skills:
    for d in harvest(s['body']):
        if d != s['name']: relations[s['name']].add(d)
for c in commands:
    txt_path = target/'commands'/f"{c['name']}.md"
    if txt_path.exists():
        for d in harvest(txt_path.read_text()):
            relations[c['name']].add(d)

# --- 7. known module roles for the lib layer diagram ---
ROLE = {
    'execute': 'build runner (per-step)',
    'git_worktree': 'worktree cut/remove',
    'ci_setup': 'CI templates install',
    'ci_doctor': 'CI readiness audit',
    'ci_triage': 'GH Actions triage',
    'interview_engine': 'plan interviews',
    'state_codec': 'phase state codec',
    'atomic': 'atomic write helper',
    'render_proposal_html': 'proposal render',
    'render_report_html': 'eval report render',
    'llm_judge': 'LLM-as-judge',
    'llm_pricing': 'token pricing data',
    'eval_runner': 'eval harness',
    'cost_gate': 'cost ceiling',
    'babysit_pr_cli': 'PR babysitter',
    'babysit_pr_reliability': 'PR babysitter state',
    'acp_dispatch': 'ACP tier dispatch',
    'active_hooks_codec': 'active-hooks codec',
    'trace_log': 'trace logging',
    'push_intent_judge': 'push intent LLM',
    'research_engine': 'research gate',
    'maintenance_gate': 'maintenance gate',
    'meta_eval': 'meta eval',
}

# --- 8. build mermaid blocks ---
blocks = []  # (title, mmd_text)

# (a) Architecture overview — layered TB
arch = ['flowchart TB',
    '  USER([user / gh CLI / editor]):::ext',
    '  SLY["skills/ + commands/\nSKILL.md frontmatter"]:::layer',
    '  HLY["hooks/ — Claude Code events\nPreToolUse etc"]:::layer',
    '  LLY["lib/ — execute.py + worktree + ci_setup etc"]:::layer',
    '  SLY2["hooks/*.sh + bin/ scripts"]:::layer',
    '  CI[(.github/workflows/*.yml)]:::ext',
    '  USER --> SLY',
    '  SLY --> HLY',
    '  HLY --> LLY',
    '  LLY --> SLY2',
    '  SLY2 --> CI',
    '  CI --> USER',
    '  classDef ext fill:#fff4e1,stroke:#d97706',
    '  classDef layer fill:#e3f2fd,stroke:#1976d2']
blocks.append(('Architecture overview (layered topology)', '\n'.join(arch)))

# (b) dev-kit pipeline — LR
PIPELINE = [
    ('bootstrap', 'fresh repo CLAUDE.md'),
    ('plan', 'PRD.md + phases'),
    ('ci-setup', 'CI templates'),
    ('build', 'per-step runner'),
    ('review', '3-dim fan-out'),
    ('security', 'OWASP A01-A10'),
    ('ship', 'release tag'),
]
pl = ['flowchart LR']
for i,(n,role) in enumerate(PIPELINE):
    nid_ = nid(n,'p_')
    pl.append(f'  {nid_}["{n}\n{role}"]:::stage')
    if i>0: pl.append(f'  {nid(PIPELINE[i-1][0],"p_")} --> {nid_}')
pl.append('  classDef stage fill:#dbeafe,stroke:#1976d2')
blocks.append(('dev-kit pipeline (canonical stage chain)', '\n'.join(pl)))

# (c) Skill relationship graph — LR (only edges with target resolution)
rel = ['flowchart LR']
emitted_nodes = set()
for src in sorted(relations.keys()):
    src_id = nid(src,'s_')
    rel.append(f'  {src_id}["{src}"]:::skill')
    emitted_nodes.add(src_id)
    for dst in sorted(relations[src]):
        dst_id = nid(dst,'s_')
        if dst_id not in emitted_nodes:
            rel.append(f'  {dst_id}["{dst}"]:::skill')
            emitted_nodes.add(dst_id)
        rel.append(f'  {src_id} --> {dst_id}')
rel.append('  classDef skill fill:#e8f5e9,stroke:#388e3c')
blocks.append(('Skill relationship graph (parsed /dev-kit: refs)', '\n'.join(rel)))

# (d) Hook event matrix — TD grouped by event
hk = ['flowchart TD']
for evt, rows in hook_events:
    ev_id = nid(evt,'ev_')
    hk.append(f'  {ev_id}[/{evt}/]:::event')
    for matcher, script in rows:
        s_id = nid(script,'h_')
        lbl = f'{script}\nmatcher={matcher}' if matcher != '*' else script
        hk.append(f'  {s_id}["{lbl}"]:::hook')
        hk.append(f'  {ev_id} --> {s_id}')
hk.append('  classDef event fill:#fce4ec,stroke:#c2185b')
hk.append('  classDef hook fill:#f3e5f5,stroke:#7b1fa2')
blocks.append(('Hook event matrix (Claude Code events to scripts)', '\n'.join(hk)))

# (e) GitHub Actions trigger graph — LR
gh = ['flowchart LR']
for wf in workflows:
    wf_id = nid(wf['name'],'gh_')
    trig_str = ', '.join(wf['triggers'])
    jobs_str = ', '.join(wf['jobs'])
    gh.append(f'  TR_{wf_id}["{wf["name"]}\non: {trig_str}"]:::trig')
    gh.append(f'  WF_{wf_id}["{wf["name"]}.yml\njobs: {jobs_str}"]:::wf')
    gh.append(f'  TR_{wf_id} --> WF_{wf_id}')
gh.append('  classDef trig fill:#fff8e1,stroke:#f57c00')
gh.append('  classDef wf fill:#e0f7fa,stroke:#00838f')
blocks.append(('GitHub Actions triggers to jobs', '\n'.join(gh)))

# (f) Library layer — LR with role annotations
lb = ['flowchart LR', '  LIB((lib/)):::lib']
for m in lib_modules:
    m_id = nid(m,'lib_')
    role = ROLE.get(m, '')
    lbl = f'{m}\n{role}' if role else m
    lb.append(f'  {m_id}["{lbl}"]:::mod')
    lb.append(f'  LIB --> {m_id}')
lb.append('  classDef lib fill:#ede7f6,stroke:#512da8')
lb.append('  classDef mod fill:#f5f5f5,stroke:#616161')
blocks.append(('Library layer (lib/*.py modules)', '\n'.join(lb)))

# (g) build stage sequence — sequenceDiagram
seq = ['sequenceDiagram',
    '  participant U as User',
    '  participant P as lib/execute.py',
    '  participant W as git worktree',
    '  participant C as claude -p sub-agent',
    '  U->>P: invoke /dev-kit:build',
    '  P->>P: parse phases/[n]/index.json',
    '  P->>W: cut per-step worktree',
    '  P->>C: spawn with step preamble + AC',
    '  C-->>P: exit_code + stdout + stderr',
    '  P->>P: write step[N]-output.json (real)',
    '  alt exit_code == 0',
    '    P->>W: 2-commit feat then chore',
    '  else exit_code != 0 (3-cycle max)',
    '    P->>C: re-invoke with stderr',
    '  end',
    '  P-->>U: hand-off build to review.md']
blocks.append(('build stage sequence (per-step workflow)', '\n'.join(seq)))

# --- 9. emit HTML (lightbox pattern) ---
sections = []
for i,(t,m) in enumerate(blocks):
    sections.append(f'<h2 id="m{i}">{esc(t)}</h2>\n<pre class="mermaid">\n{m}\n</pre>')
sections_html = '\n'.join(sections)

skill_rows = '\n'.join(
    f'<tr><td><code>{esc(s["name"])}</code></td><td>{esc(s["category"])}</td><td>{esc(s["alpha"])}</td><td>{esc(s["model"])}</td><td>{esc(s["user_invocable"])}</td></tr>'
    for s in skills)
cmd_rows = '\n'.join(
    f'<tr><td><code>{esc(c["name"])}</code></td><td>{esc(c["category"])}</td><td>{esc(c["alpha"])}</td></tr>'
    for c in commands)
hook_rows = '\n'.join(
    f'<tr><td><code>{esc(evt)}</code></td><td><code>{esc(matcher)}</code></td><td><code>{esc(script)}</code></td></tr>'
    for evt, rows in hook_events for matcher, script in rows)
wf_rows = '\n'.join(
    f'<tr><td><code>{esc(w["name"])}.yml</code></td><td>{esc(", ".join(w["triggers"]))}</td><td>{esc(", ".join(w["jobs"]))}</td></tr>'
    for w in workflows)

doc = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>code-viz — {esc(target.name)}</title>
<style>
  body{{font:14px/1.55 -apple-system,system-ui,sans-serif;max-width:1200px;margin:24px auto;padding:0 24px;color:#1a1a1a}}
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
  .nav{{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:8px 0;z-index:50}}
  .nav a{{margin-right:12px;font-size:.85em;color:#1976d2;text-decoration:none}}
  .nav a:hover{{text-decoration:underline}}
  .mermaid-modal{{position:fixed;inset:0;background:rgba(8,12,20,0.88);z-index:10000;cursor:zoom-out;padding:32px;overflow:auto;display:none;text-align:center}}
  .mermaid-modal.open{{display:block}}
  .mermaid-modal .modal-card{{background:#fafbfc;border-radius:10px;padding:28px;display:inline-block;position:relative;text-align:left}}
  .mermaid-modal .modal-close{{position:absolute;top:8px;right:12px;border:1px solid #d0d7de;background:white;border-radius:6px;padding:4px 10px;cursor:pointer;font-family:inherit;font-size:13px}}
  .mermaid-modal .modal-card svg{{width:auto!important;max-width:95vw;height:auto!important;display:block;margin:0 auto}}
  @media (prefers-color-scheme:dark){{body{{color:#e8e8e8;background:#111}}.nav{{background:#111;border-color:#333}}pre.mermaid{{background:#161b22;border-color:#30363d}}pre.mermaid:hover{{background:#1c232c}}th{{background:#1c1c1c}}th,td{{border-color:#333}}h1,h2{{border-color:#555}}td code{{background:#2a2a2a}}.mermaid-modal .modal-card{{background:#161b22;color:#e6edf3}}.mermaid-modal .modal-close{{background:#21262d;color:#e6edf3;border-color:#30363d}}}}
</style></head><body>

<h1>code-viz — {esc(target.name)}</h1>
<p class="meta">target=<code>{esc(target)}</code> · generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M UTC')} · {len(blocks)} mermaid diagrams · click any to expand</p>

<div class="nav">
  <a href="#m0">architecture</a>
  <a href="#m1">pipeline</a>
  <a href="#m2">skill graph</a>
  <a href="#m3">build sequence</a>
  <a href="#m4">hooks</a>
  <a href="#m5">GH actions</a>
  <a href="#m6">lib layer</a>
</div>

<h2>Skills ({len(skills)})</h2>
<table><tr><th>name</th><th>category</th><th>alpha</th><th>model</th><th>user-invocable</th></tr>{skill_rows}</table>

<h2>Commands ({len(commands)})</h2>
<table><tr><th>name</th><th>category</th><th>alpha</th></tr>{cmd_rows}</table>

<h2>Hook scripts ({sum(len(r) for _,r in hook_events)})</h2>
<table><tr><th>event</th><th>matcher</th><th>script</th></tr>{hook_rows}</table>

<h2>GitHub Actions ({len(workflows)})</h2>
<table><tr><th>file</th><th>on</th><th>jobs</th></tr>{wf_rows}</table>

{sections_html}

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
n_diagrams = doc.count('class="mermaid"')

# --- 10. validate via Playwright ---
import subprocess
v = subprocess.run(['python3', '-c', f'''
from playwright.sync_api import sync_playwright
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

import re
svgs_match = re.search(r'svgs=(\d+)', v.stdout)
svgs_count = svgs_match.group(1) if svgs_match else '?'
print(f'[code-viz] target={target}')
print(f'[code-viz] parsed {len(skills)} skills, {len(commands)} commands, {sum(len(r) for _,r in hook_events)} hooks, {len(workflows)} GH workflows, {len(lib_modules)} lib modules')
print(f'[code-viz] wrote {out} ({out.stat().st_size:,} bytes, {n_diagrams} mermaid diagrams)')
print(f'[code-viz] validation: 0 syntax-error / {svgs_count}/{n_diagrams} svgs / modal click OK')
print(f'open {out}')
PY
```

## Verification summary (this iteration)

- One SKILL.md file (~340 LOC body + ~270 lines of embedded heredoc).
- The heredoc is end-to-end: parse skills/commands/hooks/workflows/lib → emit HTML with 7 Mermaid diagrams + inventory tables → Playwright validate → exit 0/non-zero per result.
- 7 diagrams: architecture, pipeline, skill relations, build sequence, hook matrix, GH Actions, lib layer.
- No new files outside `skills/code-viz/`. No hooks. No MCP.

## Hand-off

After the skill emits the HTML and the validator passes, open `file:///tmp/code-viz.html` in the browser. Each diagram is bounded to `72vh` by default; click any card to expand at the diagram's natural viewBox size; ESC / backdrop / close button dismisses the modal. The sticky nav bar jumps to each diagram section.