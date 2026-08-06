> [← Skills index](README.md) · [Project README](../../README.md)

# `learn`

**Category:** `audit` · **Alpha:** `state` · **Invocation:** `/dev-kit:learn <source>` (human-invoked)

`learn` distills free-text input — a file path, a URL, prose, or the
just-finished session transcript — into a candidate
`skills/<name>/SKILL.md`. Each candidate runs through five deterministic
gates (G1–G5) and one `AskUserQuestion` per surviving candidate before
any write. It does NOT edit existing files and does NOT delegate to
sub-agents — it is a pure-prose + deterministic-gate skill.

The five gates are the alpha-bearing surface, not the model's prose.
`description:` length, frontmatter schema, section order, name
collision, and the L6 governance test are not relaxable by the author.

## When to use it

- The user types `/dev-kit:learn <free text>` and wants to convert a
  transcript / file / URL / observation into a new reusable skill.
- The user wants a structured proposal flow with a write-time approval
  gate, not a silent skill fabrication.

## How it works

A strict 3-step workflow mirrors `prune-propose` and `ci-triage`:

```
[1/3] GATHER   -> parse arg (path|url|prose|session) -> load source into context
       |  quoted: source-locator + char count + line range
       v
[2/3] DISTILL  -> 1-3 candidate SKILL.md bodies + G1-G4 verdicts
       |  quoted: candidate set + per-gate PASS/FAIL
       v
[3/3] APPROVE  -> AskUserQuestion per candidate -> Write SKILL.md
       |  quoted: approved set + written paths + git diff --stat
```

**Step 1 — gather.** The trailing argument is parsed as one of four
shapes:

| Shape  | How it loads                                                                                          |
|--------|-------------------------------------------------------------------------------------------------------|
| empty  | Looks for a current session transcript at `logs/claude-code/<branch>/<sid>.jsonl`; if reachable, scans the last 8 assistant turns. Otherwise `AskUserQuestion` for clarification. |
| path   | `Read` the file; quote `wc -l` and first 20 lines.                                                   |
| URL    | `WebFetch`; quote the resolved title + char count. WebFetch-unavailable (Codex sandbox) exits early with a clear error. |
| prose  | Echoed verbatim into context; any trailing requirement phrase (e.g. "focus on auth, skip deprecated") is quoted — these are load-bearing authoring constraints. |

**Step 2 — distill.** The model proposes 1–3 candidate SKILL.md bodies.
For each candidate it records: proposed `name` (kebab-case),
proposed `description` (one sentence, period-end), the full 7-section
body, and the G1–G4 verdict. Any FAIL blocks the write for that
candidate. The model may vary the prose, candidate name (subject to
G4), and candidate count (1–3). The deterministic gates cannot be
relaxed by the model.

**Step 3 — approve.** One `AskUserQuestion` per surviving candidate,
with four options: **Write to `skills/<name>/`** (calls `Write` once,
exactly one file), **Rename & retry** (loops back to Step 2 with the
new name), **Skip** (discard this candidate, proceed to next), and
**Abort all** (discard all candidates, exit without writing).

State is in-context only — no `.dev-kit/learn-state.json` is written.
The three steps execute within a single slash invocation.

## Validation gates

| Gate | Check                                                                          | Failure message                                   |
|------|--------------------------------------------------------------------------------|---------------------------------------------------|
| G1   | `len(desc.rstrip('.')) <= 60`                                                  | `description N chars > 60 limit`                  |
| G2   | `name:` kebab-case + matches dir / `alpha:` ∈ {state,enforcement,analysis} / `category:` ∈ 12 allowed / `when_to_use:` present | per-field violation list                           |
| G3   | `## H2` headers appear in canonical order: Workflow → Step 1 → Step 2 → Step 3 → Validation gates → Iron Laws → Next step | `section order mismatch: expected [...], got [...]` |
| G4   | `name:` not present in any other `skills/*/SKILL.md` directory                  | `name collides with skills/<existing>/`           |
| G5   | Copy `tests/test_skill_governance.py` (the L6 test) plus its `lib/` and `tests/` dependencies into a throwaway scratch repo **with `origin/main` and `main` refs initialized** (the test needs a non-empty baseline — see `tests/test_skill_governance.py:74-95`), symlink the candidate in as `skills/<name>/SKILL.md`, then `pytest tests/test_skill_governance.py -q` from the scratch root | pytest output verbatim                            |

G1–G4 are implemented by `skills/learn/scripts/validate_skill.py` and
quoted in the response. G5 is delegated to
`tests/test_skill_governance.py` — that test derives
`PROJECT_ROOT = Path(__file__).parent.parent` and scans
`PROJECT_ROOT / skills` (lines 26, 105, 156 of that test). Two ways to
satisfy G5: (a) the scratch-repo flow above, where the candidate is
symlinked into a throwaway repo whose `tests/` includes a mirror of
this test, OR (b) place the candidate under the working repo's
`skills/<name>/SKILL.md` (the live-tree flow the reviewer caught as
incompatible with the approval-before-write guarantee). Pick (a) when
the skill must be validated before any write — that is the canonical
flow named in `skills/learn/SKILL.md`.

## Usage

```bash
/dev-kit:learn [empty | path | url | prose]
```

No flags. The shape of the argument determines Step 1's input source.

## Output

A `git diff --stat` line per candidate that is approved-and-written,
the resolved source-locator + char count, the five gate verdicts (G1–G5)
per candidate, and the user-approved set so downstream
`/dev-kit:babysit-pr` or `/dev-kit:prune` can refer to it later.

## Iron Laws

- L1 (verification): the skill ships its own regression test
  (`tests/test_learn_skill.py`); that test's G1–G4 coverage is the
  verification artifact.
- L3 (quoted exit code): each phase ends with
  `python3 skills/learn/scripts/validate_skill.py <candidate>` and the exit code +
  violation list are quoted in the response.
- L4 (no silent defaulting): bare `/dev-kit:learn` does NOT
  silently fabricate a SKILL.md; it asks via `AskUserQuestion` when
  no transcript is reachable.
- L6 (alpha): `state` — the five gates are the alpha-bearing surface,
  not the prose distillation.
- L7 (alpha lives in gates): deterministic gates (char count, section
  order, collision check, L6 test) are the enforcement surface;
  prose is the model's natural reasoning.
- L8 (no prose restatement of contracts): see
  `rules/skill-authoring.md`, `iron-laws/index.md`,
  `tests/test_skill_governance.py` for SSOT.

## Memory isolation

This skill is read-only on all user-memory files. It reads only the
current session's own transcript under `logs/`, and only writes to
the new `skills/<name>/SKILL.md`. User-owned feedback files under
`~/.claude/projects/.../memory/` are never read or written.

## Related

- [`skills/learn/SKILL.md`](../../skills/learn/SKILL.md) — the canonical source-of-truth.
- [`skills/learn/scripts/validate_skill.py`](../../skills/learn/scripts/validate_skill.py) — G1–G4 gate runner.
- [`tests/test_learn_skill.py`](../../tests/test_learn_skill.py) — G1–G4 regression coverage.
- [`tests/test_skill_governance.py`](../../tests/test_skill_governance.py) — L6 gate.
- [`docs-maintenance`](docs-maintenance.md) — the broader docs-maintenance skill (repository-level audit); `learn` is its file-level analogue.

---
*Source: [`skills/learn/SKILL.md`](../../skills/learn/SKILL.md)*
