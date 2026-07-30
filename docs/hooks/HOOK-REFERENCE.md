# Hook reference — the enforcement layer

**Language:** English

This plugin's load-bearing surface is **deterministic enforcement**, not
prompt prose. Per `CLAUDE.md` Iron Law L7 ("a skill's alpha lives in the
parts the model can't self-impose"), the hooks below short-circuit the
model's tool calls before they run — they block or redact directly, so they
hold even when the model would rather skip them, and they can't be
"absorbed" by a smarter future model the way a purely reasoning-based skill
can.

The skills (`/dev-kit:*`) are convenience wrappers around these hooks plus
the build state machine (`phases/<name>/index.json`). If you only remember
one thing from this page: **the hooks are what actually enforces the rules;
the skills just make them pleasant to drive.**

For the companion audit of *where hook coverage is still thin* (known gaps,
per-runtime wiring differences), see
[`hook-coverage-gaps.md`](hook-coverage-gaps.md).

---

## Enforcement hooks, by what they guard

| Hook | What it does | Stage |
|---|---|---|
| `tdd-guard` | Blocks `lib/` edits without a failing test | Build |
| `bash-guard` | Denies destructive `git` / `rm` / shell escapes | Build |
| `secret-scan` | Redacts credential patterns in tool inputs | All |
| `slop-detector` | Catches AI-typical patterns across phrase + structure banks (KO+EN) | Build + Review + Security |
| `worktree-guard` | Hard-blocks Edit/Write in the main checkout; on deny, prints the live worktree list via `git worktree list --porcelain` | All |
| `git-guard` | Enforces branch strategy: blocks commit/push to main, force-push, `gh pr merge`; verifies `plugin.json` slot on `git push` to a feature branch | All |
| `worktree-auto-cut` | Creates the per-task worktree + branch | All |
| `stop-verify` | Quoted exit codes / test counts before session end | Plan + Design + Build + Review + Security + Ship |
| `review-yml-isolation` | Forces `review.yml` PRs to be `review.yml`-only | All |

## Hook inventory, by event

The same hooks, indexed by the Claude Code / Codex event that fires them —
useful when you're debugging *why* a hook did or didn't run:

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

**Reading the "Mode" column:** `hard-block` means the tool call is denied
outright — there is no override short of removing the hook. `advisory`
means the hook warns (and, for `tdd-guard`/`bash-guard`, can be escalated to
`--strict` to hard-block too). `fails open` means an internal error in the
hook itself doesn't block your work — it just skips the check for that
call.

---

## See also

- [Hook coverage gaps](hook-coverage-gaps.md) — known gaps in this matrix and per-runtime wiring differences (Claude Code vs. Codex).
- [`rules/git-workflow.md`](../../rules/git-workflow.md) — the worktree + branch rules `worktree-guard` and `git-guard` enforce.
- [`docs/architecture/RUNTIME-PORTABILITY.md`](../architecture/RUNTIME-PORTABILITY.md) — how the same hooks run under both Claude Code and Codex.
- Main [`README.md`](../../README.md) — the short version, under "Under the hood".
