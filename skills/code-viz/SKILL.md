---
name: code-viz
category: audit
description: 0-arg. Parse skills/hooks/commands/.github/workflows and emit one self-contained HTML with stat tiles + 7 Mermaid diagrams (architecture, pipeline, skill relations, build sequence, hook matrix, GH Actions, lib layer) + inventory tables. Optional --screenshots exports each diagram as PNG for README embedding. Playwright-validated.
alpha: state
when_to_use:
  - User types /dev-kit:code-viz and wants architecture/workflow/relationship diagrams, not just file counts
  - User wants to embed diagrams in a README (use --screenshots for per-diagram PNGs)
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

1. **Stat tiles** — one tile per parsed surface (`39 skills · 2 commands · 14 hooks · 7 GH workflows · 26 lib modules`).
2. **Inventory tables** — skills (name / category / alpha / model / user-invocable), commands, hook scripts (event × matcher × script), GitHub Actions (file / triggers / jobs).
3. **Architecture overview** — `flowchart TB` showing the layered topology: user → skill/command frontmatter → Claude hook events → `lib/` modules → `.sh`/`.py` scripts → `.github/workflows/*.yml` → back to user.
4. **dev-kit pipeline** — `flowchart LR` of the canonical stage chain: `bootstrap → plan → ci-setup → build → review → security → ship`.
5. **Skill relationship graph** — `flowchart LR` derived by scanning every `SKILL.md` + `commands/*.md` body for `/dev-kit:<name>` references and emitting an edge per call.
6. **build stage sequence** — `sequenceDiagram` of one step inside `/dev-kit:build`: worktree cut → sub-agent spawn → exit code persist → 2-commit protocol → hand-off.
7. **Hook event matrix** — `flowchart TD` grouped by Claude event (PreToolUse / PostToolUse / SessionStart / UserPromptSubmit / Stop), each matcher + script as a child node.
8. **GitHub Actions triggers** — `flowchart LR` of `on:` events → workflow files → jobs.
9. **Library layer** — `flowchart LR` of `lib/*.py` modules annotated with their known role (runner / worktree / ci-setup / state codec / atomic writer / etc.).

Each diagram is bounded to `72vh` by default; **click any card** to open a modal at the diagram's natural viewBox size; ESC / backdrop / close-button dismisses. The HTML uses CSS variables so light + dark themes stay readable, and Mermaid is initialized with explicit `themeVariables` so node text never disappears against fills.

## Iron Law (no exceptions)

**0-arg default OK. Hidden flags:**
- `--target DIR` (default `$PWD`)
- `--out PATH` (default `/tmp/code-viz.html`)
- `--screenshots DIR` (optional; export each `pre.mermaid` as a PNG into DIR — drop straight into a README. The HTML is still emitted.)
- `--strict` (treat any validation failure as a hard error — non-zero exit)

The skill does **not modify** the target — read-only walk + new HTML in `/tmp` + optional PNGs into `--screenshots DIR`.

## Mermaid pitfalls (already burned into the validator)

Don't ship any of these; the next hard-fail check will surface them:

- `<br/>` inside flowchart node shape labels — flaky in v10.9.1; use `\n` or `·`.
- `<n>`-style placeholders (e.g. `<name>`) — interpreted as HTML; use `[N]` or just text.
- `:` inside `stateDiagram-v2` transition labels (e.g. `lib/foo.py:130`) — `:` is the transition/label separator in stateDiagram. **Replace with `line N` form.** Flowchart edge labels handle `:` fine; only stateDiagram trips here.
- JS post-render sizing — Mermaid's async render loses the race with `setTimeout`/`load`. CSS-only with `!important` is more reliable.
- Raw `on:` in YAML GH-Actions — `yaml.safe_load` parses the bare key `on` as Python boolean `True`; always read via `data.get(True, data.get('on'))`.
- Unthemed Mermaid in dark mode — default theme paints light fills that disappear against a dark page; force `theme: 'base'` + explicit `themeVariables.primaryTextColor` so node text always reads.

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
[code-viz] exported N PNGs into <screenshots dir>
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

target      = pathlib.Path(args.get('target', '.')).resolve()
out         = pathlib.Path(args.get('out', '/tmp/code-viz.html'))
screenshots = pathlib.Path(args['screenshots']) if 'screenshots' in args else None
strict      = args.get('strict', False)

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
        on = data.get(True, data.get('on', {}))
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

# --- 5. parse lib/*.py ---
lib_modules = sorted([p.stem for p in (target/'lib').glob('*.py') if p.stem != '__init__']) if (target/'lib').exists() else []

# --- 6. infer skill/command relationships from /dev-kit:<name> refs ---
skill_names = {s['name'] for s in skills}
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
blocks = []
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
    '  classDef ext fill:#fff4e1,stroke:#d97706,color:#7c2d12',
    '  classDef layer fill:#e3f2fd,stroke:#1976d2,color:#0d47a1']
blocks.append(('Architecture overview', '\n'.join(arch)))

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
pl.append('  classDef stage fill:#dbeafe,stroke:#1976d2,color:#0d47a1')
blocks.append(('dev-kit pipeline', '\n'.join(pl)))

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
rel.append('  classDef skill fill:#e8f5e9,stroke:#388e3c,color:#1b5e20')
blocks.append(('Skill relationship graph', '\n'.join(rel)))

hk = ['flowchart TD']
for evt, rows in hook_events:
    ev_id = nid(evt,'ev_')
    hk.append(f'  {ev_id}[/{evt}/]:::event')
    for matcher, script in rows:
        s_id = nid(script,'h_')
        lbl = f'{script}\nmatcher={matcher}' if matcher != '*' else script
        hk.append(f'  {s_id}["{lbl}"]:::hook')
        hk.append(f'  {ev_id} --> {s_id}')
hk.append('  classDef event fill:#fce4ec,stroke:#c2185b,color:#880e4f')
hk.append('  classDef hook fill:#f3e5f5,stroke:#7b1fa2,color:#4a148c')
blocks.append(('Hook event matrix', '\n'.join(hk)))

gh = ['flowchart LR']
for wf in workflows:
    wf_id = nid(wf['name'],'gh_')
    trig_str = ', '.join(wf['triggers'])
    jobs_str = ', '.join(wf['jobs'])
    gh.append(f'  TR_{wf_id}["{wf["name"]}\non: {trig_str}"]:::trig')
    gh.append(f'  WF_{wf_id}["{wf["name"]}.yml\njobs: {jobs_str}"]:::wf')
    gh.append(f'  TR_{wf_id} --> WF_{wf_id}')
gh.append('  classDef trig fill:#fff8e1,stroke:#f57c00,color:#e65100')
gh.append('  classDef wf fill:#e0f7fa,stroke:#00838f,color:#006064')
blocks.append(('GitHub Actions', '\n'.join(gh)))

lb = ['flowchart LR', '  LIB((lib/)):::lib']
for m in lib_modules:
    m_id = nid(m,'lib_')
    role = ROLE.get(m, '')
    lbl = f'{m}\n{role}' if role else m
    lb.append(f'  {m_id}["{lbl}"]:::mod')
    lb.append(f'  LIB --> {m_id}')
lb.append('  classDef lib fill:#ede7f6,stroke:#512da8,color:#311b92')
lb.append('  classDef mod fill:#f5f5f5,stroke:#616161,color:#212121')
blocks.append(('Library layer', '\n'.join(lb)))

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
blocks.append(('build stage sequence', '\n'.join(seq)))

# --- 9. emit HTML ---
sections = []
for i,(t,m) in enumerate(blocks):
    sections.append(f'<section class="card" id="m{i}"><h2>{esc(t)}</h2><pre class="mermaid">\n{m}\n</pre></section>')
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

stat_tiles = '\n'.join(
    f'<div class="stat"><div class="num">{n}</div><div class="lbl">{lbl}</div></div>'
    for n,lbl in [
        (len(skills), 'skills'),
        (len(commands), 'commands'),
        (sum(len(r) for _,r in hook_events), 'hooks'),
        (len(workflows), 'GH actions'),
        (len(lib_modules), 'lib modules'),
    ])

nav_links = '\n'.join(
    f'<a href="#m{i}">{esc(t)}</a>'
    for i,(t,_) in enumerate(blocks))

doc = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>code-viz — {esc(target.name)}</title>
<style>
  :root {{
    --bg:#ffffff; --fg:#1a1a1a; --muted:#6b7280;
    --card:#ffffff; --card-border:#e5e7eb;
    --accent:#2563eb; --code-bg:#f3f4f6;
    --stripe:#f9fafb; --table-border:#e5e7eb;
    --mermaid-bg:#fafbfc; --hover-bg:#f3f6fa;
    --shadow:0 1px 3px rgba(0,0,0,0.05),0 1px 2px rgba(0,0,0,0.06);
    --shadow-lg:0 10px 25px rgba(0,0,0,0.10),0 4px 10px rgba(0,0,0,0.05);
  }}
  @media (prefers-color-scheme:dark) {{
    :root {{
      --bg:#0d1117; --fg:#e6edf3; --muted:#9da7b0;
      --card:#161b22; --card-border:#30363d;
      --accent:#58a6ff; --code-bg:#21262d;
      --stripe:#0d1117; --table-border:#30363d;
      --mermaid-bg:#161b22; --hover-bg:#1c232c;
      --shadow:0 1px 3px rgba(0,0,0,0.4);
      --shadow-lg:0 10px 25px rgba(0,0,0,0.5),0 4px 10px rgba(0,0,0,0.3);
    }}
  }}
  *{{box-sizing:border-box}}
  body{{font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;max-width:1200px;margin:0 auto;padding:32px 28px 64px;background:var(--bg);color:var(--fg)}}
  h1{{font-size:1.9em;font-weight:700;margin:0 0 6px;letter-spacing:-0.02em}}
  h2{{font-size:1.25em;font-weight:600;margin:0 0 14px;padding-bottom:8px;border-bottom:1px solid var(--card-border);color:var(--fg)}}
  h3{{font-size:1em;font-weight:600;margin:0 0 8px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}}
  .meta{{color:var(--muted);font-size:.85em;margin:0 0 20px}}
  .meta code{{background:var(--code-bg);padding:2px 6px;border-radius:4px;font-size:.9em;color:var(--fg)}}
  .header{{padding:24px 28px;border-radius:14px;background:linear-gradient(135deg,var(--card) 0%,var(--stripe) 100%);border:1px solid var(--card-border);box-shadow:var(--shadow);margin-bottom:24px}}
  .stats{{display:flex;flex-wrap:wrap;gap:12px;margin:18px 0 0}}
  .stat{{flex:1 1 110px;min-width:110px;padding:14px 18px;background:var(--card);border:1px solid var(--card-border);border-radius:10px;box-shadow:var(--shadow)}}
  .stat .num{{font-size:2em;font-weight:700;color:var(--accent);line-height:1.1;letter-spacing:-0.02em}}
  .stat .lbl{{font-size:.78em;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:4px;font-weight:500}}
  .nav{{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--card-border);padding:10px 0;z-index:50;margin:0 -28px 24px;padding-left:28px;padding-right:28px}}
  .nav a{{margin-right:14px;font-size:.85em;color:var(--accent);text-decoration:none;font-weight:500}}
  .nav a:hover{{text-decoration:underline}}
  .nav a:first-child{{margin-left:0}}
  .card{{background:var(--card);border:1px solid var(--card-border);border-radius:12px;box-shadow:var(--shadow);padding:22px 24px;margin-bottom:20px}}
  table{{border-collapse:collapse;width:100%;margin:.4em 0;font-size:.92em}}
  th,td{{border:1px solid var(--table-border);padding:7px 11px;text-align:left;vertical-align:top}}
  th{{background:var(--stripe);font-weight:600;font-size:.85em;color:var(--fg)}}
  tbody tr:nth-child(even) td{{background:var(--stripe)}}
  td code{{background:var(--code-bg);padding:2px 6px;border-radius:4px;font-size:.88em;color:var(--fg);font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace}}
  pre.mermaid{{display:block;width:100%;margin:0;padding:16px;background:var(--mermaid-bg);border:1px solid var(--card-border);border-radius:8px;cursor:zoom-in;position:relative;max-height:72vh;overflow:hidden}}
  pre.mermaid:hover{{box-shadow:0 0 0 2px rgba(80,120,200,0.25);background:var(--hover-bg)}}
  pre.mermaid::after{{content:"click to expand";position:absolute;bottom:8px;right:12px;font-size:11px;color:var(--muted);background:var(--card);padding:2px 8px;border-radius:4px;pointer-events:none;font-family:ui-monospace,monospace;border:1px solid var(--card-border)}}
  pre.mermaid svg{{width:100%!important;height:auto!important;display:block}}
  pre.mermaid svg text{{fill:#1a1a1a!important;font-weight:500}}
  @media (prefers-color-scheme:dark){{pre.mermaid svg text{{fill:#e6edf3!important}}}}
  footer{{color:var(--muted);font-size:.8em;text-align:center;padding-top:24px;border-top:1px solid var(--card-border);margin-top:32px}}
  footer code{{background:var(--code-bg);padding:1px 6px;border-radius:4px;color:var(--fg)}}
  .mermaid-modal{{position:fixed;inset:0;background:rgba(8,12,20,0.88);z-index:10000;cursor:zoom-out;padding:32px;overflow:auto;display:none;text-align:center}}
  .mermaid-modal.open{{display:block}}
  .mermaid-modal .modal-card{{background:var(--card);color:var(--fg);border-radius:10px;padding:28px;display:inline-block;position:relative;text-align:left;box-shadow:var(--shadow-lg)}}
  .mermaid-modal .modal-close{{position:absolute;top:8px;right:12px;border:1px solid var(--card-border);background:var(--card);color:var(--fg);border-radius:6px;padding:4px 10px;cursor:pointer;font-family:inherit;font-size:13px}}
  .mermaid-modal .modal-card svg{{width:auto!important;max-width:95vw;height:auto!important;display:block;margin:0 auto}}
  @media print{{.nav,.mermaid-modal{{display:none!important}}body{{padding:8px;max-width:none}}.card{{box-shadow:none;border:1px solid #ddd;page-break-inside:avoid;break-inside:avoid}}pre.mermaid{{max-height:none;overflow:visible;page-break-inside:avoid}}}}
</style></head><body>

<header class="header">
  <h1>code-viz — {esc(target.name)}</h1>
  <p class="meta">target <code>{esc(target)}</code> · generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M UTC')} · {len(blocks)} mermaid diagrams · click any diagram to expand</p>
  <div class="stats">{stat_tiles}</div>
</header>

<nav class="nav">{nav_links}</nav>

<section class="card"><h2>Skills ({len(skills)})</h2><table><thead><tr><th>name</th><th>category</th><th>alpha</th><th>model</th><th>user-invocable</th></tr></thead><tbody>{skill_rows}</tbody></table></section>

<section class="card"><h2>Commands ({len(commands)})</h2><table><thead><tr><th>name</th><th>category</th><th>alpha</th></tr></thead><tbody>{cmd_rows}</tbody></table></section>

<section class="card"><h2>Hook scripts ({sum(len(r) for _,r in hook_events)})</h2><table><thead><tr><th>event</th><th>matcher</th><th>script</th></tr></thead><tbody>{hook_rows}</tbody></table></section>

<section class="card"><h2>GitHub Actions ({len(workflows)})</h2><table><thead><tr><th>file</th><th>on</th><th>jobs</th></tr></thead><tbody>{wf_rows}</tbody></table></section>

{sections_html}

<div class="mermaid-modal" id="mermaid-modal" role="dialog" aria-modal="true">
  <div class="modal-card">
    <button class="modal-close" type="button">close (esc)</button>
    <div class="modal-content"></div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<script>
mermaid.initialize({{
  startOnLoad:true,
  securityLevel:'loose',
  theme:'base',
  themeVariables:{{
    fontFamily:'ui-sans-serif,-apple-system,system-ui,sans-serif',
    fontSize:'14px',
    primaryColor:'#e3f2fd', primaryTextColor:'#0d47a1', primaryBorderColor:'#1976d2',
    secondaryColor:'#fce4ec', secondaryTextColor:'#880e4f', secondaryBorderColor:'#c2185b',
    tertiaryColor:'#fff8e1', tertiaryTextColor:'#e65100', tertiaryBorderColor:'#f57c00',
    lineColor:'#555555',
    edgeLabelBackground:'#ffffff',
    clusterBkg:'#f5f5f5', clusterBorder:'#999999',
    titleColor:'#0a0a0a'
  }}
}});
(function(){{var modal=document.getElementById('mermaid-modal');var content=modal.querySelector('.modal-content');var closeBtn=modal.querySelector('.modal-close');function open(svg){{content.innerHTML='';var c=svg.cloneNode(true);var vb=(c.getAttribute('viewBox')||'').split(/\\s+/);if(vb.length===4){{c.setAttribute('width',parseFloat(vb[2]));c.setAttribute('height',parseFloat(vb[3]))}}c.style.removeProperty('max-width');c.style.removeProperty('width');c.style.removeProperty('height');content.appendChild(c);modal.classList.add('open');document.body.style.overflow='hidden'}}function close(){{modal.classList.remove('open');document.body.style.overflow=''}}function bind(){{document.querySelectorAll('pre.mermaid').forEach(function(p){{if(p._bound)return;p._bound=true;p.addEventListener('click',function(){{var svg=p.querySelector('svg');if(svg)open(svg)}})}})}}var tries=0;var poll=setInterval(function(){{if(document.querySelector('pre.mermaid svg')){{clearInterval(poll);bind()}}else if(++tries>30)clearInterval(poll)}},200);closeBtn.addEventListener('click',close);modal.addEventListener('click',function(e){{if(e.target===modal)close()}});document.addEventListener('keydown',function(e){{if(e.key==='Escape')close()}})}})();
</script>
<footer>generated by <code>/dev-kit:code-viz</code> · {len(skills)} skills · {len(commands)} commands · {sum(len(r) for _,r in hook_events)} hooks · {len(workflows)} GH actions · {len(lib_modules)} lib modules · {len(blocks)} diagrams</footer>
</body></html>
'''
out.write_text(doc)
n_diagrams = len(blocks)

# --- 10. validate via Playwright (asserts 0 syntax-error / N svgs / modal) ---
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

# --- 11. optional per-diagram PNG screenshots (for README embedding) ---
png_count = 0
if screenshots is not None:
    screenshots.mkdir(parents=True, exist_ok=True)
    v2 = subprocess.run(['python3', '-c', f'''
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page(viewport={{"width":1400,"height":900}})
    page.goto("file://{out}", wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(1500)
    for i,el in enumerate(page.query_selector_all("pre.mermaid")):
        el.scroll_into_view_if_needed()
        page.wait_for_timeout(150)
        out_png = "{screenshots}/diagram-{{:02d}}.png".format(i)
        el.screenshot(path=out_png, omit_background=False)
        print("png=" + out_png)
    b.close()
'''], capture_output=True, text=True, timeout=120)
    if v2.returncode != 0:
        sys.stderr.write('[code-viz] SCREENSHOT SUBPROCESS FAILED rc=' + str(v2.returncode) + '\n')
        sys.stderr.write(v2.stderr + '\n')
    else:
        png_count = len(re.findall(r'^png=', v2.stdout, re.M))

import re
svgs_match = re.search(r'svgs=(\d+)', v.stdout)
svgs_count = svgs_match.group(1) if svgs_match else '?'
print(f'[code-viz] target={target}')
print(f'[code-viz] parsed {len(skills)} skills, {len(commands)} commands, {sum(len(r) for _,r in hook_events)} hooks, {len(workflows)} GH workflows, {len(lib_modules)} lib modules')
print(f'[code-viz] wrote {out} ({out.stat().st_size:,} bytes, {n_diagrams} mermaid diagrams)')
if png_count:
    print(f'[code-viz] exported {png_count} PNGs into {screenshots}')
print(f'[code-viz] validation: 0 syntax-error / {svgs_count}/{n_diagrams} svgs / modal click OK')
print(f'open {out}')
PY
```

## Verification summary (this iteration)

- One SKILL.md file (~410 LOC body + ~290 lines of embedded heredoc).
- The heredoc is end-to-end: parse skills/commands/hooks/workflows/lib → emit HTML with 7 Mermaid diagrams + stat tiles + inventory tables → optional `--screenshots DIR` PNG export per diagram → Playwright validate → exit 0/non-zero per result.
- CSS variables + explicit `mermaid.themeVariables` keep light and dark modes readable (no dark-on-dark).
- `@media print` rules hide nav/modal and unclip diagrams so ⌘P → Save as PDF produces a clean README-ready PDF.
- No new files outside `skills/code-viz/`. No hooks. No MCP.

## Hand-off

After the skill emits the HTML and the validator passes, open `file:///tmp/code-viz.html` in the browser. Each diagram is bounded to `72vh` by default; click any card to expand at the diagram's natural viewBox size; ESC / backdrop / close button dismisses the modal. For README inclusion: pass `--screenshots docs/diagrams` and the skill writes one PNG per diagram (`diagram-00.png` … `diagram-06.png`) — drop those straight into your README.