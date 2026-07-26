# Eval: Harness-Quality Dimension (judge-harness-quality, v1.0.0)

You are judging a dev-harness-kit run for **harness quality** — the
properties of the harness that make it safe to invoke repeatedly in
CI: determinism, isolation, observability, testability, and rollback
safety.

Score 5 axes 0-10 each. The axes mirror `lib/llm_judge.py:DIM_AXES["harness"]`
and `eval/rubrics/harness-quality.yaml`. The harness is the unit under
review, not the LLM judge.

## Case

- **Case ID**: ${CASE_ID}
- **Dimension**: ${DIM}
- **Rubric name**: harness-quality
- **Input code** (the harness module / function the run was launched against):
```
${INPUT}
```
- **Agent output** (the harness's structured report + log excerpts):
```
${AGENT_OUTPUT}
```
- **Expected behavior** (the ground-truth harness invariants):
```
${EXPECTED}
```

## Rubric (5 axes, 0-10)

1. **determinism** — same input → same output across reruns. Reproducible
   artefacts, no hidden randomness. 10 = every rerun is byte-identical
   (modulo timestamps); 0 = reruns diverge unpredictably.
2. **isolation** — effects of one run do not bleed into another.
   Per-case tempdir, namespaced caches, no global env mutation.
   10 = strict per-run sandboxing; 0 = cross-run contamination common.
3. **observability** — every important state transition emits a
   structured log or report field. 10 = full trace from artefacts
   alone; 0 = silent failures / unparseable logs.
4. **testability** — behaviour exercisable without network, without a
   real LLM, without flake-prone timing. 10 = unit tests mock the
   judge and pass deterministically; 0 = tests require real API keys.
5. **rollback_safety** — a failed invocation is reversible without
   manual cleanup. 10 = explicit dry-run mode + staged mutations; 0 =
   apply-mode writes happen before validation.

## Output Format

ONLY a JSON object (no prose). 5 axes, each 0-10:

```json
{"determinism":N,"isolation":N,"observability":N,"testability":N,"rollback_safety":N}
```
