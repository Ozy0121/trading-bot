---
phase: 11-signal-expansion
plan: "02"
subsystem: prediction-signals
tags: [sector-etf, breadth-multiplier, sector-strength, re-entry-tracker, data-infrastructure]
dependency_graph:
  requires: [prediction_signals.py]
  provides: [sector-etf-caching, breadth-multiplier, sector-strength-detector, re-entry-tracker]
  affects: [yf_limiter.py, prediction_signals.py]
tech_stack:
  added: []
  patterns: [daily-cache-pattern, sector-etf-map, re-entry-tracking]
key_files:
  created: []
  modified:
    - yf_limiter.py
    - prediction_signals.py
    - tests/test_prediction_signals.py
decisions:
  - "Sector ETF cache follows identical pattern to existing SPY cache in yf_limiter.py"
  - "Breadth multiplier uses 3-tier classification: 1.0 (normal), 0.5 (weak), 0.25 (very weak)"
  - "Re-entry tracker is module-level dict, resets on restart — acceptable for single-bot design"
  - "Added explicit float conversions for numpy compatibility in sector strength calculations"
metrics:
  duration_seconds: 380
  completed_date: "2026-05-28T18:17:00Z"
  tasks_completed: 2
  tests_added: 9
  tests_total: 57
self_check: PASSED
---

## What Was Built

Added sector ETF data infrastructure and market regime components to support the dual-path prediction pipeline:

1. **Sector ETF bar caching** (`yf_limiter.py`): `SECTOR_ETF_MAP` with 11 sector ETFs, `get_sector_etf_bars()` with daily cache invalidation following the existing SPY cache pattern, and `prefetch_sector_etf_bars()` for batch pre-fetching before ThreadPoolExecutor runs.

2. **Breadth multiplier** (`prediction_signals.py`): `_compute_breadth_multiplier()` classifies market conditions into 3 tiers based on sector ETF 5-day returns — normal (1.0), weak breadth (0.5), very weak (0.25).

3. **Sector relative strength** (`prediction_signals.py`): `_detect_sector_strength()` computes a stock's sector ETF 20-day return vs SPY, returning a scored PatternResult for the regime filter.

4. **Re-entry tracker** (`prediction_signals.py`): `record_stop_hit()`, `_check_reentry_allowed()`, and `_prune_reentry_tracker()` enforce max 1 re-entry per symbol at 50% position size with tighter 1.0 ATR stop.

## Commits

- `91d7c8b` feat(11-02): add sector ETF bar caching to yf_limiter.py
- `9cdff83` feat(11-02): add breadth multiplier, sector strength, and re-entry tracker

## Deviations

- Added explicit `float()` conversions around numpy return values to prevent type issues downstream.
- Fixed mock patch targets in sector strength tests to match actual import paths.
