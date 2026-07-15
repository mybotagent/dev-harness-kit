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
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List

# Atomic write helper. We import from `atomic` (the canonical lib module)
# rather than redefining it inline: `lib/install.sh` ships `atomic.py` to
# `target/lib/` alongside `ci_setup.py` (see `lib/install.sh:53` for the
# copy loop and `:94` for the install-verification assertion). Using a
# single canonical implementation ensures future improvements to
# `lib/atomic.atomic_write_json` (fsync-on-replace, mode preservation,
# locale-safe tmp prefix, fallback `default=str`) automatically land in
# the marker-write path here. See issue #90.
from atomic import atomic_write_json

# Plugin root (resolved via __file__ so the module is location-independent).
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES_ROOT = _PLUGIN_ROOT / "templates" / "ci"
_HOOKS_ROOT = _PLUGIN_ROOT / "hooks"  # single source of truth for hook files

# Files installed into the target repo, relative to `target_dir`.
# Order is preserved in reports (workflows first, then scripts, then
# worktree-rule files). Adding a path here also requires the corresponding
# source under templates/ci/ OR hooks/ (worktree-rule files live in the
# latter — see `_resolve_template_source`).
EXPECTED_PATHS: tuple[str, ...] = (
    # CI workflows + scripts
    ".github/workflows/ci.yml",
    ".github/workflows/auto-fix-pr.yml",
    ".github/workflows/review.yml",
    ".githooks/pre-push",
    "scripts/validate.py",
    "scripts/test.sh",
    "scripts/branch-policy.sh",
    "scripts/ci-local.sh",
    # Worktree-rule enforcement (every task = new worktree + subagent handoff
    # + new branch). Source is canonical rules/; destination remains
    # .claude/rules/ for Claude Code discovery.
    "hooks/worktree-guard.sh",
    "hooks/task-detector.sh",
    "hooks/session-start-check.sh",
    "hooks/lib/worktree-detect.sh",
    "hooks/hooks.json",
    ".claude/rules/git-workflow.md",
    "tests/test_worktree_guard.py",
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
# Marker schema is content-only (no per-field version gate). Content is the
# source of truth; _copy_template skips when bytes match.
MARKER_SCHEMA_VERSION = "1.0.0"
# Plugin release tag — there is NO constant here. The canonical plugin
# version is `.claude-plugin/plugin.json:version`, read at runtime via
# `plugin_version(_PLUGIN_ROOT)`. Hardcoding a release tag was the source
# of a version-drift bug (see PR #111): every plugin bump had to chase
# a Python constant and a template literal. Derive at runtime instead.

# Semver 2.0.0 format (X.Y.Z with optional `-prerelease`/`+build`). Used to
# validate `.claude-plugin/plugin.json:version` shape (see plugin_version()).
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

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
    ("4", "Push a feature branch; open a PR that does NOT modify "
          ".github/workflows/*.\n"
          "       /dev-kit:review + /dev-kit:security should fire."),
    ("5", "The first PR that ADDS review.yml cannot have the action validated "
          "by the\n"
          "       severity gate until review.yml lands on the default branch. "
          "Merge that\n"
          "       bootstrap PR first; the gate works on every PR after."),
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


def _resolve_template_source(rel_path: str) -> Path:
    """Resolve an EXPECTED_PATHS entry to its on-disk source path.

    Most templates live under `templates/ci/`. Worktree-rule files (hooks,
    rules, tests) live at the plugin root (`hooks/`, `rules/`,
    `tests/`) because that is where they are developed and tested by the
    dev-harness-kit repo itself — keeping a parallel copy under
    `templates/ci/` historically caused silent byte drift across consumer
    installs. See issue #89.

    Returns the absolute source path; raises FileNotFoundError if the
    resolved source does not exist.
    """
    # Hook files: read from the plugin-root hooks/ tree (single source of
    # truth, shared with the project's own .claude/settings.json).
    if rel_path.startswith("hooks/"):
        candidate = _HOOKS_ROOT / rel_path[len("hooks/"):]
        if not candidate.exists():
            raise FileNotFoundError(f"hook source missing: {candidate}")
        return candidate
    # Canonical shared rules live at plugin-root rules/. They are installed
    # under .claude/rules/ in consumer repos because Claude Code discovers
    # project rules from that compatibility location.
    if rel_path == ".claude/rules/git-workflow.md":
        candidate = _PLUGIN_ROOT / "rules" / "git-workflow.md"
        if not candidate.exists():
            raise FileNotFoundError(f"rule source missing: {candidate}")
        return candidate
    # Default: read from the templates/ci/ tree.
    candidate = _TEMPLATES_ROOT / rel_path
    if not candidate.exists():
        raise FileNotFoundError(f"template source missing: {candidate}")
    return candidate


def _copy_template(rel_path: str, target_dir: Path, *, force: bool) -> str:
    """Copy one template file. Returns 'created' | 'overwritten' | 'skipped'.

    Raises FileNotFoundError if the template source is missing (treated as
    a programmer/install error, not a runtime idem-key collision).

    Source resolution: see `_resolve_template_source` (issue #89 split).
    """
    src = _resolve_template_source(rel_path)
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


def plugin_version(plugin_root: Path | None = None) -> str:
    """Read the canonical plugin version from `.claude-plugin/plugin.json`.

    Single source of truth for the plugin's release tag. There is no
    fallback constant — when `plugin.json` is missing or unreadable,
    returns `"0.0.0"` (the sentinel that means "no release tag pinned
    yet", i.e. an in-development checkout, not a published release).

    Args:
        plugin_root: absolute path to the dev-harness-kit checkout. When
            `None` (the default), uses `_PLUGIN_ROOT` (this module's
            parent-of-parent).

    Returns:
        The `version:` field as a string, e.g. `"0.3.0"`, or `"0.0.0"`
        when the manifest can't be read.
    """
    root = plugin_root or _PLUGIN_ROOT
    manifest = root / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        v = data.get("version")
        if isinstance(v, str) and v:
            return v
    except (OSError, json.JSONDecodeError):
        pass
    return "0.0.0"  # sentinel — not a published release


def _installed_snapshot_root() -> Path:
    """Return the path the running skill should treat as the installed snapshot.

    Defaults to the Claude Code plugin cache layout
    (`~/.claude/plugins/cache/dev-kit/dev-kit/<version>/`), with a
    marketplace-clone fallback (`~/.claude/plugins/marketplaces/dev-kit/`).
    Override `DEV_KIT_INSTALLED_ROOT` to test or run offline.
    """
    override = os.environ.get("DEV_KIT_INSTALLED_ROOT")
    if override:
        return Path(override)
    cache = Path.home() / ".claude" / "plugins" / "cache" / "dev-kit" / "dev-kit"
    if cache.is_dir():
        versions = sorted([p for p in cache.iterdir() if p.is_dir()])
        if versions:
            return versions[-1]  # semver-max / last created
    marketplace = Path.home() / ".claude" / "plugins" / "marketplaces" / "dev-kit"
    if marketplace.is_dir():
        return marketplace
    return Path()


def per_skill_drift(plugin_root: Path) -> dict:
    """Compare per-skill SKILL.md file content between HEAD and the installed snapshot.

    No frontmatter parsing, no per-skill version metadata. We diff raw
    content; if the bytes differ, the skill on the user's installed
    snapshot is "behind HEAD." Drift detection at this resolution is
    cheaper to maintain (no per-skill bookkeeping), honest (the user's
    installed copy may differ from HEAD in ways a version number
    doesn't capture), and good-enough (skill content diff is the ground
    truth for "did this skill change?").

    Args:
        plugin_root: absolute path to the dev-harness-kit checkout
            (the directory that contains `skills/`).

    Returns:
        dict[str, str] mapping skill name → drift tag:
          - `"behind"` if the installed snapshot's SKILL.md bytes differ
            from HEAD's (or the snapshot is missing the file)
          - `"ahead"` if the snapshot has a SKILL.md that HEAD doesn't
            (skill was deleted upstream — unusual)
          - `"current"` if bytes match
          - `"no_install"` if the snapshot root is missing (fresh
            install pre-first-refresh — every skill is `"no_install"`)

        Empty dict if `plugin_root/skills/` is missing.
    """
    skills_dir = plugin_root / "skills"
    if not skills_dir.is_dir():
        return {}
    installed_root = _installed_snapshot_root()
    has_install = bool(installed_root and installed_root.is_dir())
    result: dict = {}
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.exists():
            continue
        head_bytes = skill_md.read_bytes()
        if not has_install:
            result[child.name] = "no_install"
            continue
        installed_skill = installed_root / "skills" / child.name / "SKILL.md"
        if not installed_skill.exists():
            result[child.name] = "behind"
            continue
        if installed_skill.read_bytes() == head_bytes:
            result[child.name] = "current"
        else:
            result[child.name] = "behind"
    return result


def _build_marker() -> dict:
    """Build the `.dev-kit/ci-config.json` payload.

    Content-only marker — no version field. The plugin's version lives
    solely in `.claude-plugin/plugin.json` (see `plugin_version()`); dev-kit
    does not gate consumer builds on a version comparison.
    """
    return {
        "schema_version": MARKER_SCHEMA_VERSION,
        "installed_at": _now_utc_iso(),
        "installed_by": "dev-kit:ci-setup",
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


def install_ci_config(
    target_dir: Path,
    *,
    force: bool = False,
    print_checklist: bool = False,
    lint: bool = True,
) -> InstallReport:
    """Install dev-kit's CI templates into `target_dir`. Idempotent + content-aware.

    A no-op (all files skipped, marker reused) when the marker exists and every
    EXPECTED_PATHS file is already in place. With `force=True`, all template
    files are overwritten regardless.

    Args:
        target_dir: absolute path to the target project root. Must exist
            and be a directory (raises FileNotFoundError otherwise).
        force: when True, overwrite existing target files matching
            EXPECTED_PATHS. Default False (skip + report).
        print_checklist: when True and the install succeeds (no errors),
            print the post-install checklist after the marker is written.
            Default False to preserve existing test contracts.

    Returns:
        InstallReport with created/overwritten/skipped/errors lists and the
        path to the marker file (always written unless target is read-only).

    Raises:
        FileNotFoundError: target_dir is missing or not a directory, OR a
            template source file is missing (the plugin is incomplete).
        NotADirectoryError: target_dir exists but is a regular file/symlink
            to one.
    """
    started = time.monotonic()

    if target_dir is None:
        raise FileNotFoundError("target_dir is None")
    target = Path(target_dir).resolve()
    if not target.exists():
        raise FileNotFoundError(f"target_dir does not exist: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"target_dir is not a directory: {target}")

    report = InstallReport()

    # Presence-based "already installed" detection: marker exists AND every
    # template file is present ⇒ nothing to copy. Phase 1 of the skill body
    # can still detect "already installed" via marker_path.
    existing_marker = target / MARKER_REL
    if existing_marker.exists() and not force:
        if all((target / rel).exists() for rel in EXPECTED_PATHS):
            report.skipped.extend(EXPECTED_PATHS)
            report.marker_path = str(existing_marker)
            report.elapsed_ms = int((time.monotonic() - started) * 1000)
            if lint:
                report.warnings.extend(lint_installed_workflows(target))
            return report

    for rel in EXPECTED_PATHS:
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

    # Set executable bit on shell-style files + validate.py.
    _chmod_executable(EXECUTABLE_PATHS, target)

    # Write marker (overwrites on force, always succeeds idempotently).
    marker = target / MARKER_REL
    atomic_write_json(marker, _build_marker())
    report.marker_path = str(marker)

    # Lint pass on installed workflows -- catches stale gate patterns and
    # other known-bad shapes that local validate.py + ci-local.sh pass.
    # Always runs on a fresh install; on a no-op idempotent re-install the
    # skill body may opt out via the kwarg below.
    if lint:
        report.warnings.extend(lint_installed_workflows(target))

    report.elapsed_ms = int((time.monotonic() - started) * 1000)

    if print_checklist and report.ok:
        _print_post_install_checklist(target)

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
    secrets_degraded = ""
    try:
        cp = subprocess.run(
            [gh, "secret", "list", "--repo", repo, "--json", "name"],
            capture_output=True, text=True, timeout=10,
        )
        if cp.returncode == 0:
            secrets_json = cp.stdout
    except (
        subprocess.SubprocessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
        OSError,
    ) as e:
        # Surface the failure mode so the user can distinguish "secret
        # not configured" from "probe could not run" (issue #92).
        secrets_degraded = f"degraded: {type(e).__name__}: {e}"

    secret_names = set()
    if secrets_json:
        try:
            secret_names = {
                row.get("name", "") for row in _json.loads(secrets_json)
            }
        except (_json.JSONDecodeError, ValueError, TypeError):
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
            detail="" if present else secrets_degraded or "absent",
        ))

    return results


def _detect_owner_repo(target_dir: Path) -> str:
    """Best-effort `<OWNER>/<REPO>` from git remote.

    Returns `<OWNER>/<REPO>` on success. On failure (no git, no remote,
    non-GitHub remote, timeout), returns the literal `<OWNER>/<REPO>`
    placeholder with a `(auto-detect failed: <ExceptionType>)` suffix
    so the post-install checklist still renders usefully AND the user
    sees WHY auto-detection failed (issue #92 bug 2). Never raises.
    """
    placeholder = "<OWNER>/<REPO>"
    try:
        cp = subprocess.run(
            ["git", "-C", str(target_dir), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        if cp.returncode != 0 or not cp.stdout.strip():
            return f"{placeholder} (auto-detect failed: no remote)"
        url = cp.stdout.strip()
        # SSH: git@github.com:OWNER/REPO(.git)
        # HTTPS: https://github.com/OWNER/REPO(.git)
        m = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?/?$", url)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
        return f"{placeholder} (auto-detect failed: remote is not GitHub)"
    except (
        subprocess.SubprocessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
        OSError,
    ) as e:
        return f"{placeholder} (auto-detect failed: {type(e).__name__})"


def _print_post_install_checklist(target_dir: Path) -> None:
    """Print the post-install checklist to stdout. Best-effort; never raises."""
    repo = _detect_owner_repo(target_dir) or "<OWNER>/<REPO>"
    print()
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
