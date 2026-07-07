"""ci_setup.py — Install dev-kit's reusable CI templates into a target project.

Engine for the `/dev-kit:ci-setup` skill. Copies the canonical CI templates
(from `templates/ci/`) into a target repo, writes the marker file
`.dev-kit/ci-config.json`, and sets executable bits on shell scripts.

Mirrors `lib/install.sh`'s conventions (mkdir -p + copy + summary), but:
- Written in Python (cross-platform pathlib, no shell escaping on Windows).
- Idempotent: existing files are skipped unless `force=True`.
- Returns a structured `InstallReport` dataclass for the skill body.

Usage (from the skill body or directly):
    from lib.ci_setup import install_ci_config
    report = install_ci_config(Path("/path/to/target_repo"))
    print(report)
"""
from __future__ import annotations

import json
import re
import subprocess
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List

# Plugin root (resolved via __file__ so the module is location-independent).
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES_ROOT = _PLUGIN_ROOT / "templates" / "ci"

# Files installed into the target repo, relative to `target_dir`.
# Order is preserved in reports (workflows first, then scripts, then
# worktree-rule files). Adding a path here also requires adding the
# corresponding template under templates/ci/.
#
# EXPECTED_PATHS = the union installed by `dev-kit:ci-setup` with no phase
# flag (the legacy one-shot install). The two-phase install (`--bootstrap`
# then no flag) splits EXPECTED_PATHS into:
#   - BOOTSTRAP_PATHS : the 3 workflow files that anthropics/claude-code-action
#                        validates against `main`. They MUST land on the
#                        default branch in a dedicated PR before the action
#                        will run, otherwise the very PR that introduces
#                        them is skipped (the action refuses to validate a
#                        workflow file the PR itself is modifying).
#   - BODY_PATHS      : everything else — installs cleanly on a PR after the
#                        bootstrap PR is merged, and the action runs because
#                        the workflow files are stable on `main`.
EXPECTED_PATHS: tuple[str, ...] = (
    # CI workflows + scripts.
    # claude-{review,security}.yml are the wrapper files that contain the
    # anthropics/claude-code-action@v1 invocation. review.yml (the
    # orchestrator) calls them via workflow_call. The action's "workflow
    # file must be identical to main" validation gate validates the file
    # the action is invoked from -- so when PR diff changes review.yml
    # but not claude-*.yml, the wrappers are stable on main and
    # validation passes. claude-*.yml MUST land in the same PR as
    # review.yml so the orchestrator's `uses:` references resolve.
    ".github/workflows/ci.yml",
    ".github/workflows/auto-fix-pr.yml",
    ".github/workflows/review.yml",
    ".github/workflows/claude-review.yml",
    ".github/workflows/claude-security.yml",
    ".githooks/pre-push",
    "scripts/validate.py",
    "scripts/test.sh",
    "scripts/branch-policy.sh",
    "scripts/ci-local.sh",
    # Worktree-rule enforcement (every task = new worktree + new session
    # + new branch). See .claude/rules/git-workflow.md.
    "hooks/worktree-guard.sh",
    "hooks/task-detector.sh",
    "hooks/session-start-check.sh",
    "hooks/lib/worktree-detect.sh",
    "hooks/hooks.json",
    ".claude/rules/git-workflow.md",
    "tests/test_worktree_guard.py",
)

# Workflow files that anthropics/claude-code-action validates against `main`.
# These land in their own PR (`--bootstrap`) so the action's safety check
# passes on every PR after merge.
BOOTSTRAP_PATHS: tuple[str, ...] = (
    ".github/workflows/ci.yml",
    ".github/workflows/auto-fix-pr.yml",
    ".github/workflows/review.yml",
    # claude-{review,security}.yml land in the bootstrap PR alongside
    # review.yml so the orchestrator's workflow_call references resolve.
    # The action validation gate then has stable wrappers on main.
    ".github/workflows/claude-review.yml",
    ".github/workflows/claude-security.yml",
    # scripts/{validate,test,branch-policy,ci-local}.sh land in the bootstrap
    # PR so ci.yml's test and validate jobs pass (they reference these
    # scripts unconditionally -- the action safety check that skips the
    # review/security jobs does not gate test/validate jobs).
    # BODY_PATHS holds only the consumer-side artifacts (.githooks/, hooks/,
    # rules/, tests/).
    "scripts/validate.py",
    "scripts/test.sh",
    "scripts/branch-policy.sh",
    "scripts/ci-local.sh",
)

# Everything NOT in BOOTSTRAP_PATHS. Installed in the second PR (no flag)
# after the bootstrap PR is merged.
BODY_PATHS: tuple[str, ...] = tuple(
    p for p in EXPECTED_PATHS if p not in BOOTSTRAP_PATHS
)

# Files that need the executable bit after install.
EXECUTABLE_PATHS: tuple[str, ...] = (
    ".githooks/pre-push",
    "scripts/test.sh",
    "scripts/branch-policy.sh",
    "scripts/ci-local.sh",
    "scripts/validate.py",
    "hooks/worktree-guard.sh",
    "hooks/task-detector.sh",
    "hooks/session-start-check.sh",
    "hooks/lib/worktree-detect.sh",
)

MARKER_REL = ".dev-kit/ci-config.json"
# Marker schema is content-only (no version gate). Content is source of truth;
# _copy_template skips when bytes match. Anthropic marketplace pins by commit
# SHA (docs: "every commit counts as a new version"), so we don't bump versions
# to push fixes — we just push.
MARKER_SCHEMA_VERSION = "1.0.0"

# Post-install checklist: rendered (opt-in via install_ci_config(print_checklist=True))
# AFTER the marker is written. Each tuple is (number, command-block with notes).
# Empty <OWNER>/<REPO> placeholder is filled at print time from
# `git remote get-url origin` if a remote is configured; otherwise the literal
# string is shown so the user can edit it.
POST_INSTALL_CHECKLIST: tuple[tuple[str, str], ...] = (
    ("1", "Add DEV_KIT_GITHUB_TOKEN (PAT scoped to sh-ai-x/dev-harness-kit):\n"
          "       gh secret set DEV_KIT_GITHUB_TOKEN --repo <OWNER>/<REPO> --app actions\n"
          "       (omit if sh-ai-x/dev-harness-kit is public)"),
    ("2", "Add MINIMAX_API_KEY (or ANTHROPIC_API_KEY for opt-in provider):\n"
          "       gh secret set MINIMAX_API_KEY --repo <OWNER>/<REPO>"),
    ("3", "Enable pre-push hook:  git config core.hooksPath .githooks"),
    ("4", "Verify install — open any PR (including one that modifies "
          ".github/workflows/review.yml).\n"
          "       The wrapper pattern (0.1.5+) keeps claude-{review,security}.yml "
          "stable on\n"
          "       main, so the action's workflow-identity validation gate "
          "passes on EVERY PR.\n"
          "       /dev-kit:review + /dev-kit:security should fire."),
)


@dataclass
class InstallReport:
    """Structured result of an install invocation.

    `created`/`overwritten`/`skipped` are lists of POSIX-style strings
    (forward slashes, relative to `target_dir`) for JSON-friendly output.
    `marker_path` is an absolute Path. `elapsed_ms` is wall-clock duration.
    `warnings` holds non-fatal findings from `lint_installed_workflows()`
    (e.g. a stale gate-tolerance pattern in a previously-installed
    workflow that the next `--force` refresh will replace).
    """

    created: List[str] = field(default_factory=list)
    overwritten: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    marker_path: str = ""
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class ProbeResult:
    """One row of the pre-flight probe table.

    `state` is one of:
      - OK   : present and configured
      - WARN : present but missing/partial (skill still proceeds)
      - INFO : opt-in / informational (never blocks)
      - SKIP : gh absent or unauthenticated; the probe is silently bypassed
      - FAIL : fatal prerequisite (reserved; not currently emitted)
    """

    label: str
    state: str
    detail: str = ""


def _now_utc_iso() -> str:
    """ISO-8601 UTC timestamp, second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, data: dict) -> None:
    """POSIX-atomic JSON write (mirrors `lib/atomic.atomic_write_json`).

    Inline copy to avoid an import dependency on the plugin's own lib
    (target projects install ONLY what's inside templates/ci/, not lib/*.py).
    """
    import json
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _copy_template(rel_path: str, target_dir: Path, *, force: bool) -> str:
    """Copy one template file. Returns 'created' | 'overwritten' | 'skipped'.

    Raises FileNotFoundError if the template source is missing (treated as
    a programmer/install error, not a runtime idem-key collision).
    """
    src = _TEMPLATES_ROOT / rel_path
    if not src.exists():
        raise FileNotFoundError(f"template source missing: {src}")
    dst = target_dir / rel_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if not force:
            return "skipped"
        shutil.copy2(src, dst)
        return "overwritten"
    shutil.copy2(src, dst)
    return "created"


def _chmod_executable(rel_paths: tuple[str, ...], target_dir: Path) -> None:
    for rel in rel_paths:
        p = target_dir / rel
        if p.exists():
            mode = p.stat().st_mode
            p.chmod(mode | 0o111)  # set +x for owner/group/other


def _build_marker(*, phase: str = "all") -> dict:
    """Build the `.dev-kit/ci-config.json` marker.

    `phase` is one of "bootstrap" | "body" | "all":
      - "bootstrap" : only BOOTSTRAP_PATHS were installed (workflow files only)
      - "body"      : only BODY_PATHS were installed (everything else)
      - "all"       : legacy one-shot install (the entire EXPECTED_PATHS)
    """
    return {
        "schema_version": MARKER_SCHEMA_VERSION,
        "installed_at": _now_utc_iso(),
        "installed_by": "dev-kit:ci-setup",
        "phase": phase,
        "runners": ["ci.yml", "auto-fix-pr.yml", "review.yml"],
        "scripts": [
            "scripts/validate.py",
            "scripts/test.sh",
            "scripts/branch-policy.sh",
            "scripts/ci-local.sh",
        ],
        "githooks": [".githooks/pre-push"],
        "hooks": [
            "hooks/worktree-guard.sh",
            "hooks/task-detector.sh",
            "hooks/session-start-check.sh",
            "hooks/lib/worktree-detect.sh",
            "hooks/hooks.json",
        ],
        "rules": [".claude/rules/git-workflow.md"],
        "tests": ["tests/test_worktree_guard.py"],
    }


def _resolve_paths(phase: str | None) -> tuple[str, ...]:
    """Map a phase arg to the EXPECTED_PATHS subset it installs.

    phase=None | "all" : full EXPECTED_PATHS (legacy one-shot default)
    phase="bootstrap"  : BOOTSTRAP_PATHS (workflows only)
    phase="body"       : BODY_PATHS (everything else)
    """
    if phase in (None, "all"):
        return EXPECTED_PATHS
    if phase == "bootstrap":
        return BOOTSTRAP_PATHS
    if phase == "body":
        return BODY_PATHS
    raise ValueError(
        f"unknown phase={phase!r}; expected None|'all'|'bootstrap'|'body'"
    )


def install_ci_config(
    target_dir: Path,
    *,
    force: bool = False,
    print_checklist: bool = False,
    lint: bool = True,
    phase: str | None = None,
) -> InstallReport:
    """Install dev-kit's CI templates into `target_dir`. Idempotent + content-aware.

    A no-op (all files skipped, marker reused) when the marker exists and every
    EXPECTED_PATHS file is already in place. With `force=True`, all template
    files are overwritten regardless.

    Args:
        target_dir: absolute path to the target project root. Must exist
            and be a directory (raises FileNotFoundError otherwise).
        force: when True, overwrite existing target files matching the
            paths for the resolved phase. Default False (skip + report).
        phase: None|'all' (default) installs the full EXPECTED_PATHS;
            'bootstrap' installs only BOOTSTRAP_PATHS (the 3 workflow files
            that anthropics/claude-code-action validates against `main` —
            they MUST land in their own PR first so the action's safety
            check passes on every PR after); 'body' installs only
            BODY_PATHS (everything else, used in the second PR after the
            bootstrap PR is merged).

    Returns:
        InstallReport with created/overwritten/skipped/errors lists. marker_path
        is set only when a marker was written (skipped during phase="bootstrap"
        -- see M-2 in the SKILL.md two-phase section).

    Raises:
        FileNotFoundError: target_dir is missing or not a directory, OR a
            template source file is missing (the plugin is incomplete).
        NotADirectoryError: target_dir exists but is a regular file/symlink
            to one.
        ValueError: phase is not one of None|'all'|'bootstrap'|'body'.
    """
    started = time.monotonic()

    if target_dir is None:
        raise FileNotFoundError("target_dir is None")
    target = Path(target_dir).resolve()
    if not target.exists():
        raise FileNotFoundError(f"target_dir does not exist: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"target_dir is not a directory: {target}")

    paths = _resolve_paths(phase)
    marker_phase = "all" if phase in (None, "all") else phase

    report = InstallReport()

    # Presence-based "already installed" detection: marker exists AND every
    # template file for this phase is present ⇒ nothing to copy.
    existing_marker = target / MARKER_REL
    if existing_marker.exists() and not force:
        if all((target / rel).exists() for rel in paths):
            report.skipped.extend(paths)
            report.marker_path = str(existing_marker)
            report.elapsed_ms = int((time.monotonic() - started) * 1000)
            if lint:
                report.warnings.extend(lint_installed_workflows(target))
            return report

    for rel in paths:
        try:
            outcome = _copy_template(rel, target, force=force)
        except Exception as e:
            report.errors.append(f"{rel}: {e}")
            continue
        if outcome == "created":
            report.created.append(rel)
        elif outcome == "overwritten":
            report.overwritten.append(rel)
        else:
            report.skipped.append(rel)

    # Set executable bit on shell-style files + validate.py (only for files
    # this phase actually touched).
    _chmod_executable(
        tuple(rel for rel in EXECUTABLE_PATHS if rel in paths),
        target,
    )

    # Marker contract: signals INSTALL COMPLETE. Skip during bootstrap
    # because scripts/hooks/rules/tests are intentionally absent at that
    # point — writing the marker here would mislead /dev-kit:build's
    # pre-flight gate (which only checks marker existence) into starting
    # against an incomplete install. The body phase writes the marker
    # as the final step.
    if marker_phase == "bootstrap":
        report.marker_path = ""  # intentionally empty
    else:
        marker = target / MARKER_REL
        _atomic_write_json(marker, _build_marker(phase=marker_phase))
        report.marker_path = str(marker)

    # Lint pass on installed workflows -- catches stale gate patterns and
    # other known-bad shapes that local validate.py + ci-local.sh pass.
    # Always runs on a fresh install; on a no-op idempotent re-install the
    # skill body may opt out via the kwarg below.
    if lint:
        report.warnings.extend(lint_installed_workflows(target))

    report.elapsed_ms = int((time.monotonic() - started) * 1000)

    if print_checklist and report.ok:
        _print_post_install_checklist(target, phase=marker_phase)

    return report


def preflight_probe(repo: str = "") -> List[ProbeResult]:
    """Run a 5-line `gh` probe against the consumer's environment.

    All gh calls are read-only and never print secret values. When `gh`
    is absent or unauthenticated, every probe returns SKIP and the skill
    prints a one-line note -- the user can still install without gh.
    """
    import json as _json
    import subprocess
    import re as _re
    results: List[ProbeResult] = []
    gh = shutil.which("gh")
    if not gh:
        results.append(ProbeResult("gh CLI", "SKIP", "gh not on PATH"))
        for label in (
            "Repo reachable",
            "DEV_KIT_GITHUB_TOKEN set",
            "MINIMAX_API_KEY set",
            "ANTHROPIC_API_KEY set (opt-in)",
        ):
            results.append(ProbeResult(label, "SKIP", "gh not on PATH"))
        return results

    def _run(args):
        cp = subprocess.run(
            [gh, *args], capture_output=True, text=True, timeout=10,
        )
        if cp.returncode == 0:
            return ProbeResult("placeholder", "OK", "")
        detail = ""
        if cp.stderr:
            detail = cp.stderr.strip().splitlines()[-1]
        return ProbeResult("placeholder", "WARN", detail)

    auth = _run(["auth", "status"])
    auth = ProbeResult("gh auth status", auth.state, auth.detail)
    if auth.state != "OK":
        for label in (
            "Repo reachable",
            "DEV_KIT_GITHUB_TOKEN set",
            "MINIMAX_API_KEY set",
            "ANTHROPIC_API_KEY set (opt-in)",
        ):
            results.append(ProbeResult(label, "SKIP", "gh not authenticated"))
        results.insert(0, auth)
        return results
    results.append(auth)

    if not repo:
        for label in (
            "Repo reachable",
            "DEV_KIT_GITHUB_TOKEN set",
            "MINIMAX_API_KEY set",
            "ANTHROPIC_API_KEY set (opt-in)",
        ):
            results.append(ProbeResult(label, "SKIP", "no repo context"))
        return results

    repo_view = _run(["repo", "view", repo, "--json", "name"])
    repo_view = ProbeResult("Repo reachable", repo_view.state, repo_view.detail)
    if repo_view.state != "OK":
        results.append(repo_view)
        for label in (
            "DEV_KIT_GITHUB_TOKEN set",
            "MINIMAX_API_KEY set",
            "ANTHROPIC_API_KEY set (opt-in)",
        ):
            results.append(ProbeResult(label, "SKIP", "repo not reachable"))
        return results
    results.append(repo_view)

    secrets_json = ""
    try:
        cp = subprocess.run(
            [gh, "secret", "list", "--repo", repo, "--json", "name"],
            capture_output=True, text=True, timeout=10,
        )
        if cp.returncode == 0:
            secrets_json = cp.stdout
    except Exception:
        pass

    secret_names = set()
    if secrets_json:
        try:
            secret_names = {
                row.get("name", "") for row in _json.loads(secrets_json)
            }
        except Exception:
            secret_names = set()

    for secret, state_when_missing in (
        ("DEV_KIT_GITHUB_TOKEN", "WARN"),
        ("MINIMAX_API_KEY", "WARN"),
        ("ANTHROPIC_API_KEY", "INFO"),
    ):
        present = secret in secret_names
        results.append(ProbeResult(
            label=f"{secret} set",
            state="OK" if present else state_when_missing,
            detail="" if present else "absent",
        ))

    return results


def _detect_owner_repo(target_dir: Path) -> str:
    """Best-effort `<OWNER>/<REPO>` from git remote, else empty string."""
    try:
        cp = subprocess.run(
            ["git", "-C", str(target_dir), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        if cp.returncode != 0 or not cp.stdout.strip():
            return ""
        url = cp.stdout.strip()
        # SSH: git@github.com:OWNER/REPO(.git)
        # HTTPS: https://github.com/OWNER/REPO(.git)
        m = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?/?$", url)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    except Exception:
        pass
    return ""


def _print_post_install_checklist(target_dir: Path, *, phase: str = "all") -> None:
    """Print the post-install checklist to stdout. Best-effort; never raises.

    When `phase="bootstrap"` was the last install, the checklist renders a
    single next-step pointer ("run `/dev-kit:ci-setup` (no flag) for the
    body phase") instead of the full 5-step checklist, since the consumer
    isn't done yet.
    """
    repo = _detect_owner_repo(target_dir) or "<OWNER>/<REPO>"
    print()
    if phase == "bootstrap":
        print("=== Bootstrap phase done — workflow files installed ===")
        print("  1. Open a PR with these changes and MERGE it.")
        print("       This lands the 3 workflow files on the default branch,")
        print("       which anthropics/claude-code-action needs to validate")
        print("       on every subsequent PR. Until then, the action skips")
        print("       on any PR that touches .github/workflows/*.")
        print("  2. Then run: /dev-kit:ci-setup")
        print("       (no flag — installs scripts/, hooks/, rules/, tests/)")
        print("       Open that PR; the action will now run because")
        print("       review.yml is stable on the default branch.")
        print()
        print(f"Marker: {target_dir / MARKER_REL}")
        return
    print("=== Post-install setup (do these IN ORDER) ===")
    for n, body in POST_INSTALL_CHECKLIST:
        body = body.replace("<OWNER>/<REPO>", repo)
        for line in body.split("\n"):
            if line.startswith("       "):
                print(f"     {line.lstrip()}")
            else:
                print(f"  {n}. {line}")
    print()
    print(f"Marker: {target_dir / MARKER_REL}")
    print("Verify: bash scripts/ci-local.sh")


# Patterns of known-bad install artifacts that the lint pass surfaces.
# Each entry: (path, substring, explanation). The lint is best-effort and
# never raises; matches become `InstallReport.warnings` entries so the
# skill body can print them in the summary table and the user can act on
# them (typically by re-running with `--force` to refresh the template).
_KNOWN_STALE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        ".github/workflows/review.yml",
        # Pre-0.1.3 gate hard-failed in pull_request mode on missing verdicts
        # while defaulting to Approve in workflow_dispatch mode. Internal
        # inconsistency that produced spurious CI failures on PRs whose
        # /dev-kit:* agents did not post a verdict comment.
        "Re-run via workflow_dispatch if needed",
        "stale pull_request hard-fail gate in review.yml -- the gate used to exit 1 with "
        "'Missing verdict' whenever the /dev-kit:* agents skipped posting a verdict comment, "
        "even though the gate's own documented intent (lines 354-358) tolerates missing "
        "verdicts and the workflow_dispatch branch already defaulted to Approve. Re-run with "
        "`--force` to refresh the template; the patched gate defaults missing verdicts to "
        "Approve with a ::warning:: in both event modes.",
    ),
)


def lint_installed_workflows(target_dir: Path) -> List[str]:
    """Scan installed EXPECTED_PATHS for known-stale patterns.

    Returns a list of human-readable findings (one per match). The intent
    is to surface patterns that previously made the install look healthy
    locally (validate.py + ci-local.sh both pass) but produced red CI in
    GitHub Actions. The skill body renders the findings in the install
    summary and the user can act on them -- the install itself is never
    blocked by lint output.
    """
    out: List[str] = []
    target = Path(target_dir).resolve()
    for rel, needle, explain in _KNOWN_STALE_PATTERNS:
        p = target / rel
        if not p.is_file():
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if needle in content:
            out.append(f"{rel}: {explain}")
    return out


def _self_test() -> int:
    """Quick CLI sanity check — invoke as `python lib/ci_setup.py`. Exits 0 on OK."""
    target = Path.cwd()
    print(f"ci_setup.py self-test — target={target}")
    print(f"  plugin_root={_PLUGIN_ROOT}")
    print(f"  templates_root={_TEMPLATES_ROOT}")
    if not _TEMPLATES_ROOT.is_dir():
        print(f"FAIL: templates dir missing: {_TEMPLATES_ROOT}", file=sys.stderr)
        return 1
    expected = list(_TEMPLATES_ROOT.rglob("*"))
    files = [str(p.relative_to(_TEMPLATES_ROOT)) for p in expected if p.is_file()]
    print(f"  found {len(files)} template files")
    missing = [r for r in EXPECTED_PATHS if not (_TEMPLATES_ROOT / r).exists()]
    if missing:
        print(f"FAIL: missing templates: {missing}", file=sys.stderr)
        return 1
    print("OK: all EXPECTED_PATHS present in templates/")
    return 0


if __name__ == "__main__":
    sys.exit(_self_test())
