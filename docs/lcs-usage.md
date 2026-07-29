# Live Context Server (LCS) — Usage Reference

> Read-only URI surface for the harness's live state — every hook, agent, and
> operator looks at the same picture.

dev-kit · Phase 1.x (issues #346–#356) · v0.3.147

## Contents

1. [What it is](#1-what-it-is)
2. [URI grammar](#2-uri-grammar)
3. [Resources](#3-resources)
4. [CLI surface](#4-cli-surface)
5. [JSON-RPC transport (`--serve`)](#5-json-rpc-transport---serve)
6. [Integration map](#6-integration-map)
7. [Quickstart](#7-quickstart)
8. [Cheatsheet](#8-cheatsheet)
9. [README drift](#9-readme-drift-as-of-v03147)
10. [Verification log](#10-verification-log)

---

## 1. What it is

The Live Context Server (LCS) is a **read-only**, in-process URI router that
exposes the dev-kit harness's live state under one namespace —
`lcs://<resource>`. It replaces ad-hoc shell-outs to `git worktree list`,
`gh pr checks`, per-bucket token queries, and per-skill interview lookups
with one round-tripped JSON payload.

It is **not**:

- a daemon. It lives inside the calling process (one `LCSServer` per
  consumer) with a 5-second in-memory snapshot cache.
- a database. Every fetch reads fresh filesystem / subprocess state.
- mutable. Resources do not write to disk or push to a network (beyond
  `gh api` / `git` reads).

### The three pieces

1. **Server core** (`lib/lcs_server.py`, 308 LoC) — URI parser + longest-match
   router + per-URI snapshot cache. Pure functions, no global state.
2. **CLI driver** (`bin/dev-kit-lcs.py`) — Thin launcher wrapping the server.
   Spawns from Bash, MCP clients, and hooks via stdio.
3. **Resource handlers** (`lib/lcs_resources/*.py`) — One Python class per
   URI. Six ship in the default registry; three are importable on demand.

---

## 2. URI grammar

The scheme is fixed at `lcs://` (lowercase, case-sensitive). The body splits
on `/`; the last segment may be the resource name or a path param, decided
by longest-match against the registry.

```
lcs://<resource-name>[/<segment>[/...]][/]

Collection form      URI ends with "/". Some resources reject it (interview, pr).
Path-param form      URI body has one or more segments after the resource name.
Trailing-slash OK    "lcs://worktrees" and "lcs://worktrees/" both resolve.
Nested resource name "lcs://hooks/coverage" registers as a single key in the
                     registry; the longest-match resolver walks prefixes.
Slashes inside segment %2F-encoded — round-trips intact:
                     "lcs://branches/feat%2Ffoo" stays one segment.
```

Every fetch returns a normalized envelope:

```json
{
  "status":  "ok" | "partial" | "error",
  "data":    <handler-specific dict>,
  "missing": [str, ...]   // present when status="partial"
  "error":   str          // present when status="error"
}
```

Handlers never raise out — exceptions become `status="error"` payloads so the
read path stays crash-free.

---

## 3. Resources

**Six resources ship in the default registry.** Three more
(`hooks/coverage`, `interview`, `research/cache`) are importable but not in
the default CLI registry — see [README drift](#9-readme-drift-as-of-v03147).

### `lcs://worktrees[/{branch}]` — Every git worktree

Lists all worktrees via `git worktree list --porcelain`. Item form adds
dirty-file list, hook wiring, and slot version.

Collection — `lcs://worktrees`:

```json
{
  "status": "ok",
  "data": {
    "worktrees": [
      {
        "branch":       "main",
        "path":         "/Users/sanghee/dev/dev-harness-kit",
        "head":         "6bd1073bbef4b50d477aaabedfbafc4511a8d459",
        "detached":     false,
        "dirty_files":  [],
        "dirty":        false,
        "hooks_wired":  true,
        "last_touched": "2026-07-28T02:01:14+00:00",
        "slot_version": "0.3.147"
      }
    ],
    "summary": {
      "total": 1,
      "active": 1,
      "stale": 0,
      "slot_drift": {
        "min": "0.3.147",
        "max": "0.3.147",
        "behind_count": 0
      },
      "as_of": "2026-07-29T04:00:00+00:00"
    }
  }
}
```

Item — `lcs://worktrees/main`: same shape as one collection entry, plus the
`dirty_files` array populated by `git status --porcelain`.

Failure modes:
- Single broken worktree → `status="partial"`, broken subfield listed in
  `missing`.
- No `.dev-kit/runtime.json` → `slot_version: null`.

### `lcs://branches/{name}` — One branch snapshot

Local HEAD, origin HEAD, ahead/behind counters, last CI run (via `gh api`),
and the merged-from-`plugin.json` slot version. The README mentions
`lcs://branches/<name>/slot` — that sub-URI is **not implemented**; the slot
version lives on the main payload.

```json
{
  "status": "ok",
  "data": {
    "name":         "main",
    "local_head":   "6bd1073bbef4b50d477aaabedfbafc4511a8d459",
    "origin_head":  "6bd1073bbef4b50d477aaabedfbafc4511a8d459",
    "ahead":        0,
    "behind":       0,
    "last_ci_run":  { "conclusion": "success", "name": "CI", "status": "completed" },
    "slot_version": "0.3.147"
  }
}
```

Failure modes:
- Branch missing locally → `status="partial"`,
  `missing=["no such branch"]`.
- No `origin/<name>` upstream → `(ahead=0, behind=0)`, no failure.

### `lcs://pr/{number}` — One PR's CI + reviews

Powered by `gh pr view <N> --json number,title,state,statusCheckRollup,reviews,comments`.
Item-only — collection form raises `LCSError`.

Item — `lcs://pr/447`:

```json
{
  "status": "ok",
  "data": {
    "number":              447,
    "title":               "feat(audit): Phase 7 batch — cross-harness audit",
    "status":              "MERGEABLE",
    "checks":              [...],
    "reviews":             [...],
    "unresolved_threads":  [...]
  }
}
```

Failure modes:
- `gh` missing or unauthenticated → `status="partial"` with PR number +
  `missing` explaining the gap.
- PR not found → same partial envelope.

### `lcs://sessions/{id}` — One recorded session

Resolves a session across three sources, first hit wins:

1. `<logs_root>/sessions/<id>.json` — canonical state dump (Phase 0.4)
2. `<logs_root>/<id>.json` — same canonical schema, top-level
3. `<logs_root>/{claude-code,codex}/*<id>*.jsonl` — transcript-derived

Item payload (6 fields):

```json
{
  "status": "ok",
  "data": {
    "id":            "a0f83efc-...",
    "role":          "user" | "assistant",
    "cwd":           "/Users/.../dev-harness-kit",
    "current_task":  "Show worktree state",
    "last_tool":     "Bash",
    "started_at":    "2026-07-28T01:55:12Z"
  }
}
```

Failure modes:
- No record in any source → `missing=["no session <id>"]` in a partial
  envelope.

### `lcs://spend/{window}` — Token spend buckets

Walks `<logs_root>/{claude-code,codex}/**/*.jsonl` for TokenLog records and
buckets them by session, worktree, and skill.

Window grammar:

- `lcs://spend/today` — UTC day, 00:00 → 24:00
- `lcs://spend/last-hour` — 60 min ending at `now`
- `lcs://spend/<iso-start>-<iso-end>` — ISO-8601 range, both UTC with `Z` suffix

```json
{
  "status": "ok",
  "data": {
    "window":       { "since": "...", "until": "..." },
    "by_session":   [{ "key": "<id>",      "tokens": 12345 }],
    "by_worktree":  [{ "key": "main",      "tokens": 78910 }],
    "by_skill":     [{ "key": "build",     "tokens": 12321 }]
  }
}
```

Empty logs / empty window → empty arrays, no failure.

### `lcs://valuations/{plan-id}` — Build gate verdict

Reads `<project>/.dev-kit/valuations/<plan-id>.json` — the canonical verdict
envelope written by the `valuate` skill. The build gate consumes this;
`decision == proceed` with a valid status is the only way past gate.

```json
{
  "status": "ok",
  "data": {
    "plan_id":            "phase-2-3",
    "decision":           "proceed" | "revise" | "hold" | "kill",
    "rationale":          "...",
    "blocking_findings":  [...],
    "scores":             { ... },
    "persisted_at":       "2026-07-28T01:55:12Z"
  }
}
```

Failure modes:
- Missing envelope → `status="partial"` → build gate treats as `hold`.
- Read / parse error → `status="error"` → fail-closed.

### `lcs://demo/{anything}` — Echo resource · dev only

Built-in transport test. Returns the parsed URI back as JSON so the read
path can be exercised without any external state. Enabled by setting
`DEV_KIT_LCS_DEMO=1` in the environment.

```bash
$ DEV_KIT_LCS_DEMO=1 python3 bin/dev-kit-lcs.py --get 'lcs://demo/example%2Fpath'
{
  "status": "ok",
  "data": {
    "first_segment": "demo",
    "path_segments": ["demo", "example/path"],
    "is_collection": false
  }
}
```

### Resources NOT in the default registry

| URI | Status | Why it's off by default |
|---|---|---|
| `lcs://hooks/coverage` | `ok \| partial` | Reads `.claude/hooks.json` + `.codex/hooks.json` + `hooks/*.sh`. Used by hook-doctor. |
| `lcs://interview/{step}` | `ok \| partial \| error` | Reads `.dev-kit/hand-off/<step>.md`. Consumed by `lib/interview_engine.py`. Item-only. |
| `lcs://research/cache[/{sub}]` | `partial` | v1 stub — every `/{sub}` raises `LCSPartialError`. Phase 5 will populate. |

---

## 4. CLI surface

One file, four mutually exclusive flags. Exactly one is required:

```bash
$ python3 bin/dev-kit-lcs.py --help
usage: dev-kit-lcs [-h] (--list-resources | --describe NAME | --get URI | --serve)
```

| Flag | Surface | Used from | Output |
|---|---|---|---|
| `--list-resources` | human | terminal | One resource per line: `name   module.Class` |
| `--describe NAME` | both | terminal / agent | `{ "name": "...", "class": "..." }` JSON |
| `--get URI` | agent | hooks / agents / MCP | The full status/data envelope as JSON |
| `--serve` | agent | MCP clients | One JSON-RPC object per line on stdio |

### Exit codes

| Code | Meaning |
|---|---|
| **0** | OK — handler returned a complete payload |
| **1** | Unknown subcommand / argparse failure |
| **2** | URI parse error or unknown resource |
| **3** | Handler raised an exception — see `status="error"` in the payload |

> **STDERR vs STDOUT.** Error envelopes go to **stderr**; successful payloads
> go to **stdout**. Scripts that pipe `--get` through `2>/dev/null` still get
> exit code 2/3 — never rely on the captured JSON to detect failure.

### Snapshot cache

Each `LCSServer` holds a per-URI cache with `ttl_seconds=5`. The CLI spawns
a new server per invocation, so cache does not cross processes — call
`server.invalidate(uri)` inside a long-running consumer if you need fresher
data.

---

## 5. JSON-RPC transport (`--serve`)

For MCP clients and long-running consumers, `--serve` speaks JSON-RPC on
stdio. One request per line, one response per line, both newline-delimited
JSON objects.

```jsonc
request  →  {"id": 1, "method": "lcs.list", "params": {}}
response ←  {"id": 1, "result": ["branches", "pr", "sessions", "spend",
                                "valuations", "worktrees"]}

request  →  {"id": 2, "method": "lcs.get", "params": {"uri": "lcs://pr/447"}}
response ←  {"id": 2, "result": { "status": "ok", "data": { ... } }}

request  →  {"id": 3, "method": "lcs.describe", "params": {"name": "spend"}}
response ←  {"id": 3, "result": { "name": "spend",
                                "class": "lcs_resources.spend.SpendResource" }}

error    ←  {"id": 2, "error": "no registered resource matches URI ..."}
```

### Supported methods

| Method | Params | Result |
|---|---|---|
| `lcs.get` | `{"uri": "lcs://..."}` | The handler envelope (`{status, data, missing?, error?}`) |
| `lcs.list` | `{}` | Sorted list of registered resource names |
| `lcs.describe` | `{"name": "spend"}` | `{name, class}` descriptor |

Notifications (requests without `id`) are accepted silently. The server traps
`SIGTERM` / `SIGINT` for graceful MCP shutdown.

---

## 6. Integration map

Live call sites that read from `lcs://`. Hooks prefer LCS to avoid spawning
more git subshells.

| Consumer | URI | Why |
|---|---|---|
| `hooks/git-guard.sh` (PreToolUse) | `lcs://branches/{branch}` | Reads `slot_version` to validate the plugin.json bump before push — fallback to git rev-list if LCS is unavailable. |
| `lib/execute.py` (Phase 4) | `lcs://valuations/{plan-id}` | Hard no-go gate. `decision == "proceed"` is the only way past this point — the build halts otherwise. |
| `lib/research_engine.py` | `lcs://research/cache` | Phase 0 cache hit. Skips the network round-trip if the same query was resolved recently. |
| `lib/interview_engine.py` | `lcs://interview/{step}` | Reads the 5-field hand-off to gate each interview step (Phase 6 safety contract). |
| Chat surface (this skill) | any registered URI | User-friendly entry point: `/dev-kit:lcs` invokes the model-invoked skill that shells to the CLI. |

> **Why a CLI, not a Python import?** Hooks are bash scripts; MCP clients
> spawn subprocesses. `bin/dev-kit-lcs.py` is the single contract boundary —
> the server core (`lib/lcs_server.py`) stays an in-process Python module for
> direct embedding.

---

## 7. Quickstart

1. **List registered resources.**

    ```bash
    $ python3 bin/dev-kit-lcs.py --list-resources
      branches                          lcs_resources.branches.BranchesResource
      pr                                lcs_resources.pr.PRResource
      sessions                          lcs_resources.sessions.SessionsResource
      spend                             lcs_resources.spend.SpendResource
      valuations                        lcs_resources.valuations.ValuationsResource
      worktrees                         lcs_resources.worktrees.WorktreesResource
    ```

2. **Discover a resource.**

    ```bash
    $ python3 bin/dev-kit-lcs.py --describe spend
    {
      "name": "spend",
      "class": "lcs_resources.spend.SpendResource"
    }
    ```

3. **Fetch a URI.**

    ```bash
    $ python3 bin/dev-kit-lcs.py --get 'lcs://worktrees/'
    $ python3 bin/dev-kit-lcs.py --get 'lcs://branches/main'
    $ python3 bin/dev-kit-lcs.py --get 'lcs://pr/447'
    $ python3 bin/dev-kit-lcs.py --get 'lcs://spend/today'
    ```

4. **Exercise the demo resource.**

    ```bash
    $ DEV_KIT_LCS_DEMO=1 python3 bin/dev-kit-lcs.py --get 'lcs://demo/example%2Fpath'
    ```

5. **Speak JSON-RPC.**

    ```bash
    $ echo '{"id":1,"method":"lcs.list","params":{}}' \
      | python3 bin/dev-kit-lcs.py --serve
    {"id": 1, "result": ["branches", "pr", "sessions", "spend", "valuations", "worktrees"]}
    ```

---

## 8. Cheatsheet

### Use case → URI

- "What worktrees exist?" → `lcs://worktrees`
- "Is my branch slot up to date?" → `lcs://branches/{name}`
- "Is this PR green?" → `lcs://pr/{n}`
- "What's the spend this hour?" → `lcs://spend/last-hour`
- "Can the build proceed?" → `lcs://valuations/{plan-id}`
- "Where is session X?" → `lcs://sessions/{id}`

### Failure handling

- `status="partial"` → missing fields listed in `missing[]`. Treat as data
  you don't have.
- `status="error"` → check `error` string. Handler crashed (rare). Most often
  means subprocess failure (`gh` missing, etc.).
- Exit code 2 → URI malformed or resource name typo. Verify spelling against
  `--list-resources`.

---

## 9. README drift (as of v0.3.147)

> The README documents LCS in §"Live Context Server (LCS)" — but several
> claims there no longer match the code. If you copy a URI from the README
> and get a `status="partial"`, it's likely one of these:

| README claim | Reality |
|---|---|
| "five production handlers" | **Six**: `branches`, `pr`, `sessions`, `spend`, `valuations`, `worktrees`. `valuations` was added in Phase 4 (issue #373) and the README still caps at five. |
| `lcs://branches/<name>/slot` | **Not registered.** `slot_version` is a key on the `lcs://branches/<name>` main payload. The sub-URI claim is stale. |
| `lcs://hooks/coverage`, `lcs://interview/<step>`, `lcs://research/cache` listed as "production" | **Not in the default CLI registry.** They ship as importable handler classes in `lib/lcs_resources/` and are wired into the corresponding engines (`lib/interview_engine.py`, `lib/research_engine.py`, `hooks/hook-doctor.sh`), but `bin/dev-kit-lcs.py` does not register them. |
| README example wording for `/dev-kit:lcs` chat | Still accurate: model-invoked skill shells to `bin/dev-kit-lcs.py` and renders the JSON inline. |

---

## 10. Verification log

Every command in this doc was exercised at authoring time. Iron Law L3:
completion claims must quote exit codes.

| Command | Exit |
|---|---|
| `python3 bin/dev-kit-lcs.py --list-resources` | **0** |
| `python3 bin/dev-kit-lcs.py --describe spend` | **0** |
| `python3 bin/dev-kit-lcs.py --get lcs://branches/main` | **0** (`status=ok`) |
| `python3 bin/dev-kit-lcs.py --get lcs://worktrees/` | **0** (204 worktrees; 80 dirty) |
| `DEV_KIT_LCS_DEMO=1 python3 bin/dev-kit-lcs.py --get lcs://demo/example%2Fpath` | **0** (echo round-trip) |
| `echo '{...lcs.list}' | python3 bin/dev-kit-lcs.py --serve` | **0** (JSON-RPC response on stdout) |
| `python3 bin/dev-kit-lcs.py --get lcs://does-not-exist` | **2** (unknown resource) |

---

Authored in worktree `.worktrees/lcs-usage-html` · branch `docs/lcs-usage-html`
· off `origin/main @ 6bd1073`. Korean version:
[`docs/lcs-usage.ko.md`](lcs-usage.ko.md). HTML version:
[`docs/lcs-usage.html`](lcs-usage.html). Back to
[`docs/00-index.md`](00-index.md).
