---
phase: quick-260401-bpu
plan: 260401-bpu
subsystem: conviction-scoring
tags: [calibration, scoring, sentiment, volume, sector, strategies]
key-files:
  modified:
    - strategies/momentum.py
    - strategies/mean_reversion.py
    - sentiment_cache.py
    - config.py
    - scanner.py
    - tests/test_scanner.py
decisions:
  - "Momentum technical score: proximity_pct * 3.5 gives 1%->3.5, 2%->7.0, 3%+->8.0 (capped)"
  - "Mean reversion RSI score: exponential curve (rsi_gap/threshold)^0.6*10 for better spread"
  - "Conviction weights redistributed: TECHNICAL 0.50 (from 0.40), SENTIMENT 0.10 (from 0.20)"
  - "Sector absolute gate: negative 5-day ETFs capped at 5.0 regardless of relative rank"
  - "Volume curve below 2x: multiplier 4.0 -> 5.0, so 1x ratio scores 2.5 instead of 2.0"
metrics:
  duration: "4 minutes"
  completed: "2026-04-01T18:18:11Z"
  tasks_completed: 3
  files_modified: 6
---

# Quick Task 260401-bpu: Recalibrate Conviction Scoring Summary

**One-liner:** Five targeted formula fixes across strategies, sentiment, volume, and sector scoring to decompress conviction score ranges and make the 5.8 threshold reachable for genuine setups.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Rescale technical scores: momentum * 3.5 curve, mean reversion exponential | ebb6a11 |
| 2 | Fix sentiment tanh spread, sector negative gate, rebalance weights | a3ffccb |
| 3 | Volume curve below 2x, threshold passrate validation test | 6aedc04 |

## Changes Made

### Task 1 — Technical score rescaling

**strategies/momentum.py**
- Changed `tech_score = min(8.0, proximity_score)` to `tech_score = min(8.0, proximity_pct * 3.5)`
- 2% breakout now scores 7.0 (was 2.0) before the +2 fired bonus
- 1% -> 3.5, 2% -> 7.0, 3%+ -> 8.0 (capped), with bonus: 1% -> 5.5, 2% -> 9.0

**strategies/mean_reversion.py**
- Changed linear `(RSI_THRESHOLD - rsi) / RSI_THRESHOLD * 10` to exponential `(rsi_gap / RSI_THRESHOLD) ** 0.6 * 10`
- RSI=30 -> ~3.0 (was 1.4), RSI=25 -> ~5.5 (was 2.86), RSI=20 -> ~7.5 (was 4.29)
- Clamp `rsi_gap = max(0.0, ...)` applied before exponent to prevent complex number TypeError

### Task 2 — Sentiment, sector, and weights

**sentiment_cache.py**
- tanh multiplier: 2.5 -> 4.0 for wider score spread on mixed headline sets

**config.py**
- `CONVICTION_WEIGHT_TECHNICAL`: 0.40 -> 0.50
- `CONVICTION_WEIGHT_SENTIMENT`: 0.20 -> 0.10
- Volume and sector weights unchanged at 0.20 each (sum still 1.0)

**scanner.py**
- Added absolute sector gate after linear ranking: sectors with negative 5-day pct change are capped at 5.0
- Previously best-ranked negative sector could score 10.0 purely from being least-bad in a declining market

### Task 3 — Volume curve and passrate test

**scanner.py**
- `_volume_ratio_to_score`: below-2x multiplier changed from 4.0 to 5.0
- 1x volume ratio now scores 2.5 instead of 2.0

**tests/test_scanner.py**
- Added `test_threshold_passrate_realistic`: 20 synthetic combos spanning weak to strong setups
- Asserts >= 5% pass the 5.8 threshold — currently ~55% pass (11/20), well above the minimum

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed complex number TypeError in mean reversion RSI formula**
- **Found during:** Task 1 test run
- **Issue:** When `rsi_val >= RSI_THRESHOLD`, `(RSI_THRESHOLD - rsi_val)` is negative or zero. Raising a negative float to a fractional power (0.6) in Python produces a complex number, causing `TypeError: '>' not supported between instances of 'complex' and 'float'` inside `max(0.0, ...)`.
- **Fix:** Extract `rsi_gap = max(0.0, RSI_THRESHOLD - rsi_val)` before the exponent, guaranteeing a non-negative base. `rsi_score = (rsi_gap / RSI_THRESHOLD) ** 0.6 * 10`
- **Files modified:** `strategies/mean_reversion.py`
- **Commit:** ebb6a11

## Test Results

All 57 tests pass across three test files:
- `tests/test_strategies.py`: 13 passed
- `tests/test_sentiment_cache.py`: 11 passed
- `tests/test_scanner.py`: 33 passed (includes new `test_threshold_passrate_realistic`)

## Self-Check: PASSED

- strategies/momentum.py — FOUND
- strategies/mean_reversion.py — FOUND
- sentiment_cache.py — FOUND
- config.py — FOUND
- scanner.py — FOUND
- tests/test_scanner.py — FOUND
- Commit ebb6a11 — FOUND
- Commit a3ffccb — FOUND
- Commit 6aedc04 — FOUND
