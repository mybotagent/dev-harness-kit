> [← Skills index](README.md) · [Project README](../../README.md)

# `research-proposal-plan`

**Category:** `plan` · **Alpha:** `state` · **Invocation:** `/dev-kit:research-proposal-plan <idea>` (human-invoked)

`research-proposal-plan` is the self-contained 3-phase binder (research → proposal → plan). It exists because `/dev-kit:plan` auto-renders the proposal HTML AFTER phase decomposition, which means a human rejection throws away the per-step JSON + step files. This binder inverts the order: research + proposal HTML render first, the human approves (or iterates) at the gate, and only then does `/dev-kit:plan` decompose + emit. The build phase is OUT of the binder; after `/dev-kit:plan` finishes, the operator invokes `/dev-kit:build` directly.

## When to use it

- The user types `/dev-kit:research-proposal-plan <idea>`.
- The task spans more than 1 session (multi-day work) OR touches more than 3 files in its blast radius (composed trigger wired into `/dev-kit:build`).
- The operator wants the approval gate to sit BEFORE phase decomposition, not after.
- The user explicitly wants the non-skippable 3-phase pipeline (research → proposal → plan) bound to one slash.

## How it works

The binder runs three mandatory phases. Phase 1 + Phase 2 run autonomously; Phase 3 is a hand-off to the human reviewer.

1. **Phase 1 — Research.** Invokes `Skill("research", ...)` then writes `.dev-kit/hand-off/<session>/research.md` from `templates/research.md`. The research engine runs the Phase 0-3 escalation (cache / direct / multi / human) and `enforce_citations()`. Every claim in the Conclusion section must cite `url` + `fetched_at` + `source_type`, OR be flagged `[UNCITED]`. The gate to advance is `annotated = enforce_citations(conclusion)` and `[UNCITED] not in annotated` (the function returns annotated text, not a count). The phase refuses to write any source file under `src/`, `lib/`, `tests/`, `hooks/`, `skills/<other>/`, `commands/`, `tools/`.
2. **Phase 2 — Proposal.** Authors `docs/proposals/<main>/<sub>.yaml` from `templates/proposal.md` (sections derived from PRD gates 1-3: frame / validate / non-goals), then invokes `Skill("proposal", topic="<main>/<sub>")` to render the HTML. The YAML's `status:` is always `ready-for-review`; the human reviewer is the only entity that may flip it to `accepted`. The proposal skill applies defensive HTML escaping on every interpolated value (its L7 contract). Gate to advance: YAML exists, HTML exists, `status:` ∈ {`ready-for-review`, `accepted`}.
3. **Phase 3 — Plan hand-off.** The binder writes `.dev-kit/hand-off/rpp→plan.md` with the proposal path, the YAML status field, and the explicit instruction to (a) review the HTML, (b) flip `status: accepted` in the YAML, then (c) invoke `/dev-kit:plan <phase>`. The plan skill is `disable-model-invocation: true`; the binder cannot `Skill("plan", ...)` and the human re-invocation is the gate, not a workaround.

### Composition with `/dev-kit:build`

`/dev-kit:build` invokes this binder when ANY of:

- Task spans more than 1 session (multi-day work).
- Task touches more than 3 files in its blast radius.
- User explicitly typed `/dev-kit:research-proposal-plan`.

Otherwise `/dev-kit:build` runs the direct `plan → build` path. This is the "composed trigger" — both skills wire the same threshold so the binder fires consistently regardless of entry point. See `skills/build/SKILL.md` §"Composition with /dev-kit:research-proposal-plan" for the trigger wiring.

### Why the plan hand-off is a hand-off, not a sub-skill call

`skills/plan/SKILL.md:13` declares `disable-model-invocation: true`. That flag is the gate — a model that tries to drive plan from inside another skill would be bypassing the human review surface the plan skill was designed to expose. The binder respects that invariant; the human re-invocation is the gate.

### Why build is OUT

The previous binder (`research-plan-build`) bundled build into the same slash, which compressed the approval gate to zero. Build is a different tool class (Edit / Bash) and a different review surface (per-step PRs); it lives in its own slash. After `/dev-kit:plan` emits `PRD.md` + `phases/<name>/`, the operator invokes `/dev-kit:build` directly.

## Usage

```bash
/dev-kit:research-proposal-plan <idea> [--scope "<scope>"]
```

| Argument | Effect |
|---|---|
| `<idea>` | 1-line topic, mirrors `/dev-kit:plan`'s input. |
| `--scope "<scope>"` | Optional. Files / modules / behavior in scope. Mirrors the research.md `scope:` field. |

## Related

- [`research`](research.md) — Phase 0-3 escalation engine invoked by Phase 1.
- [`proposal`](proposal.md) — YAML→HTML renderer invoked by Phase 2.
- [`plan`](plan.md) — Phase 3 hand-off target. The plan skill's Gate 5/5 auto-render collision is the signal that this binder already produced the HTML.
- [`build`](build.md) — Post-hand-off executor, NOT a binder phase.
- `templates/research.md` — Phase 1 emit shape.
- `templates/proposal.md` — Phase 2 authoring checklist.
- `docs/proposals/<main>/<sub>.html` — Human review artifact.
