# dev-harness-kit — Documentation Home

> A read-only live state server for any repo that runs Claude Code or Codex.

A unified harness plugin for shipping — Plan, Build, Review, Ship with typed
sub-agent delegation, an Eval-Repair loop, and Human-on-the-Loop supervision.
The Live Context Server (LCS) sits underneath everything else: one `lcs://`
namespace that every hook, agent, and operator consults instead of
re-implementing `git` / `gh` parsing on their own.

---

## TL;DR — What is the Live Context Server (LCS)?

**LCS = one small Python program + one URI namespace.**

The Live Context Server (LCS) is a read-only URI router that lives inside the
dev-harness-kit plugin. You run
`python3 bin/dev-kit-lcs.py --get 'lcs://<resource>'` and you get back a typed
JSON envelope with the live state you asked for — current branch HEAD,
worktree list, PR status, token spend, valuation verdict, session info. Every
consumer in the harness (hooks, agents, the chat surface, MCP clients) talks
to *the same* LCS instead of each one re-implementing the `git` / `gh`
parsing on its own.

| Property | Value |
|---|---|
| **What it is** | A Python CLI + stdio JSON-RPC server |
| **Namespace** | `lcs://<resource>` |
| **Read-only** | never writes; errors are wrapped, not raised |
| **6 default resources** | `branches`, `pr`, `sessions`, `spend`, `valuations`, `worktrees` |
| **5-second cache** | concurrent reads on the same URI share one subprocess |
| **MCP-wire compatible** | any MCP client can attach via `--serve` |

Everything below explains *why LCS was needed*, *how to use it in 60 seconds*,
*what you get out of it*, and *where every other doc lives*.

---

## 1. Why this system exists, and why it has to exist

> **Start here if you have never seen dev-harness-kit before.**

### The pain (before LCS)

Eight different files in `hooks/` and `lib/` each needed the same piece of
live state: "what is the current branch slot version?" or "is PR #447 green?"
Each one shell-out to `git` or `gh`, parsed the JSON inline, wrapped errors
in its own shape, and re-implemented caching — or skipped it entirely. When
`gh` was missing, one hook crashed, another silently fell back, and a third
lied about its answer. Hot loops re-spawned `gh` 60 times in a single
babysit session.

The harness had drifted. Each consumer re-implemented the same parse logic,
in subtly different shapes, tested in isolation or not at all. Drift was
inevitable: a new field in `gh pr view` would break three hooks on a
different day each.

LCS is the answer: one in-process URI router with a typed envelope
(`{status, data, missing?, error?}`), a per-URI 5-second snapshot cache,
read-only by enforcement, and MCP-wire-compatible. Hooks and agents ask
`lcs://branches/main` and get back the same JSON shape every time — with
errors wrapped, not raised.

**Why it has to exist**: in a multi-runtime harness (Claude Code + Codex),
every consumer that re-implements state-reading creates a cross-runtime
failure surface. LCS collapses that surface to one Python module that every
consumer shares.

---

## 2. 60-second quickstart

> **If you only run three commands today, run these.**

You do not need to understand LCS to use dev-harness-kit. The first three
commands below produce a runnable demo in under a minute.

### Step 1 — see what resources the Live Context Server exposes

```bash
$ python3 bin/dev-kit-lcs.py --list-resources
  branches                          lcs_resources.branches.BranchesResource
  pr                                lcs_resources.pr.PRResource
  sessions                          lcs_resources.sessions.SessionsResource
  spend                             lcs_resources.spend.SpendResource
  valuations                        lcs_resources.valuations.ValuationsResource
  worktrees                         lcs_resources.worktrees.WorktreesResource
```

### Step 2 — ask for live state on a single URI

```bash
$ python3 bin/dev-kit-lcs.py --get 'lcs://branches/main'
{
  "status": "ok",
  "data": {
    "name":         "main",
    "local_head":   "6bd1073bbef4b50d477aaabedfbafc4511a8d459",
    "origin_head":  "6bd1073bbef4b50d477aaabedfbafc4511a8d459",
    "ahead":        0,
    "behind":       0,
    "last_ci_run":  { "conclusion": "success", "name": "CI", "status": "completed" },
    "slot_version": "0.3.147"
  }
}
```

### Step 3 — explore the full URI grammar & integration map

```bash
$ open docs/lcs-usage.html   # full HTML reference (English)
$ open docs/lcs-usage.ko.html # 동일한 문서 (한국어)
```

That is the entire LCS surface. Anything more specific is in the docs.

---

## 3. What value you actually get

> **Concrete numbers, not promises.**

| Metric | Value | Detail |
|---|---|---|
| Files consolidated | **8 → 1** | 8 readers re-implemented. 1 router now serves them all. |
| Call sites on `lcs://` | **60** | hooks, agents, and engines already read from the namespace. |
| Test LoC | **3,094** | across 10 test files — one canonical surface to maintain. |
| Return shapes | **1** | `{status, data, missing?, error?}` for every read. |

### Before vs. after

| What was duplicated | Before LCS | After LCS |
|---|---|---|
| Files that shell out to `git` / `gh` and parse JSON inline | **8** hooks/scripts, each with its own parser | **0** — only `lib/lcs_resources/*.py` touches subprocesses |
| Subprocess spawns per babysit-PR session | ~60 (3 per PR-state query × 20 queries) | ~5 (5s snapshot cache coalesces) |
| Different return shapes for "live state" | 8 (one per consumer) | 1 envelope |
| MCP-compatible introspection endpoint | none | `bin/dev-kit-lcs.py --serve` (JSON-RPC over stdio) |

### Three concrete wins

1. **Slot-bump drift detection.** `hooks/git-guard.sh` checks whether your
   `plugin.json` bump matches `origin/main` before a push. Pre-LCS: shell out,
   parse porcelain, regex the version. Post-LCS: one line reading
   `lcs://branches/main.data.slot_version`. Same answer, one source of truth,
   no drift.

2. **Build no-go gate transparency.** Phase 4 needs the `valuate` verdict to
   halt-or-proceed. Pre-LCS: the gate parses `.dev-kit/valuations/*.json`
   itself with no validation contract. Post-LCS:
   `lcs://valuations/<plan-id>` returns a typed envelope; missing becomes
   `status="partial"` → fail-closed. The fail-closed behavior is enforced by
   the handler, not by every consumer re-implementing it.

3. **Cost in babysit-PR hot loops.** Pre-LCS: 60 subprocess spawns per session
   to ask "is PR #447 green yet?" Post-LCS: 5–6 reads on a 5-second snapshot
   cache. The cache coalesces concurrent reads; the bash-guard `slot_version`
   and the chat `lcs` skill can both ask the same URI in the same instant
   and pay for one subprocess, not two.

---

## 4. Documentation map

> Pick what fits your role. Read top-to-bottom for newcomers.

> **New here?** Read the **Newcomer path** below first — it walks you through
> the four pages that matter before everything else makes sense. Everyone
> else: jump to the category that matches your role.

### Newcomer path (read in order)

- **00 — Documentation Home** (this file)
  > Why the system exists, what LCS does, three concrete value wins, and a
  > categorized index of every other doc.
- [`../README.md`](../README.md) — repo `dev-harness-kit`
  > Repo-level overview: install, the Plan/Build/Review/Ship loop, command
  > reference, and the full skill surface.
- [LCS — Live Context Server usage reference](lcs-usage.md) / [한국어](lcs-usage.ko.md)
  > The LCS reference you just touched via `--list-resources` — URI grammar,
  > every resource's contract, CLI surface, JSON-RPC wire format, integration
  > map.
- [STAGES — per-stage harness spec](STAGES.md)
  > What happens in each stage of the loop (bootstrap → plan → build →
  > review → ship), and which skill owns which step.

### LCS & Live Context Server

- [lcs-usage.md](lcs-usage.md) (English) · [lcs-usage.ko.md](lcs-usage.ko.md) (한국어)
  > Full URI grammar, every resource handler, CLI surface, exit codes,
  > JSON-RPC wire format, integration map, README drift notes, and a
  > verification log of every command quoted in the doc.

### Design proposals — the harness architecture

> 13 topic files (Korean-bodied) covering the multi-harness proposal behind
> the plugin. Most are 200–375 lines and read topically — pick one by
> question.

- [proposals/harness-architecture/00-index.html](proposals/harness-architecture/00-index.html)
  > **00 — Multi-Harness System Issue Index** — Read this first inside the
  > proposal folder — it lists the four risk layers, the build principles
  > (L7 alignment), and reading paths for 20-min / 60-min / topic-specific
  > entry.
- [01 — MCP: Model Context Protocol (wire-protocol layer)](proposals/harness-architecture/protocol-layer.html)
  > Why we use MCP instead of building one: the public standard we ride,
  > primitives, lifecycle, and the runtime-neutrality implication.
- [02 — LCS: Live Context Server (state reader)](proposals/harness-architecture/live-context-server.html)
  > The proposal behind the server core. URI grammar, longest-match
  > resolution, snapshot cache, and how handlers turn a write-free read
  > into MCP-wire shape.
- [03 — Interview Harness (ambiguity resolver)](proposals/harness-architecture/ambiguity-resolver.html)
  > How a plan's open questions are closed before code is written.
- [04 — Evaluation Harness (quality judging)](proposals/harness-architecture/quality-judge.html)
  > Multi-axis AI-output scoring with a 20-checkbox code-sanity rubric.
- [05 — Plan-value gate (valuate)](proposals/harness-architecture/value-gate.html)
  > The verdict envelope behind `lcs://valuations/<plan-id>`: proceed /
  > revise / hold / kill, blocking findings, scores.
- [06 — Research Harness (Phase 0–3 escalation)](proposals/harness-architecture/external-verifier.html)
  > Cache → direct → multi-source → human fallback. The research gate that
  > backs `lcs://research/cache`.
- [07 — Runtime neutrality (Decision 8)](proposals/harness-architecture/runtime-portability.html)
  > How Claude Code + Codex get identical behavior from one plugin — the
  > adapter layer.
- [08 — External references (insane-search / hermes / AEGIS)](proposals/harness-architecture/external-references.html)
  > What we borrowed, what we deliberately rejected from the surrounding
  > literature.
- [09 — Consolidated architecture (6 harnesses + adapters + gates)](proposals/harness-architecture/consolidated-architecture.html)
  > The big picture — how the harnesses and the adapter layer mesh. Read this
  > after 02 / 04 / 06.
- [10 — Decision record (the 8 locks)](proposals/harness-architecture/decision-record.html)
  > The eight decisions that are locked and why; what each constraint blocks.
- [11 — Migration phases (Phase 0–7)](proposals/harness-architecture/migration-phases.html)
  > Which PRs ship in which order; the build sequence behind the release
  > tags.
- [12 — Open questions (issue #280 thread)](proposals/harness-architecture/open-questions.html)
  > Decisions still requiring consensus — the loaded questions the
  > maintainers want feedback on.

### How-tos & runbooks (Markdown)

- [ci-setup.md — Install Dev-Kit's CI Templates](ci-setup.md)
  > Stand up the dev-kit CI shape (branch-policy + validate + test +
  > auto-fix) in any consumer repo.
- [maintenance-gate.md — over-engineering + clean-code + value gate](maintenance-gate.md)
  > The 20-checkbox PR-only gate (`.github/workflows/maintenance.yml`). What
  > each checkbox blocks; how to score.
- [RUNTIME-PORTABILITY.md — Claude Code ↔ Codex adapter rules](RUNTIME-PORTABILITY.md)
  > The contract both runtimes must honor for `plugin.json` + `hooks.json` to
  > mean the same thing on either side.
- [STAGES.md — per-stage harness spec](STAGES.md)
  > What each stage owns: bootstrap, plan, design, build, review, security,
  > ship.
- [COST-ANALYSIS.md](COST-ANALYSIS.md)
  > Per-bucket token spend, hard ceilings, and the cost-gate trailer format
  > that lint requires.
- [team-adoption.md](team-adoption.md)
  > Why a single maintainer and a 20-person team adopt the harness
  > differently.
- [NAMING.md — naming convention (ADR-0010 SSOT)](NAMING.md)
  > Why a hook is named `bash-guard.sh` not `bashHook.sh`; the source of
  > truth for skill/hook labels.
- [PRE-IMPL-CHECK.md](PRE-IMPL-CHECK.md)
  > The 9-question checklist to answer before writing code.
- [ACP-DISPATCH.md — M-tier architecture](ACP-DISPATCH.md)
  > How Model-tier agents find and dispatch to Capability-tier skills.
- [acp-harness.md — Agent Coordination Protocol](acp-harness.md)
  > The wire-format ACP uses to talk between agents; how it differs from
  > LCS.
- [hook-coverage-gaps.md — P4 Bucket B audit](hook-coverage-gaps.md)
  > Which hook events are wired vs. which aren't, per runtime.
- [PROPOSAL-IMPLEMENTATION-PLAN.md — Issue #280](PROPOSAL-IMPLEMENTATION-PLAN.md)
  > The high-level plan behind the 13 proposal files. Useful if you only
  > have time for one mega-doc.
- [REPOSITORY-MAP.md](REPOSITORY-MAP.md)
  > Where each component lives in the tree. Use this when grep doesn't
  > surface an answer.

### Architecture Decision Records

- [ADR-0001 — 5 → 1 absorption](adr/ADR-0001-five-to-one-absorption.md)
- [ADR-0010 — Naming Convention (SSOT)](adr/ADR-0010-naming-convention.md) (companion to `NAMING.md`)
- [ADR-0020 — Methodology Extensibility (TDD/SDD/DDD/BDD/FDD)](adr/ADR-0020-methodology-extensibility.md)
- [ADR-0021 — Eval-Repair Loop with Human Review](adr/ADR-0021-eval-repair-loop.md)
- [ADR-0022 — Refactor eval from asset freshness to agent behavior](adr/ADR-0022-eval-agent-behavior.md)

### Skill reference

- [skills/README.md](skills/README.md)
  > Browse all 35 skills by category (audit / ship / bootstrap / build /
  > docs / harness / integration / lifecycle / quality / research / runtime /
  > skill-mgmt / state). Click into any skill's `SKILL.md` for the full
  > spec.

---

## 5. Reading paths by role

> Pick the path that matches what you came here to do.

### Newcomer — I just discovered dev-harness-kit

1. [`../README.md`](../README.md) — quick start + tier table
2. **This page** (`docs/00-index.md`) — the why + value
3. [LCS reference](lcs-usage.md)
4. [STAGES](STAGES.md) — what each stage owns
5. Run `/dev-kit:bootstrap-full` in your repo

### Integrator — I'm wiring this into another repo

1. [Runtime Portability](RUNTIME-PORTABILITY.md)
2. [CI Setup](ci-setup.md)
3. [LCS proposal](proposals/harness-architecture/live-context-server.html)
4. [Hook coverage gaps](hook-coverage-gaps.md)

### Contributor — I want to add a skill / change the harness

1. [Decision record](proposals/harness-architecture/decision-record.html)
2. [ADR-0001](adr/ADR-0001-five-to-one-absorption.md) through ADR-0022
3. [Migration phases](proposals/harness-architecture/migration-phases.html)
4. [Open questions](proposals/harness-architecture/open-questions.html)

### Reviewer — I'm reading a PR and need to know what's locked

1. [Decision record](proposals/harness-architecture/decision-record.html)
2. [Open questions](proposals/harness-architecture/open-questions.html)
3. [Maintenance gate](maintenance-gate.md)
4. [Naming convention](NAMING.md)

---

## 6. Glossary

| Term | Definition |
|---|---|
| **LCS** | Live Context Server — the read-only URI router under `lcs://` that every hook/agent/operator reads. |
| **Handler** | One Python class implementing the `Resource` protocol in `lib/lcs_resources/<name>.py`. Each exposes a single named URI. |
| **URI envelope** | The `{status, data, missing?, error?}` dict every LCS read returns. |
| **Snapshot cache** | Per-URI 5-second TTL. Concurrent reads on the same URI within the window coalesce to one subprocess. |
| **MCP** | Model Context Protocol — the public wire standard LCS speaks in `--serve` mode. |
| **Stage** | One of bootstrap / plan / design / build / review / security / ship — see `STAGES.md`. |
| **Skill** | A slash command + SKILL.md bundle under `skills/<name>`. Browse all 35 at `skills/README.md`. |
| **Hook** | A bash script under `hooks/` fired by Claude Code or Codex at lifecycle events. |
| **ADR** | Architecture Decision Record — a locked decision under `docs/adr/`. |
| **Worktree** | A git worktree checked out for one task (one branch per worktree). The harness-enforced pattern. |

---

Authored at `docs/00-index.md` in worktree `.worktrees/lcs-usage-html`, off
`origin/main @ 6bd1073`. Korean version: [`docs/00-index.ko.md`](00-index.ko.md).
HTML version: [`docs/00-index.html`](00-index.html). Back to [`../README.md`](../README.md).
