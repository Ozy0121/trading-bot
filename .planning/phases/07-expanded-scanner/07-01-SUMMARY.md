---
phase: 07-expanded-scanner
plan: 01
subsystem: scoring-factors
tags: [smc, quant-factors, multi-factor-model, smartmoneyconcepts]
dependency_graph:
  requires: [indicators.py]
  provides: [smc_factors.py, quant_factors.py]
  affects: [stock_universe.py, scanner.py]
tech_stack:
  added: [smartmoneyconcepts>=0.0.27]
  patterns: [multi-factor-scoring, cross-sectional-ranking, tdd]
key_files:
  created:
    - smc_factors.py
    - quant_factors.py
    - tests/test_smc_factors.py
    - tests/test_quant_factors.py
  modified:
    - requirements.txt
decisions:
  - "swing_length=5 for daily bars (research open question 3 resolved)"
  - "Factor weights 30/25/25/20 (momentum/quality/SMC/volatility) per D-02/A1"
  - "Quality factor uses OBV + ADL slope binary scoring (>0 = +5 each)"
  - "Flat OBV test uses truly constant OHLC (not just constant close) for deterministic ADL=0"
metrics:
  duration: "4m 22s"
  completed: "2026-04-18T00:53:35Z"
  tasks_completed: 2
  tasks_total: 2
  tests_added: 8
  tests_passing: 8
---

# Phase 07 Plan 01: Factor Scoring Modules Summary

SMC + multi-factor quant scoring modules with smartmoneyconcepts 0.0.27 for tier 4 expanded scanner pipeline

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Install smartmoneyconcepts and create smc_factors.py + tests | d9ae2f6 | smc_factors.py, tests/test_smc_factors.py, requirements.txt |
| 2 | Create quant_factors.py with multi-factor model + tests (TDD) | d6f52f1 (red), a8a4852 (green) | quant_factors.py, tests/test_quant_factors.py |

## What Was Built

### smc_factors.py
- `compute_smc_score(df)` returns 0-10 float from OHLCV daily bars
- Detects: Order Blocks (up to 4.0), Liquidity Sweeps (up to 3.0), BOS/CHoCH (up to 2.0), FVG (up to 1.0)
- Uses swing_length=5 for daily bar resolution
- Each SMC function call wrapped in try/except with warning log on failure
- Guards: returns 0.0 for <20 bars, empty DataFrame, or <2 detected swings

### quant_factors.py
- `compute_quant_score(symbol, df, momentum_rank)` returns dict with 6 keys (symbol + 5 scores)
- `rank_momentum(bars_by_symbol)` computes cross-sectional percentile ranks (0.0-1.0)
- Factor weights: momentum 30%, quality 25%, SMC 25%, volatility 20%
- Quality: binary OBV slope (+5) + ADL slope (+5) over 20-bar window
- Volatility: ATR contraction ratio mapped to 0-10 (lower current ATR% = higher score)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Flat OBV test data adjusted for ADL behavior**
- **Found during:** Task 2 (TDD green)
- **Issue:** Test used `_make_ohlcv(trend="flat")` which sets close=100 but randomizes high/low/volume, causing ADL to have nonzero slope (ADL MFM depends on close position within high-low range, not just close changes)
- **Fix:** Changed test to use truly constant OHLC (high=low=open=close=100) so both OBV and ADL produce zero slopes
- **Files modified:** tests/test_quant_factors.py
- **Commit:** a8a4852

## Verification Results

All 8 tests pass across both test files:
- `tests/test_smc_factors.py`: 4 passed
- `tests/test_quant_factors.py`: 4 passed
- smartmoneyconcepts 0.0.27 installed and in requirements.txt
- No imports from scanner.py (isolation per D-04 confirmed)

## Self-Check: PASSED

All 4 created files exist. All 3 commits verified in git log.
