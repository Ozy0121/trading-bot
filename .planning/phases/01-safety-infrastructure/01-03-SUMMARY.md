---
phase: 01-safety-infrastructure
plan: 03
subsystem: safety
tags: [options, liquidation, safety, alpaca, limit-orders, validation, tdd]

# Dependency graph
requires: [01-01]
provides:
  - Options-aware liquidate_all() that uses LimitOrderRequest for OCC symbols
  - validate_options_enabled() that gates live-mode startup on Level 2+ options approval
  - server.py startup call to validate_options_enabled before bot services start
affects: [03-options-engine, 04-dashboard-enhancement]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD: RED commit (failing tests) then GREEN commit (implementation) per task"
    - "OCC symbol detection via is_options_symbol() gates order type selection in liquidate_all"
    - "Paper mode skips options approval check; live mode requires options_approved_level >= 2"

key-files:
  created: []
  modified:
    - safety.py
    - server.py
    - tests/test_safety.py

key-decisions:
  - "Options liquidation uses LimitOrderRequest at round(current_price, 2) as mid-price approximation (D-08)"
  - "validate_options_enabled() raises SystemExit(1) in live mode when level < 2 or None -- hard stop, not a warning"
  - "Paper mode unconditionally skips options validation to avoid paper account approval level mismatches (D-10)"

requirements-completed: [SAFE-04, SAFE-05]

# Metrics
duration: 4min
completed: 2026-03-28
---

# Phase 01 Plan 03: Options-Aware Liquidation and Options Trading Validation Summary

**LimitOrderRequest for options positions in emergency liquidation + startup gate blocking live mode without Level 2 options approval**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-28T18:14:26Z
- **Completed:** 2026-03-28T18:18:24Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 3

## Accomplishments

- `liquidate_all()` now detects OCC-format options symbols via `is_options_symbol()` and submits `LimitOrderRequest` at `round(current_price, 2)` (mid-price approximation per D-08). Stock positions continue to use `MarketOrderRequest`. Zero-price floor of `0.01` prevents invalid limit orders.
- `validate_options_enabled()` added to `safety.py`: in live mode requires `options_approved_level >= 2` or calls `SystemExit(1)`. In paper mode skips the check entirely (per D-10: paper accounts may not reflect live approval).
- `server.py` now calls `validate_options_enabled(trading_client, live_mode=not config.PAPER_TRADING)` immediately after `TradingClient` and `StockHistoricalDataClient` are created, before any background services start.
- All 8 new tests pass (4 liquidation, 4 validation), plus all 7 pre-existing tests continue to pass (15 total).

## Task Commits

Each task committed atomically via TDD:

1. **Task 1 RED: Failing tests for SAFE-04 and SAFE-05** - `8e0dd9c` (test)
2. **Task 1 GREEN: Options-aware liquidation and options trading validation** - `2133b8b` (feat)

## Files Created/Modified

- `safety.py` - Added `LimitOrderRequest` import; added `validate_options_enabled()`; updated `liquidate_all()` position loop to branch on `is_options_symbol()`
- `server.py` - Added `validate_options_enabled` to import; added startup call after client creation
- `tests/test_safety.py` - Added 8 tests: `test_liquidate_all_stock_only`, `test_liquidate_all_options_position`, `test_liquidate_all_mixed`, `test_liquidate_all_options_uses_limit_price`, `test_validate_options_live_level_ok`, `test_validate_options_live_level_too_low`, `test_validate_options_live_level_none`, `test_validate_options_paper_skips`

## Decisions Made

- `LimitOrderRequest` at `round(current_price, 2)` chosen as mid-price approximation for emergency options liquidation — avoids needing a live quote API call during shutdown
- `SystemExit(1)` (not `ValueError` or `RuntimeError`) used for options validation failure to produce a clean error message visible in the terminal without a traceback
- `except SystemExit: raise` pattern used to prevent the broad `except Exception` catch from swallowing the exit

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required. Options validation only runs in live mode; paper mode is unaffected.

## Next Phase Readiness

- `validate_options_enabled()` is now available for reuse if Phase 3 (options engine) needs a runtime check
- `is_options_symbol()` + `LimitOrderRequest` pattern established for options order submission in Phase 3

---
*Phase: 01-safety-infrastructure*
*Completed: 2026-03-28*
