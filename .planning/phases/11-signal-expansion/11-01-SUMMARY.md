---
phase: 11-signal-expansion
plan: "01"
subsystem: prediction-signals
tags: [signals, confirmation, tdd, stoch-rsi, mfi, vwap, keltner, macd-divergence, support-level]
dependency_graph:
  requires: []
  provides: [prediction_signals.py, 6-new-confirmation-detectors, swing-point-detection]
  affects: [prediction.py, signal_calibration.py]
tech_stack:
  added: []
  patterns: [PatternResult-detector-pattern, TDD-red-green]
key_files:
  created:
    - prediction_signals.py
    - tests/test_prediction_signals.py
    - amt_engine.py
    - order_flow.py
    - volume_profile.py
  modified:
    - prediction.py
    - signal_calibration.py
decisions:
  - "Copied untracked volume_profile.py, order_flow.py, amt_engine.py from main worktree — needed for prediction.py import chain in tests"
  - "When stoch_rsi denominator is 0 (RSI pinned at extreme), treat as 0.0 (oversold) or 1.0 based on RSI value rather than returning None"
  - "Keltner test uses tight ±0.5 bar range so ATR is small enough for channel to detect moderate price drops"
metrics:
  duration_seconds: 470
  completed_date: "2026-05-28T03:28:00Z"
  tasks_completed: 2
  files_created: 5
  files_modified: 2
---

# Phase 11 Plan 01: Prediction Signals Module Summary

**One-liner:** Six new confirmation detectors (Stoch RSI, MFI, VWAP, Keltner lower, MACD divergence, support level) with swing point detection and DEFAULT_CONFIRM dict synchronization across prediction.py and signal_calibration.py.

## What Was Built

### Task 1: prediction_signals.py + tests/test_prediction_signals.py

Created `prediction_signals.py` in the project root with 8 exported functions:

| Function | Signal | Category | Detection Threshold |
|----------|--------|----------|---------------------|
| `_detect_stoch_rsi` | Stochastic RSI | momentum | stoch_rsi < 0.10 |
| `_detect_mfi` | Money Flow Index | volume | MFI < 20 |
| `_detect_vwap` | VWAP distance | volume | price < cumulative VWAP |
| `_detect_keltner_lower` | Keltner lower band | volatility | price <= lower channel |
| `_detect_macd_divergence` | MACD bullish divergence | momentum | lower price low + higher hist low |
| `_detect_support_level` | Swing low support | structure | within 1.5% of swing low |
| `_find_swing_lows` | Swing point detection | utility | local minimum (n-bar neighbors) |
| `_find_swing_highs` | Swing point detection | utility | local maximum (n-bar neighbors) |

All detectors return `PatternResult` with the exact name strings required by the plan. Created `tests/test_prediction_signals.py` with 23 unit tests covering detection, non-detection, insufficient data, and calibration sync.

### Task 2: DEFAULT_CONFIRM dict synchronization

Added 6 new keys to both dicts at initial weight 0.5 (D-02):

- `prediction.py:DEFAULT_CONFIRM_BONUS` — keys: stoch_rsi, mfi, vwap, keltner_lower, macd_divergence, support_level
- `signal_calibration.py:DEFAULT_CONFIRM` — same 6 keys

The `_load_weights()` function's `setdefault()` loop and the `all_signals = list(DEFAULT_PRIMARY) + list(DEFAULT_CONFIRM)` line in signal_calibration.py auto-discover the new keys — no additional changes required.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Copied untracked dependency modules to worktree**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** `prediction.py` imports `volume_profile`, `order_flow`, `amt_engine` which exist in the main working directory as untracked files but are absent from this worktree branch (created at commit `ed3600b`)
- **Fix:** Copied the three files from `C:/Users/btuo1/trading-bot/` into the worktree so the import chain works during testing
- **Files modified:** amt_engine.py, order_flow.py, volume_profile.py (added)
- **Commit:** c548629

**2. [Rule 1 - Bug] Handle zero-denominator in Stochastic RSI calculation**
- **Found during:** Task 1 (GREEN phase — first test run)
- **Issue:** When prices decline steeply, RSI drops to 0.0 and stays pinned there. The rolling min and max are both 0.0, making the stoch denominator 0. After `denom.replace(0, np.nan)`, all stoch values become NaN and `dropna()` returns an empty Series, so the function returned `detected=False` even on extreme oversold data.
- **Fix:** Added explicit zero-denominator check: if pinned RSI < 10, treat stoch_rsi as 0.0 (maximally oversold); otherwise treat as 1.0.
- **Files modified:** prediction_signals.py
- **Commit:** c548629

**3. [Rule 1 - Bug] Fixed Keltner test scenario — insufficient price drop**
- **Found during:** Task 1 (GREEN phase — second test run)
- **Issue:** Test used ±5.0 high/low range creating large ATR. With ATR ≈ 5, the Keltner lower band sat at ~75 while price dropped to 85 — above the channel. Test was checking the wrong direction.
- **Fix:** Changed test to use ±0.5 bar range (small ATR) and a drop to 95.0. With tight ATR the lower band is ~96.5, so price at 95.0 is correctly below it.
- **Files modified:** tests/test_prediction_signals.py
- **Commit:** c548629

**4. [Rule 1 - Bug] Fixed support level "not detected" test scenario**
- **Found during:** Task 1 (GREEN phase — third test run)
- **Issue:** Test scenario used `[80, 90, 100, 130] * 15 bars` — the flat region at 130 generates its own swing lows (each bar equal to neighbors satisfies the <= condition), so a "support" appeared near 129 and distance was 0.78%, triggering detection.
- **Fix:** Changed to a V-shape bottom at 50 followed by a rise to 120+, so the nearest support is 50 and current price is 140% above it — clearly beyond the 1.5% threshold.
- **Files modified:** tests/test_prediction_signals.py
- **Commit:** c548629

## Known Stubs

None — all detectors are fully wired to real indicator functions and return computed values.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced. All computation is pure in-process pandas/numpy. Consistent with T-11-01 and T-11-02 dispositions in the plan's threat model (both accepted).

## Self-Check

- [x] prediction_signals.py exists at project root
- [x] tests/test_prediction_signals.py exists with 23 tests, all passing
- [x] All 6 detector function signatures confirmed present
- [x] _find_swing_lows and _find_swing_highs confirmed present
- [x] DEFAULT_CONFIRM_BONUS in prediction.py has all 6 new keys at 0.5
- [x] DEFAULT_CONFIRM in signal_calibration.py has all 6 new keys at 0.5
- [x] Both dicts have identical key sets (verified by set equality assertion)
- [x] Commits c548629 and a1195f0 verified in git log

## Self-Check: PASSED
