> [← Skills index](README.md) · [Project README](../../README.md)

# `proposal`

**Category:** `design` · **Alpha:** `state` · **Invocation:** `/dev-kit:proposal` (human-invoked)

`proposal` renders any `docs/proposals/<main>/<sub>.yaml` design document into a single self-contained HTML page at `docs/proposals/<main>/<sub>.html`, for sharing with reviewers before implementation begins. It is a distinct skill (rather than a flag on `/dev-kit:report` or `/dev-kit:plan`) because proposals are a distinct artifact with their own lifecycle — `draft → design-discussion → ready-for-review → accepted/rejected/superseded` — and because slash-command autocomplete doesn't surface flags, so a dedicated entrypoint is the only reliable way for the user to find it.

## When to use it

- The user types `/dev-kit:proposal`.
- The user wants to share a draft proposal or plan with reviewers before implementation.
- The user wants to view an existing proposal as a single self-contained HTML document.
- The plan stage's Gate 5/5 (emit) auto-invokes this skill to render the design record.

## How it works

Every proposal lives at `docs/proposals/<main>/<sub>.{yaml,html}`: `<main>` is the umbrella grouping N related sub-proposals (e.g. `harness-architecture`), and `<sub>` is the sub-topic slug (e.g. `protocol-layer`, `00-index`) — the file is named after the sub-topic, not `index.{yaml,html}`, so it stays recognizable on a flat directory listing or static-site host.

The render pipeline: (1) list available topics via `python3 -m lib.render_proposal_html --list`; (2) render one topic via `python3 -m lib.render_proposal_html <main>/<sub>`, which writes the HTML; (3) print the output path so the user can open it (`open docs/proposals/<main>/<sub>.html` on macOS, or any browser via `file://`); (4) stop — the skill never edits the YAML, only renders it. The render logic is a pure function in `lib/render_proposal_html.py` plus a `__main__` CLI entry; there is no separate `bin/dev-kit-proposal.py` binary, since the proposal skill is the only caller.

The renderer auto-attaches a `<nav class="back-link">` element (`← 00-index`) at the top of every non-index sub-topic page when a sibling `00-index.yaml` exists in the same umbrella directory; the 00-index page itself gets no back link. The pure `render()` function takes optional `back_to_href=`/`back_to_label=` kwargs, which the CLI driver wires based on the filesystem sibling check.

**Cross-references**: inside a proposal body, link to a sibling as `[label](<other-sub>.html)` (bare relative path, since both files live in the same `<main>/` directory) or `../<other-main>/<sub>.html` for a cross-umbrella link. The relative-path safety check allows bare relative paths and `../<sibling>.html`, but rejects dangerous schemes (`javascript:`, `data:`, `vbscript:`, `file:`).

The topic slug must match `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}/[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` (one `/` separator, no leading/trailing slash, no `.` segments). The legacy filenames `proposal.yaml` and `index.yaml` are reserved and skipped as leftovers from a previous refactor.

## Usage

```bash
/dev-kit:proposal [<main>/<sub>]
/dev-kit:proposal --list
```

| Form | Effect |
|---|---|
| `--list` | Lists available proposal topics. |
| `<main>/<sub>` | Renders that topic's YAML to HTML. |

## Output

```
## /dev-kit:proposal -- <main>/<sub>

**Source**: docs/proposals/<main>/<sub>.yaml
**Output**: docs/proposals/<main>/<sub>.html (one self-contained HTML doc, inline CSS only, no JS, dark-mode aware)
**Status**: <status from YAML frontmatter>
**Sections**: <count>

**Open in browser**: `open docs/proposals/<main>/<sub>.html` (macOS)
```

## Why `alpha: state`

The proposal artifact has a stateful lifecycle: a YAML source on disk, a derived HTML rendered from it, and a status tag the maintainer advances over time (draft → design-discussion → ready-for-review → accepted/rejected/superseded). That is `state` by definition — the skill persists an artifact and gates its progression, distinct from `analysis` (reasoning over a corpus) or `enforcement` (deterministic guards). Per L7, the deterministic render + status-tag + HTML-escape contract is exactly the part a model can't self-impose; the model reasons about whether a proposal should be accepted, the skill owns how it is rendered, versioned, and surfaced.

## Iron Law

Defensive HTML escaping on every interpolated value — titles, anchors, free-text fields, link URLs. A title containing `<script>` renders as `&lt;script&gt;`, never executed. The output has no `<script>` tag and no external assets (inline CSS only), so it is safe to email, archive, or open from `file://` — mirroring the `/dev-kit:report` invariant. Pinned by `HtmlEscapeTests` in `tests/test_proposal_skill.py`.

## Related

- [plan](plan.md) — Gate 5/5 auto-invokes this skill (`Skill("proposal", topic="<main>/<sub>")`) to render the design record; the hand-off chain becomes `plan → proposal → build`.
- `lib/render_proposal_html.py` — pure function: `parse_proposal_yaml` + `render` + `__main__` CLI entry.
- `lib/render_report_html.py` — sibling renderer for eval + inspect reports.
- `skills/report/SKILL.md` — sibling skill that still uses the read-only-skill + `bin/` CLI pattern this skill deviates from.
- `tests/test_proposal_skill.py` — pins the HTML-escape contract.

---
*Source: [`skills/proposal/SKILL.md`](../../skills/proposal/SKILL.md)*
