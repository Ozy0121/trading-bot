---
phase: 02-prediction-engine-stock-scanning
plan: "04"
subsystem: scanner-recalibration
tags: [scoring, sentiment, volume-fairness, market-regime, thread-safety, recalibration]
dependency_graph:
  requires: ["02-01", "02-02", "02-03"]
  provides: [recalibrated-conviction-scoring, market-regime-filter, volume-fairness, weighted-sentiment]
  affects: [scanner.py, sentiment_cache.py, config.py, tests/test_scanner.py, tests/test_sentiment_cache.py]
tech_stack:
  added: [math.tanh for sigmoid stretching]
  patterns: [weighted keyword tiers, per-day caching with threading.Lock, per-strategy volume logic]
key_files:
  modified:
    - config.py
    - sentiment_cache.py
    - scanner.py
    - tests/test_sentiment_cache.py
    - tests/test_scanner.py
decisions:
  - "Conviction threshold lowered to 5.8 (from 7.0) to achieve 10-20% pass rate (D-01 updated)"
  - "Weighted keyword tiers with tanh stretching for wider sentiment spread — strong keywords score 2x, tanh(raw*2.5) maps extremes to > 7 or < 3 (D-06)"
  - "Trending topic detection at >= 8 articles applies 1.3x deviation amplification (D-07)"
  - "Volume fairness: mean_reversion and catalyst get neutral 5.0 volume score instead of being penalized for normal volume (D-18)"
  - "SPY 20-day SMA regime filter applies MARKET_REGIME_BEARISH_MULT (0.7) to composites when bearish (D-19)"
  - "Sector cache protected by threading.Lock to prevent data races in parallel scan (D-21)"
metrics:
  duration: "~25 min"
  completed: "2026-03-29"
  tasks_completed: 2
  files_modified: 5
---

# Phase 2 Plan 4: Scoring Recalibration Summary

Recalibrated all scoring subsystems to fix 9 identified flaws that caused the bot to almost never trade (0.4% pass rate at threshold 7.0).

## What Was Done

Implemented 6 targeted fixes across config.py, sentiment_cache.py, and scanner.py, then updated/added tests for all new behaviors.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Recalibrate config, sentiment, and scanner formulas | 66c8745 | config.py, sentiment_cache.py, scanner.py |
| 2 | Update tests for recalibrated scoring | b36f2e6 | tests/test_sentiment_cache.py, tests/test_scanner.py |

## Changes Made

### config.py

- `CONVICTION_THRESHOLD` default changed from 7.0 to 5.8 (D-01 updated)
- Added `MARKET_REGIME_ETF` (default "SPY") and `MARKET_REGIME_BEARISH_MULT` (default 0.7) (D-19)

### sentiment_cache.py

- Replaced flat `_BULLISH_KEYWORDS`/`_BEARISH_KEYWORDS` lists with weighted tiers:
  - `_BULLISH_KEYWORDS_STRONG` (weight 2.0) — "surges", "strong buy", "record high", etc.
  - `_BULLISH_KEYWORDS_MODERATE` (weight 1.0) — "upgrade", "beat", "rally", etc.
  - `_BEARISH_KEYWORDS_STRONG` (weight 2.0) — "plunges", "SEC investigation", "sell rating", etc.
  - `_BEARISH_KEYWORDS_MODERATE` (weight 1.0) — "downgrade", "misses", "bearish", etc.
- `_score_headlines()` now uses tanh(raw * 2.5) for sigmoid stretching — produces >7 for clearly bullish, <3 for clearly bearish (D-06)
- `_fetch_sentiment()` now applies 1.3x deviation amplification when >= 8 articles are returned (trending topic detection D-07)

### scanner.py

- Added `import threading`
- Added `_sector_cache_lock` and `_regime_lock` at module level (D-21)
- `_get_stock_sector_score()` now wraps reads and writes with `_sector_cache_lock` (D-21)
- Added `_market_regime_multiplier()` function — checks SPY vs 20-day SMA, caches per day, returns 1.0 (neutral) or MARKET_REGIME_BEARISH_MULT (bearish) (D-19)
- `_score_symbol_multi()` now uses per-strategy volume fairness: if only volume-neutral strategies (mean_reversion, catalyst) fired, volume sub-score is 5.0 instead of the penalized formula value (D-18)
- `_score_symbol_multi()` now applies `_market_regime_multiplier()` to composite before earnings penalty (D-19)
- Conviction breakdown dict now includes `regime_multiplier` key (D-05)

## Test Coverage Added

### tests/test_sentiment_cache.py (3 new tests)
- `test_sentiment_wider_spread` — validates >7.5 bullish and <2.5 bearish with strong keyword headlines
- `test_trending_topic_amplification` — validates 8+ articles amplifies score further from neutral
- Updated existing bullish/bearish tests to use strong keyword headlines

### tests/test_scanner.py (7 new tests)
- `test_volume_fairness_mean_reversion` — asserts 5.0 volume score when only mean_reversion fires
- `test_volume_fairness_momentum` — asserts formula-based score > 5.0 for momentum with high vol ratio
- `test_market_regime_bearish` — asserts bearish composite < neutral and regime_multiplier == 0.7
- `test_market_regime_neutral` — asserts regime_multiplier == 1.0 in neutral market
- `test_sector_cache_thread_safe` — asserts _sector_cache_lock is a threading.Lock instance
- `test_conviction_threshold_58` — validates composites 5.5 and 5.7 fail the 5.8 threshold
- `test_conviction_at_threshold_58` — validates composite exactly 5.8 passes

## Test Results

56 tests pass (tests/test_scanner.py + tests/test_strategies.py + tests/test_sentiment_cache.py).

## Deviations from Plan

None — plan executed exactly as written. Note: config.py changes were partially committed in advance by parallel agent 02-05 (SWING_WATCHLIST expansion), so the config.py git commit appears in that agent's commit rather than this plan's commit. The threshold and regime config changes are confirmed present (python -c "import config; print(config.CONVICTION_THRESHOLD)" => 5.8).

## Known Stubs

None — all recalibration changes are wired end-to-end and exercised by tests.

## Self-Check: PASSED

- config.py: CONVICTION_THRESHOLD == 5.8, MARKET_REGIME_ETF and MARKET_REGIME_BEARISH_MULT present
- scanner.py: _market_regime_multiplier, _sector_cache_lock, VOLUME_NEUTRAL_STRATEGIES all present
- sentiment_cache.py: _BULLISH_KEYWORDS_STRONG, _BEARISH_KEYWORDS_STRONG, math.tanh scoring present
- Commit 66c8745: feat(02-04) recalibrate scoring — confirmed in git log
- Commit b36f2e6: test(02-04) add recalibration tests — confirmed in git log
- 56 tests pass
