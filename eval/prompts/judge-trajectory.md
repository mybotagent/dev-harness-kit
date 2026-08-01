# judge-trajectory — D7 LLM judge prompt

Phase 1 placeholder. The actual prompt lands when LLM judge wiring ships
(see proposal §03 Phase 1). The shape below is the contract Phase 1 will
honor: the judge receives the step sequence and rates the trajectory.

## Inputs

```
case_id: ${case_id}
steps:
${steps_json}

heuristic_evidence:
${heuristic_json}
```

## Output contract

```json
{
  "axes": {
    "tool_selection": 1-5,
    "sequence_logic": 1-5,
    "branching_minimal": 1-5,
    "convergence": 1-5
  },
  "evidence": "one sentence per axis"
}
```

## Axis definitions

1. **tool_selection** — Right tools chosen? Score 5 when no obvious
   better-fit tool was available.
2. **sequence_logic** — Sensible order? Score 5 when each step
   logically precedes the next.
3. **branching_minimal** — Minimal backtracking? Score 5 when
   trajectory is monotone toward goal.
4. **convergence** — Moves toward goal? Score 5 when later steps
   clearly build on earlier outputs.

## Combination with heuristic

`llm_value = round(mean(axes))` clamped to 1..5.
Final D7 value (Phase 1): `round(heuristic_value * 0.7 + llm_value * 0.3)`.
