# Eval: Security Dimension (judge-security, v2.0.0)

You are judging the agent's `/dev-kit:security` output for one case
fixture. Score 3 axes 0-10 each.

## Case

- **Case ID**: ${CASE_ID}
- **Dimension**: ${DIM}
- **Category**: ${CATEGORY} (e.g. `owasp-a01`, `owasp-a05`, `trap`)
- **Input code** (the fixture the security scanner was given):
```
${INPUT}
```
- **Agent output** (the security scan verdict + per-category findings):
```
${AGENT_OUTPUT}
```
- **Expected behavior** (the ground-truth OWASP category + severity):
```
${EXPECTED}
```

## Axes (0-10)

1. **owasp_classification_accuracy** — for each finding the agent
   emitted, was it placed in the correct OWASP A01-A10 category? 10 =
   every finding in the right category; 0 = every finding in the wrong
   one. Partial credit for off-by-one category. Per-finding, then
   average.
2. **severity_accuracy** — for each finding, does the severity
   (`critical` / `major` / `minor` / `nit`) match the actual impact?
   10 = perfectly calibrated; 0 = wildly mis-severity throughout.
3. **precision** — what fraction of the agent's findings are real
   (planted vulnerabilities, not noise)? `TP / (TP + FP)`. Trap
   fixtures that surface findings = low precision. 10 = no false
   positives; 0 = every finding is noise.

## Output Format

ONLY a JSON object (no prose). 3 axes, each 0-10:

```json
{"owasp_classification_accuracy":N,"severity_accuracy":N,"precision":N}
```
