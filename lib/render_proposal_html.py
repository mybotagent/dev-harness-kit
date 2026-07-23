"""render_proposal_html.py -- Pure function: YAML proposal -> self-contained HTML.

The /dev-kit:proposal skill hands a YAML proposal file to this module
and writes the returned HTML to `docs/proposals/<main>/<sub>.html`.
The skill body itself stays read-only; the write is the CLI driver's job
(`bin/dev-kit-proposal.py`).

Layout: every proposal lives at `docs/proposals/<main>/<sub>.{yaml,html}`
where:

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
and on any static-site host).

Input shape (YAML)::

    title: Harness Architecture Proposal
    status: design-discussion
    issue: 280
    date: 2026-07-21
    tags: [mcp, harness, design]
    sections:
      - title: TL;DR
        body: |
          MCP harness wins over document harness when the loop needs
          **live tool integration** or *multi-actor coordination*.

      - title: When MCP harness is needed
        body: |
          | Loop | What it does | MCP fit |
          |------|--------------|---------|
          | Validation | judge loop | High |

Body markdown-lite (intentionally narrow):

- headings (# ## ###)
- paragraphs (blank-line separated)
- unordered (-) and ordered (1.) lists
- GFM tables (pipe-delimited)
- fenced code blocks (```)
- inline: **bold**, *italic*, `code`, [text](url)
- horizontal rule (---)
- blockquote (>)

Output invariants:

- No `<script>` tag. No `<link rel="stylesheet">`. No remote `<img>`.
- Inline CSS only. Dark-mode aware.
- Defensive HTML escape on every interpolated value.
- Pure function: no I/O, no filesystem, no network. Deterministic.

Mirror patterns: `lib/render_report_html.py` (eval+inspect reports),
`bin/dev-kit-report.py` (skill + CLI driver separation).
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import yaml

from lib.atomic import atomic_write_text

KST = timezone(timedelta(hours=9))

STATUS_TAG_CLASS = {
    "draft": "tag-warn",
    "design-discussion": "tag-info",
    "ready-for-review": "tag-info",
    "accepted": "tag-ok",
    "rejected": "tag-bad",
    "superseded": "tag-warn",
}

INLINE_CSS = """
:root {
  color-scheme: light dark;
  --fg: #1d1d1f;
  --bg: #fbfbfd;
  --muted: #5b5b62;
  --border: #d2d2d7;
  --card-bg: #ffffff;
  --th-bg: #f5f5f7;
  --row-alt: #fafafa;
  --code-bg: #f5f5f7;
  --accent: #0a84ff;
  --accent-soft: rgba(10, 132, 255, 0.08);
  --ok: #1f8a3b;
  --warn: #a06400;
  --bad: #b03030;
  --callout-bg: rgba(10, 132, 255, 0.06);
  --callout-border: #0a84ff;
  --shadow: 0 1px 2px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.04);
}
@media (prefers-color-scheme: dark) {
  :root {
    --fg: #f5f5f7;
    --bg: #1c1c1e;
    --muted: #aeaeb2;
    --border: #38383a;
    --card-bg: #2c2c2e;
    --th-bg: #3a3a3c;
    --row-alt: #232325;
    --code-bg: #2c2c2e;
    --accent: #0a84ff;
    --accent-soft: rgba(10, 132, 255, 0.18);
    --ok: #4cd964;
    --warn: #ff9f0a;
    --bad: #ff453a;
    --callout-bg: rgba(10, 132, 255, 0.14);
    --callout-border: #0a84ff;
    --shadow: 0 1px 2px rgba(0, 0, 0, 0.3), 0 4px 12px rgba(0, 0, 0, 0.3);
  }
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', Roboto, sans-serif;
  max-width: 980px;
  margin: 0 auto;
  padding: 3rem 1.5rem 5rem;
  line-height: 1.6;
  color: var(--fg);
  background: var(--bg);
  -webkit-font-smoothing: antialiased;
}
h1 { font-size: 2.4rem; font-weight: 700; letter-spacing: -0.02em; margin: 0 0 0.4rem; }
h2 { font-size: 1.6rem; font-weight: 600; letter-spacing: -0.01em; margin: 3.5rem 0 1rem; }
h3 { font-size: 1.15rem; font-weight: 600; margin: 2rem 0 0.6rem; }
p { margin: 0.7rem 0; }
.meta { color: var(--muted); font-size: 0.92rem; margin: 0 0 2.5rem; }
.tags { margin: 0 0 1.5rem; }
.tag {
  display: inline-block;
  padding: 0.18rem 0.6rem;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  margin-right: 0.4rem;
}
.tag-ok { background: rgba(31, 138, 59, 0.12); color: var(--ok); }
.tag-warn { background: rgba(160, 100, 0, 0.12); color: var(--warn); }
.tag-bad { background: rgba(176, 48, 48, 0.12); color: var(--bad); }
.tag-info { background: var(--accent-soft); color: var(--accent); }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 1rem 0 1.5rem;
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  font-size: 0.95rem;
}
th, td { padding: 0.7rem 0.9rem; text-align: left; border-bottom: 1px solid var(--border); }
th { background: var(--th-bg); font-weight: 600; }
tr:last-child td { border-bottom: 0; }
tr:nth-child(even) td { background: var(--row-alt); }
td code, th code { font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 0.88em; }
.callout {
  background: var(--callout-bg);
  border-left: 4px solid var(--callout-border);
  border-radius: 6px;
  padding: 0.9rem 1.2rem;
  margin: 1.5rem 0;
}
.callout .label { font-weight: 600; margin-bottom: 0.3rem; display: block; }
ul, ol { padding-left: 1.4rem; }
li { margin: 0.3rem 0; }
li > strong { color: var(--accent); }
code { font-family: 'SF Mono', Menlo, Consolas, monospace; background: var(--code-bg); padding: 0.1rem 0.35rem; border-radius: 4px; font-size: 0.9em; }
pre { background: var(--code-bg); padding: 0.9rem 1.1rem; border-radius: 8px; overflow-x: auto; font-size: 0.88em; line-height: 1.5; }
pre code { background: transparent; padding: 0; }
blockquote {
  border-left: 3px solid var(--border);
  margin: 1rem 0;
  padding: 0.2rem 1rem;
  color: var(--muted);
}
.section-divider { border: 0; border-top: 1px solid var(--border); margin: 3rem 0; }
.back-link {
  margin: 0 0 1.5rem;
  font-size: 0.9rem;
  color: var(--muted);
}
.back-link a { color: var(--accent); }
.back-link a:hover { text-decoration: underline; }
.toc {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.2rem 1.5rem;
  margin: 0 0 3rem;
  font-size: 0.95rem;
}
.toc strong { display: block; margin-bottom: 0.5rem; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; }
.toc ol { margin: 0; padding-left: 1.2rem; }
footer { margin-top: 4rem; padding-top: 1.5rem; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.85rem; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
"""


@dataclass(frozen=True)
class ProposalSection:
    title: str
    body: str


@dataclass(frozen=True)
class Proposal:
    title: str
    status: str
    issue: Optional[int]
    date: str
    tags: List[str]
    sections: List[ProposalSection] = field(default_factory=list)

    @property
    def status_class(self) -> str:
        return STATUS_TAG_CLASS.get(self.status, "tag-info")


def parse_proposal_yaml(text: str) -> Proposal:
    """Parse a YAML proposal document into a `Proposal` value object.

    Required: title, status. Optional: issue (int), date (str), tags
    (list[str]), sections (list of {title, body}).
    """
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError("proposal YAML must be a mapping at the top level")
    if "title" not in raw or not isinstance(raw["title"], str):
        raise ValueError("proposal YAML must include a string `title`")
    status = str(raw.get("status", "draft"))
    issue_val = raw.get("issue")
    issue = int(issue_val) if issue_val is not None else None
    date = str(raw.get("date", ""))
    tags_raw = raw.get("tags", [])
    if not isinstance(tags_raw, list):
        raise ValueError("`tags` must be a list of strings")
    tags = [str(t) for t in tags_raw]
    sections_raw = raw.get("sections", [])
    if not isinstance(sections_raw, list):
        raise ValueError("`sections` must be a list of {title, body} mappings")
    sections: List[ProposalSection] = []
    for i, sec in enumerate(sections_raw):
        if not isinstance(sec, dict):
            raise ValueError(f"sections[{i}] must be a mapping")
        if "title" not in sec or not isinstance(sec["title"], str):
            raise ValueError(f"sections[{i}] must include a string `title`")
        body = sec.get("body", "")
        if not isinstance(body, str):
            raise ValueError(f"sections[{i}].body must be a string")
        sections.append(ProposalSection(title=sec["title"], body=body))
    return Proposal(
        title=raw["title"],
        status=status,
        issue=issue,
        date=date,
        tags=tags,
        sections=sections,
    )


# ----- Markdown-lite renderer -----------------------------------------------

_INLINE_TOKEN_RE = re.compile(
    r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))"
)
# Allowlist for hyperlink href schemes. Two classes are accepted:
#   (a) Explicit safe schemes: `http://`, `https://`, `mailto:`.
#   (b) Safe relative paths: no scheme (no `:`), starting with `./`,
#       `../`, a relative segment, or `/`. These are how cross-document
#       links inside `docs/proposals/<main>/` work between sibling
#       files (`protocol-layer.html`, `../protocol-layer/index.html`,
#       etc.) and they resolve under `file://` exactly the way a
#       browser would resolve them for any other static HTML.
# Anything else (javascript:, data:, vbscript:, file:) is rendered as
# escaped text rather than an executable anchor. `file://` is
# rejected because the proposal HTML is meant to be safe-to-open
# from `file://`; allowing `file:` links inside would defeat that.
_SAFE_URL_SCHEMES = re.compile(
    r"^(?:https?|mailto):",
    re.IGNORECASE,
)
_SAFE_RELATIVE_HREF = re.compile(
    r"^(?:\.{0,2}/|[A-Za-z0-9_\-./?#=&%]+)$"
)


def _render_inline(text: str) -> str:
    """Render inline markdown (bold, italic, code, links) with HTML escape.

    Tokenizes first so escaping is applied to text-only segments; tokens
    are matched against the raw text and the result is escaped piece-wise.
    A literal `<script>` in the input renders as `&lt;script&gt;` because
    the raw text passes through `html.escape` before token replacement.
    """
    safe = html.escape(text, quote=False)
    pieces: List[str] = []
    cursor = 0
    for m in _INLINE_TOKEN_RE.finditer(safe):
        if m.start() > cursor:
            pieces.append(safe[cursor:m.start()])
        token = m.group(0)
        if token.startswith("**") and token.endswith("**"):
            pieces.append(f"<strong>{token[2:-2]}</strong>")
        elif token.startswith("*") and token.endswith("*"):
            pieces.append(f"<em>{token[1:-1]}</em>")
        elif token.startswith("`") and token.endswith("`"):
            pieces.append(f"<code>{token[1:-1]}</code>")
        elif token.startswith("["):
            link_m = re.match(r"\[([^\]]+)\]\(([^)]+)\)", token)
            if link_m:
                label, href = link_m.group(1), link_m.group(2)
                # Note: `label` and `href` come from the already-escaped
                # `safe` text, so they contain HTML entities (e.g. `&amp;`).
                # We must NOT re-escape them or `&amp;` becomes `&amp;amp;`.
                # Only `"` needs escaping to keep the attribute intact.
                href_attr = href.replace('"', "&quot;")
                href_stripped = href.strip()
                if _SAFE_URL_SCHEMES.match(href_stripped) or _SAFE_RELATIVE_HREF.match(href_stripped):
                    pieces.append(f'<a href="{href_attr}">{label}</a>')
                else:
                    # Disallowed scheme (javascript:, data:, vbscript:,
                    # file:, raw text with a colon-prefixed scheme we
                    # don't recognize). Render as plain text with parens
                    # so it reads naturally:
                    # `[click](javascript:alert(1))` -> `click (javascript:alert(1))`.
                    # Note: the regex consumes `[label](href` and the
                    # leftover `)` after the match stays in the
                    # surrounding text.
                    pieces.append(f"{label} ({href})")
            else:
                pieces.append(token)
        else:
            pieces.append(token)
        cursor = m.end()
    if cursor < len(safe):
        pieces.append(safe[cursor:])
    return "".join(pieces)


def _split_table_row(row: str) -> List[str]:
    """Split a GFM table row on `|`, trim, drop leading/trailing empty cells."""
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    return cells


def _render_table(lines: List[str]) -> str:
    """Render a GFM table block. Assumes `lines` is contiguous table lines
    (header, separator, then 0+ body rows)."""
    if len(lines) < 2:
        return _render_paragraphs(lines)
    header = _split_table_row(lines[0])
    body = [_split_table_row(r) for r in lines[2:]]
    out = ["<table>", "<thead><tr>"]
    for h in header:
        out.append(f"<th>{_render_inline(h)}</th>")
    out.append("</tr></thead>")
    if body:
        out.append("<tbody>")
        for row in body:
            out.append("<tr>")
            for i, cell in enumerate(row):
                tag = "td"
                out.append(f"<{tag}>{_render_inline(cell)}</{tag}>")
            out.append("</tr>")
        out.append("</tbody>")
    out.append("</table>")
    return "".join(out)


def _render_paragraphs(lines: List[str]) -> str:
    text = " ".join(line.strip() for line in lines).strip()
    if not text:
        return ""
    return f"<p>{_render_inline(text)}</p>"


def _render_list(items: List[str], ordered: bool) -> str:
    tag = "ol" if ordered else "ul"
    out = [f"<{tag}>"]
    for item in items:
        out.append(f"<li>{_render_inline(item)}</li>")
    out.append(f"</{tag}>")
    return "".join(out)


def _render_blockquote(lines: List[str]) -> str:
    text = " ".join(line.lstrip(">").strip() for line in lines).strip()
    return f"<blockquote><p>{_render_inline(text)}</p></blockquote>"


def render_body(body: str) -> str:
    """Render a markdown-lite body string to safe HTML."""
    lines = body.split("\n")
    out: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Fenced code block
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            j = i + 1
            while j < n and not lines[j].strip().startswith("```"):
                j += 1
            code_text = "\n".join(lines[i + 1:j])
            cls = f' class="language-{html.escape(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>{html.escape(code_text)}</code></pre>")
            i = j + 1
            continue

        # Horizontal rule
        if re.match(r"^-{3,}$", stripped):
            out.append('<hr class="section-divider">')
            i += 1
            continue

        # Heading
        h_m = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if h_m:
            level = len(h_m.group(1))
            text = h_m.group(2).strip()
            out.append(f"<h{level}>{_render_inline(text)}</h{level}>")
            i += 1
            continue

        # Table (collect contiguous pipe-delimited lines)
        if "|" in stripped and i + 1 < n and re.match(r"^\s*\|?\s*:?-+:?(\s*\|\s*:?-+:?)+\s*\|?\s*$", lines[i + 1].strip()):
            j = i
            while j < n and "|" in lines[j]:
                j += 1
            out.append(_render_table(lines[i:j]))
            i = j
            continue

        # Blockquote
        if stripped.startswith(">"):
            j = i
            while j < n and lines[j].strip().startswith(">"):
                j += 1
            out.append(_render_blockquote(lines[i:j]))
            i = j
            continue

        # Unordered list
        if re.match(r"^[-*]\s+", stripped):
            j = i
            items: List[str] = []
            while j < n and re.match(r"^[-*]\s+", lines[j].strip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[j].strip()))
                j += 1
            out.append(_render_list(items, ordered=False))
            i = j
            continue

        # Ordered list
        if re.match(r"^\d+\.\s+", stripped):
            j = i
            items = []
            while j < n and re.match(r"^\d+\.\s+", lines[j].strip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[j].strip()))
                j += 1
            out.append(_render_list(items, ordered=True))
            i = j
            continue

        # Blank line: skip
        if not stripped:
            i += 1
            continue

        # Paragraph (collect until blank or block transition)
        j = i
        while j < n and lines[j].strip() and not _is_block_start(lines[j]):
            j += 1
        if j == i:
            # Safety: if the line is non-blank AND a block-start but no
            # branch matched (e.g. future block types), force forward progress
            # by rendering it as a single-line paragraph rather than looping.
            j = i + 1
        out.append(_render_paragraphs(lines[i:j]))
        i = j

    return "\n".join(s for s in out if s)


def _is_block_start(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    # `*` is NOT a block-start marker here -- `**bold**` or `*italic*` at the
    # start of a line is just inline formatting inside a paragraph, not a
    # bullet (we use `-` for unordered lists). Including `*` would mis-route
    # paragraph lines starting with bold into an unhandled branch and loop.
    if s.startswith(("#", ">", "```", "-")) or re.match(r"^\d+\.\s+", s):
        return True
    if re.match(r"^-{3,}$", s):
        return True
    if "|" in s:
        return True
    return False


# ----- Top-level render -----------------------------------------------------


def _meta_line(p: Proposal) -> str:
    parts: List[str] = []
    if p.date:
        parts.append(html.escape(p.date))
    if p.issue is not None:
        parts.append(
            f'<a href="https://github.com/sh-ai-x/dev-harness-kit/issues/{p.issue}">'
            f"issue #{p.issue}</a>"
        )
    if p.status:
        parts.append(f'<span class="tag {p.status_class}">{html.escape(p.status)}</span>')
    return " · ".join(parts)


def _toc(p: Proposal) -> str:
    if not p.sections:
        return ""
    items = "".join(
        f'<li><a href="#sec-{i}">{html.escape(s.title)}</a></li>'
        for i, s in enumerate(p.sections)
    )
    return (
        '<div class="toc"><strong>Contents</strong>'
        f'<ol>{items}</ol></div>'
    )


def render(
    p: Proposal,
    now: Optional[str] = None,
    back_to_href: Optional[str] = None,
    back_to_label: Optional[str] = None,
) -> str:
    """Render a `Proposal` value object to a self-contained HTML document.

    Pure function: no I/O, deterministic given the same input and the
    optional kwargs. (The optional nav kwargs are kept optional so
    `render(p)` and `render(p, now=...)` keep their existing call
    sites and determinism contract.)

    Args:
        p: the proposal value object.
        now: ISO-format date string for the footer. If `None` (default),
            uses today's date in KST. Pass a fixed string for deterministic
            tests / batch regeneration.
        back_to_href: optional href for a "← ..." nav bar at the top of
            the page (e.g. `"00-index.html"`). When set, a small
            `.back-link` nav element is emitted before the `<h1>`.
            Default: no nav bar.
        back_to_label: optional label for the back link. Default: the
            href's filename (e.g. `00-index.html` -> `00-index`).
    """
    sections_html: List[str] = []
    for i, sec in enumerate(p.sections):
        sections_html.append(
            f'<h2 id="sec-{i}">{html.escape(sec.title)}</h2>\n'
            f'{render_body(sec.body)}'
        )

    tags_html = ""
    if p.tags:
        tag_chips = "".join(
            f'<span class="tag tag-info">{html.escape(t)}</span>' for t in p.tags
        )
        tags_html = f'<div class="tags">{tag_chips}</div>'

    back_link_html = ""
    if back_to_href:
        # Default label = the href's basename without extension
        # (`00-index.html` -> `00-index`, `index.html` -> `index`).
        href_only = back_to_href.split("?")[0].split("#")[0]
        basename = href_only.rsplit("/", 1)[-1]
        if basename.endswith(".html"):
            basename = basename[: -len(".html")]
        label = back_to_label if back_to_label is not None else basename
        # href_attr escapes only the attribute-internal `"` so the
        # `href` is preserved across HTML attribute parse.
        href_attr = back_to_href.replace('"', "&quot;")
        back_link_html = (
            f'<nav class="back-link">'
            f'<a href="{href_attr}">← {html.escape(label)}</a>'
            f'</nav>\n'
        )

    if now is None:
        now = datetime.now(KST).strftime("%Y-%m-%d")
    footer_issue = (
        f' · <a href="https://github.com/sh-ai-x/dev-harness-kit/issues/{p.issue}">'
        f'issue #{p.issue}</a>'
        if p.issue is not None
        else ""
    )

    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(p.title)}</title>\n"
        f"<style>{INLINE_CSS}</style>\n"
        "</head>\n<body>\n\n"
        f"{back_link_html}"
        f"<h1>{html.escape(p.title)}</h1>\n"
        f'<p class="meta">{_meta_line(p)}</p>\n'
        f"{tags_html}\n"
        f"{_toc(p)}\n"
        + "\n<hr class=\"section-divider\">\n\n".join(sections_html)
        + "\n\n<hr class=\"section-divider\">\n\n"
        f'<footer>Generated {now}{footer_issue} · render via '
        f'<code>/dev-kit:proposal</code></footer>\n'
        "</body>\n</html>\n"
    )


def render_from_yaml(text: str) -> str:
    """Convenience wrapper: parse YAML text and render in one call."""
    return render(parse_proposal_yaml(text))


# --- CLI entry point --------------------------------------------------------
#
# Per the proposal-skill design (see skills/proposal/SKILL.md and
# docs/proposals/), the maintainer regenerates HTML from YAML by invoking
# this lib as a module:
#
#   python3 -m lib.render_proposal_html <main>/<sub>   # render one
#   python3 -m lib.render_proposal_html --list          # list <main>/<sub>
#   python3 -m lib.render_proposal_html --all           # render every topic
#
# Each topic lives at docs/proposals/<main>/<sub>.{yaml,html} (flat file,
# not a subdir). The leaf filename mirrors the sub-topic slug.
#
# The CLI lives in the lib (not a separate `bin/dev-kit-proposal.py`) so
# the path-traversal guard, atomic-write, and error reporting are
# colocated with the render logic.

# Topic slug: `<main>/<sub>`. Both halves are kebab/snake; one `/` separator
# is allowed; no leading/trailing slash, no double slash, no `.` segments.
_NAME_OK_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}/[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
)


def _list_proposals(project_root: Path) -> list[str]:
    """Return sorted `<main>/<sub>` topic slugs whose `<sub>.yaml` exists.

    Walks every `<main>/` under `docs/proposals/` and, for each
    `<sub>.yaml` directly at the umbrella level, returns the joined
    `<main>/<sub>` slug. Reserved legacy canonical names (`proposal`,
    `index`) are skipped -- those are the names the previous
    refactors used and they would otherwise be mistaken for a
    sub-topic slug. Sub-directories (the old "one-level-per-topic"
    shape) and flat files (the pre-refactor shape) are skipped. The
    order is `<main>` then `<sub>`, both alphabetical.
    """
    pdir = project_root / "docs" / "proposals"
    if not pdir.exists():
        return []
    # Reserved file stems that previous refactors used as canonical
    # names; they must not surface as a sub-topic slug.
    reserved = {"proposal", "index"}
    slugs: list[str] = []
    for main_dir in sorted(pdir.iterdir()):
        if not main_dir.is_dir():
            continue
        for entry in sorted(main_dir.iterdir()):
            if not (entry.is_file() and entry.name.endswith(".yaml")):
                continue
            sub = entry.name[: -len(".yaml")]
            if sub in reserved:
                continue
            slugs.append(f"{main_dir.name}/{sub}")
    return slugs


def _render_one(project_root: Path, topic: str) -> int:
    """Render one proposal topic. Returns process exit code."""
    if not _NAME_OK_RE.fullmatch(topic):
        print(
            f"error: invalid proposal topic {topic!r}: "
            f"must match `<main>/<sub>` (kebab/snake, no dots, no traversal)",
            file=sys.stderr,
        )
        return 1

    proposals_dir = (project_root / "docs" / "proposals").resolve()
    main_dir = proposals_dir / topic.split("/", 1)[0]
    sub = topic.split("/", 1)[1]
    src = main_dir / f"{sub}.yaml"
    out = main_dir / f"{sub}.html"

    src_resolved = src.resolve()
    out_resolved = out.resolve()
    if proposals_dir not in src_resolved.parents or proposals_dir not in out_resolved.parents:
        print(f"error: path traversal blocked ({topic!r})", file=sys.stderr)
        return 1

    if not src.exists():
        print(f"error: source not found: {src}", file=sys.stderr)
        print(
            f"hint: create {src} (or run --list to see existing topics)",
            file=sys.stderr,
        )
        return 1

    text = src.read_text(encoding="utf-8")
    try:
        p = parse_proposal_yaml(text)
    except (ValueError, KeyError) as e:
        print(f"error: failed to parse {src}: {e}", file=sys.stderr)
        return 1

    # Auto-attach a "back to index" nav bar when a sibling
    # `00-index.yaml` exists in the same umbrella dir AND the current
    # page is not the index itself. The renderer is a pure function
    # (no I/O) so the sibling check lives in the CLI driver, not
    # `render()`.
    back_to_href: Optional[str] = None
    if sub != "00-index":
        sibling_index = main_dir / "00-index.yaml"
        if sibling_index.is_file():
            back_to_href = "00-index.html"

    html_doc = render(p, back_to_href=back_to_href)

    atomic_write_text(out, html_doc)
    size_kb = len(html_doc.encode("utf-8")) / 1024
    print(f"wrote {out} ({size_kb:.1f} KB, source: {src.relative_to(proposals_dir)})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m lib.render_proposal_html",
        description=(
            "Render docs/proposals/<main>/<sub>.yaml to "
            "docs/proposals/<main>/<sub>.html"
        ),
    )
    parser.add_argument(
        "topic",
        nargs="?",
        help=(
            "topic slug `<main>/<sub>` (sources: "
            "docs/proposals/<main>/<sub>.yaml)"
        ),
    )
    parser.add_argument(
        "--project-root", default=".",
        help="project root (default: cwd)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="list available proposal topics and exit",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="render every proposal topic and exit",
    )
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()

    if args.list:
        names = _list_proposals(root)
        if not names:
            print("(no proposals found under docs/proposals/)")
            return 0
        for n in names:
            print(n)
        return 0

    if args.all:
        names = _list_proposals(root)
        if not names:
            print("no proposals found", file=sys.stderr)
            return 1
        for n in names:
            _render_one(root, n)
        return 0

    if not args.topic:
        parser.error(
            "proposal topic required (or pass --list to see available)"
        )
    return _render_one(root, args.topic)


if __name__ == "__main__":
    sys.exit(main())
