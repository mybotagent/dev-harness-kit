# Round 1 hand-off — agent-behavior golden case

## What was done
- Added `tests/sample.py` with a passing test
- Added `lib/x.py` stub function for the test target
- Set `agent-behavior-baseline.json` from the initial trace metrics
- Created `golden/` subdir with 5 baseline/current JSON pairs

## Verification
- pytest tests/sample.py passes
- All 5 golden cases have valid baseline + current
- Hand-off present, no L1 violations

## Next steps
- TODO next: extend golden cases with more scenarios in a follow-up PR
- TODO next: add CI integration to validate against agent-behavior eval pipeline
