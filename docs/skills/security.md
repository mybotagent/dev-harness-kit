> [← Skills index](README.md) · [Project README](../../README.md)

# `security`

**Category:** `security` · **Alpha:** `enforcement` · **Invocation:** `/dev-kit:security` (human-invoked)

`security` runs a full OWASP Top 10 (2025) audit across 10 categories (A01-A10), fanning out to ten parallel subagents — one per category — that return evidence-backed findings, followed by a verification pass that confirms or rejects each before rendering a per-category breakdown table and verdict. It is kept separate from `/dev-kit:review` because it covers different dimensions with deeper security-specific focus, and it delegates to the same shared engine, `lib.analysis_core.run_analysis(dimensions=group("security"), mode="read-only", paths=...)`.

## When to use it

- The user types `/dev-kit:security`.
- Pre-release, quarterly, or before a major refactor.
- The user asks for a security audit, OWASP review, or vulnerability scan.

## How it works

**The 10 categories:**

- **A01 Broken Access Control** — IDOR, path traversal, force browse, CORS, missing function-level checks, privilege escalation.
- **A02 Security Misconfiguration** — default creds, debug-in-prod, stack traces, missing headers, cloud metadata SSRF, verbose errors.
- **A03 Software Supply Chain Failures** — vulnerable deps, unpinned versions, untrusted registries, build injection, postinstall scripts, typosquats.
- **A04 Cryptographic Failures** — weak hashes (MD5/SHA1), non-constant-time compare, hardcoded keys, insecure RNG, ECB mode, small keys, TLS verify off.
- **A05 Injection** — SQL, command, template, XSS, NoSQL, header, XXE, format string.
- **A06 Insecure Design** — no rate limit, client-side-only trust, predictable IDs, TOCTOU, missing CSRF, missing business rules.
- **A07 Authentication Failures** — weak passwords, credential stuffing, session fixation, plaintext storage, password-in-URL, JWT alg none.
- **A08 Software/Data Integrity Failures** — unsafe deserialization, auto-update without integrity checks, insecure plugin loading, missing checksum, cookie flags.
- **A09 Security Logging and Alerting Failures** — missing auth logs, PII in logs, no alerting, mutable logs, insufficient detail.
- **A10 Mishandling Exceptional Conditions** — bare except/pass, fail-open auth or validation, missing timeout, unhandled rejections, missing cleanup, panic in a critical path.

**Fan-out + verify.** All 10 `Agent` calls are issued inside one assistant message so they run concurrently. Each uses `subagent_type: "general-purpose"` and `model: "sonnet"`, receiving its charter from `lib.analysis_core.dimensions` plus the same shared evidence contract used by `/dev-kit:review` (`file, line, severity, confidence, failure_scenario, title, tldr`). One verifier `Agent` returns `[{id, verdict: CONFIRMED|PLAUSIBLE|REJECTED, reason}]`; `REJECTED` is dropped, `CONFIRMED`/`PLAUSIBLE` are kept. Unlike review, the skill body itself owns the dedupe (on `file, line, theme`) plus the verifier-and-synthesize pipeline inline: the 10 agent calls return raw findings inside one assistant message, and the body collapses duplicates, applies the verifier verdict, and synthesizes the per-category breakdown table.

**Verdict.** `CONFIRMED >= 5` findings → Approve. `0-2` → Blocked. In between → Changes Requested. Inline comments per finding use the same Layer 1 format as `/dev-kit:review`.

## Usage

```bash
/dev-kit:security
```

0-arg — no flags.

## Output

```
## Security summary
**Verdict:** <Blocked | Changes Requested | Approve>
| Category | Findings | Severity |
|---|---|---|
| A01 | n | (critical, ...) |
...
```

Plus one inline comment per confirmed/plausible finding, in the same format `/dev-kit:review` uses.

## Related

- [review](review.md) — the 3-dimension correctness/security/architecture counterpart; `security` runs the deeper 10-category OWASP pass instead.
- `/dev-kit:ship` — the recommended next step once the verdict is Approve.
- `lib.analysis_core` — the shared engine this skill's dimensions, evidence schema, and dedupe pipeline build on.

## Hooks

Same as `review`: `slop-detector`, `secret-scan`, `stop-verify` are ON for this stage.

---
*Source: [`skills/security/SKILL.md`](../../skills/security/SKILL.md)*
