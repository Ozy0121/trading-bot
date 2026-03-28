---
phase: 01-safety-infrastructure
plan: 02
subsystem: safety
tags: [alpaca, bracket-orders, fill-polling, stop-loss, take-profit, oco, pdt, pytest]

# Dependency graph
requires:
  - phase: 01-01
    provides: pytest fixtures (conftest.py), config constants ORDER_FILL_TIMEOUT/ORDER_FILL_POLL_INTERVAL, load_state_from_file
provides:
  - OrderClass.BRACKET on every stock buy (stop-loss 3% below, take-profit 6% above entry)
  - poll_order_fill with 10s timeout; handles FILLED, PARTIALLY_FILLED, REJECTED, CANCELED
  - get_active_stop_loss_symbols to detect HELD bracket legs via QueryOrderStatus.ALL + nested=True
  - place_oco_exit for OCO stop-loss+take-profit recovery on unprotected positions
  - check_shutdown_stop_losses for shutdown verification of all held positions
  - Startup: auto-recreates missing bracket orders for existing positions
  - Shutdown: warns about any position lacking server-side stop-loss before liquidation
  - bracket_info in shared state for per-symbol stop/take-profit display (BRACKET-04 prep)
affects: [03-liquidation-options, 04-options-engine, dashboard-bracket-display]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bracket order pattern: MarketOrderRequest(order_class=OrderClass.BRACKET, stop_loss=StopLossRequest(...), take_profit=TakeProfitRequest(...))"
    - "Fill polling: tight loop with monotonic deadline, returns on any terminal status, logs timeout warning"
    - "Bracket child leg detection: must use QueryOrderStatus.ALL + nested=True; legs appear as OrderStatus.HELD"
    - "OCO recovery: LimitOrderRequest(order_class=OrderClass.OCO) for existing positions without bracket"

key-files:
  created:
    - tests/test_bracket.py
  modified:
    - safety.py
    - bot.py
    - state.py

key-decisions:
  - "Bracket child legs only visible with QueryOrderStatus.ALL + nested=True (critical Alpaca gotcha)"
  - "Partial fills accepted: bracket legs auto-placed by Alpaca for filled qty, no special handling needed"
  - "load_state_from_file() called at run_bot startup to restore peak prices and PDT state before bracket check"

patterns-established:
  - "Bracket safety check: every place_buy must call poll_order_fill then log BRACKET_ORDER_PLACED"
  - "OCO recovery: place_oco_exit called for any position without HELD stop-loss leg during startup"

requirements-completed: [SAFE-03, BRACKET-01, BRACKET-02, BRACKET-03]

# Metrics
duration: 4min
completed: 2026-03-28
---

# Phase 01 Plan 02: Bracket Orders — Server-Side Stop-Loss on Every Buy Summary

**OrderClass.BRACKET on every stock buy with fill polling, startup OCO recovery for unprotected positions, and shutdown stop-loss verification**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-28T18:14:00Z
- **Completed:** 2026-03-28T18:18:28Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Every stock buy now submits a bracket order with stop-loss 3% below and take-profit 6% above entry — orders live on Alpaca's servers even when the bot is offline
- Fill polling with 10s timeout runs after every order submission: handles FILLED, PARTIALLY_FILLED, REJECTED with explicit log messages and return values
- Bot startup checks all existing positions for active bracket stop-loss legs; recreates missing ones via OCO order automatically (BRACKET-02)
- Shutdown signal handler warns about any unprotected positions before liquidation (BRACKET-03)
- bracket_info stored in shared_state per symbol for future dashboard display (BRACKET-04 prep)
- All 13 bracket tests pass; full suite of 20 tests passes

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Failing tests for safety helper functions** - `6b5a3d0` (test)
2. **Task 1 GREEN: poll_order_fill, get_active_stop_loss_symbols, place_oco_exit, check_shutdown_stop_losses** - `eb66c56` (feat)
3. **Task 2: Bracket orders in place_buy + startup/shutdown checks** - `c356b33` (feat)

## Files Created/Modified

- `tests/test_bracket.py` - 13 tests covering SAFE-03, BRACKET-01, BRACKET-02, BRACKET-03
- `safety.py` - Added poll_order_fill, get_active_stop_loss_symbols, place_oco_exit, check_shutdown_stop_losses; updated imports to include StopLossRequest, TakeProfitRequest, LimitOrderRequest, OrderClass, OrderStatus
- `bot.py` - Modified place_buy to use OrderClass.BRACKET + fill polling; added startup bracket check in run_bot; added shutdown check in _handle_signal; updated imports
- `state.py` - Added bracket_info dict for per-symbol stop/take-profit state

## Decisions Made

- Partial fills accepted without retry: Alpaca automatically places bracket child legs for the filled quantity, so no special handling is needed
- `load_state_from_file()` called at bot startup (before bracket check) to restore peak prices and PDT history from prior session
- Bracket child legs must be queried with `QueryOrderStatus.ALL` + `nested=True` — they appear as `OrderStatus.HELD` and are invisible when filtering by `QueryOrderStatus.OPEN`

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. Bracket orders are placed via existing Alpaca credentials; no new API permissions needed beyond existing trading access.

## Next Phase Readiness

- Bracket infrastructure complete: every buy is server-protected even with bot offline
- `bracket_info` in shared_state is populated per symbol — dashboard can read it to display stop/take-profit prices (BRACKET-04)
- Plans 03 and 04 can build on the test fixture and safety patterns established in plans 01-02

---
*Phase: 01-safety-infrastructure*
*Completed: 2026-03-28*
