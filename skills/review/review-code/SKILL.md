---
name: review-code
category: review
description: 3-dim parallel fan-out (correctness + security + architecture) with verifier pass. evidence-only findings.
when_to_use: |
  - User types /dev-kit:review
  - User asks "review this code" / "review the diff" / "review the PR"
allowed-tools: Read Grep Glob Bash Agent
disable-model-invocation: false
model: opus
---

# review-code — Multi-Dimension Code Review (3 dim)

## 3 Dimensions (단일 메시지 병렬 fan-out, MUST-10)

| Dim | Charter |
|---|---|
| **correctness** | logic / edge cases / null-boundary / state / error / race / API misuse |
| **security** | OWASP-aligned: injection / dynamic execution / unsafe deserialization / IDOR / SSRF / weak crypto / secrets / CI / unsafe defaults |
| **architecture** | module boundaries / coupling / layering / leaky abstractions / duplication / God objects / extensibility |

각 sub-agent는 같은 contract: `failure_scenario` + `confidence: high|medium|low` 명시.

## Verifier Pass (별개 사이클)

After fan-out: 1 verifier sub-agent refutes candidate findings. CONFIRMED | PLAUSIBLE | REJECTED.

## Severity (3 tiers)

| Severity | Verdict |
|---|---|
| 🔴 critical | Blocked |
| 🟠 major | Changes Requested |
| 🟡 minor | Approve (optional) |
| ⚪ nit | Approve |

## 출력

- PR summary: `## Review summary\n**Verdict:** <Blocked|Changes Requested|Approve>`
- Inline comments: `[severity · CONFIRMED] title @ path:line`

## Hook 정렬

Review 단계:
- `slop-detector, secret-scan, stop-verify` ON
- 그 외 OFF

## 회귀 fixture (보존)

`fixtures/real-bugs/sql_injection.py` → security/critical 1+ finding 자동 검증.
`fixtures/traps/parameterized_query.py` → 0 finding (false-positive 방지).
