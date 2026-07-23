# /dev-kit:proposal — Skill README

> Render a hand-authored `docs/proposals/<name>.yaml` proposal into a single
> self-contained HTML document for pre-implementation review and sharing.
> Slash command: `/dev-kit:proposal`.

## What this skill does

Renders any YAML file under `docs/proposals/` into a sibling `<name>.html`
next to it. The HTML is:

- **Self-contained** — inline CSS only, no `<script>`, no external
  `<link rel="stylesheet">`, no remote `<img>`. Safe to email, archive, or
  open directly from `file://`.
- **Dark-mode aware** — uses `prefers-color-scheme` so the same file reads
  correctly in light and dark browser themes.
- **HTML-escaped** — every interpolated value (title, body, link URL,
  frontmatter fields) passes through `html.escape`. A `<script>` in YAML
  renders as `&lt;script&gt;`; the browser never executes it.
- **URL-scheme allowlisted** — only `https://`, `http://`, and `mailto:`
  links become anchors. `javascript:`, `data:`, `vbscript:`, `file:`,
  and bare relative paths render as plain text with the scheme shown
  in parentheses.

The skill does **not** edit the YAML. The user authors the proposal;
this skill renders and writes the HTML.

## Why a separate skill (not a flag on `/dev-kit:report` or `/dev-kit:plan`)

The user typed `/dev-kit:proposal` and got a single result. The flag-vs-slash
choice is the architecture:

- Proposals are a **distinct artifact** (pre-implementation design records)
  with a **distinct lifecycle** — `draft` → `design-discussion` →
  `ready-for-review` → `accepted` / `rejected` / `superseded`.
- Slash autocomplete does not surface flags. A `proposal` flag on
  `/dev-kit:plan` would be invisible at the moment of invocation.
- The render output is the **handoff artifact** itself — share the HTML
  file with reviewers, archive it in the repo, link it from the issue.

The pattern is the same as `/dev-kit:llm-refresh`: a domain-specific
lifecycle persisted in versioned files, with a deterministic render.

## File layout

```
skills/proposal/
├── SKILL.md                 # slash command frontmatter + body
├── README.md                # this file
└── (no scripts/ — CLI lives in lib/render_proposal_html.py)

lib/
└── render_proposal_html.py  # pure renderer + __main__ CLI entry point

docs/proposals/
├── 00-index.yaml            # proposal source (YAML in, HTML out)
├── 00-index.html            # generated HTML (rendered artifact)
├── 01-protocol-layer.yaml
├── 01-protocol-layer.html
└── ...                      # one .yaml + .html per proposal

tests/
└── test_proposal_skill.py   # parse + render + escape + determinism tests
```

The proposal skill **deviates** from the project's typical skill pattern
(`read-only-skill` + `bin/dev-kit-*.py` CLI driver):

- The proposal skill has `Write` permission (it writes the HTML).
- The CLI lives in `lib/render_proposal_html.py`'s `__main__` block,
  not in a separate `bin/dev-kit-proposal.py`.
- The skill invokes `python3 -m lib.render_proposal_html <name>` directly.

Rationale (from `skills/proposal/SKILL.md` §Architecture): the proposal
skill is the only caller, the maintainer workflow is *edit YAML, regenerate
HTML*, and a separate binary added indirection without adding capability.
The path-traversal guard, atomic-write, and error reporting are colocated
with the render logic.

## Invocation

### Slash command (human)

```
/dev-kit:proposal <name>          # render one proposal
/dev-kit:proposal --list          # list available proposals
/dev-kit:proposal --all           # render every proposal
```

`<name>` is the file stem — `00-index` renders `docs/proposals/00-index.yaml`
to `docs/proposals/00-index.html`.

### Direct CLI (debug + scripting)

```bash
# from the repo root
python3 -m lib.render_proposal_html 00-index         # render one
python3 -m lib.render_proposal_html --list            # list available
python3 -m lib.render_proposal_html --all             # render all
python3 -m lib.render_proposal_html my-slug --project-root /path/to/repo
```

The renderer is a **pure function** with a thin I/O wrapper. The two
testable entry points are:

```python
from lib.render_proposal_html import render_from_yaml, render, parse_proposal_yaml

html = render_from_yaml(yaml_text)              # parse + render
p = parse_proposal_yaml(yaml_text)              # value object only
html = render(p, now="2026-07-23")              # pass fixed `now` for deterministic output
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | render succeeded; `--list` returns 0 even when no proposals are found (prints `(no proposals found under docs/proposals/)`) |
| 1 | invalid name, source not found, YAML parse failure, path-traversal blocked, `--all` with no proposals |

## Output (in chat)

```
## /dev-kit:proposal -- <name>

**Source**: docs/proposals/<name>.yaml
**Output**: docs/proposals/<name>.html (one self-contained HTML doc, inline CSS only, no JS, dark-mode aware)
**Status**: <status from YAML frontmatter>
**Sections**: <count>

**Open in browser**: `open docs/proposals/<name>.html` (macOS)
```

The output file is the deliverable. Open it directly with
`open docs/proposals/<name>.html` on macOS, or any browser via `file://`.

## Authoring a proposal

Create `docs/proposals/<name>.yaml` with this shape:

```yaml
title: <one-line title>
status: draft | design-discussion | ready-for-review | accepted | rejected | superseded
issue: <issue number, optional>
date: YYYY-MM-DD
tags: [<tag1>, <tag2>]
sections:
  - title: <section 1>
    body: |
      Markdown-lite body. Supports:

      - # ## ### headings
      - paragraphs
      - **bold**, *italic*, `code`
      - [link text](https://...)
      - unordered (- ) and ordered (1. ) lists
      - | GFM tables |
      - ``` fenced code blocks ```
      - > blockquotes
      - --- horizontal rules
  - title: <section 2>
    body: |
      ...
```

Required top-level fields: `title`, `status`. Optional: `issue` (int),
`date` (str), `tags` (list[str]), `sections` (list of `{title, body}`).
Validation lives in `lib/render_proposal_html.py::parse_proposal_yaml`
and `tests/test_proposal_skill.py::ParseYAMLTests`.

### Status field lifecycle

| Status | Tag class | Use for |
|---|---|---|
| `draft` | `tag-warn` | Initial outline, not yet ready for review |
| `design-discussion` | `tag-info` | Open for comment on approach |
| `ready-for-review` | `tag-info` | Complete, awaiting reviewer verdict |
| `accepted` | `tag-ok` | Approved — implementation follows via `/dev-kit:plan` → `/dev-kit:build` |
| `rejected` | `tag-bad` | Decided against; record kept for context |
| `superseded` | `tag-warn` | Replaced by a later proposal (link it in `tags` or `sections`) |

Unknown statuses fall back to `tag-info` (visible in
`ParseYAMLTests::test_status_class_unknown_falls_back_to_info`).

## Markdown-lite grammar

The body renderer is intentionally narrow — see
`lib/render_proposal_html.py::render_body` for the exact block-detector
state machine. Supported inline + block constructs:

| Construct | Syntax | Notes |
|---|---|---|
| Heading | `# H1`, `## H2`, `### H3` | No H4+ |
| Paragraph | blank-line separated text | Auto-collected |
| Bold | `**text**` | |
| Italic | `*text*` | `*` is NOT a list bullet; only `-` is |
| Inline code | `` `text` `` | |
| Link | `[label](https://...)` | Only `https?`, `mailto` produce anchors |
| Unordered list | `- item` | `*` is rejected to keep bold/italic unambiguous |
| Ordered list | `1. item` | |
| GFM table | `\| col \| col \|` + `\|---\|---\|` | Contiguous pipe-delimited lines |
| Fenced code | ` ```lang ... ``` ` | Lang flows into `class="language-..."` |
| Blockquote | `> text` | |
| Horizontal rule | `---` | At least 3 dashes |

**Forward-progress safety** — the `render_body` state machine forces
forward progress on any line that no block branch matched, so even
malformed input terminates. The earlier infinite-loop bug on
`**bold** at start of line` is covered by
`RenderBodyTests::test_bold_at_start_of_line_is_inline_not_block` and
`test_paragraph_terminates`.

## Why this is `alpha: state`

Per CLAUDE.md Iron Law L6, every new skill must declare `alpha:`. The
proposal artifact has a **stateful lifecycle**:

- A YAML source on disk is the SSOT.
- HTML is **derived state** regenerated from YAML.
- The `status:` field is a **state machine** that the maintainer advances
  over time (`draft` → `design-discussion` → `ready-for-review` → …).
- The skill renders the artifact and gates its progression.

That is `state` by definition — distinct from `analysis` (reasoning over a
corpus) and `enforcement` (deterministic guards). The skill persists a
proposal artifact and gates its progression. **L7 fit**: the deterministic
render + URL-scheme allowlist + HTML-escape contract is exactly the part
next-gen models can't self-impose. The model can reason about *whether*
a proposal should be accepted; the skill owns *how* the artifact is
rendered, versioned, and surfaced for review.

## Trust model

- **Self-authored, never untrusted input.** Proposals are hand-edited by
  maintainers and reviewed via PRs. The renderer's security layer (HTML
  escape, URL-scheme allowlist) is a **defense-in-depth** against a
  malicious author, not the primary trust anchor.
- **No `<script>` ever, anywhere.** Output is safe to email, archive, or
  open from `file://`. `OutputInvariantsTests::test_no_script_tag_in_output`
  enforces this. The `INLINE_CSS` constant is the only CSS source.
- **URL-scheme allowlist.** `javascript:`, `data:`, `vbscript:`, `file:`,
  and bare relative paths are rejected at render time. The proposal HTML
  is meant to be safe-to-open from `file://`; allowing `file:` links would
  defeat that. See `RenderBodyTests::test_link_*_scheme_rejected`.
- **Atomic write.** `lib/render_proposal_html.py::_render_one` writes via
  `lib.atomic.atomic_write_text` so a partial render cannot leave a
  half-written HTML on disk.
- **Path-traversal guard.** The name argument is matched against
  `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` and the resolved paths are checked
  to lie under `docs/proposals/`. A relative-path argument cannot escape
  the proposals directory.
- **Deterministic when `now` is fixed.** Pass `render(p, now="YYYY-MM-DD")`
  for byte-identical output across runs. Default uses today's KST date —
  `test_render_is_deterministic_when_now_is_fixed` and
  `test_render_default_now_is_today` pin both.

## How to add a new proposal

1. Create `docs/proposals/<slug>.yaml` with the shape above.
2. Run `/dev-kit:proposal <slug>` to render the HTML.
3. Open `docs/proposals/<slug>.html` in a browser and review.
4. Commit both `.yaml` and `.html` — the HTML is the shareable artifact
   (viewable offline from `file://`).
5. Update the `status:` field as the proposal progresses through review.
   Re-run `/dev-kit:proposal <slug>` to refresh the HTML after each edit.

## How to handle a vendor pattern change

The renderer's block grammar is intentionally narrow. If a future
proposal needs a construct not yet supported (e.g. nested lists,
definition lists, footnotes):

1. Extend `lib/render_proposal_html.py::render_body` and add the
   corresponding block detector to `_is_block_start`.
2. Add a `RenderBodyTests` case covering the new construct.
3. Add a release note in the proposal's body — the renderer is the
   rendering contract, not a generic Markdown implementation.

## Hand-off

After a proposal is `accepted:`, the implementation work follows
`/dev-kit:plan` → `/dev-kit:build`. The proposal HTML is the design record
that closes the issue; the implementation PR references the proposal's
`issue:` number for traceability.

The proposal skill is intentionally **read-only** with respect to the YAML.
Editing the YAML is the maintainer's responsibility; the skill only renders.

## Related files

- `skills/proposal/SKILL.md` — slash command frontmatter + body.
- `lib/render_proposal_html.py` — pure renderer + `__main__` CLI entry.
- `lib/render_report_html.py` — sibling renderer (eval + inspect reports).
- `bin/dev-kit-report.py` — sibling CLI driver pattern (kept as-is; this
  skill deviated from it intentionally).
- `skills/report/SKILL.md` — sibling skill (still uses the read-only-skill
  + `bin/` pattern).
- `skills/llm-refresh/README.md` — closest sibling in skill README structure.
- `tests/test_proposal_skill.py` — parse + render + escape + invariants.
- `tests/test_render_report_html.py` — sibling renderer test contract.
- `docs/proposals/` — proposal source/output directory.
- `rules/skill-authoring.md` — L6 skill gate that this skill satisfies with
  `alpha: state` declared on `skills/proposal/SKILL.md:5`.

## Why this skill exists

Without `/dev-kit:proposal`, each proposal would be hand-edited as HTML
(or pasted into a generic Markdown service that introduces its own
scripting risk). The deterministic `lib/render_proposal_html.py` renderer
plus the `status:` state machine plus the inline-CSS-only output is the
single edit point: a maintainer edits YAML, regenerates HTML, and shares
the file. The skill is intentionally narrow, deterministic, and filesystem-
scoped so a silent vulnerability is impossible.
