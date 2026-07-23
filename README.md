# dev-harness-kit

> An AI-native delivery harness for Claude Code and Codex: plan, build, review,
> verify, and ship with deterministic hooks and human approval at the end.

[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

## Start here

The normal workflow is:

```text
install → bootstrap → plan → build → review → ship
```

| Need | Command |
|---|---|
| Install | `claude plugin marketplace add sh-ai-x/dev-harness-kit` then `claude plugin install dev-kit` |
| New repository | `/dev-kit:bootstrap-full` |
| Plan work | `/dev-kit:plan` |
| Implement work | `/dev-kit:build` |
| Review changes | `/dev-kit:review` |
| Security review | `/dev-kit:security` |
| Watch a PR | `/dev-kit:babysit-pr` |
| Release | `/dev-kit:ship` |

For local plugin development, use `claude --plugin-dir /path/to/dev-harness-kit`.

## Install and update

Use Node 22 for Claude plugin CLI commands when required by the installed CLI:

```bash
nvm install 22
nvm use 22
claude plugin marketplace add sh-ai-x/dev-harness-kit
claude plugin install dev-kit
```

Refresh the Codex marketplace checkout and versioned cache with the maintained
updater:

```bash
bash skills/codex-cache-update/scripts/update.sh
bash skills/codex-cache-update/scripts/update.sh --dry-run
```

The updater prints the marketplace path, manifest version, cache path, and
`cache synchronized`. Restart Codex after a refresh. Override paths with
`CODEX_MARKETPLACE_DIR` and `CODEX_CACHE_ROOT` when needed.

## New-project setup

Run the one-shot setup in a new consumer repository:

```bash
/dev-kit:bootstrap-full
```

Run the stages separately when needed:

```bash
/dev-kit:bootstrap
/dev-kit:ci-setup
/dev-kit:ci-doctor
```

`/dev-kit:ci-setup` is idempotent and supports `--force` for template refreshes.

## Daily workflow

```bash
/dev-kit:plan
/dev-kit:build
/dev-kit:review
/dev-kit:security       # when the change needs a full security pass
/dev-kit:babysit-pr     # after opening a PR
/dev-kit:ship           # after approval and green gates
```

The user remains responsible for final review and merge.

## Choose by intent

### Setup and configuration

`/dev-kit:bootstrap`, `/dev-kit:bootstrap-full`, `/dev-kit:ci-setup`,
`/dev-kit:ci-doctor`, `/dev-kit:config`, `/dev-kit:log setup|on|off|status`,
and `/dev-kit:codex-cache-update` cover setup, CI, configuration, logging, and
cache refreshes.

### Planning and implementation

Use `/dev-kit:plan`, `/dev-kit:build`, `/dev-kit:build-debug`,
`/dev-kit:build-tdd`, `/dev-kit:build-refactor`, `/dev-kit:build-verify`,
or `/dev-kit:feat-remove` for planned work, debugging, TDD, cleanup,
verification, and safe feature removal.

### Review, cleanup, and release

Use `/dev-kit:review`, `/dev-kit:security`, `/dev-kit:audit`, `/dev-kit:inspect`,
`/dev-kit:refactor`, `/dev-kit:prune`, `/dev-kit:babysit-pr`, `/dev-kit:bump`,
or `/dev-kit:ship` for review, audits, cleanup, PR monitoring, version bumps,
and releases.

### Evaluation and observability

Use `/dev-kit:eval`, `/dev-kit:repair`, `/dev-kit:report`, `/dev-kit:status`,
`/dev-kit:cost-gate`, `/dev-kit:token-analyzer`, `/dev-kit:llm-refresh`, or
`/dev-kit:proposal` for evaluation, reporting, cost, token, model, and proposal
workflows.

The authoritative command surface is the skill frontmatter and filesystem:

```bash
rg -l '^user-invocable: true' skills/*/SKILL.md
```

## Usage-driven discovery

Enable local capture before reading usage data:

```bash
/dev-kit:log setup
/dev-kit:log on
```

Then inspect the two telemetry signals with `tools/skill_usage.py`:

```bash
python3 tools/skill_usage.py
python3 tools/skill_usage.py --top 0
python3 tools/skill_usage.py --days 0 --top 0
python3 tools/skill_usage.py --cwd /path/to/project
python3 tools/skill_usage.py --json --per-cwd
```

`turns` measures attributed work, while `invocations` measures distinct Skill
tool calls. Use `--days 0` for all-time data, `--top 0` for all skills, and
`--cwd` to scope the report. An empty report means capture is disabled or the
selected logs do not match the configured window/glob; it is not a usage ranking.

Related tools:

```bash
python3 tools/session_monitor.py --list --skill-usage
python3 tools/token_efficiency_analyzer.py --help
```

Captured transcripts are local and ignored by Git. See [logs/README.md](logs/README.md)
for the capture format.

## Provider selection

Local selection belongs in `.env`; CI selection belongs in the GitHub repository
variable. Keep them aligned:

```bash
bin/set-provider.sh deepseek
gh variable set CI_REVIEW_PROVIDER --body deepseek
gh secret set DEEPSEEK_API_KEY
```

Provider names and matching secret names are defined by `bin/set-provider.sh`.

## Worktree rule

Every implementation task uses a new worktree and branch. The main checkout is
for inspection and integration; `worktree-guard.sh` blocks edits there.

```bash
git fetch origin main
git worktree add -b fix/example .worktrees/example origin/main
```

Read `rules/git-workflow.md` for the complete handoff contract.

## Repository map

| Path | Purpose |
|---|---|
| `skills/` | User-facing skill instructions |
| `hooks/` | Canonical hook sources and shared libraries |
| `.codex-plugin/` | Codex plugin and hook manifests |
| `commands/` | Source slash-command definitions |
| `lib/` | Orchestration, CI, and state helpers |
| `tools/` | Usage, logging, monitoring, and analysis utilities |
| `tests/` | Regression and contract tests |
| `templates/ci/` | Consumer repository templates |
| `docs/` | Operational and architecture documentation |

Use `rg --files`, manifests, and the relevant `SKILL.md` as the source of truth;
this table is intentionally not an exhaustive inventory.

## Contributing

Read the repository rules before editing:

```bash
sed -n '1,220p' rules/git-workflow.md
sed -n '1,220p' rules/session-hygiene.md
sed -n '1,220p' rules/skill-authoring.md
sed -n '1,220p' rules/test-files.md
```

Run focused tests for the area you change, then the relevant broader suite.
Every completion claim must include the command, exit code, and test count.

## License

MIT. See [LICENSE](LICENSE).
