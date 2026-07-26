# Eval: Operating-System Quality Dimension (judge-os-quality, v1.0.0)

You are judging a dev-harness-kit run for **OS-level quality** — the
properties of the harness that govern how it interacts with the
operating environment: permissions, cost, rollback, escalation, and
audit trail.

Score 5 axes 0-10 each. The axes mirror `lib/llm_judge.py:DIM_AXES["os"]`
and `eval/rubrics/os-quality.yaml`. The "OS" here is the runtime
boundary around the harness: env vars, files, subprocess, CI logs.

## Case

- **Case ID**: ${CASE_ID}
- **Dimension**: ${DIM}
- **Rubric name**: os-quality
- **Input code** (the harness module / function under review):
```
${INPUT}
```
- **Agent output** (the harness's structured report + cost / log lines):
```
${AGENT_OUTPUT}
```
- **Expected behavior** (the ground-truth OS-level invariants):
```
${EXPECTED}
```

## Rubric (5 axes, 0-10)

1. **permission_separation** — capability boundaries between caller,
   harness, and provider are explicit. 10 = each tier holds only the
   permissions it needs; 0 = one tier holds too many (secrets in
   source, arbitrary shell exec).
2. **cost_visibility** — token / dollar cost is reported per run, not
   hidden in CI logs. 10 = structured per-case tokens_in / tokens_out
   block; 0 = no cost data anywhere.
3. **rollback_capability** — a failed invocation leaves the system in
   a state the operator can roll back to without manual forensics.
   10 = staged diffs + atomic_write; 0 = silent partial writes on failure.
4. **escalation_path** — when the harness detects disagreement (e.g.
   cross-judge variance > 0.5), it surfaces a deterministic escalation
   marker. 10 = explicit "needs human review" in the report; 0 =
   silent averaging across disagreeing judges.
5. **audit_trail** — every run leaves a forensic record: case id,
   dim, judge scores, raw output (truncated), verdict, version. 10 =
   report is enough to reconstruct the run days later; 0 = only an
   aggregated verdict is retained.

## Output Format

ONLY a JSON object (no prose). 5 axes, each 0-10:

```json
{"permission_separation":N,"cost_visibility":N,"rollback_capability":N,"escalation_path":N,"audit_trail":N}
```
