---
name: plan-ralph
category: plan
description: PM/기획 전 과정을 단일 Ralph 루프로. 아이디어 → PRD.md까지. 6 gates (frame → evidence → diff → non-goals → socratic → prd-writer) + Seed convergence. Socratic gate is the grill-me interview — sharpen the plan by questioning the user. PRD.md 외 다른 산출물 절대 ❌.
when_to_use: |
  - User types /dev-kit:plan with an idea
  - User wants PRD regenerated
  - Resume from .pm-prd-fast/decision-log.md (HOLD after pause)
allowed-tools: Read Write Glob AskUserQuestion
disallowed-tools: Bash Edit NotebookEdit WebFetch
model: opus
disable-model-invocation: false
safety:
  safety_valve: 8
  convergence: composite (rubric ≥ 75 + final_similarity ≥ 0.85 + DoD 5 conditions)
  narrowed_delta: bool
  dedup_metric: identical-answer-cycle=2
  user_interrupt: true
user-invocable: false
---

# plan-ralph — Integrated PM (Plan+Design merged, MUST-50)

## Core Goal
**Only planning artifacts.** No code, build, or deploy. Take user goal + AC + non-goals → run 6 gates + Seed convergence in a single Ralph loop → emit `PRD.md` + `phases/<name>/step<N>.md`.

## Inputs / Outputs

- **Input**: user 1-line idea + AC (1–5) + non-goals (1–3)
- **Output**: `PRD.md` + `.pm-prd-fast/*.md` + `phases/<name>/{index.json, step<N>.md}` + `.dev-kit/hand-off/plan→build.md`
- **Cumulative**: `.pm-prd-fast/decision-log.md` + `.dev-kit/loop-log.json`

## 6 integrated gates (1 Ralph loop)

```
[1/8] frame-problem       — idea + customer + situation + cause + cost
       ↓
[2/8] evidence-gate      — rubric ≥ 75 OR 3+ independent sources
       ↓
[3/8] diff-profit-gate   — 3 alternatives + customer-language differentiation + positive unit margin
       ↓
[4/8] non-goals          — 3+ non-goals with rationale + breach-response
       ↓
[5/8] socratic-deepen    — GRILL-ME interview (5 questions, ≥3 must pass)
       ↓
[6/8] phase-decompose    — phases/<name>/index.json auto (MUST-50 absorption)
       ↓
[7/8] seed-convergence   — interview-harness: similarity ≥ 0.85
       ↓
[8/8] prd-writer         — PRD.md 6-section DoD 5 conditions
```

## Gate 5/8 — Socratic deepen (grill-me interview)

This is the **grill-me** phase. Ask the user **5 questions in order**, one per round. The user must answer at least 3. If a round answer is too vague, sharpen once, then accept whatever the user says.

| # | Question | Pass criterion |
|---|---|---|
| 1 | "What specifically breaks if you ship nothing in the next 2 weeks?" | names a concrete failure mode (not "we'd be sad") |
| 2 | "Who is the *first* user, and what's the smallest thing they'd pay or click for?" | names a real person/role and a specific action |
| 3 | "What's the cheapest experiment that would invalidate the bet in 1 week?" | answer is testable by ≤5 people with ≤1 day of work |
| 4 | "What did you try before that didn't work, and what did you learn?" | names a real prior attempt + a non-tautological lesson |
| 5 | "If this works, what's the *next* thing you build, and why?" | identifies a downstream dependency or follow-on |

For each round, use `AskUserQuestion` to ask. Record the answer in `.pm-prd-fast/decision-log.md`. If the user gives the same answer to the same question in 2 consecutive rounds, mark that round as "best effort" and move on (don't loop).

After all 5 rounds (or 3 passes), write the **Socratic section** in PRD.md:

```markdown
## Socratic interview summary
- Q1 [PASS/FAIL]: <question> — <answer>
- Q2 [PASS/FAIL]: <question> — <answer>
- ...
- Passes: 3/5 (≥3 required)
```

## Rules (no exceptions)

- 5-field loop declared (MUST-15): safety_valve=8, convergence composite, narrowed_delta, dedup_metric, user_interrupt
- No artifacts other than PRD.md (no code, package.json, Dockerfile, test code)
- User requesting "just write the code" before PRD is complete → still no code
- After HOLD, user re-invokes `/dev-kit:plan` to resume
- `loop-log.json` appends narrowing per cycle (MUST-16)

## Hook alignment

Plan/Design stage:
- `slop-detector=OFF` (planning docs tolerate LLM-typical phrasing)
- `stop-verify=ON`
- Others OFF

## Hand-off

On PRD.md complete:
- `state_codec.transition_stage(root, "build")`
- `state_codec.append_hand_off(root, "plan", "build", "...")` auto
- Write `.dev-kit/hand-off/plan→build.md`
- Wait for `/dev-kit:build` invocation
