# Progress log — <task name>

> Per-session log for tasks spanning >1 Claude Code session. Pattern 2
> from `docs/proposals/playbook-application/02-reanalysis.yaml`. Append
> one section per session, never edit prior entries; the diff is the
> audit trail.

## Session 1 — <YYYY-MM-DD HH:MM UTC>

**Operator:** <name or handle>
**Branch:** `<branch-name>`
**Worktree:** `<absolute path or slug>`

### Goal

<one-paragraph statement of what this session set out to deliver; e.g.
"Land Pattern 2 (long-running templates) — 4 template files + 1 SKILL.md
update + 1 test fixture, green PR.">

### Work done

- <concrete deliverable 1, file path + one-line summary>
- <concrete deliverable 2, file path + one-line summary>
- <concrete deliverable 3, ...>

### Tests status

- `pytest tests/test_long_running_templates.py -v` → exit `<N>`, `<X>`
  passed, `<Y>` failed.
- New regressions in pre-existing suite: <count or "none">.
- Notable output (truncate to last 5 lines if long):

  ```
  <paste>
  ```

### Blockers

- <blocker 1 + link/issue id; "none" if session completed cleanly>

### Next session should

1. <ordered, actionable next step 1 — the most important one first>
2. <next step 2>
3. <next step 3>

### Commits

- `<sha>` — <subject line>
- `<sha>` — <subject line>

## Session 2 — <YYYY-MM-DD HH:MM UTC>

**Operator:** <name>
**Branch:** `<branch-name>`

### Goal

Resume the Pattern 2 PR — finish templates wired into skills/build,
address Codex review comments, push the branch and open the PR.

### Work done

- Re-ran `templates/init.sh`; baseline rc=0, picked next feature `F-004`.
- Implemented `progress.log.md` section contract (6 sub-headings) and
  added `test_progress_log_has_required_sections`.
- Re-ran test suite — exit 0, all green.

### Tests status

- `pytest tests/test_long_running_templates.py -v` → exit `0`, `6`
  passed, `0` failed.
- Notable output (last 5 lines):

  ```
  PASSED test_session_handoff_has_resume_sections
  PASSED test_progress_log_has_required_sections
  PASSED test_feature_list_exists
  PASSED test_skill_build_references_templates
  PASSED test_init_sh_has_valid_bash_syntax
  ```

### Blockers

None — Codex review returned Approve on first pass.

### Next session should

1. Push branch with `git push -u origin <branch>`.
2. `python3 tools/linear_sync.py` to ensure Linear issue is up-to-date.
3. `gh pr create --base <default-branch> --head <branch>` with the PR
   body stub.

### Commits

- `<sha>` — feat(templates): add long-running session templates
- `<sha>` — test(templates): validate structure + bash syntax
