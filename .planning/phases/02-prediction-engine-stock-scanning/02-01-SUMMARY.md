---
phase: 02-prediction-engine-stock-scanning
plan: "01"
subsystem: strategies
tags: [strategies, conviction-scoring, momentum, mean-reversion, catalyst, registry]
dependency_graph:
  requires: []
  provides: [strategies/REGISTRY, config/CONVICTION_THRESHOLD, config/SWING_WATCHLIST, state/scan_results]
  affects: [02-02, 02-03]
tech_stack:
  added: []
  patterns: [strategy-registry, pure-scan-functions, tdd]
key_files:
  created:
    - strategies/__init__.py
    - strategies/momentum.py
    - strategies/mean_reversion.py
    - strategies/catalyst.py
    - tests/test_strategies.py
  modified:
    - config.py
    - state.py
decisions:
  - "Strategy scan() functions are pure: accept (symbol, df) -> dict, no side effects"
  - "catalyst.scan() accepts optional pre-fetched catalysts dict to avoid redundant API calls"
  - "Mean reversion test uses gradual decline + sharp final plunge to reliably create RSI<35 + price below lower BB"
metrics:
  duration: "~10 min"
  completed: "2026-03-28"
  tasks_completed: 2
  files_created: 5
  files_modified: 2
---

# Phase 02 Plan 01: Strategy Foundation Summary

**One-liner:** Three strategy scan modules (momentum breakout, mean reversion, catalyst) with REGISTRY dict, conviction-scoring config, and scan_results state keys — 13 unit tests all pass.

## What Was Built

### Config Extensions (`config.py`)
- `CONVICTION_THRESHOLD = 7.0` — minimum composite score to execute a trade
- `CONVICTION_WEIGHT_TECHNICAL = 0.40`, `VOLUME = 0.20`, `SENTIMENT = 0.20`, `SECTOR = 0.20`
- Weight sum validation: raises `ValueError` if weights don't sum to 1.0
- `SWING_WATCHLIST` — 25 symbols loaded from `SWING_WATCHLIST` env var

### State Extensions (`state.py`)
Three new keys added to `_state` dict:
- `scan_results: []` — list of candidate dicts from scanner
- `last_scan_time: None` — ISO timestamp of last scan completion
- `scan_conviction_scores: {}` — `{symbol: composite_score}` quick lookup

### Strategy Registry (`strategies/__init__.py`)
- `REGISTRY: dict[str, callable]` with 3 entries: `momentum`, `mean_reversion`, `catalyst`
- All values callable with signature `(symbol: str, df: pd.DataFrame) -> dict`

### Momentum Strategy (`strategies/momentum.py`)
- Fires when `last_close > 20-day rolling high` AND `volume_ratio >= 2.0`
- Technical score: proximity to N-day high (0-8) + 2.0 breakout bonus
- Returns: `{strategy, fired, technical_score, volume_ratio, details}`

### Mean Reversion Strategy (`strategies/mean_reversion.py`)
- Fires when `RSI(14) < 35` AND `last_close <= lower_BB * 1.02`
- Requires minimum 22 bars; returns safe defaults otherwise
- Score formula: `max(0, (35 - rsi) / 35 * 10)` + 2.0 support bonus

### Catalyst Strategy (`strategies/catalyst.py`)
- ARK buying: +5.0, Analyst upgrade: +5.0, both: 10.0, neither: 0.0
- Accepts optional pre-fetched `catalysts` dict to avoid repeated API calls
- Signature: `scan(symbol, df, catalysts=None) -> dict`

### Unit Tests (`tests/test_strategies.py`)
13 tests covering:
- Registry structure and callability
- Momentum: fires on breakout+volume, no-fire on flat, score bounds, insufficient data
- Mean reversion: fires on oversold+BB, no-fire on flat, insufficient data
- Catalyst: both flags, neither, ARK-only, upgrade-only, missing symbol

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed oversold DataFrame test helper**
- **Found during:** Task 2 TDD GREEN phase
- **Issue:** `make_oversold_df()` used a straight-line decline which caused `last_close` to always remain above `bb_lower` (BB tracks the ongoing decline). RSI was 0.0 but `at_bb_lower` was False.
- **Fix:** Changed to gradual decline (45 bars) + sharp final plunge (5 bars) — this creates BB lower anchored to the prior gradual slope while the final plunge dips below it.
- **Files modified:** `tests/test_strategies.py`
- **Commit:** 9de6eb4

## Known Stubs

None — all strategy functions are fully implemented with real indicator calculations.

## Self-Check: PASSED

- strategies/__init__.py: FOUND
- strategies/momentum.py: FOUND
- strategies/mean_reversion.py: FOUND
- strategies/catalyst.py: FOUND
- tests/test_strategies.py: FOUND
- config.py CONVICTION_THRESHOLD: FOUND
- state.py scan_results: FOUND
- All 13 tests: PASS
