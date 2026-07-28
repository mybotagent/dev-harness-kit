#!/usr/bin/env python3
"""dev-kit-lcs-route.py -- NL-to-URI router with break-even rule.

Implements Gap 1 of the LCS UX proposal (issue #455). A thin,
deterministic classifier that decides whether a natural-language
operator question should be answered by a single shell call or routed
to the Live Context Server (LCS).

Break-even rule (the entire router in one sentence):

    If a single shell call answers the question, use the shell.
    If it requires N correlated calls across heterogeneous sources,
    route to LCS.

This binary is a plain CLI, NOT a skill: a skill that decides whether
to call another skill is the L6 anti-pattern (a stateless reasoning
surface that next-gen models absorb). The router is a deterministic
classifier + URI lookup table -- the deterministic part is what stops
the model from re-deciding the routing on every invocation.

CLI surface:

    python3 bin/dev-kit-lcs-route.py "what branch am I on?"
    # → emits a JSON verdict on stdout
    # {"question": "...", "verdict": "shell", "rule_id": "...", "reason": "..."}

    python3 bin/dev-kit-lcs-route.py --invoke "what worktrees are stale?"
    # → invokes dev-kit-lcs.py --get lcs://worktrees (the LCS CLI owns stdout/exit)

    python3 bin/dev-kit-lcs-route.py --list-rules
    # → prints the break-even rule table as JSON

Exit codes:
  0  success (verdict emitted or --list-rules printed)
  1  invalid arguments (argparse's default for unknown args)
  2  empty question (stdin / argv) -- with stderr message
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent
_LCS_CLI = _HERE.parent / "dev-kit-lcs.py"

# ──────────────────────────────────────────────────────────────────
# Break-even rule table (mirrors proposal Gap 1, ordered by priority)
# ──────────────────────────────────────────────────────────────────
#
# Order matters: the first matching rule wins. Shell rules come first
# so a one-tool question never pays the LCS classifier overhead; the
# spend/sessions/pr rules come before the generic worktrees rule so
# "token spend per worktree" routes to spend (the primary intent) and
# not to the worktrees resource the question happens to mention.

RULES: list[dict] = [
    # ── shell wins (one tool answers) ────────────────────────────
    {
        "rule_id": "shell-current-branch",
        "verdict": "shell",
        "shell_cmd": "git branch --show-current",
        "reason": "single shell call: git branch --show-current",
        "_pattern": re.compile(
            r"^\s*(what(?:'?s| is)?\s+)?(the\s+)?"
            r"(current\s+)?branch(\s+(?:am\s+i|i'?m|i\s+am)\s+on"
            r"|\s+name|\s+now)?\s*\??\s*$",
            re.IGNORECASE,
        ),
    },
    {
        "rule_id": "shell-head-sha",
        "verdict": "shell",
        "shell_cmd": "git rev-parse HEAD",
        "reason": "single shell call: git rev-parse HEAD",
        "_pattern": re.compile(
            r"\b(head\s+sha|commit\s+sha|current\s+commit|head\s+commit"
            r"|latest\s+commit|what'?s\s+head|what\s+is\s+head)\b",
            re.IGNORECASE,
        ),
    },
    {
        "rule_id": "shell-working-tree-dirty",
        "verdict": "shell",
        "shell_cmd": "git status --porcelain",
        "reason": "single shell call: git status --porcelain",
        "_pattern": re.compile(
            r"\b(is\s+the\s+(?:working\s+tree|wt|worktree)?\s*"
            r"(?:dirty|clean)|uncommitted\s+changes?"
            r"|working\s+tree\s+(?:dirty|clean))\b",
            re.IGNORECASE,
        ),
    },
    {
        "rule_id": "shell-pwd",
        "verdict": "shell",
        "shell_cmd": "pwd",
        "reason": "single shell call: pwd",
        "_pattern": re.compile(
            r"^\s*(what(?:'?s| is)?\s+)?(the\s+)?(current\s+)?"
            r"(working\s+)?(directory|cwd|pwd)"
            r"(\s+(?:am\s+i|i'?m|i\s+am)\s+in)?\s*\??\s*$",
            re.IGNORECASE,
        ),
    },
    # ── lcs wins (N correlated calls) ────────────────────────────
    {
        "rule_id": "lcs-spend",
        "verdict": "lcs",
        "uri_template": "lcs://spend/{window}",
        "reason": "multi-source: walk logs/**/*.jsonl + parse + bucket",
        # spend/usage/cost in either direction; optional trailing window
        # (last 24h, past 7d). The optional group lets the rule match
        # "what's the spend?" (no window) AND "token spend ... last 24h?"
        # -- the template strips the placeholder when no window is captured.
        "_pattern": re.compile(
            r"\b(?:spend|token\s+spend|token\s+usage|token\s+cost)s?\b"
            r"(?:.*?(?:\blast|past)\s+"
            r"(?P<window>\d+\s*[hHdDm]"
            r"|\d+\s*(?:hour|day|minute)s?))?",
            re.IGNORECASE,
        ),
    },
    {
        "rule_id": "lcs-sessions",
        "verdict": "lcs",
        "uri_template": "lcs://sessions/{id}",
        "reason": "multi-source: scan runtime transcripts",
        "_pattern": re.compile(
            r"\b(?:session|agent\s+session|active\s+session)s?\b"
            r"(?:\s+(?:is\s+)?(?:doing|running|with\s+id)\s+"
            r"(?P<id>[\w./-]+))?",
            re.IGNORECASE,
        ),
    },
    {
        "rule_id": "lcs-pr",
        "verdict": "lcs",
        "uri_template": "lcs://pr/{n}",
        "reason": "needs gh pr checks + gh run view + slot cross-ref",
        "_pattern": re.compile(
            r"\bpr\s*#?\s*(?P<n>\d+)\b"
            r"|\b(?:ci|slot|status|checks?|review|verdict)\s+"
            r"(?:on|for|of)\s+pr\s*#?\s*(?P<n2>\d+)\b",
            re.IGNORECASE,
        ),
    },
    {
        "rule_id": "lcs-branch-slot",
        "verdict": "lcs",
        "uri_template": "lcs://branches/{name}/slot",
        "reason": "partial: needs path resolution + cat plugin.json",
        "_pattern": re.compile(
            r"\bslot\s+(?:version|state)?\s+(?:on|for|of)\s+"
            r"(?:branch\s+)?(?P<name>[\w./-]+)"
            r"|\bbranch\s+(?P<name2>[\w./-]+)\s+slot\b",
            re.IGNORECASE,
        ),
    },
    {
        "rule_id": "lcs-worktrees-stale",
        "verdict": "lcs",
        "uri": "lcs://worktrees",
        "reason": "needs git worktree list + per-tree age + per-tree slot version",
        # Match either direction (worktrees→staleness OR staleness→worktrees)
        # so the operator can phrase it either way.
        "_pattern": re.compile(
            r"\b(stale|zombie|drift|behind\s+main)\b.*?\bworktrees?"
            r"|\bworktrees?.*?\b(stale|zombie|drift|active|behind\s+main)\b",
            re.IGNORECASE,
        ),
    },
    {
        "rule_id": "lcs-worktrees",
        "verdict": "lcs",
        "uri": "lcs://worktrees",
        "reason": "multi-source aggregation: git worktree list + per-tree slot/version state",
        "_pattern": re.compile(
            r"\b(worktrees?|all\s+worktrees?|list\s+worktrees?)\b",
            re.IGNORECASE,
        ),
    },
]


# Alternate group-name aliases: when a regex alternation uses two
# different names for the same conceptual capture (Python regex forbids
# duplicate named groups), normalize them to the canonical key the URI
# template uses.
_ALIASES = {"name2": "name", "n2": "n", "window2": "window", "id2": "id"}


def _strip_internal(rule: dict) -> dict:
    """Drop internal keys (compiled regex) for JSON serialization."""
    return {k: v for k, v in rule.items() if not k.startswith("_")}


def _apply_uri_template(rule: dict, match: re.Match) -> str:
    """Render the URI for a matched lcs rule using the captured groups.

    Falls back to the bare template (no placeholder) when the rule's
    pattern matched without capturing a value -- e.g. "what's the spend?"
    produces ``lcs://spend`` instead of a malformed ``lcs://spend/{window}``.
    """
    if "uri" in rule:
        return rule["uri"]
    template = rule.get("uri_template", "lcs://<unknown>")
    groups = {k: v for k, v in match.groupdict().items() if v}
    # Normalize alt-group names to the canonical key the template uses.
    for alias, canonical in _ALIASES.items():
        if alias in groups:
            groups.setdefault(canonical, groups.pop(alias))
    if not groups:
        # No capture → strip the trailing "/{placeholder}" if present.
        if "{" in template:
            return template.split("/{", 1)[0]
        return template
    normalized = {k: re.sub(r"\s+", "", v) for k, v in groups.items()}
    try:
        return template.format(**normalized)
    except KeyError:
        # No canonical match -- fall back to the bare template.
        return template.split("/{", 1)[0]


def classify(question: str) -> dict:
    """Classify an operator question as ``shell`` or ``lcs``.

    Returns a verdict dict with the original question, verdict,
    rule_id, reason, and (when verdict=lcs) the resolved URI.
    Unknown questions fall through to ``verdict: shell`` with the
    explicit "no matching rule, fall through to direct tool" reason --
    the router never invents LCS routing for an unmapped question.
    """
    for rule in RULES:
        match = rule["_pattern"].search(question)
        if not match:
            continue
        result = {
            "question": question,
            "verdict": rule["verdict"],
            "rule_id": rule["rule_id"],
            "reason": rule["reason"],
        }
        if rule["verdict"] == "lcs":
            result["uri"] = _apply_uri_template(rule, match)
        else:
            result["shell_cmd"] = rule["shell_cmd"]
        return result
    return {
        "question": question,
        "verdict": "shell",
        "rule_id": "<fall-through>",
        "reason": "no matching rule, fall through to direct tool",
    }


def list_rules() -> list[dict]:
    """Return the break-even rule table as a JSON-serializable list.

    Each entry exposes the same fields the operator sees on a
    classified run (verdict, uri, uri_template, shell_cmd, reason,
    rule_id) plus the canonical question that exemplifies it. The
    internal compiled pattern is omitted -- it never reaches stdout.
    """
    return [_strip_internal(rule) for rule in RULES]


# ──────────────────────────────────────────────────────────────────
# CLI surface
# ──────────────────────────────────────────────────────────────────


def cmd_route(question: str, *, invoke: bool) -> int:
    """Print the classification JSON for ``question`` (or invoke LCS)."""
    if not question.strip():
        print("error: empty question", file=sys.stderr)
        return 2
    result = classify(question)
    if invoke and result.get("verdict") == "lcs":
        # Hand the call to dev-kit-lcs.py and let it own stdout/exit codes.
        proc = subprocess.run(
            [sys.executable, str(_LCS_CLI), "--get", result["uri"]],
            check=False,
        )
        return proc.returncode
    print(json.dumps(result, indent=2))
    return 0


def cmd_list_rules() -> int:
    """Print the break-even rule table as JSON."""
    print(json.dumps(list_rules(), indent=2))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dev-kit-lcs-route",
        description=(
            "NL-to-URI router with break-even rule "
            "(LCS UX Gap 1, issue #455)."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "question", nargs="?", default=None, metavar="QUESTION",
        help="operator question to route (verdict + URI)",
    )
    group.add_argument(
        "--list-rules", action="store_true",
        help="print the break-even rule table as JSON",
    )
    parser.add_argument(
        "--invoke", action="store_true",
        help="on lcs verdict, shell out to dev-kit-lcs.py --get <uri>",
    )
    args = parser.parse_args(argv)

    if args.list_rules:
        return cmd_list_rules()
    return cmd_route(args.question or "", invoke=args.invoke)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
