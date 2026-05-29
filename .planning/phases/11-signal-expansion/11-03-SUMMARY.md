---
phase: 11-signal-expansion
plan: 03
subsystem: testing
tags: [prediction, momentum-breakout, mean-reversion, integration-tests, dual-path, breadth-multiplier, re-entry, support-stops]

# Dependency graph
requires:
  - phase: 11-signal-expansion
    provides: "prediction_signals.py with 6 new detectors, breadth multiplier, re-entry tracker, sector ETF caching"
  - phase: 11-signal-expansion
    plan: 01
    provides: "_detect_stoch_rsi, _detect_mfi, _detect_vwap, _detect_keltner_lower, _detect_macd_divergence, _detect_support_level, _find_swing_lows, _find_swing_highs"
  - phase: 11-signal-expansion
    plan: 02
    provides: "_compute_breadth_multiplier, _detect_sector_strength, record_stop_hit, _check_reentry_allowed, prefetch_sector_etf_bars"
provides:
  - "Dual-path prediction pipeline (mean reversion + momentum breakout) fully wired in prediction.py"
  - "Prediction.source field distinguishing mean_reversion from momentum_breakout"
  - "_predict_momentum() function with ADX gate, N-day high breakout, volume surge detection"
  - "Integration tests covering the full wired pipeline (57 tests total)"
  - "Breadth multiplier applied in _passes_regime_filter"
  - "Support-based stop placement and resistance-based take-profit targeting"
  - "Re-entry logic enforcing 50% sizing after first stop, blocked after second"
affects: [prediction, dashboard, predict_batch, signal_calibration, prediction_log]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dual-path prediction: predict() runs both mean reversion and momentum breakout, returns highest-confidence result"
    - "Lazy imports for circular dependency break: prediction_signals imports PatternResult from prediction; prediction imports from prediction_signals inside function bodies"
    - "ADX as hard gate: momentum path returns None immediately if ADX <= 25, no partial results"
    - "Integration tests mock at module boundary: patch volume_profile.score_volume_profile, order_flow.score_order_flow, amt_engine.score_amt"
    - "Lazy import patching: yf_limiter.prefetch_sector_etf_bars patched at module level, not prediction.prefetch"

key-files:
  created:
    - ".planning/phases/11-signal-expansion/11-03-SUMMARY.md"
  modified:
    - "prediction.py - source field on Prediction, 6 new confirms wired, _predict_momentum(), breadth in regime filter, support stops, resistance targets, re-entry logic, sector ETF prefetch in predict_batch"
    - "tests/test_prediction_signals.py - 13 integration tests added covering dual-path pipeline (57 total)"

key-decisions:
  - "Lazy imports used for prediction_signals in predict() and _predict_momentum() to break circular dependency (prediction_signals imports PatternResult from prediction)"
  - "Dual-path returns higher-confidence result: if both MR and momentum fire, winner is whichever has higher confidence"
  - "ADX > 25 is a hard gate for momentum path — returns None immediately, not a soft scoring penalty"
  - "Support stop only upgrades stop_loss if support_stop > current stop_loss AND < 97% of current price (avoids too-tight stops)"
  - "Re-entry blocked after 2 stop hits (D-21): predict() returns None, not reduced sizing"
  - "Integration tests use synthetic DataFrames with mocked VP/CVD/AMT to isolate pipeline wiring from data quality"
  - "prefetch_sector_etf_bars patched at yf_limiter module level in tests (lazy import pattern)"

patterns-established:
  - "Regime filter accepts sector_etf_bars parameter for breadth computation"
  - "All new Phase 11 signals appended after existing confirms in predict() loop"
  - "source field on Prediction dataclass defaults to 'mean_reversion', overridden to 'momentum_breakout' in _predict_momentum()"

requirements-completed: []

# Metrics
duration: 45min
completed: 2026-05-29
---

# Phase 11 Plan 03: Signal Integration Summary

**Dual-path prediction pipeline wired with 10 confirmation signals, momentum breakout path via _predict_momentum(), breadth-adjusted sizing, support-based stops, resistance targets, and re-entry logic — 57 integration tests all passing**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-05-29T00:30:00Z
- **Completed:** 2026-05-29T00:50:00Z
- **Tasks:** 2 (Task 1 pre-completed at 116db89, Task 2 committed at 7c7b8c2)
- **Files modified:** 2

## Accomplishments

- Dual-path prediction engine: predict() now runs both mean reversion (RSI2/IBS/consec_down/BB) and momentum breakout (_predict_momentum) paths and returns the higher-confidence result
- All 6 new confirmation signals (stoch_rsi, mfi, vwap, keltner_lower, macd_divergence, support_level) wired into predict() confirms loop, adding to patterns for tracking via active_signals
- _predict_momentum() implemented with hard ADX > 25 gate, N-day high breakout detection, volume surge (>1.5x) primary, MACD cross / Keltner upper / sector strength confirmations
- Breadth multiplier applied in _passes_regime_filter() — weak breadth reduces position_mult, reason string notes "breadth 0.5x"
- Support-aware stop: swing lows below current price inform stop placement (0.5% below nearest support if tighter than ATR/5% floor)
- Resistance-aware target: nearest swing high above current price used as take-profit if R:R >= 1.5 (beats BB-mid R:R)
- Re-entry logic: _check_reentry_allowed() blocks predict() entirely after 2 stop hits (D-21), applies 50% sizing and 1.0x ATR stop on first re-entry (D-20)
- predict_batch() pre-fetches all 11 sector ETF bars via prefetch_sector_etf_bars() before ThreadPoolExecutor (Pitfall 5 resolved)
- 13 integration tests added; 57 total tests passing across Plans 01, 02, and 03

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire dual-path prediction pipeline** - `116db89` (feat)
2. **Task 2: Integration tests for wired pipeline** - `7c7b8c2` (test)

## Files Created/Modified

- `prediction.py` - Prediction.source field, 6 new confirms wired, _predict_momentum(), breadth in _passes_regime_filter, support stops, resistance targets, re-entry logic, sector ETF prefetch in predict_batch, source passed to _log_predictions
- `tests/test_prediction_signals.py` - 13 integration tests added: _make_oversold_df, _make_breakout_df helpers, _make_regime_ok_df helper, TestPredictIncludesNewSignals, TestPredictSourceField, TestMomentumPath (ADX gate, 2-primary requirement), TestPredictBatchCallsPrefetch, TestBreadthInRegimeFilter, TestSupportStopPlacement, TestReentry50PctSize, TestActiveSignalsIncludesNewSignals

## Decisions Made

- Lazy imports inside predict() and _predict_momentum() break the circular import: prediction_signals.py imports PatternResult from prediction.py, so prediction.py cannot import from prediction_signals at module level
- When both mean reversion and momentum fire, higher confidence wins — no priority bias toward either path
- ADX gate in _predict_momentum() is unconditional: None returned immediately, ADX not used as a soft penalty
- Support stop uses `max(s for s in support_levels if s < current_price)` — nearest support below current price, not any swing low
- Integration tests mock VP/CVD/AMT at their module (volume_profile, order_flow, amt_engine) not at prediction module to correctly intercept the lazy calls inside predict()
- prefetch_sector_etf_bars patched at `yf_limiter.prefetch_sector_etf_bars` (lazy import origin) not at `prediction.prefetch_sector_etf_bars` (not a module-level attribute)

## Deviations from Plan

None — plan executed exactly as written. The lazy import pattern for circular dependency resolution was an implementation detail consistent with the existing comment on line 46-47 of prediction.py.

## Issues Encountered

- **ADX too high on synthetic linear uptrend:** A perfectly linear uptrend produces ADX ~100, exceeding ADX_MAX=60 and failing _passes_regime_filter. Fixed by using a sine-wave oscillating uptrend (_make_regime_ok_df) that keeps ADX moderate while still passing the 200-SMA filter.
- **Lazy import mock path:** prefetch_sector_etf_bars is imported inside predict_batch(), not at prediction module level. Patching `prediction.prefetch_sector_etf_bars` raised AttributeError. Fixed by patching at `yf_limiter.prefetch_sector_etf_bars`.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Dual-path prediction engine is complete and tested. predict() now produces both mean reversion and momentum breakout predictions.
- All 57 tests pass, covering unit (Plans 01/02) and integration (Plan 03) scenarios.
- The prediction pipeline is ready for: scanner integration, dashboard display of momentum_breakout source, and historical accuracy tracking differentiated by source field.

---
*Phase: 11-signal-expansion*
*Completed: 2026-05-29*
