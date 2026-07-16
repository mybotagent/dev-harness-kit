---
paths:
  - "**/*"
---

# Session hygiene rules (dev-harness-kit)

These rules govern *how Claude Code sessions behave* in this repo — model
selection, prompt-cache lifecycle, and tool-call economy. They apply to
every session that makes tool calls, regardless of branch or task.

## Iron Laws

1. **No model or CLAUDE.md swap mid-session.** A single token shift in
   the system prompt invalidates the entire prompt cache. Pick the model
   and the ruleset *before* the first tool call, then ride them out.
   Re-reading CLAUDE.md = billable re-input + cold cache.
2. **Cartography, not re-reads.** Build a structural map of any large
   file once. Subsequent turns reuse the entry point (line range,
   section header, or a `Grep`-narrowed read), never re-read the whole
   file from offset 0. Each "read from line 1 again" double-bills input.
3. **Volatile content stays in the prompt tail, never the prefix.**
   Timestamps, run IDs, ephemeral session IDs, today's date — anything
   that changes per turn — belongs at the *end* of the user message.
   A volatile prefix silently busts the cache on every follow-up turn.
4. **`/compact` and sub-agent delegation, not `/clear` + new session.**
   `/clear` drops the cached prefix and forces a cold re-read on the
   next turn. Reach for `/compact` first; spawn a sub-agent for noisy
   exploration; only escalate to `/clear` when the prefix is genuinely
   unrecoverable.
5. **Match the model to the task.** Opus is reserved for design, spec
   authoring, and architectural judgement. Bug fixes, single-line edits,
   refactors, and ad-hoc Q&A run on Sonnet (default) or Haiku.
   "Important" ≠ "Opus"; a typo fix on Opus shows up in cost telemetry
   immediately and is the most common unnecessary-cost signal.
6. **Never re-inject cached context as a user message.** Repeating a
   tool result, file excerpt, or prior-turn output verbatim into the
   next user prompt double-bills input tokens *and* pushes useful
   cached prefix out of the cache. Reference by anchor
   (`see Read on lines 42–87`, `the failing test above`) instead.

## Why these exist

- The prompt cache hit ratio is the single largest cost lever in
  Claude Code. A 50% → 70% shift on a single session scales linearly
  with every session that shares a stable prefix.
- `/clear` resets billable input on the very next turn — a stealth
  cost double-count relative to `/compact`.
- Model mismatch (Opus on a typo fix, Sonnet on a system-design
  decision) is the most common unnecessary-cost signal in any
  per-session cost dashboard.

## Enforcement

The Iron Laws above are guidelines; enforcement is currently
human-driven (reviewers read PR summaries for cost anomalies). No
automated hook enforces them — they exist as a shared vocabulary so
that "Opus on a typo fix" is unambiguous across reviews.

| Rule | Mechanism |
|---|---|
| 1 — model/CLAUDE.md swap | Reviewer reads PR summary's model column |
| 2 — repeated full-file reads | Reviewer flags Read-heavy PRs |
| 3 — volatile prefix | Reviewer flag on PR summary |
| 4 — `/clear` reflex | Reviewer flag on PR summary |
| 5 — model overspec | Reviewer flag on PR summary |
| 6 — repeated user-message context | Reviewer flag on PR summary |

## Related

- `tools/cost_gate_status.py` — per-PR cost aggregator (CI-driven).
- `.claude/rules/git-workflow.md` — branch + worktree protocol.
- `CLAUDE.md` §1 — project Iron Laws (L1–L5).