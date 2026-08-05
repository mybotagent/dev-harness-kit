---
name: learn
category: audit
alpha: state
description: Distill source text into a new SKILL.md with approval gate.
when_to_use:
  - User types /dev-kit:learn <free text>
  - User wants to convert a transcript/file/URL/observation into a new reusable skill
allowed-tools: Read Write Glob Grep WebFetch Bash AskUserQuestion
disallowed-tools: Edit Agent
model: sonnet
user-invocable: true
---
> [← Skills index](../../README.md)

# /dev-kit:learn — distill source text into a new SKILL.md

Turns free-text input (file path, URL, prose, or the just-finished
session transcript) into a candidate `skills/<name>/SKILL.md`. Each
candidate is gated by 5 deterministic checks (G1-G5) and one
`AskUserQuestion` per surviving candidate before any write. Mirrors
the `prune-propose` and `ci-triage` 3-step state machine; does NOT
edit existing files and does NOT delegate to sub-agents.

**Tmux classification**: pure-prose change. No hooks, no subagent
dispatch, no persistent loops, no MCP server. Tmux-safe by definition.

## Workflow

```
[1/3] GATHER  -> parse arg (path|url|prose|session) -> load source into context
       | quoted: source-locator + char count + line range
       v
[2/3] DISTILL -> propose candidate name + description + 7-section body
       | quoted: candidate set + validation-gate results (PASS/FAIL per gate)
       v
[3/3] APPROVE -> AskUserQuestion per candidate -> Write SKILL.md to skills/<name>/
       | quoted: approved set + written paths + git diff --stat
```

## Step 1 — gather

Parse the trailing argument and load the source.

- `empty`  → if a current session transcript is reachable at
  `logs/claude-code/<branch>/<sid>.jsonl`, scan the last 8 assistant
  turns. Otherwise `AskUserQuestion` for clarification.
- `path`   → `Read` the file; quote `wc -l` and first 20 lines.
- `URL`    → `WebFetch`; quote the resolved title + char count.
- `prose`  → echo verbatim into context; quote any trailing
  requirement phrase (e.g. "focus on auth, skip deprecated") —
  these are load-bearing authoring constraints, not incidental.

Quoted output per shape: source-locator, char count, optional
line range. If `WebFetch` is unavailable (Codex sandbox), exit with
a clear error before any distill.

## Step 2 — distill

Propose 1-3 candidate SKILL.md bodies. Each candidate runs through
G1-G4 (see next section); any FAIL blocks the write. The model may
vary the prose, candidate name (subject to G4), and candidate count
(1-3). The deterministic gates cannot be relaxed by the model.

For each candidate, record:

- proposed `name` (kebab-case)
- proposed `description` (one sentence, period-end)
- the full 7-section body
- G1-G4 verdict (PASS / FAIL with violation messages)

## Step 3 — approve

One `AskUserQuestion` per surviving candidate, options:

1. **Write to `skills/<name>/`** — calls `Write` once, exactly one
   file. Quoted output: written path + `git diff --stat`.
2. **Rename & retry** — loops back to Step 2 with the new name.
3. **Skip** — discard this candidate, proceed to next.
4. **Abort all** — discard all candidates, exit without writing.

State is in-context only — no `.dev-kit/learn-state.json` is
written. The three steps execute within one slash invocation.

## Validation gates

| Gate | Check | Failure message |
|---|---|---|
| **G1** description-length | `len(desc.rstrip('.')) <= 60` | `description N chars > 60 limit` |
| **G2** frontmatter schema | `name:` kebab-case + matches dir / `alpha:` ∈ {state,enforcement,analysis} / `category:` ∈ 12 allowed / `when_to_use:` present | per-field violation list |
| **G3** section order | `## H2` headers appear in canonical order: Workflow → Step 1 → Step 2 → Step 3 → Validation gates → Iron Laws → Next step | `section order mismatch: expected [...], got [...]` |
| **G4** name collision | `name:` not present in any other `skills/*/SKILL.md` directory | `name collides with skills/<existing>/` |
| **G5** L6 governance | candidate symlinked into a scratch tree, then `pytest tests/test_skill_governance.py -q` | pytest output verbatim |

G1-G4 are implemented by `scripts/validate_skill.py`. G5 is delegated
to `tests/test_skill_governance.py` (the existing L6 gate).

## Iron Laws

- **L1 (verification)**: this skill ships its own regression test
  (`tests/test_learn_skill.py`). The test file's coverage of G1-G4
  is the verification artifact for the skill.
- **L3 (quoted exit code)**: each phase ends with `python3
  scripts/validate_skill.py <candidate>` and the exit code +
  violation list quoted in the response.
- **L4 (no silent defaulting)**: bare `/dev-kit:learn` does NOT
  silently fabricate a SKILL.md; it asks `AskUserQuestion` when no
  transcript is reachable.
- **L6 (alpha)**: `state` — the 5 gates are the alpha-bearing
  surface, not the prose distillation.
- **L7 (alpha lives in gates)**: deterministic gates (char count,
  section order, collision check, L6 test) are the enforcement
  surface; prose is the model's natural reasoning.
- **L8 (no prose restatement of contracts)**: see
  `rules/skill-authoring.md`, `iron-laws/index.md`,
  `tests/test_skill_governance.py` for SSOT.

## Files installed

| Path | Role |
|---|---|
| `skills/learn/SKILL.md` | This file. |
| `skills/learn/scripts/validate_skill.py` | G1-G4 gate runner. |
| `tests/test_learn_skill.py` | G1-G4 regression coverage. |

Phase 2 (deferred, conditional on Phase 1 usage metrics):
`skills/learn/scripts/parse_source.py` for 4-shape input parsing.
See `docs/proposals/learn-skill/main.html` for the deferred scope.

## Memory isolation

This skill is **read-only** on all user-memory files. It only reads
the current session's own transcript under `logs/` and only writes
to the new `skills/<name>/SKILL.md`. User-owned feedback files
under `~/.claude/projects/.../memory/` are never read or written.

## Next step

```bash
python3 -m pytest tests/test_skill_governance.py tests/test_learn_skill.py -v
git add skills/learn/ tests/test_learn_skill.py skills/README.md
git commit
git push
```

The skill does NOT push, open PR, or bump version — that's the
user's call. Hand off after the commit lands on the branch.
