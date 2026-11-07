> [← Skills index](README.md) · [Project README](../../README.md)

# `codex-cache-update`

**Category:** `shortcuts` · **Alpha:** `analysis` · **Invocation:** `/dev-kit:codex-cache-update` (human-invoked)

`codex-cache-update` refreshes the dev-kit Codex marketplace checkout and synchronizes the matching versioned plugin cache so a new Codex session actually loads current plugin files. It exists as its own skill because `codex plugin marketplace upgrade dev-kit` can report "already up to date" while the versioned cache directory it reads from still holds stale files — a gap the skill closes with an explicit second sync step.

## When to use it

- The user types `/dev-kit:codex-cache-update`.
- The user asks to update or refresh the Codex dev-kit plugin cache.
- `codex plugin marketplace upgrade dev-kit` reports up to date but the files are stale.
- A new dev-kit version or commit was merged to main.

## How it works

The bundled updater is run from the repository root:

```bash
bash skills/codex-cache-update/scripts/update.sh
```

The updater first runs `codex plugin marketplace upgrade dev-kit`, then reads the marketplace plugin version and synchronizes the marketplace checkout into `$HOME/.codex/plugins/cache/dev-kit/dev-kit/<version>` with `rsync --delete`. This second step is required precisely because the marketplace command's "already up to date" report does not guarantee the versioned cache directory matches. The sync excludes Git metadata, worktrees, generated dev-kit state, Python bytecode, and evaluation caches from the installed cache.

The command prints the marketplace commit, the cache directory, and a final `cache synchronized` line. The user should confirm the source and cache manifests report the same version before restarting Codex. `--dry-run` inspects differences without changing the cache.

Default Codex paths can be overridden with environment variables:

```bash
CODEX_MARKETPLACE_DIR="$HOME/.codex/.tmp/marketplaces/dev-kit" \
CODEX_CACHE_ROOT="$HOME/.codex/plugins/cache/dev-kit/dev-kit" \
bash skills/codex-cache-update/scripts/update.sh
```

## Usage

```bash
bash skills/codex-cache-update/scripts/update.sh [--dry-run]
```

| Variable / Flag | Default | Purpose |
|---|---|---|
| `CODEX_MARKETPLACE_DIR` | `$HOME/.codex/.tmp/marketplaces/dev-kit` | Location of the marketplace checkout. |
| `CODEX_CACHE_ROOT` | `$HOME/.codex/plugins/cache/dev-kit/dev-kit` | Root of the versioned plugin cache to synchronize. |
| `--dry-run` | off | Inspect differences without changing the cache. |

## Output

No report file — the command's own stdout is the artifact: the marketplace commit, the cache directory path, and a final `cache synchronized` confirmation line.

## Related

- `skills/codex-cache-update/scripts/update.sh` — the updater script that does the actual `codex plugin marketplace upgrade` + `rsync --delete` work.

---
*Source: [`skills/codex-cache-update/SKILL.md`](../../skills/codex-cache-update/SKILL.md)*
