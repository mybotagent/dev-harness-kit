# LCS in the normal dev-kit workflow — a beginner's tour

After the trim in PR #462, LCS has **zero production consumers in hooks**. This document explains what LCS is, where it actually fires today, when it should fire when `--serve` lands, and what the normal workflow looks like with and without it.

Read time: ~5 minutes.

---

## 1. One-line answer

> **Today in dev-kit's normal workflow, LCS fires 0 times per task.** The CLI is dormant; the hooks have been trimmed to direct shell. LCS remains installed, tested, and callable — it's a substrate for any future consumer that actually needs shared state.

---

## 2. The pieces, named

| piece | path | role |
|---|---|---|
| CLI launcher | `bin/dev-kit-lcs.py` | one-shot CLI; same Python that handles hooks today |
| Server core | `lib/lcs_server.py` | in-process dict + 5s TTL cache; per-process |
| Resource handlers | `lib/lcs_resources/{worktrees,branches,pr,sessions,spend,valuations}.py` | one per URI shape |
| Hook consumers | `hooks/*.sh` | callsite that issues `--get lcs://<uri>` |
| Tests | `tests/test_lcs_*.py` | contract tests for each handler (118 tests) |
| Operator CLI surface | `python3 bin/dev-kit-lcs.py --get lcs://worktrees` | manual debug / future consumers |
| Daemon mode | `bin/dev-kit-lcs.py --serve` | **not yet built** (PR not landed) |

---

## 3. What fires LCS today (the audit, after PR #462)

```bash
$ grep -n 'python3 "bin/dev-kit-lcs' hooks/*.sh | grep -v '#'
# (no output)

$ grep -rn 'lcs://\|dev-kit-lcs' hooks/*.sh
hooks/git-guard.sh:                 # comments mention lcs://branches (no live call)
hooks/worktree-guard.sh:            # comments mention lcs://worktrees (no live call)
```

**Zero live invocations in production hooks.** Both hooks now use direct `git show …` / `git worktree list …`.

Where LCS *does* fire today:

| fires | frequency | purpose |
|---|---|---|
| `tests/test_lcs_*.py` | every `pytest tests/ -q` run | contract pinning — 118 tests cover each URI's response shape |
| `python3 bin/dev-kit-lcs.py --list-resources` | only when an operator or CI step explicitly invokes it | discovery |
| `python3 bin/dev-kit-lcs.py --get lcs://X` | only when an operator invokes directly | one-shot debug |

That's the entire production surface after the trim.

---

## 4. The normal workflow

### 4.1 A typical task (one task → one worktree → one branch → one PR)

| step | tool / hook fired | what runs | LCS fired? |
|---|---|---|---|
| 1. Cut a worktree | `git worktree add -b feat/…` (typed by operator) | none — no hook fires on this raw git call from the shell out-of-band | no |
| 2. `Edit lib/foo.py` | `worktree-guard.sh` fires | `git worktree list --porcelain` directly — no LCS | no |
| 3. `git add … && git commit` | `git-guard.sh` fires | `git show origin/main:.claude-plugin/plugin.json | python3 -c "import sys,json;…"` directly — no LCS | no |
| 4. `git push` | `git-guard.sh` fires again | same direct jq fallback | no |
| 5. CI runs | none of dev-kit's hooks; GitHub Actions | none | no |
| 6. PR review | none of dev-kit's hooks; humans/LLM | none | no |

**LCS reads in the typical workflow: 0.** The hooks that used to call it have been trimmed to direct shell because the cache benefit was empirically 0% (measured in this conversation) and the Python startup tax was net-negative per call.

> **Scope note (added by the trim audit):** the "one task → one worktree → one branch → one PR" model is the *primary* dev-kit workflow, not the only one. Other shapes that exist in this codebase: (a) **version-bump PRs** (only `plugin.json` touched, often direct in main, e.g. PRs `b4aac41`, `690a7d1`); (b) **multi-PR splits** (one feature branch → several PRs, e.g. the LCS-UX rollout split #457/#458/#459/#460 across one branch); (c) **multi-commit PRs** (a single PR with 5–10 commits, typical for refactors); (d) **maintenance chores** (`docs/...`, `chore/...` paths) that don't fit the feature-work shape. For (d) the LCS row in the table above is the same: 0 reads.

### 4.2 Where LCS *should* be invoked, given a future state with `--serve`

If you rebuild the LCS call path against a `--serve` daemon (one Python process, unix socket), the calls become:

| step | tool / hook fired | what runs | LCS served via daemon |
|---|---|---|---|
| 2. `Edit lib/foo.py` | `worktree-guard.sh` | `curl --unix-socket /var/run/lcs.sock lcs://worktrees/` — same answer from cached daemon | yes — one process serves N reads |
| 3. `git commit` | `git-guard.sh` | `curl --unix-socket /var/run/lcs.sock lcs://branches/<n>` — slot version | yes — same daemon, cache hit |
| 4. `git push` | `git-guard.sh` fires | same slot check, cache hit | yes — cached 0 ms |
| babysit iteration N | `/dev-kit:babysit-pr` | daemon-resident reads inside Python client | yes — fast iteration |

**That is the future state where LCS becomes net-positive.** Until `--serve` lands, *do not* re-add the LCS call to git-guard or worktree-guard — the trim analysis in this conversation showed it's net-negative.

---

## 5. The two routes from a question to an answer

When a question needs live repo state, the model (or operator) chooses between:

```
                    ┌─ shell directly (one fork, fast) ── git worktree list
                    │                                       git rev-parse
                    │                                       gh pr view
"what worktrees?"  ─┤
                    │
                    └─ LCS via CLI (one fork, slower) ───── bin/dev-kit-lcs.py --get …
                            or  
                            LCS via daemon (one fork + cache) ─ bin/dev-kit-lcsd (not yet built)
```

The decision rule — same one as `docs/lcs-perf-explained.md` §7:

> **Pick shell** for 1-tool questions (faster, no startup tax). **Pick LCS** when you have N ≥ 2 consumers within one process asking the same URI, OR when a daemon can serve them.

Today, in dev-kit, only the test suite has N ≥ 2 consumers within one process (pytest sets up each test's LCS calls in the same Python). That's why LCS remains useful **as a substrate** even though no production hook fires it.

---

## 6. Tools / skills that interact with LCS, today

| tool / skill | uses LCS? | how |
|---|---|---|
| `/dev-kit:lcs` skill (`skills/lcs/SKILL.md`) | yes — but `user-invocable: false` | the model can fire it; humans don't see it in autocomplete |
| `python3 bin/dev-kit-lcs.py --get lcs://X` | yes — directly | operator debug, future consumers |
| `tools/benchmark_lcs_vs_shell.py` | yes — `--repeats 5` CLI calls | benchmark + perf evidence |
| `tests/test_lcs_*.py` (8 files) | yes — pytest | contract tests |
| `tools/dev-kit-proposal.py` / `/dev-kit:proposal` skill | no LCS | renders proposal yaml → html |
| hooks trimmed in #462 | no LCS (was: yes) | now shell |
| `/dev-kit:babysit-pr` | no LCS (was: would have via hooks) | uses `gh`, not LCS |
| `/dev-kit:route` (Gap 1, not merged) | no LCS | classifier only; outputs `lcs://X` URI for the caller to call |
| `/dev-kit:valuate` | reads `lcs://valuations/<plan-id>` (in CHANGELOG) | not observed in the current hook scripts; would require a host-side consumer |

---

## 7. Concrete: when an operator should *manually* call LCS

| situation | call |
|---|---|
| "Show me every worktree" | `python3 bin/dev-kit-lcs.py --get lcs://worktrees/` |
| "What's the slot version on `feat/foo`?" | `python3 bin/dev-kit-lcs.py --get lcs://branches/feat/foo/` |
| "Is PR #460 MERGEABLE?" | `python3 bin/dev-kit-lcs.py --get lcs://pr/460` |
| "What are the wired URIs?" | `python3 bin/dev-kit-lcs.py --list-resources` |
| "Is the slot drift between slots X and Y?" | `python3 bin/dev-kit-lcs.py --get lcs://branches/<newer>/` then compare to the older version manually |
| "Show me what hooks fire on each runtime" | `python3 bin/dev-kit-lcs.py --get lcs://hooks/coverage` (reserved URI; returns exit 2 today) |

For everything except the reserved URIs, this works out of the box and prints a typed JSON envelope.

---

## 8. Future: `--serve` mode (the architecture's bet)

If a daemon is built (`bin/dev-kit-lcsd`) and at least two consumers in the same harness talk to it via a unix socket, then:

- The 5s cache benefit finally fires (cache hits compound across reads)
- The Python startup tax is paid **once per daemon lifetime**, not per call
- Sub-agents in the same session can share cache (if they share a client)
- Multi-tool pipelines (CI run + review + docs) can share state

Until then, **LCS is the right architecture in a state that hasn't yet paid for itself.** That is the honest reading after this conversation's trim.

---

## 9. Where to look for the rest of the picture

| file | what's in it |
|---|---|
| `tools/benchmark_lcs_vs_shell.py` | the actual measurement tool; produces the headline numbers in the PR |
| `tests/test_lcs_performance.py` | pins the framework so the bench doesn't rot |
| `docs/proposals/lcs-perf/before-and-after.html` (branch `feat/lcs-perf-evidence`) | the proposal + measured numbers + Win/Lose tables + decision flow |
| `bin/dev-kit-lcs.py` | the CLI; --serve is defined but daemon mode has not been built |
| `lib/lcs_resources/<name>.py` | the 6 handlers; each has its own pytest file |

---

## 10. Glossary

| term | meaning |
|---|---|
| LCS | Live Context Server — `bin/dev-kit-lcs.py` + `lib/lcs_server.py` + 6 handlers |
| URI | `lcs://<resource>[/<param>]` — the address form of a question |
| Snapshot | the answer LCS returned for one URI at one point in time |
| TTL | time-to-live; default 5s for the in-process cache |
| Daemon mode (`--serve`) | one long-lived Python listening on a unix socket; **not yet built** |
| Slot | the `plugin.json` version a branch's PR should be on; checked by `git-guard.sh` |
| Normal workflow | one task → one worktree → one branch → one PR; covered in §4 |
