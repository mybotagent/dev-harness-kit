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
# Plugin release tag written into the marker as `ci_setup_version`. Read by
# skills/build/SKILL.md as a lexicographic pre-flight gate (>= "0.1.0"). Bump
# in the same commit that lands a build-gate-visible change so a fresh
# `bootstrap → ci-setup → build` flow never trips the default-`"0.0.0"` fallback.
# Kept in sync with templates/ci/ci-config.example.json contract.
PLUGIN_CI_SETUP_VERSION = "0.1.0"

# Per-skill semver (PEP 440 via packaging.version.Version). Used by
# extract_skill_versions() to read each skill's `version:` frontmatter and
# by validate_min_skill_versions() to compare installed vs consumer floor.
# Pre-release sort must work: 0.1.0-rc.1 < 0.1.0.
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


def _parse_skill_frontmatter(path: Path) -> dict:
    """Read a SKILL.md file and return the YAML frontmatter as a dict.

    Self-contained: regex-based key scan, NO external `yaml` dependency.
    Rationale: `lib/ci_setup.py` runs on consumer CI runners whose Python
    may not have `pyyaml` installed (CI installs only `pytest` per
    .github/workflows/ci.yml). A yaml import that fails at runtime would
    silently turn every skill into `{"version": None}` and trip the
    extract_skill_versions ValueError on first call. The regex approach
    only extracts scalar values per top-level key; for the values
    extract_skill_versions actually consumes (`name`, `version`) this is
    sufficient.

    Returns {} on missing/malformed frontmatter.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != "---":
        return {}
    end = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            end = i
            break
    if end is None:
        return {}
    # Walk the frontmatter block as top-level scalar keys. A `key: value`
    # on its own line is a scalar. A `key: |` is a block scalar whose
    # value spans indented lines; we collect its text but don't parse it
    # as YAML (caller only needs `name` + `version`, both scalars).
    result: dict = {}
    i = 1
    while i < end:
        line = lines[i]
        if not line or line[0] in (" ", "\t", "#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key = m.group(1)
        tail = m.group(2).rstrip()
        if tail == "|" or tail == ">":
            # Block scalar (literal / folded). Indented continuation lines
            # follow; capture them as a single string until next
            # top-level key or end of frontmatter.
            buf: list = []
            i += 1
            while i < end and (lines[i].startswith((" ", "\t")) or lines[i] == ""):
                buf.append(lines[i].strip())
                i += 1
            result[key] = "\n".join(buf).strip()
            continue
        # Strip surrounding quotes if present
        if len(tail) >= 2 and tail[0] in ('"', "'") and tail[-1] == tail[0]:
            tail = tail[1:-1]
        result[key] = tail
        i += 1
    return result


def extract_skill_versions(plugin_root: Path) -> dict:
    """Read every `skills/*/SKILL.md` under `plugin_root` and return {name: version}.

    Walks the top-level skills/ directory (flat layout per
    .claude/rules/skill-authoring.md). For each skill directory containing a
    SKILL.md, parses the frontmatter and extracts the `version:` field. The
    field must match SEMVER_RE — otherwise the skill is listed in a
    `ValueError` (so a missing/invalid version surfaces in CI rather than
    silently being treated as 0.0.0).

    Args:
        plugin_root: absolute path to the dev-harness-kit checkout (the
            directory that contains the `skills/` folder).

    Returns:
        Dict mapping skill name → semver string, e.g. `{"build": "0.1.0", ...}`.

    Raises:
        ValueError: one or more skills are missing the `version:` field or
            the value does not match SEMVER_RE. The exception message lists
            every offender so a single CI run shows the full set.
    """
    skills_dir = plugin_root / "skills"
    if not skills_dir.is_dir():
        return {}
    result: dict = {}
    missing: list = []
    invalid: list = []
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.exists():
            continue
        meta = _parse_skill_frontmatter(skill_md)
        name = meta.get("name") or child.name
        version = meta.get("version")
        if version is None or version == "":
            missing.append(name)
            continue
        if not isinstance(version, str) or not SEMVER_RE.match(version):
            invalid.append(f"{name}={version!r}")
            continue
        result[name] = version
    problems: list = []
    if missing:
        problems.append(f"missing version: {', '.join(missing)}")
    if invalid:
        problems.append(f"invalid semver: {', '.join(invalid)}")
    if problems:
        raise ValueError(
            "skills with bad version frontmatter — " + "; ".join(problems)
        )
    return result


def _build_marker(min_skill_versions: dict | None = None) -> dict:
    """Build the `.dev-kit/ci-config.json` payload.

    Args:
        min_skill_versions: consumer's opt-in floor, preserved across
            `--force` rewrites. `None` means "no prior value" → the field
            is written as `{}` (permissive default). The argument is
            explicit so callers can't accidentally clobber a consumer's
            floor by omitting it.
    """
    return {
        "schema_version": MARKER_SCHEMA_VERSION,
        "ci_setup_version": PLUGIN_CI_SETUP_VERSION,
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
        # Per-skill version mirror (auto-written; read by validate.py for
        # the PR build gate). Live source of truth is skills/<name>/SKILL.md
        # frontmatter in this dev-kit checkout; mirrored here so consumer
        # PRs don't have to read dev-kit source files.
        "installed_skill_versions": extract_skill_versions(_PLUGIN_ROOT),
        # Consumer's opt-in floor. Empty {} = no constraint (permissive
        # default; no behavior change for consumers who never edit it).
        "min_skill_versions": dict(min_skill_versions) if min_skill_versions else {},
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
    # Preserve the consumer's opt-in min_skill_versions floor so a
    # `ci-setup --force` does NOT clobber a deliberate declaration. Read
    # the existing marker (if any) just before the write; absent or
    # unparseable → default to empty (permissive).
    marker = target / MARKER_REL
    preserved_min: dict = {}
    if existing_marker.exists():
        try:
            existing_data = json.loads(existing_marker.read_text(encoding="utf-8"))
            if isinstance(existing_data, dict):
                raw = existing_data.get("min_skill_versions")
                if isinstance(raw, dict):
                    preserved_min = raw
        except (OSError, json.JSONDecodeError):
            preserved_min = {}
    _atomic_write_json(marker, _build_marker(min_skill_versions=preserved_min))
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
