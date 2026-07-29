---
name: plan
category: plan
description: 0-arg plan stage. Take 1-line idea → PRD.md + phases/<name>/{index.json, step<N>.md} in 5 gates. Quantified value (cost/LTV) + ambiguity loop (0-10) replace the old 5-question grill-me.
alpha: state
when_to_use: |
  - User types /dev-kit:plan with an idea
  - User wants PRD regenerated
  - Resume from .dev-kit/decision-log.md (HOLD after pause)
allowed-tools: Read Write Glob AskUserQuestion Skill
disallowed-tools: Bash Edit NotebookEdit WebFetch
model: opus
disable-model-invocation: true
user-invocable: true
safety:
  safety_valve: 8
  convergence: composite (ambiguity_score <= 3 AND value_score >= 3.0)
  narrowed_delta: bool
  dedup_metric: identical-ambiguity-cycle=2
  user_interrupt: true
---
> [← Skills index](../../README.md)

## Worktree precondition (REQUIRED — fail-closed)

Before answering Gate 1, verify the cwd is inside a worktree, not the main repo
checkout. `hooks/worktree-guard.sh` hard-blocks every `Write` from the main
checkout; if you proceed without checking, gate answers are captured but
`PRD.md` is never emitted and the failure surfaces only when `/dev-kit:build`
later fails on missing phase.

Detect via `Read` on `./.git`:

| Result | Meaning | Action |
|---|---|---|
| file content starts with `gitdir:` | inside a worktree | proceed to Gate 1 |
| `Read` fails because `./.git` is a directory | main checkout | **STOP**. Do NOT ask Gate 1. Tell the parent agent: "Worktree required. Per `rules/git-workflow.md`, every task = new worktree + client handoff + new branch. Run: `git fetch origin main && git worktree add -b <type>/<slug> .worktrees/<slug> origin/main` — Claude Code opens a new session in that path; Codex spawns/hand-offs a subagent with that path as cwd, then re-invokes `/dev-kit:plan`." |
| `Read` fails for any other reason (no repo, file missing) | outside any git repo | proceed (no worktree rule applies) |

This mirrors the discriminator in `hooks/lib/worktree-detect.sh`
(`--git-dir == --git-common-dir`) but uses `Read` instead of `Bash` because
plan's `disallowed-tools: Bash` blocks the shell form.

# /dev-kit:plan — Idea → PRD.md + phases (5 gates, 1 Ralph loop)

Self-contained. The earlier `plan-ralph` dispatch was absorbed (issue #58). No
sub-skill invocation; everything below runs inside this single skill invocation.

## Interview consume gate (REQUIRED unless `--skip-interview`)

Before Gate 1, consume the Phase 6 5-field safety contract from the
interview hand-off at `.dev-kit/hand-off/<step>.md`. Read it with the
`Read` tool (the LCS viewer was on `allowed-tools: ... Skill ...`
but the LCS substrate was dropped in #463; the contract now lives in
plain markdown that any consumer can read with `Read`).

Decision table (read `.dev-kit/hand-off/<step>.md` frontmatter):

| `status` (hand-off frontmatter) | Plan action |
|---|---|
| `ok` | Proceed to Gate 1; treat interview answers as canonical PRD §1 inputs. |
| `best-effort` | Proceed with a 1-line WARN to `.dev-kit/decision-log.md`; Gate 2 evidence-gate still applies. |
| `user-acknowledged` | Proceed; treat as `best-effort` for downstream gating. |
| `held` (or missing file / no `status` field) | **STOP.** Do NOT ask Gate 1. Tell the user: "Interview contract not clear. Per Phase 6 (issue #385), plan refuses to emit PRD while the interview hand-off is `held`. Run `/dev-kit:interview <plan-file>` first, then re-invoke `/dev-kit:plan`." |
| `--skip-interview` flag present | Skip the consume entirely (backward compat). Write a SKIPPED line to `.dev-kit/decision-log.md` so the audit trail is honest. |

Defence-in-depth: if the hand-off file is missing or frontmatter is
malformed, treat as `held`.

## Core goal

Planning artifacts only. No code, build, or deploy. Take a 1-line idea → run 5
gates in one Ralph loop → emit `PRD.md` + `phases/<name>/{index.json, step<N>.md}`
+ `.dev-kit/hand-off/plan→build.md`.

## Inputs / outputs

- **Input**: 1-line idea (from user prompt) + 1-5 AC + 1-3 non-goals.
- **Flag**: `--skip-interview` bypasses the interview consume gate
  below (Phase 6 backward compat).
- **Output**:
  - `PRD.md` — 6-section plan
  - `phases/<name>/index.json` — phase state machine (see "Phase JSON schema")
  - `phases/<name>/step<N>.md` — one per step (N=0..K-1)
  - `.dev-kit/decision-log.md` — accumulated Q&A + score deltas
  - `.dev-kit/loop-log.json` — narrowing per cycle (MUST-16)
  - `.dev-kit/hand-off/plan→build.md`
- **Cumulative**: every iteration appends to `decision-log.md` + `loop-log.json`.

## 5 gates (1 Ralph loop)

```
[1/5] frame        — goal + target user + 1-line situation
       ↓
[2/5] validate     — evidence (≥3 sources) + value_score + ambiguity loop
       ↓
[3/5] non-goals    — 3+ non-goals with rationale + breach-response
       ↓
[4/5] decompose    — phases/<name>/index.json + step<N>.md (per-step status)
       ↓
[5/5] emit         — PRD.md 6-section DoD pass + hand-off
```

The 8-gate structure (frame → evidence → diff → non-goals → socratic → phase-decompose → seed-convergence → prd-writer) was collapsed: G2 evidence, G3 diff-profit, and G5 socratic-deepen all probed "is this idea worth building?" with overlapping asks, and G7 seed-convergence was a numeric re-check of what G2 already asked for. The new G2 `validate` runs them once, with quantified inputs, in a single ambiguity loop.

## Gate 1/5 — frame

Ask the user (single message, in order):

| # | Field | Pass criterion |
|---|---|---|
| 1 | **goal** | one sentence: what we ship and what changes for the user |
| 2 | **target user** | one named persona (role + context) — not "everyone" |
| 3 | **situation** | one sentence: where the user is today, before this exists |

Accept whatever the user types. If any field is empty, ask once, then proceed
with `"<unspecified>"`. Write all 3 fields to `.dev-kit/decision-log.md` under
`# frame`. No exit code, no test count — this is input capture, not work.

## Gate 2/5 — validate (evidence + value + ambiguity loop)

This gate replaces the old "5-question grill-me" with a quantified loop. Three
numeric inputs feed one composite convergence test; the loop iterates only on
the dimension that is failing.

### 2.1 — Evidence (≥3 sources)

Ask once: "Cite 3 independent signals the target user actually wants this.
Independent = different origin (e.g. user interview, market data, analogue
product, prior failed attempt, paying-customer ask)."

Write each signal as `{source, claim, date}` to `decision-log.md`. If the user
gives <3, the gate fails. **No more "if vague, sharpen once"** — count, not
quality, gates this input.

### 2.2 — Value score (cost / LTV)

Compute, do not ask:

```
value_score = (LTV_per_user × reachable_users_year1) / total_cost
```

| Field | Source | Unit |
|---|---|---|
| `LTV_per_user` | user-declared (ask if missing) | $ or "value unit" |
| `reachable_users_year1` | user-declared or top-of-funnel estimate | integer |
| `total_cost` | sum of eng-hours × rate + infra $ + GTM | $ |

Write the 3 numbers + the formula result to `decision-log.md`. Threshold:
`value_score >= 3.0`. Below 3 → gate fails; tell the user the gap and the
single biggest lever to close it (cheaper, more reachable, or higher LTV — pick
one, do not enumerate).

### 2.3 — Ambiguity loop (0-10)

Compute, do not ask:

```
ambiguity_score_0 = 10
```

Each loop iteration asks **exactly one** question targeting the highest-leverage
unknown. After the answer, re-score:

| Knob | Question topic | Score impact |
|---|---|---|
| user | "Who is the first user, and what do they click/pay for first?" | -2 to -3 |
| pain | "What breaks for them today, and how often?" | -2 |
| scope | "What is the smallest version that pays for itself in 2 weeks?" | -2 |
| metric | "What single number moves if this works?" | -1 |
| kill | "What would make you kill it after launch?" | -1 |

The re-score is the model's call, but **must** be lower than the previous
iteration (narrowed_delta). If two iterations in a row produce the same score,
`dedup_metric: identical-ambiguity-cycle=2` fires → break out, mark "best
effort", and accept the current score.

### 2.4 — Convergence test

```
PASS  iff  evidence_count >= 3
        AND value_score >= 3.0
        AND ambiguity_score <= 3
```

On FAIL, loop on the failing dimension. Cap at `safety_valve=8` iterations.
On cap with no pass, write `"status": "held"` to `loop-log.json` and surface
the remaining gap to the user; do not auto-emit PRD.md.

### 2.5 — Decision-log entry

```markdown
# gate-2 cycle N
- evidence: N sources (need 3)
- LTV: $X × Y users = $Z / cost $W = value_score V.V
- ambiguity: 10 → 7 (asked: who is the first user)
- next: ask about X (next highest-leverage unknown)
```

## Gate 3/5 — non-goals

Ask once: "List 3 things this PRD will NOT do. For each, name a one-line
rationale and the breach-response (what we do if a reviewer asks us to add it)."

If the user gives <3, generate 3 candidates from `decision-log.md` context and
ask the user to confirm or replace. Write to `PRD.md` §3 (Non-goals).

## Gate 4/5 — decompose (phases JSON + step files)

Emit `phases/<name>/index.json` using the schema below. One step = one
shippable layer / module. Order: dependency-first (e.g. data model before API
before UI).

The top-level `worktree` field carries the branch base from which every per-step
worktree is derived (`<branch-base>-step<N>`). Emit it as `<prefix>-<phase>`,
where `<prefix>` follows the worktree-cut convention (typically `plan/<slug>`,
e.g. `plan/plugin-harness-v3`). The build runner reads it; if absent it falls
back to `feat/<phase>`, which is a defense-in-depth default, not the contract.

For each step in order:
1. Call `lib/execute.py:register_step(root, phase, step=N, name=<slug>)` —
   this creates the index.json entry with `status="unimplemented"`.
2. Write `phases/<name>/step<N>.md` using the **pinned template** below
   (`Status` / `Read first` / `Task` / `Acceptance Criteria` /
   `Verification & Status Update` / `Don't`). Plan only writes the
   `Status: pending` line; the runner and the executing sub-agent own
   the rest of the status lifecycle.
3. The runner transitions `unimplemented → pending` automatically when
   `step<N>.md` exists and the step number matches the index. If not,
   explicitly call `update_step_status(root, phase, step=N, status="pending")`.

### Phase JSON schema

```json
{
  "schema_version": "1.0.0",
  "phase": "0-mvp",
  "project": "<repo-name>",
  "created_at": "<iso8601>",
  "worktree": "<branch-base>",
  "ambiguity_score": 3,
  "value_score": 4.7,
  "evidence_count": 3,
  "steps": [
    {
      "step": 0,
      "name": "<kebab-slug>",
      "title": "<human title>",
      "status": "pending",
      "ambiguity_delta": 0.0
    }
  ]
}
```

### Per-step `status` (state machine)

SSOT: `lib/execute.py:VALID_STATUSES` (+ `SKIPPABLE_STATUSES`, `RESUMABLE_STATUSES`).
The plan skill only writes `unimplemented` (via `register_step`) and `pending`
(after writing `step<N>.md`). Runtime states (`in_progress`, `completed`,
`error`, `blocked`) are owned by the harness-runner; plan MUST NOT set them.
See the source constants for the current set + transition table.

### Step file template (pinned)

`phases/<name>/step<N>.md` MUST follow this template verbatim — section
order, headings, and the marker block in the `Verification & Status Update`
section are part of the **plan ↔ build SSOT** (the build runner's parser
reads the marker block; the agent reads the sections). Plan fills the
placeholder lines in `{curly braces}`; the runner and the executing
sub-agent fill the rest at runtime.

````markdown
# Step {N}: {title}

## Status
**pending** — last update: {iso8601 timestamp at plan-emit time}

## Read first
- `/PRD.md`
- `/docs/ARCHITECTURE.md` (if it exists in this project)
- `/docs/ADR.md` (if it exists in this project)
- `phases/{phase}/step{0..N-1}.md` (prior step files in this phase)
- {file paths created or modified by earlier steps in this phase}

## Task
{Signature-level instructions: file paths, function/class interfaces, logic
outline. Implementation is the sub-agent's call. Non-negotiable rules
(idempotency, security, data integrity, backward compat) MUST be written
explicitly — "be careful" is not enough.}

## Acceptance Criteria
```bash
{Executable verification commands. Each must exit 0 on success. Quote exit
codes in the AC reply, e.g. "AC1: npm test → exit 0 (47 passed)".}
```

## Verification & Status Update (REQUIRED before claiming done)
1. Run the AC commands above. Quote each exit code.
2. Update `phases/{phase}/index.json` for THIS step (one of three outcomes):
   - **Success** → `"status": "completed"`, `"summary": "<one-line: files created/modified + key decisions>"`
   - **Unrecoverable failure** (3 retries exhausted) → `"status": "error"`, `"error_message": "<concrete error: which AC failed, with exit code + last 3 lines>"`
   - **External dependency** (API key, manual config, human approval) → `"status": "blocked"`, `"blocked_reason": "<what's needed>"`, then STOP — do not continue to the next step.
3. Emit EXACTLY these two HTML-comment markers as the **last two lines** of
   the final reply. The build runner parses them with the regex in
   `lib/execute.py:parse_status_marker()`:

```
<!-- status: completed | error | blocked -->
<!-- summary: <one-line outcome> | error_message: <concrete error> | blocked_reason: <what's needed> -->
```

   The marker value MUST match the `status` field written to `index.json`
   in step 2. If the marker is missing or malformed, the runner falls back
   to the index.json status (so the contract is best-effort, not blocking).

## Don't
- {X를 하지 마라. 이유: Y — one prohibition per bullet, in this format}
- {Do not break existing tests; do not bypass tdd-guard; do not modify
  files outside the path scope declared in `## Read first`.}
````

### Marker contract (plan ↔ build SSOT)

The two-line HTML-comment block in the `Verification & Status Update`
section is the only place where the sub-agent's outcome reaches the
runner. It is pinned here so the build runner's parser has a stable
contract.

| Marker | Allowed values | Companion marker |
|---|---|---|
| `<!-- status: ... -->` | `completed` \| `error` \| `blocked` | second line carries the matching field |
| `<!-- summary: ... -->` | free text (one line) | required when `status: completed` |
| `<!-- error_message: ... -->` | free text (one line) | required when `status: error` |
| `<!-- blocked_reason: ... -->` | free text (one line) | required when `status: blocked` |

**Rules:**

- The two markers MUST be the last two lines of the sub-agent's final
  reply. The runner scans the tail of stdout with a regex.
- The `status:` marker value MUST match the field written to
  `phases/{phase>/index.json` for that step. If they disagree, the
  runner trusts the index.json (the marker is a hint, not a hard
  contract).
- If the marker is missing, the runner falls back to the exit code:
  `exit 0` → `completed`, non-zero → `error` with
  `error_message = f"claude exited {rc}"`. The `summary` field is left
  empty in this fallback.
- Parsing happens in `lib/execute.py` (added in the follow-up
  `feat(execute): live spinner + summary carry-forward` PR). This
  template pin defines the contract; the build PR implements the
  parser.

## Gate 5/5 — emit

Write `PRD.md` with the 6 sections below. DoD 5 conditions (all required):

1. §1 Frame includes the 3 fields from Gate 1 verbatim.
2. §2 Validate shows `value_score >= 3.0` and `ambiguity_score <= 3` (or
   `status: held` if cap was hit — in which case, stop and ask the user).
3. §3 Non-goals has ≥3 entries each with rationale + breach-response.
4. §4 Phase plan points at `phases/<name>/index.json` and lists every step
   title.
5. §5 AC list (1-5 items) maps 1:1 to step AC commands in `phases/<name>/step<N>.md`.
6. §6 Hand-off names `/dev-kit:build` as the next invocation.

Then:
- Append final cycle to `.dev-kit/loop-log.json` (MUST-16).
- Write `.dev-kit/hand-off/plan→build.md` summarizing the plan for the build
  stage.
- **Auto-render the design proposal** (see "Proposal auto-invoke" below) —
  the final cleanup step of Gate 5/5 is to materialize the proposal HTML
  the reviewer will see before `/dev-kit:build` is invoked.

## Proposal auto-invoke (Gate 5/5 final step)

Gate 5/5 ends with a single, deterministic handoff to the
`/dev-kit:proposal` skill so the design record is auto-rendered at
`docs/proposals/<main>/<sub>.html`. The chain becomes
**plan → proposal → build**; the user no longer has to remember to run
`/dev-kit:proposal` manually.

### Slug derivation

The proposal topic is `<main>/<sub>`:

- `<main>` = the umbrella. For this project the umbrella is hardcoded
  to the design-domain name (a future PR can externalize it to a
  project-level config if a different umbrella is needed). The
  `harness-architecture` umbrella was removed in #463 along with its
  proposal bundle; the umbrella currently resolves to a per-PR topic.
- `<sub>` = the phase directory name (the `<name>` in `phases/<name>/`
  emitted in Gate 4/5). One source of truth — same name as the
  phase directory, same name as the proposal sub-topic, same name
  as the worktree branch base's `<phase>` segment.

If the phase name violates the proposal-slug regex
(`^[A-Za-z0-9][A-Za-z0-9_-]{0,63}/[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`),
the proposal skill will reject the render and Gate 5/5 surfaces the
slug error in the hand-off — the user is asked to rename the phase,
not the proposal.

### YAML emission

Write `docs/proposals/<main>/<sub>.yaml` with the canonical
shape (see `skills/proposal/SKILL.md` "Authoring a proposal"). Each
PRD § becomes one proposal `section` (title = PRD heading, body = PRD
section text, reduced to the markdown-lite subset the proposal
renderer understands). Frontmatter:

- `title`: PRD §1 goal (1-line, from Gate 1 `goal`).
- `status`: `design-discussion` (plan just finished, review not yet
  started).
- `issue`: the issue number from the plan context if known; omit
  otherwise.
- `date`: today's date in KST.
- `tags`: `[<phase-name>]` plus any tag the user supplied in Gate 1.

Do NOT edit or move existing proposal files; the auto-emit only
writes `<main>/<sub>.yaml` for the current phase's sub-topic.
If the sub-topic already exists with a different content, the
proposal skill must refuse to overwrite (it has no overwrite flag)
and Gate 5/5 surfaces the conflict for the user to resolve.

### Render invocation

Call the proposal skill with the topic slug:

```text
Skill("proposal", topic="<main>/<sub>")
```

The proposal skill reads `<main>/<sub>.yaml` and writes
`<main>/<sub>.html` via
`python3 -m lib.render_proposal_html <main>/<sub>`. The plan skill's
`disallowed-tools: Bash` deliberately does not block this — `Skill`
is its own tool and the proposal skill internally has Bash
permission.

### Hand-off chain

On success, the chain emitted in
`.dev-kit/hand-off/plan→build.md` becomes:

1. `plan` (this skill) — `PRD.md` + `phases/<name>/`
2. `proposal` (auto-invoked) — `docs/proposals/<main>/<sub>.html`
3. `build` (user-invoked next) — implementation

`§6 Hand-off` in PRD.md must list `/dev-kit:proposal <main>/<sub>` as
the "review artifact" link in addition to `/dev-kit:build` as the
next stage. This makes the proposal visible from the PRD itself, not
only from the skill chain.

## Rules (no exceptions)

- 5-field loop declared (MUST-15): `safety_valve=8`, composite convergence,
  `narrowed_delta`, `dedup_metric`, `user_interrupt`.
- **Interview consume gate (Phase 6)**: plan MUST read
  `.dev-kit/hand-off/<step>.md` frontmatter via `Read` before Gate 1.
  `status: held` → refuse to plan; `ok | best-effort | user-acknowledged`
  → proceed. The `--skip-interview` flag bypasses the gate for backward
  compat only and MUST be logged to `.dev-kit/decision-log.md`.
- No artifacts other than PRD.md, phases/<name>/, .dev-kit/decision-log.md, .dev-kit/hand-off/.
- No code, no `package.json`, no `Dockerfile`, no test code.
- "Just write the code" before PRD.md is complete → still no code.
- After HOLD, user re-invokes `/dev-kit:plan` to resume from
  `.dev-kit/decision-log.md`.
- `loop-log.json` appends narrowing per cycle (MUST-16).

## Hook alignment

Plan stage:
- `slop-detector=OFF` (planning docs tolerate LLM-typical phrasing)
- `stop-verify=ON`
- Others OFF

## Hand-off

On PRD.md complete:
- `state_codec.transition_stage(root, "build")`
- `state_codec.append_hand_off(root, "plan", "build", "...")` auto
- Write `.dev-kit/hand-off/plan→build.md`
- **Auto-invoke `/dev-kit:proposal <main>/<sub>`** (see "Proposal
  auto-invoke") to materialize the design record at
  `docs/proposals/<main>/<sub>.html`.
- Wait for `/dev-kit:build` invocation

## Next step

`/dev-kit:build` — converts `phases/<name>/step<N>.md` into per-step
implementation via harness-runner. The design record is at
`docs/proposals/<main>/<sub>.html` (auto-rendered by Gate 5/5's
proposal step), so reviewers can read the proposal before the build
starts.
