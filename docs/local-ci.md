# Local CI mode

Run the same review pipeline that `.github/workflows/review.yml` +
`maintenance.yml` + `auto-fix-pr.yml` run in GH-Actions — **locally**,
without consuming GH-Actions minutes. Two deliverables, both additive
(the existing workflows are unchanged):

1. `bin/review-local.sh` — local equivalent of the
   review + maintenance workflow orchestration.
2. `/dev-kit:babysit-pr --local-verify [--local-test-cmd "..."]` —
   optional local-test gate inside the babysit iteration loop.

## When to use

- The repo has hit its GH-Actions minute cap on private plans.
- The operator wants to iterate on a review verdict locally (faster
  feedback loop than waiting for CI to spin up).
- The operator is testing a provider switch (`bin/set-provider.sh
  <provider>`) or a new `--local-test-cmd` ahead of pushing.

## When NOT to use

- The branch's PR requires a reviewer bot or org-level MCP that's only
  available via `anthropics/claude-code-action`. Local `claude -p` does
  not have access to the same MCP servers; inline comments go through
  `gh pr comment` instead of `mcp__github_inline_comment__create_inline_comment`.
- The PR requires `gh pr merge` — merging is always a human action.
  `bin/review-local.sh`'s `--auto-approve` casts `gh pr review --approve`
  only; the operator merges the PR themselves.

---

## Local review: `bin/review-local.sh`

A direct shell port of the orchestration half of
`.github/workflows/review.yml` + `maintenance.yml`. The LLM-judge
skills (`/dev-kit:review`, `/dev-kit:security`, `/dev-kit:maintenance`)
are reused verbatim via the local `claude -p` invocation.

### Usage

```bash
# Dry-run (no LLM call, no PR mutation): preview env + planned commands.
bin/review-local.sh --pr 123 --dry-run

# Full review + auto-approve on clean verdict.
bin/review-local.sh --pr 123 --auto-approve

# Force a specific provider (overrides .env:CI_REVIEW_PROVIDER).
bin/review-local.sh --pr 123 --provider anthropic --auto-approve

# Run only /dev-kit:review (skip security + maintenance).
bin/review-local.sh --pr 123 --review-only

# Force-anthropic, only security, no auto-approve (dry-run).
bin/review-local.sh --pr 123 --security-only --provider anthropic --dry-run
```

### Slash command

```bash
/dev-kit:review-local --pr 123 --auto-approve
```

The slash command is a thin wrapper over `bin/review-local.sh`. Both
paths apply the same provider switching + gate logic.

### Provider setup

The script reads `CI_REVIEW_PROVIDER` from the process env, then
`.env` (matches `bin/set-provider.sh` resolution). Switch via:

```bash
bin/set-provider.sh anthropic
bin/set-provider.sh deepseek
bin/set-provider.sh minimax
```

The matching `*_API_KEY` must be in `.env` (or the process env):

```bash
# .env (gitignored)
ANTHROPIC_API_KEY=sk-ant-...
MINIMAX_API_KEY=sk-cp-...
DEEPSEEK_API_KEY=sk-...
```

`bin/review-local.sh` reads the key via `lib/ci_setup.read_env_key()`
and passes the same `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` /
`ANTHROPIC_MODEL*` block as `review.yml:120-131` to the `claude -p`
invocation via the `env KEY=... claude -p ...` prefix. The key never
enters the parent shell's persistent environment, so subsequent `gh` /
shell calls cannot leak it via `/proc/<pid>/environ` or core dumps.

### What it does (mirrors `review.yml` step-by-step)

| Step | Source step name | Local equivalent |
|---|---|---|
| Resolve provider | review.yml `Resolve PR + provider` step | `lib/ci_setup.read_provider()` |
| Set ANTHROPIC_* env | review.yml `Run /dev-kit:review via …` env block | `provider_env_for "$PROVIDER"` (sourced from `lib/review_local_lib.sh`) |
| Run `/dev-kit:review` | review.yml `Run /dev-kit:review via …` step | `claude -p "/dev-kit:review --diff ..."` |
| Run `/dev-kit:security` | review.yml `Run /dev-kit:security via …` step | `claude -p "/dev-kit:security --diff ..."` |
| Run `/dev-kit:maintenance` | maintenance.yml `Run /dev-kit:maintenance via …` step | `claude -p "/dev-kit:maintenance --diff ..."` |
| Extract verdict | review.yml `Extract <skill> verdict` step | capture `claude -p` stdout per skill, pipe to `python3 -m lib.maintenance_gate --extract-verdict-from-stdin` |
| Bump-PR skip | review.yml job-level `if:` filter | `is_bump_pr "$PR_TITLE"` (sourced from `lib/review_local_lib.sh`) |
| Combined verdict gate | review.yml `Combined verdict gate` step | `rank()` (from `lib/review_local_lib.sh`) + worst-of wins |
| L3-evidence gate | review.yml `L3 evidence gate (PR body must quote test count)` step | `extract_pytest_tail "$PR_BODY"` (from `lib/review_local_lib.sh`) |
| Auto-approve | review.yml `Auto-approve on clean verdict` step | `gh pr review --approve --body "..."` (only with `--auto-approve`) |
| Audit comment | review.yml `Extract <skill> verdict` audit line | `gh pr comment --body "<!-- dev-kit-verdict-audit --> ..."` |

### Caveats

- **No MCP inline-comment server**: the workflow has access to
  `mcp__github_inline_comment__create_inline_comment` via
  `claude-code-action`. Local `claude -p` does not. The skill body
  falls back to `gh pr comment` (per `skills/review/SKILL.md`).
- **Local API key exposure**: the script scopes the key to the
  `claude -p` invocation only (via `env KEY=... claude -p ...`). It
  does NOT enter the parent shell's persistent env. Do NOT run it on
  a shared host regardless -- the agent still processes PR content
  with operator credentials.
- **Cannot `gh pr merge`**: the script never merges. The operator
  runs `gh pr merge` manually after `--auto-approve` lands.
- **No provider fallback**: `--provider` is strict; an unknown
  provider exits 1. The script does not auto-switch to `minimax`.
  This matches `bin/set-provider.sh` behavior.

---

## Local babysit: `--local-verify`

`/dev-kit:babysit-pr` already runs locally (the skill body lives in
the current shell). What `--local-verify` adds is a **pre-commit
local test gate** so iterations abort *before* `git push` when the
local test suite fails — saving the GH-Actions run that would
otherwise be consumed by a known-failing commit.

### Usage

```bash
# Default: run pytest -q before each iteration's push.
# (Additive flag; default behavior is unchanged when --local-verify is absent.)
/dev-kit:babysit-pr --local-verify

# Project-specific test command. Stdout/stderr MUST include a
# pytest-style tail line ('<N> passed in <Ns>s' or '<N> failed in <Ns>s')
# per MUST-L3.
/dev-kit:babysit-pr --local-verify --local-test-cmd "make test"
```

### What it does

The skill's §Algorithm loop gains a new step 7.5 between
APPLY FIX (step 7) and VERIFY LOCAL (step 8):

```
7.5. LOCAL VERIFY (only when --local-verify set)
     - lib.babysit_pr_cli.run_local_verify(cmd=--local-test-cmd,
                                          cwd=<worktree>)
       executes the command via `bash -c "$cmd"` and returns a
       LocalVerifyResult. The iteration proceeds only when
       passed=True AND tail_line is the quoted pytest tail line.
     - non-zero exit OR missing tail line OR timeout -> abort iteration
       BEFORE git add / commit / push (MUST-L3 enforcement).
```

The existing step 8 (VERIFY LOCAL — re-run the specific failing check)
is preserved. `--local-verify` adds a *broader* pre-commit check, not
a replacement.

### Why this matters

Without `--local-verify`, the babysit loop's typical flow is:

```
fix → git add → git commit → git push → wait for GH-Actions CI
```

A known-failing local test consumes one GH-Actions run per iteration.
With `--local-verify`:

```
fix → pytest -q (LOCAL) → fix re-iteration → ... → git add → git commit → git push
```

Failing iterations abort before the push, so no GH-Actions run is
consumed until the iteration actually passes the gate. The user still
verifies locally, but the GH-Actions budget is preserved for genuinely
green PRs.

### Implementation

- Parser: `lib/babysit_pr_cli.py::parse_babysit_args()` gains two
  `--local-verify` + `--local-test-cmd` fields. `run_babysit_once()`
  is unchanged (the helper stays pure).
- Skill body: `skills/babysit-pr/SKILL.md` §Algorithm step 7.5
  documents the new step. The Bash invocation lives in the
  orchestrator script, not in `lib/`.
- Tests: `tests/test_babysit_pr_cli.py::TestParseBabysitArgs` adds
  T22-T24 (default-off, flag-on, override, coexists-with-other-flags).

### Caveats

- **Local test suite must be sane**: `--local-verify` trusts the
  local test result. If the local test suite is itself broken or
  stale (e.g. missing fixture), the gate refuses to push. Operators
  should run `pytest -q` once without `--local-verify` to confirm
  the local baseline before relying on the flag.
- **MUST-L3 is enforced by the skill body, not by the helper**: if
  the test command exits 0 but its stdout lacks a pytest-style tail
  line, the skill refuses to flip to "ready to push". The operator
  must either pick a test command that emits the tail line or paste
  the evidence manually.
- **No fallback to GH-Actions**: refusing to push means the iteration
  aborts. The operator can re-run `/dev-kit:babysit-pr` without
  `--local-verify` to fall back to the default push-and-wait-CI flow.

---

## Related

- `bin/review-local.sh` — local equivalent of the GH-Actions review workflow.
- `commands/review-local.md` — slash command wrapper.
- `skills/babysit-pr/SKILL.md` — babysit-pr skill (additive `--local-verify` flag).
- `lib/maintenance_gate.py` — verdict-extraction + combined-gate helper.
- `lib/ci_setup.py` — provider resolution + secret name lookup.
- `bin/set-provider.sh` — local provider switch (`bin/set-provider.sh anthropic`).
- `.github/workflows/review.yml` — GH-Actions equivalent (unchanged).
- `.github/workflows/maintenance.yml` — GH-Actions equivalent (unchanged).
- `scripts/ci-local.sh` — pre-existing local validator runner (no LLM review).
- `tests/test_review_local_sh.py` — shell-level tests for `bin/review-local.sh`.
- `tests/test_babysit_pr_cli.py` — parser + orchestrator tests for babysit-pr.
- `tests/test_commands_install.py` — slash-command install governance.
