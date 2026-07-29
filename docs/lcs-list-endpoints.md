# LCS list endpoints

Three LCS resources expose **list variants** that let operators discover
ids without shelling out to `git`, `gh`, or scanning JSONL transcripts:

| URI | Returns |
|---|---|
| `lcs://branches` | All local branches with `name`, `local_head`, `ahead`, `behind`, `last_ci_conclusion` |
| `lcs://sessions` | Indexed sessions with `id`, `role`, `started_at`, `current_task`, `last_tool` |
| `lcs://prs` | Open PRs with `n`, `title`, `head`, `ci_state`, `review_state` |

## Empty-index behavior

When the canonical index is empty (e.g. no `logs/sessions/<id>.json`
dumps exist), the list returns `summary.total: 0` rather than
`partial`. "No sessions indexed" is honest data, not an error.

## Picking a row, then drilling in

The list variants return **small payloads** (not the full per-record
detail). Pick a row from the list, then call the `<id>`-keyed
variant for the full record:

```
$ lcs://branches                    # list all branches
$ lcs://branches/main               # full record for main
$ lcs://branches/feat/lcs-ux-discovery   # full record for a branch
$ lcs://sessions                    # list indexed sessions
$ lcs://sessions/<uuid>             # full record
$ lcs://prs                         # list open PRs
$ lcs://pr/460                      # full record for PR #460
```

See `docs/proposals/lcs-ux/router-and-summaries.html` (Gap 3) for the
design rationale and acceptance criteria.
