# dev-harness-kit

> AI-native unified harness plugin — Plan → Build → Review → Ship with typed
> sub-agent delegation, an Eval-Repair loop, and Human-on-the-Loop supervision.

[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

---

## Quick start

The usual delivery loop is:

```text
install → bootstrap → plan → build → review → ship
```

Start with `/dev-kit:bootstrap-full` in a new repository, then use
`/dev-kit:plan`, `/dev-kit:build`, `/dev-kit:review`, and `/dev-kit:ship` as the
work moves through the loop. Use `/dev-kit:skill-usage --top 0` to inspect every
skill, including skills with no captured usage.

### Usage tiers

These tiers are navigation defaults, not hard-coded usage counts. Measure the
current workspace with `python3 tools/skill_usage.py`; the report's `turns` and
`invocations` are the source of truth for actual usage. The full skill surface is
kept here so an uncalled skill is still discoverable.

| Tier | Start here when | Skills |
|---|---|---|
| Tier 1 — delivery loop | You are starting, implementing, reviewing, or shipping normal work | `bootstrap`, `bootstrap-full`, `plan`, `build`, `review`, `security`, `babysit-pr`, `ship`, `ci-doctor`, `ci-setup`, `log`, `codex-cache-update`, `skill-usage` |
| Tier 2 — focused engineering | You need a targeted diagnostic, refactor, removal, configuration, or cost pass | `feat-remove`, `inspect`, `audit`, `refactor`, `prune`, `config`, `bump`, `cost-gate`, `status`, `token-analyzer` |
| Tier 3 — specialist and occasional | You are evaluating behavior, repairing an asset, publishing a report, or maintaining the harness | `eval`, `evaluate`, `valuate`, `research`, `interview`, `repair`, `report`, `proposal`, `docs-maintenance`, `llm-refresh`, `prune-propose`, `harness-audit` |

Tier 1 covers the common cases; Tier 2 and Tier 3 are the focused-specialist
extension set. Model-invoked sub-skills (`build-tdd`, `build-debug`,
`build-verify`, `build-refactor`, `hook-doctor`, `lcs`) are deliberately
hidden from autocomplete and live one layer down — see
[Skills by audience](#skills-by-audience) for the user-vs-model split. Confirm
the live surface and frontmatter with:

```bash
find skills -mindepth 2 -maxdepth 2 -name SKILL.md -print | sort
python3 tools/skill_usage.py --days 0 --top 0
```

## Documentation

**Start here if you are new to dev-harness-kit:**

[`docs/home/00-index.html`](docs/home/00-index.html) — the documented entry point. Walks through *why the system exists*, *what value you get*, a 60-second quickstart, and a categorized map of every doc, ADR, and skill in the repo.  Korean version: [`docs/home/00-index.ko.html`](docs/home/00-index.ko.html).

### What this plugin is, in two sentences

dev-harness-kit ships the `Plan → Build → Review → Ship` loop for Claude Code and Codex in any repository. Underneath it sits the **Live Context Server (LCS)** — a read-only URI router at `lcs://<resource>` that lets every hook, agent, and operator ask the same question the same way, with a typed envelope (`{status, data, missing?, error?}`) instead of each one re-parsing `git` / `gh` / log files.

### Why LCS exists (the one-paragraph version)

Eight files in `hooks/` and `lib/` each needed the same live state — `slot_version`, PR status, session info, spend — and each shell-out to `git`/`gh`, parsed the JSON inline, and wrapped errors in its own shape. When `gh` was missing, one hook crashed, another silently fell back, a third lied. Hot loops re-spawned `gh` 60 times in a single babysit session. LCS is one Python module that every consumer now reads from; concurrent reads in a 5-second window collapse to one subprocess. The full numbers + before/after are in [`docs/home/00-index.html`](docs/home/00-index.html).

### How to use it (the 60-second quickstart)

```bash
# 1. See what LCS exposes
python3 bin/dev-kit-lcs.py --list-resources

# 2. Ask for live state
python3 bin/dev-kit-lcs.py --get 'lcs://branches/main'

# 3. Read the full reference in your browser
open docs/home/00-index.html
```

That is the whole LCS surface. Anything deeper is in the docs index.

### Doc map (categorized)

Every doc ships in **both** `.md` and `.html` formats. The HTML column is
preferred for browsing (sticky topnav, dark/light theme auto-switch,
copy-able code blocks); the MD column renders natively on GitHub and is
easier to grep.

| Topic | HTML | MD | What you get |
|---|---|---|---|
| Why + value + quickstart | [`docs/home/00-index.html`](docs/home/00-index.html) / [`.ko`](docs/home/00-index.ko.html) | [`docs/home/00-index.md`](docs/home/00-index.md) / [`.ko`](docs/home/00-index.ko.md) | Beginner landing — read first |
| LCS reference (full) | [`docs/lcs/lcs-usage.html`](docs/lcs/lcs-usage.html) / [`.ko`](docs/lcs/lcs-usage.ko.html) | [`docs/lcs/lcs-usage.md`](docs/lcs/lcs-usage.md) / [`.ko`](docs/lcs/lcs-usage.ko.md) | URI grammar, every resource, CLI surface, JSON-RPC, integration map |
| STAGES (what each loop step owns) | [`docs/stages/STAGES.html`](docs/stages/STAGES.html) | [`docs/stages/STAGES.md`](docs/stages/STAGES.md) | bootstrap → plan → build → review → security → ship |
| CI install (run dev-kit CI elsewhere) | [`docs/quality/ci-setup.html`](docs/quality/ci-setup.html) | [`docs/quality/ci-setup.md`](docs/quality/ci-setup.md) | `branch-policy` + validate + test + auto-fix workflows |
| Maintenance gate (PR-only quality) | [`docs/quality/maintenance-gate.html`](docs/quality/maintenance-gate.html) | [`docs/quality/maintenance-gate.md`](docs/quality/maintenance-gate.md) | 20-checkbox rubric enforced in `.github/workflows/maintenance.yml` |
| Runtime portability (Claude Code ↔ Codex) | [`docs/architecture/RUNTIME-PORTABILITY.html`](docs/architecture/RUNTIME-PORTABILITY.html) | [`docs/architecture/RUNTIME-PORTABILITY.md`](docs/architecture/RUNTIME-PORTABILITY.md) | The contract both runtimes honor so plugin.json means the same thing |
| Multi-harness design proposal | [`docs/planning/PROPOSAL-IMPLEMENTATION-PLAN.html`](docs/planning/PROPOSAL-IMPLEMENTATION-PLAN.html) + [`docs/proposals/harness-architecture/00-index.html`](docs/proposals/harness-architecture/00-index.html) | [`docs/planning/PROPOSAL-IMPLEMENTATION-PLAN.md`](docs/planning/PROPOSAL-IMPLEMENTATION-PLAN.md) + same proposal dir | 13 topic files (Korean) covering the architecture |
| Naming convention (SSOT) | [`docs/naming/NAMING.html`](docs/naming/NAMING.html) | [`docs/naming/NAMING.md`](docs/naming/NAMING.md) · [ADR-0010](docs/adr/ADR-0010-naming-convention.md) | Why a hook is `bash-guard.sh`, not `bashHook.sh` |
| Pre-implementation gate | [`docs/planning/PRE-IMPL-CHECK.html`](docs/planning/PRE-IMPL-CHECK.html) | [`docs/planning/PRE-IMPL-CHECK.md`](docs/planning/PRE-IMPL-CHECK.md) | 9 questions before code |
| Cost & risk | [`docs/quality/COST-ANALYSIS.html`](docs/quality/COST-ANALYSIS.html) | [`docs/quality/COST-ANALYSIS.md`](docs/quality/COST-ANALYSIS.md) | Token ceilings, cost-gate trailer format |
| Team adoption | [`docs/adoption/team-adoption.html`](docs/adoption/team-adoption.html) | [`docs/adoption/team-adoption.md`](docs/adoption/team-adoption.md) | Why a single maintainer and a 20-person team adopt the harness differently |
| Hook coverage gaps (P4 Bucket B audit) | [`docs/hooks/hook-coverage-gaps.html`](docs/hooks/hook-coverage-gaps.html) | [`docs/hooks/hook-coverage-gaps.md`](docs/hooks/hook-coverage-gaps.md) | Which hook events are wired vs. which aren't, per runtime |
| ACP dispatch (M-tier architecture) | [`docs/architecture/ACP-DISPATCH.html`](docs/architecture/ACP-DISPATCH.html) | [`docs/architecture/ACP-DISPATCH.md`](docs/architecture/ACP-DISPATCH.md) | How Model-tier agents find and dispatch to Capability-tier skills |
| ACP (Agent Coordination Protocol) | [`docs/architecture/acp-harness.html`](docs/architecture/acp-harness.html) | [`docs/architecture/acp-harness.md`](docs/architecture/acp-harness.md) | The wire-format ACP uses to talk between agents; how it differs from LCS |
| Skill reference | [`docs/skills/README.md`](docs/skills/README.md) | same | All 35 skills with category + α classification |
| Decision records | [`docs/adr/`](docs/adr) | same | 5 locked ADRs (0001, 0010, 0020, 0021, 0022) |
| Repo map | [`docs/repo/REPOSITORY-MAP.html`](docs/repo/REPOSITORY-MAP.html) | [`docs/repo/REPOSITORY-MAP.md`](docs/repo/REPOSITORY-MAP.md) | Where each component lives in the tree |

If you have only five minutes, open [`docs/home/00-index.html`](docs/home/00-index.html) and read sections 1–3 (why, quickstart, value). Everything else can wait.

The same docs are also available as Markdown:

- [`docs/home/00-index.md`](docs/home/00-index.md) / [`docs/home/00-index.ko.md`](docs/home/00-index.ko.md) — landing (beginner intro + categorized index)
- [`docs/lcs/lcs-usage.md`](docs/lcs/lcs-usage.md) / [`docs/lcs/lcs-usage.ko.md`](docs/lcs/lcs-usage.ko.md) — full LCS reference (URI grammar, resources, CLI surface, JSON-RPC, integration map, verification log)

The HTML versions are preferred for browsing (sticky topnav, collapsible
sections, dark/light theme auto-switch, copy-able code blocks); the MD
versions are easier to grep and render natively on GitHub.

## Enforcement hooks (the durable moat)

This plugin's load-bearing surface is **deterministic enforcement**, not
prompt prose. Per `CLAUDE.md` Iron Law L7 ("a skill's alpha lives in the
parts the model can't self-impose"), the hooks below short-circuit the
model's tool calls — they cannot be absorbed by model improvements.

| Hook | What it does | Stage |
|---|---|---|
| `tdd-guard` | Blocks `lib/` edits without a failing test | Build |
| `bash-guard` | Denies destructive `git` / `rm` / shell escapes | Build |
| `secret-scan` | Redacts credential patterns in tool inputs | All |
| `slop-detector` | Catches AI-typical patterns across phrase + structure banks (KO+EN) | Build + Review + Security |
| `worktree-guard` | Hard-blocks Edit/Write in the main checkout; on deny, enriches the message with the live worktree list via `lcs://worktrees` (shell-out fallback) | All |
| `git-guard` | Enforces branch strategy: blocks commit/push to main, force-push, `gh pr merge`; verifies `plugin.json` slot via `lcs://branches/<name>` (shell-out fallback) on `git push` to a feature branch | All |
| `worktree-auto-cut` | Creates the per-task worktree + branch | All |
| `stop-verify` | Quoted exit codes / test counts before session end | Plan + Design + Build + Review + Security + Ship |
| `review-yml-isolation` | Forces `review.yml` PRs to be `review.yml`-only | All |

The skills (`/dev-kit:*`) are convenience wrappers around these hooks +
the state machine (`phases/<name>/index.json` + `STATUS_TRANSITIONS`).
The next-gen-model thesis (issue #295) says the analysis-heavy skills
get absorbed; the **hooks and state machine don't**.

---

## Table of contents

- [What it is](#what-it-is)
- [Install](#install)
- [Keeping the plugin up to date](#keeping-the-plugin-up-to-date)
- [First-time consumer setup](#first-time-consumer-setup)
- [Command reference](#command-reference)
- [Quick start and usage tiers](#quick-start)
- [Core concepts](#core-concepts)
  - [Worktree rule](#worktree-rule)
  - [Skills by audience](#skills-by-audience)
  - [Live Context Server (LCS)](#live-context-server-lcs)
- [Tooling](#tooling)
  - [Loghooks](#loghooks-dev-kitlog)
  - [Token efficiency analyzer](#token-efficiency-analyzer)
  - [Cost gate](#cost-gate)
- [Consumer CI install](#consumer-ci-install)
- [Codex CLI compatibility](#codex-cli-compatibility)
- [Agent-behavior eval](#agent-behavior-eval)
- [Repository layout](#repository-layout)
- [Design principles](#design-principles)
- [Contributing](#contributing)

---

## What it is

`dev-harness-kit` ships as a single Claude Code / Codex plugin (`dev-kit`) that
covers the full delivery loop. Highlights:

- **Plan + Design in one command** — `/dev-kit:plan` auto-generates `PRD.md` +
  `phases/<name>/{index.json, step<N>.md}` through a 5-gate loop
  (`frame → validate → non-goals → decompose → emit`) driven by quantified
  ambiguity and value scores rather than a fixed questionnaire.
- **Per-step sub-agent Build** — `/dev-kit:build` delegates each step to a
  sub-agent with an integrated TDD + auto-fix loop.
- **Parallel Review / Security** — `/dev-kit:review` (correctness + security +
  architecture) and `/dev-kit:security` (OWASP A01–A10) fan out to subagents and
  run a verification pass that rejects false positives.
- **Agent-behavior eval** — `/dev-kit:eval` replays recorded transcripts and
  judges them against per-dimension rubrics plus a code-sanity checklist.
- **Eval-Repair loop** — auto-check → specialized fixer → final Human Review.
- **Human-on-the-Loop** — the harness auto-progresses; the user approves last.
- **Worktree enforcement** — hooks block edits in the main checkout and nudge
  every new task onto its own worktree + branch.
- **Consumer install** — `/dev-kit:ci-setup` ships a self-aware CI workflow set
  that works both inside this repo and in downstream consumer repos.
- **Cost visibility** — a token-efficiency dashboard and a live cost gate,
  fed by opt-in session loghooks.
- **Session monitor** — `python3 tools/session_monitor.py` lists every Claude Code
  and Codex session across this repo's worktrees with live / idle / stale
  status; pick one with the inline arrow-key UI and the tool emits the
  exact `cd <wt> && claude --resume <sid>` resume command for you to run
  with `!`. A stdlib-only inline picker is also available over `ssh` /
  from a plain shell.

---

## Install

Requires the Claude Code CLI. See [Node compatibility](#node-compatibility)
before running any `claude plugin …` command.

```bash
# Marketplace install (recommended)
claude plugin marketplace add sh-ai-x/dev-harness-kit
claude plugin install dev-kit

# …or from a local checkout
git clone https://github.com/sh-ai-x/dev-harness-kit
claude plugin marketplace add ./dev-harness-kit
claude plugin install dev-kit

# At the start of every session
/reload-plugins
```

The install pins the `version` field from `.claude-plugin/plugin.json`, and the
loaded copy lives in a version-named cache directory
(`~/.claude/plugins/cache/dev-kit/dev-kit/<version>/`). The marketplace source
tracks the `main` branch (`.claude-plugin/marketplace.json` → `source.ref: main`), so a new
version is available after each merge — see
[Keeping the plugin up to date](#keeping-the-plugin-up-to-date).

### Live-source dev (recommended for contributors)

The marketplace install pins one published version. When you are developing this
repo, point Claude Code at your local checkout instead so edits are live with no
re-install:

```bash
claude --plugin-dir /path/to/dev-harness-kit
```

Save the keystrokes with a shell alias in `~/.zshrc` (or `~/.bashrc`):

```bash
alias claude-dev='claude --plugin-dir /path/to/dev-harness-kit'

claude-dev   # in a project dir: loads your local edits, no rebuild
claude       # falls back to the marketplace-pinned install
```

When both are available, the local `--plugin-dir` copy wins for that session.

> **Don't symlink `~/.claude/skills/dev-kit` to the repo.** A marketplace install
> and a skills-dir plugin sharing the same `name` collide, and the loader rejects
> the second copy. Use the alias above for a no-flag live-source install.

### Node compatibility

The bundled Claude Code CLI crashes on **Node ≥ 25**
(`TypeError: Cannot read properties of undefined (reading 'prototype')` at
`cli.js:384`). Run every `claude plugin …` command on **Node 22**:

```bash
nvm install 22 && nvm use 22
```

The `--plugin-dir` flag is unaffected — it bypasses the failing CLI path
entirely.

---

## Keeping the plugin up to date

A marketplace install loads a cached copy at
`~/.claude/plugins/cache/dev-kit/dev-kit/<version>/`. After a PR merges to
`main`, that cache is stale until refreshed.

**Refresh when:**

- A PR merged to `main` and you want the new behavior in your current session.
- `/dev-kit:*` output no longer matches the latest source.
- A consumer repo's `/dev-kit:ci-setup` reports a missing file (e.g.
  `scripts/branch-policy.sh: No such file or directory`) — the cache is stale.

### Claude Code

The `dev-kit` marketplace entry points at `main`, so after each merge the
marketplace catalog auto-bumps the pinned version. The cleanest path is:

```bash
# Preferred: pull the latest pinned version from the marketplace.
# Works from any shell — and from inside a Claude Code session, where the
# updater path bypasses the CLI bug (see "Node compatibility" above).
claude plugin update dev-kit
```

If that fails (most commonly because you're inside a Claude Code session and
the bundled CLI throws the Node `TypeError`), the maintenance script does the
same job with raw `git pull` + `rsync`:

```bash
# Escape hatch: pull the marketplace clone + rsync into the versioned cache.
bin/devkit-refresh.sh
bin/devkit-refresh.sh --dry-run    # show what would change first
```

> **Why `devkit-refresh.sh` exists:** `claude plugin install --force` and
> `claude plugin update` both hit the same CLI path that throws the Node
> `TypeError` above when invoked *from inside* a Claude Code session. The script
> does the same job with plain `git pull` + `rsync`, which works everywhere. It
> reads the cache version from `plugin.json` (falling back to the marketplace
> clone's short SHA if the field is absent) and preserves executable bits on
> shipped hook/template scripts.

If even that is unavailable, you can refresh the cache by hand:

```bash
cd ~/.claude/plugins/marketplaces/dev-kit && git pull origin main --ff-only
rsync -a --delete --exclude=.git \
  ~/.claude/plugins/marketplaces/dev-kit/ \
  ~/.claude/plugins/cache/dev-kit/dev-kit/<version>/
```

### Codex

```bash
bash skills/codex-cache-update/scripts/update.sh
bash skills/codex-cache-update/scripts/update.sh --dry-run   # inspect only
```

It upgrades the Codex marketplace checkout and synchronizes the matching
versioned cache — even when the marketplace command reports it is already
current — then prints the marketplace path, manifest version, cache path, and a
final `cache synchronized` line. Override paths for a non-default install:

```bash
CODEX_MARKETPLACE_DIR="$HOME/.codex/.tmp/marketplaces/dev-kit" \
CODEX_CACHE_ROOT="$HOME/.codex/plugins/cache/dev-kit/dev-kit" \
bash skills/codex-cache-update/scripts/update.sh
```

After any refresh, restart the client or run `/reload-plugins` where supported.

---

## First-time consumer setup

Most users are consumers. End-to-end "I have a new repo" flow:

```bash
# 1. Create + clone
gh repo create myorg/myrepo --private --clone && cd myrepo

# 2. Install the plugin
claude plugin marketplace add sh-ai-x/dev-harness-kit
claude plugin install dev-kit
# (live source: claude --plugin-dir /path/to/dev-harness-kit)

# 3. One-shot setup: CLAUDE.md + AGENTS.md + active-hooks.json + CI templates
/dev-kit:bootstrap-full
#    = /dev-kit:bootstrap then /dev-kit:ci-setup --force.
#    Run them separately if you only want one half.

# 4. First commit + push
git add -A && git commit -m "chore: bootstrap dev-kit"
git push -u origin main
```

**Use `--force` on first install.** On a fresh repo the result is identical to a
default install (all files copy either way), but `--force` is robust against a
partial previous attempt and a stale plugin cache. Re-run with `--force` later to
pull upstream template changes — see
[Consumer CI install](#consumer-ci-install) for refresh vs first-install
semantics.

Typical next step: `/dev-kit:plan` to generate the PRD and phases.

---

## Command reference

Invoke with `/dev-kit:<skill>`. This list groups the user-facing entry points by
workflow stage; only skills with `user-invocable: true` in their `SKILL.md`
appear in slash autocomplete. Inspect that frontmatter (or use autocomplete) for
the authoritative, current surface — see [Skills by audience](#skills-by-audience).

**Setup**

| Command | Purpose |
|---|---|
| `/dev-kit:bootstrap` | First entry — generate `CLAUDE.md` |
| `/dev-kit:bootstrap-full` | One-shot bootstrap + ci-setup (new-project default) |
| `/dev-kit:ci-setup` | Install CI templates (workflows + hooks + scripts + worktree files) |
| `/dev-kit:ci-doctor` | Read-only PASS/FAIL audit of CI readiness |
| `/dev-kit:log setup\|on\|off\|status` | Toggle session loghooks per project |
| `/dev-kit:config` | Skill / MCP / hook / methodology picker |

**Plan → Build**

| Command | Purpose |
|---|---|
| `/dev-kit:plan` | PRD + phases (Plan + Design unified) |
| `/dev-kit:build` | Run per-step sub-agents |
| `/dev-kit:adapt` | Mid-build plan/spec amendment |
| `/dev-kit:feat-remove` | Remove a feature (call-graph sweep + deletion report) |

**Review → Ship**

| Command | Purpose |
|---|---|
| `/dev-kit:review` | 3-dim review (correctness + security + architecture) |
| `/dev-kit:security` | OWASP A01–A10 audit |
| `/dev-kit:audit` | Batch slop + secret audit |
| `/dev-kit:inspect` | 8-dim code-health audit (read-only) |
| `/dev-kit:refactor` | 3-phase refactor: inspect → cleanup → review |
| `/dev-kit:prune` | 4-phase deletion sweep: sweep → dependents → report → verify (`--target <feat>` for one feature) |
| `/dev-kit:babysit-pr` | PR babysitter loop (poll CI, fix, re-iterate) |
| `/dev-kit:ship` | Release tag |
| `/dev-kit:bump [major\|minor\|patch]` | Explicit version bump + push |

**Eval / cost / reporting**

| Command | Purpose |
|---|---|
| `/dev-kit:eval` | Agent-behavior eval (review/security/plan + code-sanity) |
| `/dev-kit:repair approve\|reject\|defer <asset>` | Eval-Repair Human Review |
| `/dev-kit:report` | HTML viewer for eval + inspect reports |
| `/dev-kit:token-analyzer` | Token-efficiency dashboard from session logs |
| `/dev-kit:cost-gate` | Live cost gate (spend + threshold + commit footer) |
| `/dev-kit:status` | HOTL visualization: loop progress + cycles + hand-off chain |
| `/dev-kit:llm-refresh` | Refresh `docs/llm-info/<provider>.json` from each vendor's pricing page |
| `/dev-kit:codex-cache-update` | Codex marketplace + versioned cache sync (CLI escape hatch) |
| `/dev-kit:skill-usage [options]` | Run `tools/skill_usage.py` and show turns/invocations |

**Docs / shortcuts**

| Command | Purpose |
|---|---|
| `/dev-kit:proposal` | Render `docs/proposals/<name>.yaml` → self-contained HTML |
| `/dev-kit:docs-maintenance` | Audit stale docs, refresh README, drop volatile facts |

---

## Core concepts

### Worktree rule

The canonical rule is `rules/git-workflow.md`. Claude Code discovers it through
the `.claude/rules` compatibility symlink; Codex reads the same file through
`AGENTS.md`. The requirement is hard:

> **Every task = new worktree + client handoff + new branch.** Claude Code opens
> a new session in the worktree; Codex spawns a subagent there. No edits on the
> previous task's branch or in the main checkout.

Enforced by four hooks:

- `worktree-guard.sh` — hard-blocks any Edit/Write in the main checkout.
- `worktree-auto-cut.sh` — on a new-task prompt in the main checkout, derives a
  slug, cuts the worktree, and hands the task off; falls back to a manual-cut
  nudge on any failure.
- `session-start-check.sh` — gentle reminder at session start.

The canonical worktree path is the client-neutral `.worktrees/<slug>/` at the
repo root, so Claude Code and Codex open the same checkout for a branch. Legacy
`.claude/worktrees/` and `.codex/worktrees/` checkouts stay discoverable for log
analysis, but new automatic cuts use `.worktrees/`. These worktree-rule files
also ship to consumer repos via `templates/ci/`.

### Skills by audience

Each `SKILL.md` carries a `user-invocable` frontmatter flag:

- **`user-invocable: true`** (or unset) — surfaces in `/dev-kit:` autocomplete.
  *You* type it.
- **`user-invocable: false`** — hidden. *Claude* auto-invokes it as a sub-step
  when its parent skill runs.

This is the boundary between two skill audiences:

- **User Invokable Skill** (`user-invocable: true`) — an explicit workflow or
  utility the user chooses from `/dev-kit:` autocomplete.
- **Model-use skill** (`user-invocable: false`) — an internal specialist the
  model selects when an event or parent workflow requires it. `hook-doctor` is
  model-use: visible hook failure text should trigger diagnosis without asking
  the user to know a second slash command.

If a skill name doesn't autocomplete, it's an internal sub-skill — type the
user-facing parent instead (e.g. `/dev-kit:refactor`, not
`/dev-kit:build-refactor`). Mental model: user-facing skills are the verbs (the
*what*); internal skills are the machinery (the *how*).

[`skills/README.md`](skills/README.md) is the canonical human-readable index
of every skill shipped by the plugin, grouped by `category:` frontmatter
field with an alphabetical fallback list. Every `SKILL.md` has a
`> [← Skills index](../../README.md)` back-link at the very top of its
body so the reader can hop back from any skill to the inventory. Use
`skills/README.md` for browsing; use the slash autocomplete for
invocation. This README does not duplicate the live skill surface — the
inventory changes too often for a hand-maintained count here to stay
correct. Discover the current count with:

```bash
find skills -mindepth 2 -maxdepth 2 -name SKILL.md | wc -l
```

When a hook reports `failed` or `exited with code`, invoke the hidden
`hook-doctor` skill automatically. It checks the provider-specific manifest,
runtime dependencies, plugin root, and plugin version, then runs only the safe
provider cache updater when repair is possible. A client restart is still
required after cache repair because hooks are loaded at session start.

For a longer, human-facing writeup of each skill (overview, when to use it,
how it works, flags, output), see [`docs/skills/README.md`](docs/skills/README.md).
It also separates human-invocable skills from model-invoked sub-skills, and
is where `/dev-kit:token-analyzer` and every other skill's full detail lives
rather than in this README.

### Live Context Server (LCS)

The **LCS** is the harness's read-only state substrate. Every runtime fact
the harness cares about — worktrees, branches, PRs, sessions, token spend,
hook coverage, valuation verdicts, interview state, the research cache — is
exposed through a single URI namespace:

```text
lcs://<resource>[/<param>]
```

The model (and the operator) asks the harness "what is the repo doing right
now?" through one of two surfaces:

| Surface | How | When to use |
|---|---|---|
| **Chat** — `/dev-kit:lcs` | Model-invoked skill that shells out to `bin/dev-kit-lcs.py` and renders the JSON payload inline. For NL questions about LCS state, the dispatcher consults `bin/dev-kit-lcs-route.py` (break-even rule: shell wins when one tool answers; LCS wins when N are needed). | "Show me every worktree", "what's the spend this hour", "is PR #447 MERGEABLE?", "what worktrees are stale?". |
| **CLI** — `bin/dev-kit-lcs.py` | Stdlib-only launcher; `--get <uri>`, `--list-resources`, `--describe <name>`, or `--serve` (JSON-RPC on stdio, MCP-compatible). | Hooks / scripts / CI; anything that doesn't want a chat round-trip. |

Both reach the same resource registry. The skill is hidden from autocomplete
(`user-invocable: false`, `alpha: state`) — the model auto-invokes it
whenever a parent skill needs a state lookup. Source:
[`skills/lcs/SKILL.md`](skills/lcs/SKILL.md).

#### Production resources

The default CLI registry wires the 6 core production handlers (`worktrees`,
`branches`, `pr`, `sessions`, `spend`, `valuations`); the remaining URIs are
reserved shapes that return exit code 2 if a caller asks for them before the
corresponding handler ships. Live list + per-resource docstrings live in
`lib/lcs_resources/`; the source is the source of truth.

| URI | What it returns |
|---|---|
| `lcs://worktrees` | Every git worktree, with a `summary` block (active/stale counts, `slot_drift`, `as_of`) for freshness at a glance. |
| `lcs://worktrees/<branch>` | One worktree's HEAD SHA, slot version, last commit. |
| `lcs://branches` | List variant: every local branch with summary stats (lets you discover a name before drilling in). |
| `lcs://branches/<name>` | Local + remote branches, ahead/behind counts, last-CI status. |
| `lcs://branches/<name>/slot` | Slot metadata (`slot-id`, runtime, last release). |
| `lcs://prs` | List variant: every open PR with `n`, `title`, `head`, `ci_state`, `review_state`. |
| `lcs://pr/<n>` | One PR's CI checks, review verdict, merge state, slot version. |
| `lcs://sessions` | List variant: every indexed session with `id`, `role`, `started_at`, `current_task`, `last_tool`. |
| `lcs://sessions/<id>` | One recorded Claude / Codex session (turns, tools, tokens). |
| `lcs://spend/<window>` | Token spend over a time window, bucketed by model + worktree. |
| `lcs://hooks/coverage` | Which hook fires against which runtime (claude-code vs codex). |
| `lcs://interview/<step>` | Current state of the plan-emission interview (step + answers). |
| `lcs://research/cache` | Research cache contents (queries, hits, freshness). |
| `lcs://valuations/<plan-id>` | A `valuate` verdict (decision + per-axis rationale). |

`<window>` is `today` / `last-hour` / an ISO range; `<step>` is the
interview step id; the rest are obvious from context. URIs are pure — no side effects, no writes, no network I/O beyond `gh api` / `git` reads.

**Listing what's wired vs. what's reserved.** A documented URI that is not a
registered route is worse than no URI (the operator types the URI, gets exit
2, and concludes LCS is broken), so `--list-routes` on the CLI splits the
two:

```bash
python3 bin/dev-kit-lcs.py --list-routes
# registered:
#   lcs://worktrees            worktrees
#   lcs://branches/<name>      branches
#   ...
# reserved (not implemented):
#   lcs://hooks/coverage
#   lcs://interview/<step>
#   lcs://research/cache
```

**When to route to LCS vs. just shell out.** A separate sibling binary
`bin/dev-kit-lcs-route.py` answers the NL question "what resource should
handle this?" against a deterministic break-even rule: *if a single shell
call answers the question, use the shell; if it requires N correlated calls
across heterogeneous sources, route to LCS.* The router is not a skill (a
skill that decides whether to call another skill is L6 anti-pattern); it
is a thin CLI binary, ~200 tokens per routed call, ROI positive only on
multi-source aggregations. See `python3 bin/dev-kit-lcs-route.py --list-rules`.

#### Hook integration

The 8 enforcement hooks consult LCS state instead of shelling out to `git`
where the lookup would be expensive or error-prone:

- `worktree-guard.sh` enriches the deny message with the live `lcs://worktrees`
  list (falls back to a `git worktree list` shell-out if LCS is unreachable).
- `git-guard.sh` verifies the `plugin.json` slot via `lcs://branches/<name>`
  on `git push` to a feature branch (shell-out fallback).
- `log-on-session-start.sh` resolves the active worktree through LCS at
  session start so the loghooked transcript carries the right branch label.
- `provider-divergence-check.sh` reads `lcs://branches/<name>` to check
  the runtime-provider slot before nudging.

This is the **Phase 2 batch** (PR #442). The dispatch is `lcs_server.run_lcs()`
behind a thin shell wrapper; if the LCS Python module fails to import, the
hook falls back to the shell-out path with a stderr note — failure to
consult LCS never blocks the hook's primary job.

#### When to add a new resource

A new `lcs://<x>` shape is the right move when more than one skill / hook
needs the same live read. Drop a module in `lib/lcs_resources/<x>.py`
implementing the `Resource` protocol (`name`, `fetch(parsed) -> dict`,
`schema: dict | None`); the dispatcher auto-registers it. The
`/dev-kit:lcs` skill needs no change — it shells out and prints whatever
the registry returns.

---

## Tooling

### Loghooks (`/dev-kit:log`)

Wraps the standalone [`loghooks`](https://github.com/sh-ai-x/loghooks) repo
(Claude Code `Stop` + `SessionEnd`, plus Codex equivalents) as a one-command
on/off toggle per project.

```bash
/dev-kit:log setup   # copy tools/save_log.py + scaffold logs/{claude-code,codex}/
/dev-kit:log on      # merge hooks into .claude/settings.json + .codex/hooks.json
/dev-kit:log status  # managed=N captured=N
/dev-kit:log off     # strip sentinel-tagged entries; scaffold left in place
```

Every installed entry carries `_loghooks_managed=true`; `off` strips only those,
so pre-existing user hooks survive. Captured transcripts land in
`logs/<tool>/<branch>/<sid>.jsonl` (grouped by `gitBranch`) and are gitignored.
See [`logs/README.md`](logs/README.md) and `skills/log/SKILL.md`.

### Token efficiency analyzer

A stdlib-only Python CLI (`tools/token_efficiency_analyzer.py`) turns the
`logs/{claude-code,codex}/**/*.jsonl` transcripts captured by loghooks into
one self-contained HTML dashboard — no dependencies, no JavaScript, no
network. The user-facing entry point is the `/dev-kit:token-analyzer` skill;
the CLI is also directly invokable for CI use:

```bash
python3 tools/token_efficiency_analyzer.py --repo "my-project" --days 30
open token-dashboard-my-project-30d.html
```

Full detail — flags, the 4-dimension scoring rubric, the 6 warning triggers,
and the per-model pricing table — lives in
[`docs/skills/token-analyzer.md`](docs/skills/token-analyzer.md).

### Preview

![Token efficiency dashboard — dev-harness-kit, last 30 days](docs/screenshots/token-dashboard-dev-harness-kit-30d.png)

*The screenshot above is regenerated from the latest dashboard HTML by
`tools/render_dashboard.py` (Playwright + Chrome, 1440 × 2x). Refresh after
any `tools/token_efficiency_analyzer.py` change.*

### Cost gate

A **read-only** cost layer, distinct from the post-hoc token dashboard:
cost-gate prints the running ledger on demand and emits the trailer block the
PR aggregator needs, while the analyzer replays historical sessions. **The
gate is observed only — it never blocks a tool call.** Full detail — the
warn/flag threshold table, override env vars, and the commit-trailer
format — lives in [`docs/skills/cost-gate.md`](docs/skills/cost-gate.md).

### Session monitor (`tools/session_monitor.py`)

The CLI form is the same data layer exposed for plain-shell use: over `ssh`,
in CI, in a quick `Terminal.app` window, or anywhere you want a single
keystroke to land back inside a specific worktree's conversation.

```bash
# Interactive inline picker (real TTY required — arrow keys + Enter)
python3 tools/session_monitor.py

# Plain listing (works without a TTY; safe to run from any harness)
python3 tools/session_monitor.py --list --days 30

# Machine-readable JSON for scripting / non-Claude-Code callers
python3 tools/session_monitor.py --json --days 30 | jq '.total_sessions, .live_sessions'

# Debug the resume argv synthesis for the first session
python3 tools/session_monitor.py --print-resume-command
# -> cd /Users/sanghee/dev/dev-harness-kit && claude --resume <sid>

# Install a `session-monitor` shell alias into your rc (idempotent)
python3 tools/session_monitor.py --cli-setup
# -> then: source ~/.zshrc   (now `session-monitor` works from any cwd)
```

Both the `--list` output and the interactive picker group sessions by
worktree and print a `STATUS SRC ID MODEL BRANCH AGE` column-label line
under each group header, so `branch` reads as its own labeled column.

The interactive picker is built directly on `termios` + ANSI escapes
(stdlib only, no `curses`, no third-party deps). On `Enter` it restores
the original `termios` mode, `cd`s into the session's worktree, and
`exec`s `claude --resume <sid>` (Claude Code) or `codex resume <sid>`
(Codex) — `exec` replaces the Python process so the user lands directly
in the resumed session. If the worktree is gone or merged, the picker
falls back to the main checkout and prints a warning.

Each session's `branch` is overridden with the worktree's current
`git rev-parse --abbrev-ref HEAD` so the picker shows the branch the
worktree is *actually* on, not the one captured at save-log time. Stale
worktrees (merged/gone) and detached-HEAD worktrees keep the log-captured
branch as a fallback.

**Common flags**

| Flag | Default | Purpose |
|---|---|---|
| `--days N` | `30` | Look-back window; older sessions are dropped |
| `--repo <name>` | (none) | Substring filter on the repo basename |
| `--logs-dir <path>` | `<main-repo>/logs` | Root for `claude-code/` and `codex/` subdirs |
| `--list` | off | Plain stdout listing (previewable in any harness) |
| `--json` | off | Machine-readable output for scripts / skill consumers |
| `--print-resume-command` | off | Print the cwd + argv for the first session; exit |
| `--cli-setup` | off | Install a `session-monitor` alias into `~/.zshrc`/`~/.bashrc` (idempotent); exit |
| `--dry-run` | off | With `--cli-setup`, print the alias block without writing |

**Status semantics**

| Glyph | Status | Meaning |
|:---:|---|---|
| `●` | `live` | A running `claude`/`codex` process is cwd'd into the session's worktree, OR the last turn landed within the 180 s recency window |
| `○` | `idle` | Captured and within `--days`, but not recently active |
| `⌀` | `stale` | Worktree is merged into `main` or gone; resume falls back to the main checkout |

**Why a tool alongside a skill:** the skill needs the harness (to render
`AskUserQuestion`); the CLI needs a TTY (to render the picker). They share
one data layer — `discover → aggregate → group → enrich → render` — and
the skill's `--json` mode is literally the CLI's JSON output piped into
the model. No LLM sits in the loop for either; both are pure consumers of
the `/dev-kit:log` transcripts.

### Skill usage (`tools/skill_usage.py`)

Per-skill telemetry over the same `/dev-kit:log` transcripts: aggregates
two distinct signals - `attributionSkill` turn-count (depth / work done
by the skill) and explicit `Skill` tool-use blocks (distinct human
kicks). High turns + low invocations reads as a babysitter loop; both
low is prune-eligible; high turns + high invocations is a heavy hitter.
Workspace attribution is captured per `cwd` so target-project usage is
separable from self-dev.

```bash
# Top skills (default 30-day window) - markdown table to stdout
python3 tools/skill_usage.py

# Same report through the installed command wrapper
/dev-kit:skill-usage

# Narrow to one workspace, fresh window
python3 tools/skill_usage.py --cwd /path/to/project --days 7

# Machine-readable, e.g. piped into a plan or eval script
python3 tools/skill_usage.py --json | jq '.[0:5]'

# Same data scoped to one worktree's session list
python3 tools/session_monitor.py --skill-usage --skill-days 30
```

Stdlib only; `--days 0` disables the time window; `--cwd <prefix>` filters
to a single workspace. The `--skill-usage` / `--skill-days` flags on
`tools/session_monitor.py` reuse the same aggregator to print per-skill
totals next to the per-worktree session listing.

Use `--top 0` to include skills with zero activity in the selected window.
Those rows are useful for a complete inventory and for deciding whether a
specialist skill needs better documentation or a cleanup review; do not treat
zero captured usage as proof that the skill is obsolete.

---

## Consumer CI install

`/dev-kit:ci-setup` is what makes dev-kit work in *other* repos. It copies:

- GitHub Actions workflows (ci, auto-fix-pr, review)
- scripts (validate, test, branch-policy, ci-local)
- a pre-push hook
- worktree-rule files (hooks, lib, rule, tests)

The shipped `review.yml` is **self-aware**: it detects whether the checkout is
the dev-kit plugin itself (self-install) or a plain consumer repo (clones from
public source), so one workflow file works in both contexts.

**Switching the CI review provider:** provider selection is env-based — no
committed default, so the same repo can be used by different operators with
different providers without conflicts.

- **Local** (when running `/dev-kit:review` outside GitHub Actions): set in
  `.env:CI_REVIEW_PROVIDER`. Manage via `bin/set-provider.sh <provider>` —
  it upserts the key, prints the diff, and reminds you to set the matching
  GitHub repo variable + secret. `.env` is gitignored, so this is per-user.
- **CI** (`.github/workflows/review.yml`): read from the GitHub repo
  variable `vars.CI_REVIEW_PROVIDER`, with the `workflow_dispatch`
  `review_provider` input as a per-run override. Set via
  `gh variable set CI_REVIEW_PROVIDER --body <minimax|anthropic|deepseek>`.
  When neither is set, the workflow fails loud with a remediation hint.

Each provider also needs its matching repo secret (`MINIMAX_API_KEY`,
`ANTHROPIC_API_KEY`, or `DEEPSEEK_API_KEY`) pushed via `gh secret set`. A
PR that itself edits `.github/workflows/review.yml` is skipped by
`claude-code-action`'s anti-tampering guard — expected, and it resolves once the
PR merges.

### `--force`: when and when not

`ci-setup` is **idempotent by default** — the marker `.dev-kit/ci-config.json`
records install time + content hashes, so a matching re-run is a no-op. `--force`
overwrites the expected files regardless.

**Use `--force`** for a first install, to pull a newly added or fixed template,
or when you suspect a stale/partial install (marker present but a file missing or
drifted). **Avoid `--force`** on a clean re-run with no upstream changes, or when
you've hand-edited installed files (it overwrites local customizations — review
the diff first).

```bash
bin/devkit-refresh.sh                         # 1. refresh cache → latest templates
cd /path/to/consumer-repo
/dev-kit:ci-setup --force                      # 2. install
git diff .github/ scripts/ .githooks/ hooks/ .claude/ tests/   # 3. review the diff
/dev-kit:ci-doctor                             # 4. verify readiness (repeat until PASS)
git add -A && git commit -m "chore(ci): refresh dev-kit templates"   # 5. commit
```

---

## Codex CLI compatibility

Codex CLI's plugin format ([openai/plugins](https://github.com/openai/plugins))
is a `.codex-plugin/plugin.json` manifest with a `"skills"` field pointing at the
skills directory and a `"hooks"` field pointing at the bundled
`.codex-plugin/hooks/hooks.json`. That bundled copy mirrors the canonical
`hooks/hooks.json` (Codex requires plugin hook files inside the plugin root); a
regression test keeps the two event inventories synchronized. Codex commands use
`${PLUGIN_ROOT}`; Claude Code uses `${CLAUDE_PLUGIN_ROOT}` and keeps loading
`hooks/hooks.json` directly.

After enabling the plugin, review and trust its hooks with `/hooks` in Codex —
new or changed non-managed hooks are skipped until trusted. Check local status:

```bash
python3 bin/dev-kit-hooks-status.py          # human-readable
python3 bin/dev-kit-hooks-status.py --json    # machine-readable
```

The report distinguishes Claude Code registration, Codex registration + trust,
the `.dev-kit/.active-hooks.json` matrix, and Git's separate pre-commit and
pre-push hooks. The pre-commit gate checks staged Python files with host-installed
Ruff and never auto-fixes them; pre-push keeps the branch and version policy.
Activate both hooks after installing Ruff:

```bash
brew install ruff                              # macOS
apt install ruff                               # Debian/Ubuntu
git config core.hooksPath .githooks
```

### Hook inventory

| Hook | Event | Purpose | Mode |
|---|---|---|---|
| `tdd-guard.sh` | PreToolUse (Write\|Edit\|MultiEdit) | TDD test-first enforcement | advisory / `--strict` |
| `bash-guard.sh` | PreToolUse (Bash) | Block destructive commands | advisory / `--strict` |
| `git-guard.sh` | PreToolUse (Bash) | Branch strategy enforcement | hard-block |
| `worktree-guard.sh` | PreToolUse (Write\|Edit\|MultiEdit) | Block edits in main checkout | hard-block |
| `review-yml-isolation.sh` | PreToolUse (Bash) | Force `review.yml` changes into their own commit/PR | hard-block |
| `worktree-auto-cut.sh` | UserPromptSubmit | Auto-cut a worktree for a new-task prompt in main | advisory (fails open) |
| `session-start-check.sh` | SessionStart | Remind about the worktree rule | advisory |
| `log-on-session-start.sh` | SessionStart | Auto-install loghooks each session (idempotent) | advisory |
| `provider-divergence-check.sh` | SessionStart | Nudge when `.env:CI_REVIEW_PROVIDER` is off-list, diverges, or missing | advisory |
| `secret-scan.sh` | PostToolUse (Write\|Edit) | Detect credentials in edits | hard-block |
| `slop-detector.sh` | PostToolUse (Write\|Edit) | Block AI slop (phrase + structure + scoring, KO+EN) | advisory (opt-in strict) |
| `worktree-log-auto-install.sh` | PostToolUse (Bash) | Install loghooks into a newly-added worktree | advisory |
| `acp-tier-assert.sh` | PreToolUse (`*`) | Enforce ACP agent tier-assertion line on first tool call (M/T/L) | hard-block |
| `stop-verify.sh` | Stop | Run regression tests on session end | hard-block |

---

## Agent-behavior eval

`/dev-kit:eval` measures whether the **agent produces the right output for the
right input** when running the dev-kit skills. The unit is a *case fixture + a
recorded transcript → per-dimension rubric judgment*. Replay-only in v1: a case
without a recorded transcript is `SKIPPED` (a setup gap, not a regression).

**Three eval dimensions** (each axis 0–10):

| Dim | Axes | Measures |
|---|---|---|
| `review` | verdict consistency · severity calibration · precision · recall · code-sanity | review verdict + findings quality |
| `security` | OWASP classification · severity accuracy · precision | A01–A10 mapping + false-positive rate |
| `plan` | spec clarity · step atomicity · AC executability · dependency ordering | atomic, runnable, buildable plans |

`/dev-kit:eval` covers these three. The `/dev-kit:evaluate` companion adds the
**`harness-quality`** and **`os-quality`** dimensions (cross-cutting rubric
checks for env / secret / CI cost), run by the same `--dim` flag on the
underlying runner — see [`docs/skills/evaluate.md`](docs/skills/evaluate.md)
and the `eval/rubrics/` registry.

Per-case axis mean → verdict: **OK** ≥ 8.0 · **DRIFT_WARNING** 5.0–7.9 · **ROT**
< 5.0 · **SKIPPED** (no transcript). The `review` dim embeds a 20-checkbox
code-sanity rubric (clean-code + over-engineering + value/meaning), frozen in
`ADR-0022`.

```bash
# Full eval → .dev-kit/eval-report.md
python lib/eval_runner.py --project-root . [--dry-run]
python lib/eval_runner.py --project-root . --dim plan
python lib/eval_runner.py --project-root . --case review-04-factory-one-impl
```

`--dry-run` skips LLM calls (mocks each case at 7.0/DRIFT_WARNING) — useful in CI
without an API key. Adding a case requires no code change: drop a case JSON in
`eval/cases/<dim>/` and a transcript in `eval/transcripts/<dim>/`, then re-run.
See `docs/adr/ADR-0022-eval-agent-behavior.md` for the full rationale.

---

## Repository layout

The concept-level tree and directory guide live in the
[`Repository map`](docs/repo/REPOSITORY-MAP.md), so the main README stays
searchable while the original layout reference remains available.

---

## Design principles

- **NO-DUP** — Iron Laws live in one place (`CLAUDE.md §1`), enforced by hook +
  skill.
- **NO-BOTTLENECK** — 0-arg UX, lazy `CLAUDE.md`, parallel sub-agents.
- **NO-MEANINGLESS-LOOP** — explicit loop semantics + auto-STOP + user interrupt.
- **Human-on-the-Loop** — auto-progress with the user as supervisor and a 1×
  interrupt.
- **Methodology extension** — TDD / SDD / DDD / BDD / FDD selectable.
- **A2A typed** — sub-agent ↔ main communication via a JSON-Schema SSOT.
- **Plugin-only** — the plugin manifest is the single source of truth.
- **Worktree-per-task** — enforced by hooks, documented in `rules/git-workflow.md`.
- **Consumer-install** — one self-aware workflow set works in this repo and in
  consumer repos.

See `docs/adr/` for the full ADR series.

---

## Contributing

Pass the pre-impl gate (`docs/planning/PRE-IMPL-CHECK.md`) and the 8-dimension cost check
(`docs/quality/COST-ANALYSIS.md`), then:

```bash
python3 -m pytest tests/ -q
claude plugin validate .claude-plugin/plugin.json
```

Reference docs: [`docs/stages/STAGES.md`](docs/stages/STAGES.md),
[`docs/naming/NAMING.md`](docs/naming/NAMING.md), [`CHANGELOG.md`](CHANGELOG.md).

## License

MIT
