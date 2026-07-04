---
name: security-scan
category: security
description: 10-dim OWASP Top 10 2025 fan-out (A01-A10). Per-category breakdown table.
when_to_use: |
  - User types /dev-kit:security
  - Pre-release / quarterly / before major refactor
allowed-tools: Read Grep Glob Bash Agent
disable-model-invocation: false
model: opus
---

# security-scan — OWASP Top 10 Audit (10 dim, 별도 커맨드, MUST-50)

## 10 OWASP 2025 Categories (단일 메시지 fan-out, MUST-10)

| ID | Category | Catches |
|---|---|---|
| A01 | Broken Access Control | IDOR / path traversal / force browse / CORS / missing function-level / privilege escalation |
| A02 | Security Misconfiguration | default creds / debug-in-prod / stack trace / missing headers / cloud metadata SSRF / verbose errors |
| A03 | Software Supply Chain Failures | vulnerable deps / unpinned versions / untrusted registries / build injection / postinstall / typosquats |
| A04 | Cryptographic Failures | weak hashes (MD5/SHA1) / non-constant-time compare / hardcoded keys / insecure RNG / ECB / small keys / TLS verify off |
| A05 | Injection | SQL / command / template / XSS / NoSQL / header / XXE / format string |
| A06 | Insecure Design | no rate limit / client-side-only trust / predictable IDs / TOCTOU / missing CSRF |
| A07 | Authentication Failures | weak passwords / cred stuffing / session fixation / plaintext / password-in-URL / JWT alg none |
| A08 | Software/Data Integrity | unsafe deserialization / auto-update w/o integrity / insecure plugin / missing checksum / cookie flags |
| A09 | Security Logging Failing | missing auth logs / PII in logs / no alerting / mutable logs / insufficient detail |
| A10 | Mishandling Exceptional Conditions | bare except pass / fail-open auth / fail-open validation / missing timeout / unhandled rejection / panic |

각 sub-agent는 동일 contract (failure_scenario + confidence).

## 출력

- PR summary: `## Security summary\n**Verdict:** <Blocked|Changes Requested|Approve>`
- Per-category breakdown table: `| Category | Findings | Severity |`

## Verifier Pass

CONFIRMED 만 카운트. ≥ 5/10 임계값:
- ≥ 5 → Approve
- 3~4 → Changes Requested
- 0~2 → Blocked (재검토 권장)

## Hook 정렬

Security stage: `slop-detector, secret-scan, stop-verify` ON.

## 회귀 fixture

`fixtures/real-bugs/a05_sql_injection.py` → A05 1+ finding 자동 검증.
`fixtures/traps/a05_parameterized_query.py` → 0 finding.
