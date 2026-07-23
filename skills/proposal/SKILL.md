---
name: proposal
category: design
description: 0-arg HTML renderer for design proposals / plans. Renders any docs/proposals/<main>/<sub>.yaml to docs/proposals/<main>/<sub>.html for pre-implementation review.
alpha: state
when_to_use: |
  - User types /dev-kit:proposal
  - User wants to share a draft proposal/plan with reviewers before implementation
  - User wants to view an existing proposal as a single self-contained HTML doc
  - Plan stage (Gate 5/5 emit) auto-invokes this skill to render the design record
allowed-tools: Read Write Bash
model: sonnet
user-invocable: true
---
> [← Skills index](../../README.md)

# /dev-kit:proposal -- design proposal HTML viewer

Renders any `docs/proposals/<main>/<sub>.yaml` to a single self-contained
HTML document at `docs/proposals/<main>/<sub>.html`. The skill is
generic across proposals; the MCP harness content (issue #280) is one example
input, not the skill's purpose.

**Layout invariant**: every proposal lives at
`docs/proposals/<main>/<sub>.{yaml,html}`.

- `<main>` is the umbrella (e.g. `harness-architecture` -- one umbrella
  groups N related sub-proposals; for issue #280 the umbrella holds 12
  sub-topics + the 00-index navigation page).
- `<sub>` is the sub-topic slug (e.g. `protocol-layer`,
  `live-context-server`, `00-index`). The file is named after the
  sub-topic -- not `index.{yaml,html}` -- so the leaf is recognisable
  on a flat directory listing and from a static-site host.

Cross-references from the 00-index page (`<main>/00-index.html`) to a
sibling are bare `<sub>.html` (no `../` needed, because all files live
in the same `<main>/` directory and resolve as siblings under `file://`
and on any static-site host). The relative-path safety check
specifically allows bare relative paths and `../<sibling>.html` for
cross-document links; the dangerous schemes (`javascript:`, `data:`,
`vbscript:`, `file:`) are still rejected.

**Back-to-index nav**: the renderer's CLI auto-attaches a
`<nav class="back-link">` element at the top of every non-index
sub-topic page (rendered as `← 00-index` linking to `00-index.html`)
when a sibling `00-index.yaml` exists in the same umbrella dir. The
00-index page itself gets no back link (it IS the index). The pure
function `render()` takes optional `back_to_href=` and
`back_to_label=` kwargs; the CLI driver wires them based on the
filesystem sibling check.

**Why a separate skill, not a flag on `/dev-kit:report` or `/dev-kit:plan`**: the
user has to remember the flag and slash autocomplete does not surface flags.
Proposals are a distinct artifact (pre-implementation plans) with a distinct
lifecycle (designed → reviewed → accepted/rejected → implemented). The slash
is the entrypoint; the YAML→HTML render is the work.

## What it does

1. List available proposal topics: `python3 -m lib.render_proposal_html --list`
2. Render one: `python3 -m lib.render_proposal_html <main>/<sub>` writes
   `docs/proposals/<main>/<sub>.html`
3. Print the file path so the user can open it in a browser
   (`open docs/proposals/<main>/<sub>.html` on macOS, or any browser
   via `file://`).
4. Stop. The skill does not edit the YAML -- the user authors the proposal;
   this skill renders.

The render logic lives in `lib/render_proposal_html.py` (pure function) plus a
`__main__` CLI entry (`python3 -m lib.render_proposal_html`). No separate
`bin/dev-kit-proposal.py` -- see the "Architecture" section below.

## Output (in chat)

```
## /dev-kit:proposal -- <main>/<sub>

**Source**: docs/proposals/<main>/<sub>.yaml
**Output**: docs/proposals/<main>/<sub>.html (one self-contained HTML doc, inline CSS only, no JS, dark-mode aware)
**Status**: <status from YAML frontmatter>
**Sections**: <count>

**Open in browser**: `open docs/proposals/<main>/<sub>.html` (macOS)
```

## Authoring a proposal

Create `docs/proposals/<main>/<sub>.yaml` with this shape:

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
      - [cross-doc link](<sub>.html) -- bare relative paths and
        `../<sibling>.html` are both allowed
      - unordered (- ) and ordered (1. ) lists
      - | GFM tables |
      - ``` fenced code blocks ```
      - > blockquotes
      - --- horizontal rules
  - title: <section 2>
    body: |
      ...
```

Then run `/dev-kit:proposal <main>/<sub>` to render. The topic slug must
match `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}/[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`
(one `/` separator; no leading/trailing slash; no `.` segments). The
filenames must not collide with the reserved legacy canonical names
`proposal.yaml` and `index.yaml` -- if they do, the renderer treats
the file as a leftover from a previous refactor and skips it.

### Cross-references between proposals

Inside a body, link to another proposal in the same umbrella as
`[label](<other-sub>.html)`. From a proposal at `<main>/<sub>.html`,
the relative hop to a sibling is the bare `<other-sub>.html` (same
directory under `<main>/`). The 00-index page follows this convention
-- the 12 sub-topic links in its table read as `[label](<sub>.html)`
and resolve to siblings of the index.

Cross-umbrella links (rare) would use `../<other-main>/<sub>.html`.
The proposal skill does not enforce a single umbrella -- each
`<main>/<sub>` pair is independent at the filesystem level.

## Why this is `alpha: state`

Per CLAUDE.md Iron Law L6, every new skill must declare an `alpha:` field. The
proposal artifact has **stateful lifecycle**: a YAML source on disk, a derived
HTML rendered from it, a status tag (draft → design-discussion →
ready-for-review → accepted/rejected/superseded) that the maintainer advances
over time. That is `state` by definition -- the skill persists a proposal
artifact and gates its progression, distinct from analysis (reasoning over a
corpus) and enforcement (deterministic guards).

**L7 fit**: the deterministic render + status-tag + HTML-escape contract is
exactly the part next-gen models can't self-impose. The model can reason
about *whether* a proposal should be accepted; the skill owns *how* the
artifact is rendered, versioned, and surfaced for review.

## Iron Law

**Defensive HTML escaping on every interpolated value.** The renderer escapes
titles, anchors, free-text fields, and link URLs. A title with `<script>` in
it renders as `&lt;script&gt;` -- the browser never executes it. The contract
is enforced by the `HtmlEscapeTests` class in `tests/test_proposal_skill.py`
(e.g. `test_script_in_title_escaped`, `test_script_in_body_escaped`,
`test_link_href_escapes_quotes`, `test_ampersand_escaped`,
`test_less_than_greater_than_escaped`).

**No `<script>` tag, no external assets, inline CSS only.** The output is
safe to email, archive, or open from `file://`. Mirrors the `/dev-kit:report`
invariant.

## Hand-off

Next: open `docs/proposals/<main>/<sub>.html` in a browser, share the
file with reviewers, then update the YAML's `status:` field as the proposal
progresses through review.

After a proposal is `accepted:`, the implementation work follows
`/dev-kit:plan` → `/dev-kit:build`. The proposal itself is the design record
that closes the issue.

**Auto-invoked by `/dev-kit:plan` Gate 5/5 (emit)**: when the plan skill
finishes a 5-gate interview it writes a proposal YAML derived from the PRD
and calls this skill to render the HTML. The topic slug is derived from
the phase name (see `skills/plan/SKILL.md` Gate 5/5). The hand-off chain
becomes `plan → proposal (this skill) → build`.

## Editing the proposal

The YAML is hand-edited, not generated. Re-run
`/dev-kit:proposal <main>/<sub>` (or `python3 -m lib.render_proposal_html
<main>/<sub>`) to refresh the HTML.

## Related

- `lib/render_proposal_html.py` -- pure function: `parse_proposal_yaml` +
  `render` + `__main__` CLI entry
- `lib/render_report_html.py` -- sibling renderer (eval + inspect reports)
- `bin/dev-kit-report.py` -- sibling CLI driver (kept as-is; this skill no
  longer uses this pattern)
- `skills/report/SKILL.md` -- sibling skill (still uses the
  read-only-skill + bin CLI pattern; we deviated from it)
- `skills/plan/SKILL.md` -- Gate 5/5 calls this skill to auto-render the
  design record

## Architecture

This skill deviates from the project's typical read-only-skill +
`bin/dev-kit-*` CLI pattern. The proposal skill has Write permission and
invokes `python3 -m lib.render_proposal_html <topic>` directly. The CLI
logic lives in the lib's `__main__` block. Rationale: the proposal skill is
the only caller, the maintainer workflow is "edit YAML, regenerate HTML",
and a separate binary added indirection without adding capability.
- `docs/proposals/<main>/<sub>.{yaml,html}` -- per-sub-topic flat files
  under an umbrella; the leaf is named after the sub-topic (not
  `index.{yaml,html}`) so the file is recognisable on a flat
  directory listing and on a static-site host
- Issue #280 -- the MCP harness analysis (12 sub-topics + 00-index under
  the `harness-architecture` umbrella) is the first proposal authored
  against this skill
