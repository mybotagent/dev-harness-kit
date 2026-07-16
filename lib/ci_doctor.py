"""ci_doctor.py — Read-only CI readiness audit for `/dev-kit:ci-doctor`.

Issue #212-D1: after `/dev-kit:bootstrap-full`, a consumer has no way to
answer "given my current secrets + files + workflow templates, would the
CI on my next PR succeed?" This module answers that question with a
deterministic, read-only check suite. Every probe is side-effect-free:
no files mutated, no secrets written, no PRs opened.

Engine for the `/dev-kit:ci-doctor` skill. Pure stdlib, no external
deps. Returns a `DoctorReport` dataclass; the skill body renders the
PASS/FAIL summary.

Usage:
    from lib.ci_doctor import audit
    report = audit(target_dir=Path('/path/to/repo'))
    print(report.summary_lines())

Public surface:
    audit(target_dir, *, provider=None) -> DoctorReport
    DoctorReport          # dataclass with `checks` + `summary_lines()`
    Check                  # one row of the audit table
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


# Lazy import of ci_setup to avoid a circular dep. The provider catalog +
# reader live there; this module is read-only and never writes.
def _ci_setup():
    import importlib.util as ilu
    name = "ci_setup"
    spec = ilu.spec_from_file_location(
        name, Path(__file__).resolve().parent / "ci_setup.py"
    )
    mod = ilu.module_from_spec(spec)
    import sys
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@dataclass
class Check:
    """One row of the audit table.

    `state` is one of:
      - PASS : check passed (marker present, secret configured, etc.)
      - FAIL : check failed (file missing, secret absent, gh not authed)
      - SKIP : check could not run (gh absent, repo context missing)
      - INFO : informational only (e.g. opt-in secret absent)
    """

    label: str
    state: str
    detail: str = ""

    def row(self) -> str:
        tag = self.state
        return f"[{tag:<4}] {self.label}: {self.detail}".rstrip()


@dataclass
class DoctorReport:
    """Aggregate audit result.

    `checks` is the ordered list of `Check` rows. `ok` is True iff every
    PASS-or-INFO check passed AND no FAIL was recorded. SKIP rows are
    advisory (e.g. gh absent) and do not flip `ok` to False — a consumer
    without gh can still install templates, just can't verify them
    end-to-end.
    """

    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.state != "FAIL" for c in self.checks)

    def failing(self) -> list[Check]:
        return [c for c in self.checks if c.state == "FAIL"]

    def summary_lines(self) -> list[str]:
        """Render a PASS/FAIL summary table for stdout."""
        lines: list[str] = []
        verdict = "PASS" if self.ok else "FAIL"
        fail_count = len(self.failing())
        skip_count = sum(1 for c in self.checks if c.state == "SKIP")
        lines.append(f"ci-doctor verdict: {verdict}")
        lines.append(f"  checks: {len(self.checks)}  failing: {fail_count}  skipped: {skip_count}")
        for c in self.checks:
            lines.append(f"  {c.row()}")
        return lines


# Files the install MUST leave behind (subset of ci_setup.EXPECTED_PATHS
# that gates next-PR viability). Workflows + marker + provider selector.
REQUIRED_FILES: tuple[str, ...] = (
    ".github/workflows/ci.yml",
    ".github/workflows/review.yml",
    ".github/workflows/auto-fix-pr.yml",
    ".github/ci-review-provider.txt",
    ".dev-kit/ci-config.json",
)


def _detect_owner_repo(target_dir: Path) -> str:
    """Mirror ci_setup._detect_owner_repo — duplicated here to avoid
    importing the writer module for a read-only audit."""
    try:
        cp = subprocess.run(
            ["git", "-C", str(target_dir), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        if cp.returncode != 0 or not cp.stdout.strip():
            return ""
        url = cp.stdout.strip()
        m = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?/?$", url)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    except (subprocess.SubprocessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""
    return ""


def _list_repo_secrets(repo: str) -> tuple[set[str], str]:
    """Return (set-of-secret-names, degraded-message).

    When gh is absent or unauthenticated, returns an empty set and a
    non-empty degraded message; the caller should surface that as a SKIP
    rather than a FAIL (the user might just not be running this locally
    with gh auth).
    """
    gh = shutil.which("gh")
    if not gh:
        return set(), "gh not on PATH"
    try:
        cp = subprocess.run(
            [gh, "auth", "status"],
            capture_output=True, text=True, timeout=10,
        )
        if cp.returncode != 0:
            return set(), "gh not authenticated"
    except (subprocess.SubprocessError, subprocess.TimeoutExpired, OSError) as e:
        return set(), f"gh auth error: {e}"
    try:
        cp = subprocess.run(
            [gh, "secret", "list", "--repo", repo, "--json", "name"],
            capture_output=True, text=True, timeout=10,
        )
        if cp.returncode != 0:
            err = (cp.stderr or "").strip().splitlines()[-1] if cp.stderr else ""
            return set(), f"gh secret list failed: {err or 'unknown'}"
        names = {row.get("name", "") for row in json.loads(cp.stdout)}
        return names, ""
    except (subprocess.SubprocessError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as e:
        return set(), f"gh secret list error: {e}"


def _check_required_files(target: Path) -> list[Check]:
    out: list[Check] = []
    for rel in REQUIRED_FILES:
        p = target / rel
        if not p.is_file():
            out.append(Check(f"file present: {rel}", "FAIL", "missing"))
        else:
            size = p.stat().st_size
            out.append(Check(f"file present: {rel}", "PASS", f"{size} bytes"))
    return out


def _check_marker_payload(target: Path) -> list[Check]:
    marker = target / ".dev-kit" / "ci-config.json"
    if not marker.is_file():
        return [Check("marker parseable", "FAIL", ".dev-kit/ci-config.json missing")]
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [Check("marker parseable", "FAIL", f"parse error: {e}")]
    out = [Check("marker parseable", "PASS", "JSON ok")]
    if not isinstance(payload, dict) or not payload:
        out.append(Check("marker non-empty", "FAIL", "empty payload"))
    else:
        out.append(Check("marker non-empty", "PASS", f"{len(payload)} keys"))
    if payload.get("ci_review_provider_file") != ".github/ci-review-provider.txt":
        out.append(Check(
            "marker records provider file", "FAIL",
            "expected `.github/ci-review-provider.txt`",
        ))
    else:
        out.append(Check("marker records provider file", "PASS", ""))
    return out


def _check_provider_file(target: Path) -> list[Check]:
    p = target / ".github" / "ci-review-provider.txt"
    if not p.is_file():
        return [Check("provider file content", "FAIL", "file missing")]
    raw = p.read_text(encoding="utf-8").strip().lower()
    cs = _ci_setup()
    if not raw:
        return [Check("provider file content", "FAIL", "empty")]
    if raw not in cs.PROVIDER_SECRETS:
        return [Check("provider file content", "FAIL", f"unknown provider '{raw}'")]
    return [Check("provider file content", "PASS", raw)]


def _check_secrets(target: Path, provider: str | None) -> list[Check]:
    repo = _detect_owner_repo(target)
    if not repo:
        return [Check("repo context", "SKIP", "no GitHub remote on origin")]
    secrets, degraded = _list_repo_secrets(repo)
    if degraded:
        return [Check("repo secrets", "SKIP", degraded)]
    cs = _ci_setup()
    provider = provider or cs.read_provider_file(target)
    needed = cs.required_secrets_for_provider(provider)
    out: list[Check] = []
    for name in needed:
        if name in secrets:
            out.append(Check(f"secret set: {name}", "PASS", ""))
        else:
            out.append(Check(f"secret set: {name}", "FAIL",
                             f"run: {cs.gh_secret_set_command(repo, name)}"))
    return out


def _check_gh_auth() -> Check:
    gh = shutil.which("gh")
    if not gh:
        return Check("gh CLI", "SKIP", "gh not on PATH")
    try:
        cp = subprocess.run(
            [gh, "auth", "status"], capture_output=True, text=True, timeout=5,
        )
    except (subprocess.SubprocessError, subprocess.TimeoutExpired, OSError) as e:
        return Check("gh auth", "FAIL", f"gh auth error: {e}")
    return Check(
        "gh auth", "PASS" if cp.returncode == 0 else "FAIL",
        (cp.stderr or "").strip() if cp.returncode != 0 else "",
    )


def audit(target_dir: Path, *, provider: str | None = None) -> DoctorReport:
    """Run the full check suite. Side-effect free.

    Args:
        target_dir: repo root to audit (defaults to a fresh tmpdir would
            also work; pass the real consumer path for an honest answer).
        provider: override the provider selection (default = read from
            `.github/ci-review-provider.txt`). Used by tests.

    Returns:
        DoctorReport with one row per check.
    """
    target = Path(target_dir).resolve()
    if not target.is_dir():
        return DoctorReport(checks=[
            Check("target dir", "FAIL", f"not a directory: {target}"),
        ])
    report = DoctorReport()
    report.checks.append(Check("target dir", "PASS", str(target)))
    report.checks.extend(_check_required_files(target))
    report.checks.extend(_check_marker_payload(target))
    report.checks.extend(_check_provider_file(target))
    report.checks.append(_check_gh_auth())
    report.checks.extend(_check_secrets(target, provider))
    return report


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    r = audit(target)
    for line in r.summary_lines():
        print(line)
    sys.exit(0 if r.ok else 1)
