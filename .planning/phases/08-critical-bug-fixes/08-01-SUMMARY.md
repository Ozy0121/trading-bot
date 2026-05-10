---
phase: 08-critical-bug-fixes
plan: 01
subsystem: prediction-engine
tags: [bugfix, prediction, veto-logic, accuracy, position-sizing]
dependency_graph:
  requires: []
  provides: [get_symbol_accuracy, live-veto-logic, compound-position-sizing]
  affects: [prediction.py, prediction_log.py]
tech_stack:
  added: []
  patterns: [per-symbol-accuracy-lookup, compound-position-multiplier]
key_files:
  created: []
  modified:
    - prediction.py
    - prediction_log.py
decisions:
  - "CVD/AMT veto is now live -- rejects setups when CVD score <= 0 or AMT is imbalanced_down"
  - "Historical accuracy queries prediction_log per symbol instead of hardcoded zeros"
  - "SPY regime penalty compounds with other penalties via *= instead of overwriting"
metrics:
  duration: 148s
  completed: 2026-05-10
---

# Phase 08 Plan 01: Fix Prediction Engine Bugs Summary

Fixed 5 bugs in prediction.py that undermined prediction quality: dead CVD/AMT veto branch, hardcoded zero accuracy, position sizing overwrite, unused imports (numpy, fetch_bars), and invalid callable type hint.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add per-symbol accuracy function to prediction_log.py | adc0cd3 | prediction_log.py |
| 2 | Fix all 5 prediction.py bugs | ab68cd2 | prediction.py |

## Changes Made

### Task 1: get_symbol_accuracy function
- Added `get_symbol_accuracy(symbol, window=50)` to prediction_log.py
- Filters prediction records by symbol and resolved outcome status
- Returns dict with `accuracy` (0.0-1.0) and `samples` (int)
- Placed after existing `get_accuracy()` function

### Task 2: 5 prediction.py bug fixes
1. **Dead veto branch (Fix 1):** Changed `_get_confirmations()` from always returning `False` to computing actual veto status based on CVD seller control (score <= 0) and AMT imbalanced_down state. Added logging when veto triggers.
2. **Hardcoded accuracy (Fix 2):** Replaced `historical_accuracy = 0.0` / `historical_samples = 0` with a try/except block that calls `get_symbol_accuracy(symbol)` from prediction_log.
3. **Position sizing overwrite (Fix 3):** Changed `position_mult = 0.5` to `position_mult *= 0.5` so SPY regime penalty compounds with other penalties.
4. **Unused imports (Fix 4):** Removed `import numpy as np` and `fetch_bars` from openbb_data import.
5. **Invalid type hint (Fix 5):** Changed `callable` to `Callable` from typing module in `predict_batch` signature.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED
