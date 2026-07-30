# dev-harness-kit

> A plugin that gives Claude Code and Codex a repeatable way to plan, build,
> review, and ship real code — with guardrails that the model can't talk its way
> around.

[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**Language:** English · [한국어](README.ko.md)

---

## What is this?

`dev-harness-kit` installs one plugin — called `dev-kit` — into your project. Once
it's installed, you drive real development work through a handful of slash
commands that always follow the same loop:

```
bootstrap → plan → build → review → ship
```

Each step does one job. `plan` turns an idea into a written spec and a checklist
of build steps. `build` works through that checklist one step at a time, running
the tests as it goes. `review` and `ship` check the result and cut a release.

The important part is the guardrails. dev-kit installs **hooks** — small scripts
that run automatically on every file edit and shell command. They block things
like committing straight to `main`, editing files outside a working branch, or
claiming "done" without a passing test. These are enforced by code, not by
politely asking the model, so they hold even when the model would rather skip
them.

It works in both Claude Code and Codex, and the same commands mean the same thing
in both.

**New here?** The friendliest starting point is
[`docs/home/00-index.md`](docs/home/00-index.md)
([한국어](docs/home/00-index.ko.md)) — it explains *why* the system exists and
walks a 60-second tour. This README covers install, the commands you'll use most,
and what to do when work doesn't go in a straight line.

---

## Install

You need the Claude Code CLI. **Run every `claude plugin …` command on Node 22** —
the bundled CLI crashes on Node 25 and newer:

```bash
nvm install 22 && nvm use 22
```

Then install the plugin:

```bash
# Recommended: from the marketplace
claude plugin marketplace add sh-ai-x/dev-harness-kit
claude plugin install dev-kit

# …or from a local clone
git clone https://github.com/sh-ai-x/dev-harness-kit
claude plugin marketplace add ./dev-harness-kit
claude plugin install dev-kit

# At the start of each session
/reload-plugins
```

The install pins the `version` from `.claude-plugin/plugin.json` and keeps the
loaded copy in a version-named cache folder
(`~/.claude/plugins/cache/dev-kit/dev-kit/<version>/`). The marketplace tracks the
`main` branch, so a new version is available after each merge — see
[Keeping the plugin up to date](#keeping-the-plugin-up-to-date).

**Working on this repo itself?** Point Claude Code at your local checkout so your
edits are live with no re-install (this path also sidesteps the Node 25 bug):

```bash
claude --plugin-dir /path/to/dev-harness-kit
```

A handy alias for `~/.zshrc` or `~/.bashrc`:

```bash
alias claude-dev='claude --plugin-dir /path/to/dev-harness-kit'
```

> **Don't** symlink `~/.claude/skills/dev-kit` to the repo. A marketplace install
> and a skills-dir plugin with the same name collide, and the loader rejects the
> second copy. Use the alias above instead.

---

## Quickstart

On a brand-new repo, one command does all the first-time setup:

```bash
/dev-kit:bootstrap-full
```

That writes three project files (`CLAUDE.md`, `AGENTS.md`, and the hook
configuration) **and** installs the CI templates, in a single shot. It is exactly
`/dev-kit:bootstrap` followed by `/dev-kit:ci-setup` — run them separately if you
only want one half.

From there, the everyday loop is three commands:

```bash
/dev-kit:plan      # turn an idea into a written spec + a list of build steps
/dev-kit:build     # work through those steps one at a time, tests included
/dev-kit:review    # check the finished diff for correctness/security/design
```

What each one leaves behind, so you can see the progress on disk:

- **`/dev-kit:plan`** creates `PRD.md` (the spec) and a `phases/<name>/` folder
  holding one file per build step plus an `index.json` that tracks each step's
  status.
- **`/dev-kit:build`** works through those steps, writing code and running the
  acceptance checks, and marks each step `completed` in `index.json` as it goes.
- **`/dev-kit:review`** reads the diff and returns a verdict (Approve / Changes
  Requested / Blocked) with per-line findings.

When review is green, `/dev-kit:ship` cuts the release tag. That's the whole loop.

> A full "I have a brand-new repo" walkthrough (create repo → install → bootstrap
> → first commit) is at [First-time setup, end to end](#first-time-setup-end-to-end).

---

## Most-used skills

There are many skills, but these are the ones you'll actually reach for. Every
slash command is `/dev-kit:<name>`. Each links to its detailed page.

### Setting up a project

| Command | What it does |
|---|---|
| [`/dev-kit:bootstrap`](docs/skills/bootstrap.md) | First entry on a fresh repo — writes `CLAUDE.md`, `AGENTS.md`, and the hook config. |
| [`/dev-kit:bootstrap-full`](docs/skills/bootstrap-full.md) | `bootstrap` **and** `ci-setup` in one shot. The usual new-project starting point. |
| [`/dev-kit:ci-setup`](docs/skills/ci-setup.md) | Installs dev-kit's CI workflows and hooks into your repo so PRs run the same checks. |
| [`/dev-kit:ci-doctor`](docs/skills/ci-doctor.md) | Read-only check that answers "is my CI set up right — would the next PR pass?" |

### Planning and building

| Command | What it does |
|---|---|
| [`/dev-kit:plan`](docs/skills/plan.md) | Turns an idea into `PRD.md` + a step-by-step build checklist. |
| [`/dev-kit:build`](docs/skills/build.md) | Works through the checklist one step at a time, writing tests and code and verifying each step. |

### Getting a PR over the line

| Command | What it does |
|---|---|
| [`/dev-kit:babysit-pr`](docs/skills/babysit-pr.md) | Watches your open PR, fixes failing checks, pushes, and repeats until CI is green and review approves. |

### Keeping the project healthy

| Command | What it does |
|---|---|
| [`/dev-kit:inspect`](docs/skills/inspect.md) | Read-only whole-codebase health scan (dead code, duplication, smells) → one report. |
| [`/dev-kit:token-analyzer`](docs/skills/token-analyzer.md) | Shows where your Claude Code / Codex token spend is going, as an HTML dashboard. |
| [`/dev-kit:docs-maintenance`](docs/skills/docs-maintenance.md) | Audits stale docs and refreshes the README without baking in facts that go out of date. |
| [`/dev-kit:log`](docs/skills/log.md) | Turns session logging on/off. It's what feeds `token-analyzer`, `skill-usage`, and the session monitor. |
| [`/dev-kit:skill-usage`](commands/skill-usage.md) | Shows which skills you actually use, and how much — useful for pruning. |

For the complete, always-current list of every skill (there are more than the
ones above), see [`docs/skills/README.md`](docs/skills/README.md). It's grouped by
category with a one-line summary each. You can also just type `/dev-kit:` and let
autocomplete show you what's available.

> **A note on skill names:** if a name doesn't show up in autocomplete, it's an
> internal helper the model runs on its own (like `build-tdd` inside `build`) —
> you type the parent command, not the helper. The plain rule: user-facing
> commands are the *verbs*; internal skills are the *machinery*.

---

## When the flow doesn't go straight through

Real work pauses, backtracks, and skips steps. Here's the short version of each
common case. The full, example-by-example walkthrough is in
[`docs/workflow/WORKFLOW-SCENARIOS.md`](docs/workflow/WORKFLOW-SCENARIOS.md).

**You got interrupted mid-build.** Just run `/dev-kit:build` again. Build tracks
each step's status in `phases/<name>/index.json` (`unimplemented → pending →
in_progress → completed`), and re-running always picks up from the first step
that isn't `completed`. Closing your laptop after step 2 means the next run starts
at step 3 — no flag, no re-planning.

**The plan turned out wrong while a step was in progress.** Run
[`/dev-kit:adapt`](commands/adapt.md). It pauses the in-flight step, shows you
exactly where the plan and the actual output disagree, proposes one small patch to
the spec/step file, and — only after you approve it — writes the patch and resumes
the build. Use this for a small correction; if the whole plan is wrong at the
root, re-run `/dev-kit:plan` instead.

**You came back on a different day or a different terminal** and lost your place.
Run `python3 tools/session_monitor.py`. It lists your recent sessions across the
repo's worktrees and hands you back the exact command to resume the right one.
(This needs `/dev-kit:log` to have been on — that's what records the sessions.)
See [Session monitor](#session-monitor) below for the flag reference.

**You want to skip the Valuate step.** Go ahead — it's advisory. `/dev-kit:valuate`
scores whether a plan is worth building, but nothing forces you to run it and the
build proceeds either way (the old hard gate was removed in PR #463). Skip it for
small obvious work; run it as a cheap gut check on bigger bets.

**You want to skip straight to Build without a full plan.** There is **no
one-command bypass** today. Your honest options are to scope `/dev-kit:plan` very
tightly (it can emit a one- or two-step plan quickly) or to hand-seed a minimal
`phases/<name>/index.json` yourself. The [workflow scenarios
doc](docs/workflow/WORKFLOW-SCENARIOS.md#case-5-skipping-straight-to-build-without-a-full-plan)
explains both, and why the removed `tdd-fast` / `quick-fix` shortcuts are not an
option anymore.

---

## The worktree rule (please read)

This is the one hard rule that surprises newcomers, and it's enforced by a hook,
so you can't accidentally opt out.

> **Every task gets its own git worktree and branch.** You never edit files in the
> main checkout, and you never commit or push straight to `main`.

A worktree is just a second, isolated copy of your repo on a separate branch. The
plugin cuts one for you automatically when you start a new task in the main
checkout, or you can cut one yourself:

```bash
git worktree add -b feat/my-task .worktrees/feat-my-task origin/main
```

Then work inside that folder. If you try to edit the main checkout, the
`worktree-guard` hook blocks the edit and prints the list of live worktrees so you
can jump into one. The full rule (branch naming, the exact protocol, the hooks
that enforce it) lives in [`rules/git-workflow.md`](rules/git-workflow.md).

---

## Doc map

Most topic docs ship in **both** `.md` (for grep and GitHub) and `.html` (for
browsing with a sticky nav and dark/light theme). The landing page, the skill
index, and the workflow-scenarios doc are Markdown-only. Where a Korean version
exists, it's linked in the same row.

| Topic | HTML | MD | 한국어 | What you get |
|---|---|---|---|---|
| Why + value + quickstart | — | [`docs/home/00-index.md`](docs/home/00-index.md) | [`00-index.ko.md`](docs/home/00-index.ko.md) | Beginner landing — read first |
| When the flow doesn't go straight through | — | [`docs/workflow/WORKFLOW-SCENARIOS.md`](docs/workflow/WORKFLOW-SCENARIOS.md) | — | Resume a paused build, adapt a wrong plan, skip a step |
| What each loop step owns | [`docs/stages/STAGES.html`](docs/stages/STAGES.html) | [`docs/stages/STAGES.md`](docs/stages/STAGES.md) | [`STAGES.ko.md`](docs/stages/STAGES.ko.md) | bootstrap → plan → valuate → build → review → security → ship |
| CI install (run dev-kit CI elsewhere) | [`docs/quality/ci-setup.html`](docs/quality/ci-setup.html) | [`docs/quality/ci-setup.md`](docs/quality/ci-setup.md) | [`ci-setup.ko.md`](docs/quality/ci-setup.ko.md) | `branch-policy` + validate + test + auto-fix workflows |
| Maintenance gate (PR-only quality) | [`docs/quality/maintenance-gate.html`](docs/quality/maintenance-gate.html) | [`docs/quality/maintenance-gate.md`](docs/quality/maintenance-gate.md) | — | 20-checkbox rubric enforced in `.github/workflows/maintenance.yml` |
| Runtime portability (Claude Code ↔ Codex) | [`docs/architecture/RUNTIME-PORTABILITY.html`](docs/architecture/RUNTIME-PORTABILITY.html) | [`docs/architecture/RUNTIME-PORTABILITY.md`](docs/architecture/RUNTIME-PORTABILITY.md) | [`RUNTIME-PORTABILITY.ko.md`](docs/architecture/RUNTIME-PORTABILITY.ko.md) | The contract both runtimes honor so plugin.json means the same thing |
| Naming convention (SSOT) | [`docs/naming/NAMING.html`](docs/naming/NAMING.html) | [`docs/naming/NAMING.md`](docs/naming/NAMING.md) · [ADR-0010](docs/adr/ADR-0010-naming-convention.md) | [`NAMING.ko.md`](docs/naming/NAMING.ko.md) | Why a hook is `bash-guard.sh`, not `bashHook.sh` |
| Pre-implementation gate | [`docs/planning/PRE-IMPL-CHECK.html`](docs/planning/PRE-IMPL-CHECK.html) | [`docs/planning/PRE-IMPL-CHECK.md`](docs/planning/PRE-IMPL-CHECK.md) | — | 9 questions before code |
| Cost & risk | [`docs/quality/COST-ANALYSIS.html`](docs/quality/COST-ANALYSIS.html) | [`docs/quality/COST-ANALYSIS.md`](docs/quality/COST-ANALYSIS.md) | — | Token ceilings, cost-gate trailer format |
| Team adoption | [`docs/adoption/team-adoption.html`](docs/adoption/team-adoption.html) | [`docs/adoption/team-adoption.md`](docs/adoption/team-adoption.md) | — | Why a single maintainer and a 20-person team adopt the harness differently |
| Hook reference (the enforcement layer) | — | [`docs/hooks/HOOK-REFERENCE.md`](docs/hooks/HOOK-REFERENCE.md) | — | Every hook, by stage and by trigger event |
| Hook coverage gaps | [`docs/hooks/hook-coverage-gaps.html`](docs/hooks/hook-coverage-gaps.html) | [`docs/hooks/hook-coverage-gaps.md`](docs/hooks/hook-coverage-gaps.md) | — | Which hook events are wired vs. which aren't, per runtime |
| ACP dispatch (M-tier architecture) | [`docs/architecture/ACP-DISPATCH.html`](docs/architecture/ACP-DISPATCH.html) | [`docs/architecture/ACP-DISPATCH.md`](docs/architecture/ACP-DISPATCH.md) | [`ACP-DISPATCH.ko.md`](docs/architecture/ACP-DISPATCH.ko.md) | How Model-tier agents find and dispatch to Capability-tier skills |
| ACP (Agent Coordination Protocol) | [`docs/architecture/acp-harness.html`](docs/architecture/acp-harness.html) | [`docs/architecture/acp-harness.md`](docs/architecture/acp-harness.md) | [`acp-harness.ko.md`](docs/architecture/acp-harness.ko.md) | The wire-format ACP uses to talk between agents |
| Skill reference | — | [`docs/skills/README.md`](docs/skills/README.md) | [`README.ko.md`](docs/skills/README.ko.md) | All skills with category + classification |
| Decision records | — | [`docs/adr/`](docs/adr) | — | Locked ADRs (historical; English only) |
| Repo map | [`docs/repo/REPOSITORY-MAP.html`](docs/repo/REPOSITORY-MAP.html) | [`docs/repo/REPOSITORY-MAP.md`](docs/repo/REPOSITORY-MAP.md) | — | Where each component lives in the tree |

If you have five minutes, open [`docs/home/00-index.md`](docs/home/00-index.md)
and read the first three sections (why, quickstart, value). Everything else can
wait.

---

## First-time setup, end to end

The complete "I have a brand-new repo" flow:

```bash
# 1. Create + clone
gh repo create myorg/myrepo --private --clone && cd myrepo

# 2. Install the plugin
claude plugin marketplace add sh-ai-x/dev-harness-kit
claude plugin install dev-kit
# (live source instead: claude --plugin-dir /path/to/dev-harness-kit)

# 3. One-shot setup: CLAUDE.md + AGENTS.md + hook config + CI templates
/dev-kit:bootstrap-full

# 4. First commit + push
git add -A && git commit -m "chore: bootstrap dev-kit"
git push -u origin main
```

**Use `--force` on the very first install** (`/dev-kit:ci-setup --force`, which
`bootstrap-full` runs for you). On a fresh repo the result is identical to a
plain install, but `--force` is robust against a half-finished earlier attempt or
a stale plugin cache. You also re-run with `--force` later to pull updated
templates — see [Consumer CI install](#consumer-ci-install) for the details.

Typical next step: `/dev-kit:plan` to generate the spec and build steps.

---

## Keeping the plugin up to date

A marketplace install runs from a cached copy at
`~/.claude/plugins/cache/dev-kit/dev-kit/<version>/`. After a PR merges to `main`,
that cache is stale until you refresh it.

**Refresh when** a PR merged and you want the new behavior now, `/dev-kit:*`
output no longer matches the latest source, or a consumer repo's `ci-setup`
complains about a missing file.

**Claude Code** — the clean path works from any shell, including inside a Claude
Code session:

```bash
claude plugin update dev-kit
```

If that fails (usually the Node bug when run from inside a session), use the
escape-hatch script, which does the same job with plain `git pull` + `rsync`:

```bash
bin/devkit-refresh.sh
bin/devkit-refresh.sh --dry-run    # preview first
```

**Codex:**

```bash
bash skills/codex-cache-update/scripts/update.sh
bash skills/codex-cache-update/scripts/update.sh --dry-run
```

After any refresh, restart the client or run `/reload-plugins` where supported.

---

## Consumer CI install

`/dev-kit:ci-setup` is what makes dev-kit's checks run in *your* repo. It copies in
the GitHub Actions workflows (ci, auto-fix-pr, review), the helper scripts
(validate, test, branch-policy, ci-local), a pre-push hook, and the worktree-rule
files. The shipped `review.yml` is self-aware — one file works whether the
checkout is the dev-kit plugin itself or a plain consumer repo.

`ci-setup` is **idempotent**: a marker file (`.dev-kit/ci-config.json`) records
what was installed, so a matching re-run does nothing. Use `--force` for a first
install, to pull a newly added/fixed template, or when you suspect a stale
install. Avoid `--force` on a clean re-run with no upstream changes, or if you've
hand-edited installed files — it overwrites local customizations, so review the
diff first.

```bash
bin/devkit-refresh.sh                                              # 1. refresh cache
cd /path/to/consumer-repo
/dev-kit:ci-setup --force                                          # 2. install
git diff .github/ scripts/ .githooks/ hooks/ .claude/ tests/       # 3. review
/dev-kit:ci-doctor                                                 # 4. verify (repeat to PASS)
git add -A && git commit -m "chore(ci): refresh dev-kit templates" # 5. commit
```

**Picking the CI review provider** is env-based, with no committed default, so
different operators can use different providers in the same repo. Locally, set
`CI_REVIEW_PROVIDER` in `.env` (managed via `bin/set-provider.sh <provider>`,
which is gitignored and per-user). In CI, set the GitHub repo variable
`vars.CI_REVIEW_PROVIDER` and the matching secret (`MINIMAX_API_KEY`,
`ANTHROPIC_API_KEY`, or `DEEPSEEK_API_KEY`). Full detail and the Codex-side setup
live in [`docs/quality/ci-setup.md`](docs/quality/ci-setup.md).

---

## Tooling reference

### Session logging (`/dev-kit:log`)

Session logging is what powers the token analyzer, the skill-usage report, and
the session monitor — none of them have data until you turn it on.

```bash
/dev-kit:log setup   # scaffold logs/{claude-code,codex}/ and copy the log tool
/dev-kit:log on      # install the log hooks into this project's settings
/dev-kit:log status  # managed=N captured=N
/dev-kit:log off     # remove only dev-kit's log hooks; your own hooks survive
```

Captured transcripts land in `logs/<tool>/<branch>/<sid>.jsonl` and are
gitignored. See [`docs/skills/log.md`](docs/skills/log.md).

### Token efficiency analyzer

`/dev-kit:token-analyzer` (or the CLI `tools/token_efficiency_analyzer.py`) turns
those logged sessions into a self-contained HTML dashboard — no dependencies, no
JavaScript, no network. It scores each session, flags cost anti-patterns, and
estimates USD savings.

```bash
python3 tools/token_efficiency_analyzer.py --repo "my-project" --days 30
open token-dashboard-my-project-30d.html
```

The flags, the scoring rubric, and the pricing table are documented in
[`docs/skills/token-analyzer.md`](docs/skills/token-analyzer.md).

![Token efficiency dashboard — dev-harness-kit, last 30 days](docs/screenshots/token-dashboard-dev-harness-kit-30d.png)

### Cost gate

A separate, **read-only** cost layer: `/dev-kit:cost-gate` prints the running
spend ledger on demand and emits the trailer block the PR aggregator needs. It
never blocks a tool call — it's observe-only. Thresholds, override env vars, and
the trailer format are in [`docs/skills/cost-gate.md`](docs/skills/cost-gate.md).

### Session monitor

`tools/session_monitor.py` finds a paused session and gets you back into it — the
answer to "I closed my terminal, how do I return to that build?" (See the
[workflow scenarios doc](docs/workflow/WORKFLOW-SCENARIOS.md#case-3-coming-back-from-a-different-terminal-or-day)
for the narrative version.)

```bash
python3 tools/session_monitor.py                       # interactive picker (needs a real TTY)
python3 tools/session_monitor.py --list --days 30       # plain listing, any shell
python3 tools/session_monitor.py --json --days 30        # machine-readable
python3 tools/session_monitor.py --print-resume-command  # print the resume command and exit
python3 tools/session_monitor.py --cli-setup             # install a `session-monitor` shell alias
```

On Enter, the picker changes into the session's worktree and re-opens the
conversation (`claude --resume <sid>` or `codex resume <sid>`); if the worktree
is gone, it falls back to the main checkout with a warning.

**Common flags**

| Flag | Default | Purpose |
|---|---|---|
| `--days N` | `30` | Look-back window; older sessions are dropped |
| `--repo <name>` | (none) | Substring filter on the repo basename |
| `--logs-dir <path>` | `<main-repo>/logs` | Root for `claude-code/` and `codex/` subdirs |
| `--list` | off | Plain stdout listing (works without a TTY) |
| `--json` | off | Machine-readable output for scripts |
| `--print-resume-command` | off | Print the cwd + resume command for the first session; exit |
| `--cli-setup` | off | Install a `session-monitor` alias into `~/.zshrc`/`~/.bashrc`; exit |
| `--dry-run` | off | With `--cli-setup`, print the alias block without writing |

**Status glyphs**

| Glyph | Status | Meaning |
|:---:|---|---|
| `●` | `live` | A running `claude`/`codex` process is in the session's worktree, or the last turn was within the recency window |
| `○` | `idle` | Captured and within `--days`, but not recently active |
| `⌀` | `stale` | Worktree is merged into `main` or gone; resume falls back to the main checkout |

### Skill usage (`/dev-kit:skill-usage`)

Per-skill telemetry over the same logged sessions: it shows how many turns each
skill drove and how many times you explicitly invoked it. High turns + low
invocations reads as a babysitter loop; both low means it's a prune candidate.

```bash
python3 tools/skill_usage.py                 # top skills, 30-day window
/dev-kit:skill-usage                         # same, through the command wrapper
python3 tools/skill_usage.py --top 0         # include skills with zero recent usage
python3 tools/skill_usage.py --cwd /path --days 7   # one workspace, fresh window
```

`--top 0` lists even unused skills — useful for a complete inventory. Don't read
zero captured usage as proof a skill is obsolete.

---

## Under the hood

Short pointers to the deeper material, so this README stays readable.

**The enforcement hooks** are the load-bearing part — deterministic guards that
short-circuit tool calls (block edits in the main checkout, deny destructive
`git`/`rm`, redact secrets, enforce test-first, require quoted exit codes before a
session ends). The skills are convenience wrappers around these hooks plus the
build state machine. The full hook inventory (by stage, and by the event that
fires each one) is in
[`docs/hooks/HOOK-REFERENCE.md`](docs/hooks/HOOK-REFERENCE.md); known coverage
gaps and per-runtime wiring differences are in
[`docs/hooks/hook-coverage-gaps.md`](docs/hooks/hook-coverage-gaps.md).

**What each stage reads and writes**, so you can see the data flow at a glance:

| Skill | Stage | Reads | Writes |
|---|---|---|---|
| `/dev-kit:plan` | Plan | Operator prompt | `PRD.md`, `phases/<name>/step<N>.md`, `phases/<name>/index.json` |
| `/dev-kit:valuate` | Valuate | `.dev-kit/hand-off/plan*.md` | `.dev-kit/valuations/<plan-id>.json` |
| `/dev-kit:build` | Build | `phases/<name>/index.json` + per-step file | per-step `output.json` |
| `/dev-kit:review` | Review | PR diff | verdict (Approve / Changes Requested / Blocked) |
| `/dev-kit:security` | Security | PR diff | per-OWASP verdict |
| `/dev-kit:ship` | Ship | Review verdict + AC outputs | `git tag` + CHANGELOG entry |

The verdict envelope `/dev-kit:valuate` writes (`decision` / `rationale` /
`blocking_findings`) is pinned by
`lib/valuation_engine.py:decision_is_canonical_envelope`. There used to be an
auto-gate that hard-blocked Build on a non-`proceed` verdict; it was removed in
PR #463 — see [Case 4 of the workflow scenarios doc](docs/workflow/WORKFLOW-SCENARIOS.md#case-4-skipping-the-valuate-step)
for what that means in practice.

**Agent-behavior eval** — `/dev-kit:evaluate` replays recorded transcripts and
judges them against per-dimension rubrics (review / security / plan) plus a
20-checkbox code-sanity checklist; adding `--harness-quality` or `--os-quality`
registers the matching cross-cutting rubric on the same runner. Details in
[`docs/skills/evaluate.md`](docs/skills/evaluate.md), with the rationale in
`docs/adr/ADR-0022-eval-agent-behavior.md`.

**Codex compatibility** — the same skills and hooks run under Codex CLI via a
`.codex-plugin/` manifest that mirrors the canonical hook config; a regression
test keeps the two in sync. Check local hook status with
`python3 bin/dev-kit-hooks-status.py`. Runtime portability is documented in
[`docs/architecture/RUNTIME-PORTABILITY.md`](docs/architecture/RUNTIME-PORTABILITY.md).

**Repository layout** — the directory-by-directory guide is the
[repository map](docs/repo/REPOSITORY-MAP.md).

**Design principles:**

- **NO-DUP** — Iron Laws live in one place (`CLAUDE.md §1`), enforced by hook + skill.
- **NO-BOTTLENECK** — 0-arg UX, lazy `CLAUDE.md`, parallel sub-agents.
- **NO-MEANINGLESS-LOOP** — explicit loop semantics + auto-STOP + user interrupt.
- **Human-on-the-Loop** — auto-progress with the user as supervisor and a 1× interrupt.
- **Methodology extension** — TDD / SDD / DDD / BDD / FDD selectable.
- **A2A typed** — sub-agent ↔ main communication via a JSON-Schema SSOT.
- **Plugin-only** — the plugin manifest is the single source of truth.
- **Worktree-per-task** — enforced by hooks, documented in `rules/git-workflow.md`.
- **Consumer-install** — one self-aware workflow set works in this repo and in consumer repos.

The full reasoning behind each of these lives in the ADR series under
[`docs/adr/`](docs/adr).

---

## Contributing

Pass the pre-impl gate ([`docs/planning/PRE-IMPL-CHECK.md`](docs/planning/PRE-IMPL-CHECK.md))
and the cost check ([`docs/quality/COST-ANALYSIS.md`](docs/quality/COST-ANALYSIS.md)),
then:

```bash
python3 -m pytest tests/ -q
claude plugin validate .claude-plugin/plugin.json
```

Reference docs: [`docs/stages/STAGES.md`](docs/stages/STAGES.md),
[`docs/naming/NAMING.md`](docs/naming/NAMING.md), [`CHANGELOG.md`](CHANGELOG.md),
and the shared rules under [`rules/`](rules).

## License

MIT
