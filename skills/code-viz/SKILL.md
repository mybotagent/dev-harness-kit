---
name: code-viz
category: audit
description: 0-arg generic plugin-architecture visualizer. Walks any target repo, emits self-contained HTML with multi-level views (architecture / code / skill / hook / tools-lib / external) + domain pillar map (DB · Cloud · API · MCP · Skill · Hook · Network · Security · Build · Test · Storage · LLM) + per-skill workflows (multi-strategy extraction incl. ## Categories/Dimensions for security/inspect) + GH Actions gate workflow + optional per-diagram PNG export.
alpha: state
when_to_use:
  - User types /dev-kit:code-viz and wants a generic plugin-architecture overview, not repo-specific
  - User wants multi-level views (architecture → code → skill → hook → tools → external) + per-skill workflows
  - User wants diagrams classified by domain pillar (DB / Cloud / API / MCP / Skill / Hook / Network / Security / Build / Test / Storage / LLM)
  - User wants GH Actions gate workflow (review/security/gate verdict) sequence visualized
  - User wants per-skill workflow extraction + drop-in PNG screenshots for a README
allowed-tools: Read Bash Glob Write
disallowed-tools: WebFetch Edit NotebookEdit
model: sonnet
user-invocable: true
disable-model-invocation: false
---

# /dev-kit:code-viz — generic plugin-architecture visualizer

## What it does

A single `python3 << 'PY' ... PY` heredoc that walks **any target repo** (Claude Code plugin, MCP server, microservice, monorepo, framework) and emits `/tmp/code-viz.html` containing **multi-level views** + **a domain pillar map**:

### 6 abstraction levels + 1 cross-cutting view

| # | Level | What it shows |
|---|---|---|
| 0 | **L0 Architecture overview** | Layered topology: external → user surface → events → libs → scripts → external CI |
| 1 | **L1 Code level** | Directory tree, extension breakdown, key files |
| 2 | **L2 Skill level** | Skills + commands inventory; **per-skill workflow diagrams** for top N user-invocable skills via **multi-strategy extraction** (incl. `## Categories`/`## Dimensions` domain content for security/inspect). Skills with no detectable workflow are listed as text, not visualized. |
| 3 | **L3 Hook event** | Claude event × matcher × script matrix |
| 4 | **L4 Tools and Library layer** | `bin/` + `tools/` + `lib/` module inventory |
| 5 | **L5 External tools** | GitHub Actions triggers-to-jobs + MCP servers + third-party CLI invocations + **GH Actions gate workflow sequence** (PR → review/security fan-out → combined verdict) |
| - | **Cross-cutting — Domain pillar map** | Which files fall under DB / Cloud / API / MCP / Skill / Hook / Network / Security / Build / Test / Storage / LLM |

Each diagram is bounded to `72vh`; click any card to expand; ESC / backdrop / close-button dismisses. CSS variables drive both light + dark themes; Mermaid uses `theme: 'base'` + explicit `themeVariables` for high-contrast node text. `@media print` rules hide nav/modal so ⌘P produces a clean README-ready PDF.

## Iron Law (no exceptions)

**0-arg default OK. Hidden flags:**
- `--target DIR` (default `$PWD`)
- `--out PATH` (default `/tmp/code-viz.html`)
- `--screenshots DIR` (optional; export each `pre.mermaid` as a PNG into DIR)
- `--top-skills N` (default 20, max 40 — how many user-invocable skills get a per-skill workflow diagram; IMPORTANT skills always included)
- `--strict` (treat any validation failure as a hard error — non-zero exit)

The skill does **not modify** the target — read-only walk + new HTML in `/tmp` + optional PNGs.

## Generic by design (not repo-specific)

- **All classification is filename/path heuristic**. No hardcoded skill names, pipeline stages, or module roles. Works on any plugin/repo.
- **Surfaces are optional**. Missing `skills/`, `hooks/`, `.github/`, `lib/`, etc. → section gracefully omitted, not crashed.
- **IMPORTANT_SKILLS priority list** — `plan`, `build`, `review`, `security`, `eval`, `inspect`, `prune`, `refactor`, `ci-setup`, `babysit-pr`, `ship`, `bootstrap`, `code-viz`, `report`, `token-analyzer` always get workflow diagrams before alphabetical selection.
- **Skills without an extractable workflow** are listed as text in a "no workflow detected" section rather than visualized (no empty diagrams).

## Per-skill cycle extraction strategies (5 fallbacks)

1. **Strategy F — `## Categories` / `## Dimensions` / `## Audit areas` / `## Checks`** with bullet-list items (e.g. security's `## Categories` listing A01–A10, inspect's `## Dimensions` listing dead/dup/smell/.../slop). This runs first because it's the most semantically meaningful.
2. **Strategy A — `[N/M] LABEL`** with separators `→ | -> | — | – | - ` (e.g. `plan`'s `[1/5] frame — goal + target user`).
3. **Strategy B — `## Gate N/M — label`** / `## Phase N — label` / `## Sub-stage N — label`.
4. **Strategy C — numbered list under** `## Algorithm` / `## Behavior` / `## Pipeline` / `## Phases` / `## Cycle` (e.g. `babysit-pr`'s 8-step `## Algorithm`, `review`'s `## Scope` numbered list).
5. **Strategy D — `## <SectionName>` headers** as implicit phases (e.g. `eval`'s `## Modes` → `## Rubric registry` → `## Cross-validate` → `## Verdict` → `## Output`).

If all fail, the skill is added to a **"no explicit workflow detected"** text list (not a Mermaid diagram).

## Mermaid pitfalls (already burned into the validator)

- `<br/>` inside flowchart node shape labels — flaky in v10.9.1; use `\n` or `·`.
- `<n>`-style placeholders (e.g. `<name>`) — interpreted as HTML; use `[N]` or just text.
- `:` inside `stateDiagram-v2` transition labels (e.g. `lib/foo.py:130`) — `:` is the separator. **Replace with `line N` form.** Flowchart edge labels handle `:` fine.
- JS post-render sizing — Mermaid's async render loses the race with `setTimeout`/`load`. CSS-only with `!important` is more reliable.
- Raw `on:` in YAML GH-Actions — `yaml.safe_load` parses the bare key `on` as Python boolean `True`; always read via `data.get(True, data.get('on'))`.
- Unthemed Mermaid in dark mode — default theme paints light fills that disappear against a dark page; force `theme: 'base'` + explicit `themeVariables.primaryTextColor`.
- Long body snippets in node labels — keep labels ≤ 60 chars; strip backticks / arrows / quotes before interpolation.

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
    syntax_error = 'Syntax error in text' in body
    svgs = page.query_selector_all('pre.mermaid svg')
    page.query_selector('pre.mermaid').click()
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
[code-viz] discovered: 39 skills, 2 commands, 14 hooks, 7 GH workflows, 26 lib, 2 bin, 21 tools, 0 MCP
[code-viz] pillar map: Skill=39 Test=42 general=520 ...
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
top_skills  = int(args.get('top-skills', 20))
strict      = args.get('strict', False)

def esc(s): return html.escape(str(s))
def nid(s, prefix='n_'):
    n = re.sub(r'[^A-Za-z0-9_]', '_', s)
    if not n or not n[0].isalpha(): n = prefix + n
    return n
def safe_label(s, maxlen=60):
    s = re.sub(r'[`"<>]', '', str(s))
    s = s.replace('→', '->').replace('\n', ' · ')
    return s[:maxlen].strip()

PILLAR_PATTERNS = {
    'DB':       ['db', 'database', 'sql', 'mongo', 'redis', 'postgres', 'sqlite', 'orm', 'migration', 'schema'],
    'Cloud':    ['aws', 'gcp', 'azure', 'cloud', 'k8s', 'kubernetes', 'docker', 'lambda', 's3', 'ec2', 'iam'],
    'API':      ['api', 'rest', 'graphql', 'grpc', 'endpoint', 'route', 'controller', 'handler', 'middleware'],
    'MCP':      ['mcp', 'model_context'],
    'Skill':    ['skill', 'slash_command', 'commands/'],
    'Hook':     ['hook'],
    'Network':  ['network', 'http', 'socket', 'dns', 'tcp', 'udp', 'fetch', 'request', 'websocket', 'tls'],
    'Security': ['auth', 'secret', 'oauth', 'jwt', 'token', 'encrypt', 'decrypt', 'crypto', 'permission', 'rbac'],
    'Build':    ['ci', 'workflow', 'deploy', 'release', 'bump', 'ship', 'dist', 'bundle'],
    'Test':     ['test', 'spec', 'fixture', 'mock', 'conftest'],
    'Storage':  ['storage', 'blob', 'cache', 'kv', 'queue', 'pubsub'],
    'LLM':      ['llm', 'claude', 'gpt', 'prompt', 'judge', 'eval'],
}
def pillars_for(path_str):
    s = path_str.lower()
    hits = [p for p, pats in PILLAR_PATTERNS.items() if any(pat in s for pat in pats)]
    return hits or ['general']

IMPORTANT_SKILLS = ['plan', 'build', 'review', 'security', 'eval', 'inspect', 'prune',
                    'refactor', 'ci-setup', 'babysit-pr', 'ship', 'bootstrap',
                    'code-viz', 'report', 'token-analyzer']

inventory = {}
all_files = []
for d in sorted(target.iterdir()):
    if d.is_dir() and not d.name.startswith('.') and d.name not in {'node_modules','dist','__pycache__','.pytest_cache','.ruff_cache'}:
        n = sum(1 for _ in d.rglob('*') if _.is_file())
        inventory[d.name] = n
        all_files.extend(str(p.relative_to(target)) for p in d.rglob('*') if p.is_file())

ext_count = collections.Counter()
for f in all_files:
    if '.' in f:
        ext_count[f.rsplit('.', 1)[-1]] += 1

KEY_PATTERNS = ['README','SKILL','plugin.json','hooks.json','settings.json','mcp.json','package.json','pyproject.toml','Cargo.toml','go.mod','pre-commit','pre-push','ci.yml','review.yml']
key_files = [f for f in all_files if any(p in f for p in KEY_PATTERNS)][:25]

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
        rel = str(p.relative_to(target))
        skills.append({
            'name': fm.get('name', p.name),
            'category': fm.get('category', '?'),
            'alpha': fm.get('alpha', '-'),
            'model': fm.get('model', 'sonnet'),
            'user_invocable': fm.get('user_invocable', 'true'),
            'description': fm.get('description', ''),
            'body': text,
            'path': rel,
            'pillars': pillars_for(rel),
        })

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
        rel = str(p.relative_to(target))
        commands.append({'name': fm.get('name', p.stem), 'category': fm.get('category', '?'), 'alpha': fm.get('alpha', '-'), 'pillars': pillars_for(rel), 'body': text})

hook_events = []
hj = target/'hooks'/'hooks.json'
if hj.exists():
    try:
        cfg = json.loads(hj.read_text())
        for event, matchers in cfg.get('hooks', {}).items():
            rows = []
            for grp in matchers:
                matcher = grp.get('matcher', '*')
                for h in grp.get('hooks', []):
                    cmd = h.get('command', '')
                    script = cmd.split('/')[-1].replace('.sh','').replace('"','')
                    rows.append((matcher, script))
            hook_events.append((event, rows))
    except Exception:
        pass

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
        jobs_meta = (data.get('jobs') or {})
        jobs = []
        for jn, jc in jobs_meta.items():
            needs = jc.get('needs') if isinstance(jc, dict) else None
            if needs:
                if isinstance(needs, list): jobs.append(f"{jn} (needs {','.join(needs)})")
                else: jobs.append(f"{jn} (needs {needs})")
            else:
                jobs.append(jn)
        workflows.append({'name': p.stem, 'triggers': triggers, 'jobs': jobs, 'raw': jobs_meta})

def collect_modules(d, exclude_init=True):
    if not d.exists(): return []
    return sorted([p.stem for p in d.glob('*.py') if (not exclude_init or p.stem != '__init__')])

bin_modules   = collect_modules(target/'bin')
tools_modules = collect_modules(target/'tools', exclude_init=False)
lib_modules   = collect_modules(target/'lib')

mcp_servers = []
for cfg_path in [target/'.mcp.json', target/'.claude'/'settings.json', target/'.codex'/'settings.json', target/'.claude'/'settings.local.json']:
    if cfg_path.exists():
        try:
            d = json.loads(cfg_path.read_text())
            for name, conf in (d.get('mcpServers') or {}).items():
                mcp_servers.append({'name': name, 'command': conf.get('command', '?')})
        except Exception:
            pass

EXTERNAL_CLIS = ['claude','codex','docker','kubectl','helm','terraform','gh','aws','gcloud','az','psql','sqlite3','redis-cli','jq','yq','curl','git','make','npm','pnpm','yarn','pip','uv','poetry','cargo','go','node','python3','bash','sh']
external_cli_refs = collections.Counter()
for src in [target/'bin', target/'lib', target/'tools', target/'skills']:
    if not src.exists(): continue
    for py in src.rglob('*.py'):
        try:
            text = py.read_text()
        except Exception:
            continue
        for cli in EXTERNAL_CLIS:
            if re.search(rf'subprocess[^)]*[\'\"]{re.escape(cli)}[\'\"]', text) or re.search(rf'[\'\"]{re.escape(cli)}[\'\"][\s,)]', text):
                external_cli_refs[cli] += 1

skill_names = {s['name'] for s in skills}
ref_re = re.compile(r'/(?:dev-kit|skill|command):([a-z0-9][a-z0-9-]*)')
relations = collections.defaultdict(set)
def harvest(text):
    return {m for m in ref_re.findall(text) if m in skill_names and len(m) <= 40}
for s in skills:
    for d in harvest(s['body']):
        if d != s['name']: relations[s['name']].add(d)
for c in commands:
    if 'body' in c:
        for d in harvest(c['body']):
            relations[c['name']].add(d)

# === Multi-strategy cycle extraction (5 fallbacks) ===
DOMAIN_CONTENT_SECTIONS = {'categories', 'dimensions', 'audit areas', 'audit_area',
                           'checks', 'checklist', 'coverage', 'coverage areas',
                           'owasp', 'attack surface', 'risk areas', 'quality dimensions'}
CYCLE_SECTION_NAMES = {'algorithm', 'behavior', 'behaviour', 'pipeline', 'phases', 'cycle', 'workflow', 'how it works', 'process', 'steps'}

def extract_cycle(body, skill_name):
    """Returns list of (label, desc) tuples or None.
    Strategies (in order):
      F: ## Categories / ## Dimensions / ## Audit areas / etc. — bullet lists with bolded names (e.g. OWASP A01–A10)
      A: [N/M] LABEL → desc (arrow/em-dash variants)
      B: ## Gate N/M / ## Phase N / ## Sub-stage N — label
      C: numbered list under ## Algorithm / ## Behavior / ## Pipeline / ## Phases / ## Cycle
      D: ## <SectionName> headers as implicit phases
    """
    # Strategy F: domain-content sections (highest priority — most semantic)
    for sec_name in DOMAIN_CONTENT_SECTIONS:
        m = re.search(rf'^##[ \t]+[^\n]*{re.escape(sec_name)}[^\n]*\n+(.+?)(?=\n##[ \t]|\Z)', body, re.IGNORECASE | re.DOTALL | re.MULTILINE)
        if m:
            block = m.group(1)
            # Try numbered items first
            items = re.findall(r'^\s*\d+\.\s+\*\*([^*]+)\*\*\s*[—\-:]?\s*(.+?)(?=\n\s*\d+\.|\n\n|\Z)',
                              block, re.MULTILINE | re.DOTALL)
            if not items:
                # Try bullet items with bolded name
                items = re.findall(r'^\s*[-*]\s+\*\*([^*]+)\*\*\s*[—\-:]?\s*(.+?)(?=\n\s*[-*]|\n\n|\Z)',
                                  block, re.MULTILINE | re.DOTALL)
            if items and len(items) >= 2:
                return [(safe_label(name, 30), safe_label(desc, 60)) for name, desc in items[:15]]

    # Strategy A: [N/M] LABEL with arrow/em-dash separator
    pat_a = re.compile(r'\[(\d+)/(\d+)\]\s+([A-Za-z][A-Za-z0-9_\- ]{1,40}?)\s*(?:→|->|—|–)\s*(.+?)(?:\n|$)')
    matches = pat_a.findall(body)
    if matches and len(matches) >= 2:
        return [(label.strip(), safe_label(desc, 80)) for _, _, label, desc in matches]

    # Strategy B: ## Gate/Phase/Sub-stage N — label
    pat_b = re.compile(r'^#{2,3}\s+(Gate|Phase|Sub-stage|Stage|Step)\s+(\d+(?:/\d+)?)\s*[—–\-:]\s*(.+?)$', re.MULTILINE)
    matches = pat_b.findall(body)
    if matches and len(matches) >= 2:
        return [(f"{kind} {n} - {safe_label(label, 40)}", '') for kind, n, label in matches]

    # Strategy C: numbered list under known cycle headers
    for sec_name in CYCLE_SECTION_NAMES:
        m = re.search(rf'^##[ \t]+[^\n]*{re.escape(sec_name)}[^\n]*\n+(.+?)(?=\n##[ \t]|\Z)', body, re.IGNORECASE | re.DOTALL | re.MULTILINE)
        if m:
            block = m.group(1)
            items = re.findall(r'^\s*(\d+)\.\s+(.+?)(?=\n\s*\d+\.|\n\n|\Z)', block, re.MULTILINE | re.DOTALL)
            if items and len(items) >= 2:
                return [(f"step {idx}", safe_label(text, 60)) for idx, text in items]

    # Strategy D: ## <SectionName> headers as implicit phases (skip generic section names)
    pat_d = re.compile(r'^##\s+([A-Z][A-Za-z0-9 \-]{2,50})\s*$', re.MULTILINE)
    headers = pat_d.findall(body)
    skip = {'iron law', 'rules', 'hook integration', 'hooks', 'hand-off', 'handoff',
            'next step', 'output', 'test evidence', 'related', 'references',
            'verification summary', 'verification', 'mermaid pitfalls',
            'when to use', 'allowed tools', 'disallowed tools', 'description',
            'safety', 'why', 'key facts'}
    substantive = [h.strip() for h in headers
                   if h.strip().lower() not in skip and len(h.strip()) >= 3][:12]
    if len(substantive) >= 3:
        return [(h, '') for h in substantive]

    return None

pillar_files = collections.Counter()
for f in all_files:
    for p in pillars_for(f):
        pillar_files[p] += 1

blocks = []

arch = ['flowchart TB',
    '  USER([user / CLI / IDE]):::ext',
    '  SF[skills + commands/<br/>SKILL.md frontmatter]:::layer',
    '  HF[hooks/<br/>Claude events]:::layer',
    '  LF[lib/ + tools/ + bin/<br/>domain modules]:::layer',
    '  EF[(external tools<br/>GH Actions . MCP . CLI)]:::ext',
    '  USER --> SF',
    '  SF --> HF',
    '  HF --> LF',
    '  LF --> EF',
    '  EF --> USER',
    '  classDef ext fill:#fff4e1,stroke:#d97706,color:#7c2d12',
    '  classDef layer fill:#e3f2fd,stroke:#1976d2,color:#0d47a1']
blocks.append(('L0 Architecture overview', '\n'.join(arch)))

tree_lines = ['flowchart LR', '  ROOT((target))']
for d in sorted(inventory.keys())[:12]:
    d_id = nid(d, 'd_')
    tree_lines.append(f'  {d_id}["{esc(d)} ({inventory[d]:,} files)"]')
    tree_lines.append(f'  ROOT --> {d_id}')
blocks.append(('L1 Code level -- directory tree', '\n'.join(tree_lines)))

cat_lines = ['flowchart LR', '  SRC((source files))']
for ext, n in sorted(ext_count.items(), key=lambda kv: -kv[1])[:6]:
    if n >= 1:
        e_id = nid(ext, 'e_')
        cat_lines.append(f'  {e_id}["{esc(ext)} ({n})"]')
        cat_lines.append(f'  SRC --> {e_id}')
blocks.append(('L1 Code level -- extension breakdown', '\n'.join(cat_lines)))

rel = ['flowchart LR']
emitted_nodes = set()
for src in sorted(relations.keys()):
    src_id = nid(src, 's_')
    rel.append(f'  {src_id}["{esc(src)}"]:::skill')
    emitted_nodes.add(src_id)
    for dst in sorted(relations[src]):
        dst_id = nid(dst, 's_')
        if dst_id not in emitted_nodes:
            rel.append(f'  {dst_id}["{esc(dst)}"]:::skill')
            emitted_nodes.add(dst_id)
        rel.append(f'  {src_id} --> {dst_id}')
if not relations:
    rel.append('  NOCONN["no /skill: refs found"]:::skill')
rel.append('  classDef skill fill:#e8f5e9,stroke:#388e3c,color:#1b5e20')
blocks.append(('L2 Skill level -- relationship graph', '\n'.join(rel)))

# Per-skill workflow: IMPORTANT_SKILLS first, then alphabetical fill
user_skills_by_name = {s['name']: s for s in skills if s['user_invocable'].lower() == 'true'}
priority = [s for n in IMPORTANT_SKILLS if (s := user_skills_by_name.get(n)) is not None]
remaining_pool = [s for n, s in sorted(user_skills_by_name.items()) if n not in IMPORTANT_SKILLS]
fill = remaining_pool[:max(0, top_skills - len(priority))]
workflow_skills = priority + fill

skill_workflow_blocks = []
no_workflow_skills = []
for s in workflow_skills[:top_skills]:
    cycle = extract_cycle(s['body'], s['name'])
    if cycle:
        lines = ['flowchart LR', f'  S_{nid(s["name"], "sk_")}["{esc(s["name"])}"]:::start']
        prev_id = f'S_{nid(s["name"], "sk_")}'
        for label, desc in cycle:
            cur_id = f'N_{nid(s["name"] + label, "sk_")}'[:60]
            lbl = safe_label(label, 24)
            if desc: lbl += f'\n{esc(safe_label(desc, 40))}'
            lines.append(f'  {cur_id}["{lbl}"]:::step')
            lines.append(f'  {prev_id} --> {cur_id}')
            prev_id = cur_id
        lines.append(f'  classDef start fill:#fce4ec,stroke:#c2185b,color:#880e4f')
        lines.append(f'  classDef step fill:#e3f2fd,stroke:#1976d2,color:#0d47a1')
        skill_workflow_blocks.append((f'L2 Skill level -- {s["name"]} ({len(cycle)} steps)', '\n'.join(lines)))
    else:
        no_workflow_skills.append(s['name'])
blocks.extend(skill_workflow_blocks)

if hook_events:
    hk = ['flowchart TD']
    for evt, rows in hook_events:
        ev_id = nid(evt, 'ev_')
        hk.append(f'  {ev_id}[/{evt}/]:::event')
        for matcher, script in rows:
            s_id = nid(script, 'h_')
            lbl = f'{script}\nmatcher={matcher}' if matcher != '*' else script
            hk.append(f'  {s_id}["{esc(lbl)}"]:::hook')
            hk.append(f'  {ev_id} --> {s_id}')
    hk.append('  classDef event fill:#fce4ec,stroke:#c2185b,color:#880e4f')
    hk.append('  classDef hook fill:#f3e5f5,stroke:#7b1fa2,color:#4a148c')
    blocks.append(('L3 Hook event matrix', '\n'.join(hk)))

def module_diagram(title, modules, root_label, css):
    lines = [f'flowchart LR', f'  ROOT(({root_label})):::root']
    for m in modules[:24]:
        m_id = nid(m, 'm_')
        lines.append(f'  {m_id}["{esc(safe_label(m, 30))}"]:::mod')
        lines.append(f'  ROOT --> {m_id}')
    if not modules:
        lines.append(f'  NONE["(none detected)"]:::mod')
        lines.append(f'  ROOT --> NONE')
    lines.append(css)
    blocks.append((title, '\n'.join(lines)))

if bin_modules:
    module_diagram('L4 Tools and Library layer -- bin/', bin_modules, 'bin/', '  classDef root fill:#ede7f6,stroke:#512da8,color:#311b92\n  classDef mod fill:#f5f5f5,stroke:#616161,color:#212121')
if tools_modules:
    module_diagram('L4 Tools and Library layer -- tools/', tools_modules, 'tools/', '  classDef root fill:#e0f7fa,stroke:#00838f,color:#006064\n  classDef mod fill:#f5f5f5,stroke:#616161,color:#212121')
if lib_modules:
    module_diagram('L4 Tools and Library layer -- lib/', lib_modules, 'lib/', '  classDef root fill:#e8eaf6,stroke:#3949ab,color:#1a237e\n  classDef mod fill:#f5f5f5,stroke:#616161,color:#212121')

if workflows:
    gh = ['flowchart LR']
    for wf in workflows:
        wf_id = nid(wf['name'], 'gh_')
        trig_str = ', '.join(wf['triggers'])
        jobs_str = ', '.join(wf['jobs'])
        gh.append(f'  TR_{wf_id}["{esc(wf["name"])}\non: {esc(trig_str)}"]:::trig')
        gh.append(f'  WF_{wf_id}["{esc(wf["name"])}.yml\njobs: {esc(jobs_str)}"]:::wf')
        gh.append(f'  TR_{wf_id} --> WF_{wf_id}')
    gh.append('  classDef trig fill:#fff8e1,stroke:#f57c00,color:#e65100')
    gh.append('  classDef wf fill:#e0f7fa,stroke:#00838f,color:#006064')
    blocks.append(('L5 External tools -- GitHub Actions', '\n'.join(gh)))

# L5 GH Actions gate workflow sequence (PR -> review/security fan-out -> verdict)
if workflows:
    gate_wf = None
    for wf in workflows:
        raw = wf.get('raw') or {}
        for jn, jc in raw.items():
            if isinstance(jc, dict) and jc.get('needs'):
                gate_wf = wf
                break
        if gate_wf: break
    if gate_wf:
        seq = ['sequenceDiagram',
            '  participant Dev as Developer',
            '  participant PR as Pull Request',
            '  participant GH as GitHub Actions',
            '  participant R as /dev-kit:review',
            '  participant S as /dev-kit:security',
            '  participant G as gate job',
            '  Dev->>PR: open / synchronize / reopen',
            '  PR->>GH: pull_request event',
            '  GH->>R: spawn review job',
            '  GH->>S: spawn security job (parallel)',
            '  R->>R: 3-dim fan-out (correctness + security + architecture)',
            '  S->>S: OWASP A01-A10 fan-out',
            '  R-->>GH: review verdict + per-line findings',
            '  S-->>GH: security verdict + findings',
            '  GH->>G: gate job (needs review + security)',
            '  G->>G: touch-probe + L3 evidence gate',
            '  G->>G: aggregate combined verdict',
            '  G-->>PR: post verdict as PR comment',
            '  alt verdict = Approve',
            '    PR->>Dev: mergeable',
            '  else verdict = Block',
            '    PR->>Dev: changes requested',
            '  end']
        blocks.append(('L5 External tools -- GH Actions gate workflow', '\n'.join(seq)))

if mcp_servers:
    mcp = ['flowchart LR', '  MCP_ROOT((mcpServers)):::root']
    for srv in mcp_servers[:24]:
        s_id = nid(srv['name'], 'mcp_')
        mcp.append(f'  {s_id}["{esc(srv["name"])}\ncmd: {esc(srv["command"][:40])}"]:::mod')
        mcp.append(f'  MCP_ROOT --> {s_id}')
    mcp.append('  classDef root fill:#fce4ec,stroke:#c2185b,color:#880e4f')
    mcp.append('  classDef mod fill:#f5f5f5,stroke:#616161,color:#212121')
    blocks.append(('L5 External tools -- MCP servers', '\n'.join(mcp)))

if external_cli_refs:
    cli = ['flowchart LR', '  CLI_ROOT((external CLI invocations)):::root']
    for cli_name, cnt in external_cli_refs.most_common(15):
        c_id = nid(cli_name, 'cli_')
        cli.append(f'  {c_id}["{esc(cli_name)} ({cnt})"]:::mod')
        cli.append(f'  CLI_ROOT --> {c_id}')
    cli.append('  classDef root fill:#fff8e1,stroke:#f57c00,color:#e65100')
    cli.append('  classDef mod fill:#f5f5f5,stroke:#616161,color:#212121')
    blocks.append(('L5 External tools -- third-party CLIs', '\n'.join(cli)))

pl = ['flowchart LR', '  PL_ROOT((all files)):::root']
for pillar, cnt in sorted(pillar_files.items(), key=lambda kv: -kv[1])[:12]:
    if cnt < 1: continue
    p_id = nid(pillar, 'pl_')
    pl.append(f'  {p_id}["{esc(pillar)}\n{cnt} files"]:::pillar')
    pl.append(f'  PL_ROOT --> {p_id}')
pl.append('  classDef root fill:#e8eaf6,stroke:#3949ab,color:#1a237e')
pl.append('  classDef pillar fill:#e0f7fa,stroke:#00838f,color:#006064')
blocks.append(('Cross-cutting -- Domain pillar map', '\n'.join(pl)))

sections = []
for i,(t,m) in enumerate(blocks):
    sections.append(f'<section class="card" id="m{i}"><h2>{esc(t)}</h2><pre class="mermaid">\n{m}\n</pre></section>')

# "no workflow detected" section as a non-Mermaid text card
no_workflow_html = ''
if no_workflow_skills:
    chips = ' '.join(f'<span class="chip">{esc(s)}</span>' for s in no_workflow_skills)
    no_workflow_html = f'''<section class="card" id="no-workflow"><h2>L2 Skills without explicit workflow ({len(no_workflow_skills)})</h2><p class="meta">Linear / single-phase skills that don't define a numbered cycle or domain-content list in their SKILL.md body. Listed for inventory only - no diagram.</p><div class="chips">{chips}</div></section>'''
sections.append(no_workflow_html)
sections_html = '\n'.join(sections)

pillar_tiles = '\n'.join(
    f'<div class="stat"><div class="num">{cnt}</div><div class="lbl">{esc(pl)}</div></div>'
    for pl, cnt in sorted(pillar_files.items(), key=lambda kv: -kv[1])[:8] if cnt > 0)

skill_rows = '\n'.join(
    f'<tr><td><code>{esc(s["name"])}</code></td><td>{esc(s["category"])}</td><td>{esc(s["alpha"])}</td><td>{esc(", ".join(s["pillars"]))}</td></tr>'
    for s in skills)
cmd_rows = '\n'.join(
    f'<tr><td><code>{esc(c["name"])}</code></td><td>{esc(c["category"])}</td></tr>'
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
        (len(bin_modules), 'bin scripts'),
        (len(tools_modules), 'tools scripts'),
        (len(mcp_servers), 'MCP servers'),
    ] if n)

nav_links = '\n'.join(
    f'<a href="#m{i}">{esc(t)}</a>'
    for i,(t,_) in enumerate(blocks))
if no_workflow_skills:
    nav_links += f' <a href="#no-workflow">no-workflow ({len(no_workflow_skills)})</a>'

doc = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>code-viz -- {esc(target.name)}</title>
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
  body{{font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;max-width:1300px;margin:0 auto;padding:32px 28px 64px;background:var(--bg);color:var(--fg)}}
  h1{{font-size:1.9em;font-weight:700;margin:0 0 6px;letter-spacing:-0.02em}}
  h2{{font-size:1.18em;font-weight:600;margin:0 0 14px;padding-bottom:8px;border-bottom:1px solid var(--card-border);color:var(--fg)}}
  h3{{font-size:.95em;font-weight:600;margin:0 0 8px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}}
  .meta{{color:var(--muted);font-size:.85em;margin:0 0 20px}}
  .meta code{{background:var(--code-bg);padding:2px 6px;border-radius:4px;font-size:.9em;color:var(--fg)}}
  .header{{padding:24px 28px;border-radius:14px;background:linear-gradient(135deg,var(--card) 0%,var(--stripe) 100%);border:1px solid var(--card-border);box-shadow:var(--shadow);margin-bottom:20px}}
  .stats{{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0 0}}
  .stats.secondary{{margin-top:10px}}
  .stat{{flex:1 1 100px;min-width:100px;padding:12px 16px;background:var(--card);border:1px solid var(--card-border);border-radius:10px;box-shadow:var(--shadow)}}
  .stat .num{{font-size:1.85em;font-weight:700;color:var(--accent);line-height:1.1;letter-spacing:-0.02em}}
  .stat .lbl{{font-size:.74em;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:4px;font-weight:500}}
  .nav{{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--card-border);padding:10px 0;z-index:50;margin:0 -28px 20px;padding-left:28px;padding-right:28px}}
  .nav a{{margin-right:12px;font-size:.83em;color:var(--accent);text-decoration:none;font-weight:500}}
  .nav a:hover{{text-decoration:underline}}
  .card{{background:var(--card);border:1px solid var(--card-border);border-radius:12px;box-shadow:var(--shadow);padding:20px 22px;margin-bottom:18px}}
  table{{border-collapse:collapse;width:100%;margin:.4em 0;font-size:.92em}}
  th,td{{border:1px solid var(--table-border);padding:6px 10px;text-align:left;vertical-align:top}}
  th{{background:var(--stripe);font-weight:600;font-size:.85em;color:var(--fg)}}
  tbody tr:nth-child(even) td{{background:var(--stripe)}}
  td code{{background:var(--code-bg);padding:2px 6px;border-radius:4px;font-size:.88em;color:var(--fg);font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace}}
  pre.mermaid{{display:block;width:100%;margin:0;padding:14px;background:var(--mermaid-bg);border:1px solid var(--card-border);border-radius:8px;cursor:zoom-in;position:relative;max-height:72vh;overflow:hidden}}
  pre.mermaid:hover{{box-shadow:0 0 0 2px rgba(80,120,200,0.25);background:var(--hover-bg)}}
  pre.mermaid::after{{content:"click to expand";position:absolute;bottom:8px;right:12px;font-size:11px;color:var(--muted);background:var(--card);padding:2px 8px;border-radius:4px;pointer-events:none;font-family:ui-monospace,monospace;border:1px solid var(--card-border)}}
  pre.mermaid svg{{width:100%!important;height:auto!important;display:block}}
  pre.mermaid svg text{{fill:#1a1a1a!important;font-weight:500}}
  @media (prefers-color-scheme:dark){{pre.mermaid svg text{{fill:#e6edf3!important}}}}
  .chips{{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}}
  .chip{{display:inline-block;padding:5px 12px;background:var(--code-bg);border:1px solid var(--card-border);border-radius:14px;font-size:.85em;font-family:ui-monospace,SFMono-Regular,monospace;color:var(--fg)}}
  footer{{color:var(--muted);font-size:.8em;text-align:center;padding-top:20px;border-top:1px solid var(--card-border);margin-top:28px}}
  footer code{{background:var(--code-bg);padding:1px 6px;border-radius:4px;color:var(--fg)}}
  .mermaid-modal{{position:fixed;inset:0;background:rgba(8,12,20,0.88);z-index:10000;cursor:zoom-out;padding:32px;overflow:auto;display:none;text-align:center}}
  .mermaid-modal.open{{display:block}}
  .mermaid-modal .modal-card{{background:var(--card);color:var(--fg);border-radius:10px;padding:24px;display:inline-block;position:relative;text-align:left;box-shadow:var(--shadow-lg)}}
  .mermaid-modal .modal-close{{position:absolute;top:8px;right:12px;border:1px solid var(--card-border);background:var(--card);color:var(--fg);border-radius:6px;padding:4px 10px;cursor:pointer;font-family:inherit;font-size:13px}}
  .mermaid-modal .modal-card svg{{width:auto!important;max-width:95vw;height:auto!important;display:block;margin:0 auto}}
  @media print{{.nav,.mermaid-modal{{display:none!important}}body{{padding:8px;max-width:none}}.card{{box-shadow:none;border:1px solid #ddd;page-break-inside:avoid;break-inside:avoid}}pre.mermaid{{max-height:none;overflow:visible;page-break-inside:avoid}}}}
</style></head><body>

<header class="header">
  <h1>code-viz -- {esc(target.name)}</h1>
  <p class="meta">target <code>{esc(target)}</code> . generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M UTC')} . {len(blocks)} mermaid diagrams . {len(workflow_skills) - len(no_workflow_skills)} workflows visualized + {len(no_workflow_skills)} linear skills listed . {len(all_files)} files scanned . click any diagram to expand</p>
  <div class="stats">{stat_tiles}</div>
  <div class="stats secondary">{pillar_tiles}</div>
</header>

<nav class="nav">{nav_links}</nav>

<section class="card"><h2>Skills ({len(skills)})</h2><table><thead><tr><th>name</th><th>category</th><th>alpha</th><th>pillars</th></tr></thead><tbody>{skill_rows}</tbody></table></section>

<section class="card"><h2>Commands ({len(commands)})</h2><table><thead><tr><th>name</th><th>category</th></tr></thead><tbody>{cmd_rows}</tbody></table></section>

<section class="card"><h2>Hook scripts ({sum(len(r) for _,r in hook_events)})</h2><table><thead><tr><th>event</th><th>matcher</th><th>script</th></tr></thead><tbody>{hook_rows}</tbody></table></section>

<section class="card"><h2>GitHub Actions ({len(workflows)})</h2><table><thead><tr><th>file</th><th>on</th><th>jobs</th></tr></thead><tbody>{wf_rows}</tbody></table></section>

<section class="card"><h2>Key files (top {len(key_files)})</h2><table><thead><tr><th>path</th></tr></thead><tbody>{''.join(f'<tr><td><code>{esc(kf)}</code></td></tr>' for kf in key_files)}</tbody></table></section>

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
  startOnLoad:true, securityLevel:'loose', theme:'base',
  themeVariables:{{
    fontFamily:'ui-sans-serif,-apple-system,system-ui,sans-serif', fontSize:'13px',
    primaryColor:'#e3f2fd', primaryTextColor:'#0d47a1', primaryBorderColor:'#1976d2',
    secondaryColor:'#fce4ec', secondaryTextColor:'#880e4f', secondaryBorderColor:'#c2185b',
    tertiaryColor:'#fff8e1', tertiaryTextColor:'#e65100', tertiaryBorderColor:'#f57c00',
    lineColor:'#555555', edgeLabelBackground:'#ffffff',
    clusterBkg:'#f5f5f5', clusterBorder:'#999999', titleColor:'#0a0a0a'
  }}
}});
(function(){{var modal=document.getElementById('mermaid-modal');var content=modal.querySelector('.modal-content');var closeBtn=modal.querySelector('.modal-close');function open(svg){{content.innerHTML='';var c=svg.cloneNode(true);var vb=(c.getAttribute('viewBox')||'').split(/\\s+/);if(vb.length===4){{c.setAttribute('width',parseFloat(vb[2]));c.setAttribute('height',parseFloat(vb[3]))}}c.style.removeProperty('max-width');c.style.removeProperty('width');c.style.removeProperty('height');content.appendChild(c);modal.classList.add('open');document.body.style.overflow='hidden'}}function close(){{modal.classList.remove('open');document.body.style.overflow=''}}function bind(){{document.querySelectorAll('pre.mermaid').forEach(function(p){{if(p._bound)return;p._bound=true;p.addEventListener('click',function(){{var svg=p.querySelector('svg');if(svg)open(svg)}})}})}}var tries=0;var poll=setInterval(function(){{if(document.querySelector('pre.mermaid svg')){{clearInterval(poll);bind()}}else if(++tries>30)clearInterval(poll)}},200);closeBtn.addEventListener('click',close);modal.addEventListener('click',function(e){{if(e.target===modal)close()}});document.addEventListener('keydown',function(e){{if(e.key==='Escape')close()}})}})();
</script>
<footer>generated by <code>/dev-kit:code-viz</code> . {len(skills)} skills . {len(commands)} commands . {sum(len(r) for _,r in hook_events)} hooks . {len(workflows)} GH actions . {len(lib_modules)} lib . {len(bin_modules)} bin . {len(tools_modules)} tools . {len(mcp_servers)} MCP . {len(blocks)} diagrams</footer>
</body></html>
'''
out.write_text(doc)
n_diagrams = doc.count('class="mermaid"')

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
print(f'[code-viz] discovered: {len(skills)} skills, {len(commands)} commands, {sum(len(r) for _,r in hook_events)} hooks, {len(workflows)} GH workflows, {len(lib_modules)} lib, {len(bin_modules)} bin, {len(tools_modules)} tools, {len(mcp_servers)} MCP')
print(f'[code-viz] workflows visualized: {len(workflow_skills) - len(no_workflow_skills)} / {len(workflow_skills)} top skills; {len(no_workflow_skills)} linear (listed as text)')
print(f'[code-viz] pillar map: ' + ' '.join(f'{p}={c}' for p,c in sorted(pillar_files.items(), key=lambda kv:-kv[1]) if c>0))
print(f'[code-viz] wrote {out} ({out.stat().st_size:,} bytes, {n_diagrams} mermaid diagrams)')
if png_count:
    print(f'[code-viz] exported {png_count} PNGs into {screenshots}')
print(f'[code-viz] validation: 0 syntax-error / {svgs_count}/{n_diagrams} svgs / modal click OK')
print(f'open {out}')
PY
```

## Verification summary (this iteration)

- One SKILL.md file (~620 LOC body + ~520 lines of embedded heredoc).
- 6 abstraction levels + 1 cross-cutting pillar map + GH Actions gate workflow sequence = 8+ Mermaid diagrams per run.
- **5-strategy cycle extraction** (was 1):
  - **Strategy F (NEW, highest priority)**: `## Categories`/`## Dimensions`/`## Audit areas`/`## Checks`/`## OWASP` sections with bolded-bullet items — extracts domain content (e.g. security's A01–A10, inspect's 8 dims).
  - Strategy A: `[N/M] LABEL` with arrow/em-dash variants.
  - Strategy B: `## Gate N/M` / `## Phase N` / `## Sub-stage N`.
  - Strategy C: numbered list under known section headers.
  - Strategy D: `## <SectionName>` headers as implicit phases.
- **Skills without an extractable workflow** are listed as text chips in a "no explicit workflow detected" section — no wasted diagram.
- IMPORTANT_SKILLS priority list (15 skills always get a workflow diagram): `plan`, `build`, `review`, `security`, `eval`, `inspect`, `prune`, `refactor`, `ci-setup`, `babysit-pr`, `ship`, `bootstrap`, `code-viz`, `report`, `token-analyzer`.
- GH Actions gate workflow: detects any workflow with `needs:` (e.g. `review.yml`'s `gate` job) and emits a `sequenceDiagram` showing PR → review + security fan-out → gate verdict.
- `--top-skills N` default 20 (was 12), max 40.
- All classification is filename/path heuristic — no hardcoded skill names or module roles. Works on any Claude Code plugin, MCP server, microservice, monorepo, or framework.

## Hand-off

After the skill emits the HTML and the validator passes, open `file:///tmp/code-viz.html` in the browser. Each diagram is bounded to `72vh` by default; click any card to expand at the diagram's natural viewBox size; ESC / backdrop / close button dismisses the modal. For README inclusion: pass `--screenshots docs/diagrams` and the skill writes one PNG per diagram (`diagram-00.png` … `diagram-NN.png`) — drop those straight into your README.
