---
phase: 01-safety-infrastructure
plan: 04
subsystem: ui
tags: [flask, dashboard, bracket-orders, stop-loss, take-profit, html, css, javascript, pytest]

# Dependency graph
requires:
  - phase: 01-02
    provides: get_active_stop_loss_symbols, check_shutdown_stop_losses, bracket_info in shared_state

provides:
  - /api/positions enhanced with stop_loss_price, take_profit_price, bracket_status per position
  - POST /api/config/exits for runtime update of TRAILING_STOP_PCT / TAKE_PROFIT_PCT
  - POST /api/stop with check_only=true for shutdown bracket protection check
  - Positions table with Stop-Loss, Take-Profit, Status columns + bracket status badges
  - Exit Settings panel in controls column with Apply Changes button
  - Shutdown warning modal for unprotected positions (Stop Without Protection?)
affects: [future-dashboard-plans, options-engine, ui-verification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Flask test client pattern: dashboard.set_dependencies() + app.test_client() for API integration tests"
    - "Runtime config mutation: config.TRAILING_STOP_PCT = val updates the live config module in place"
    - "Shutdown check gate: POST /api/stop?check_only=true returns protection status without side effects"

key-files:
  created: []
  modified:
    - dashboard.py
    - templates/index.html
    - tests/test_bracket.py

key-decisions:
  - "UI sends percentages (e.g. 4.0), config stores decimals (0.04) — /api/config/exits divides by 100 at boundary"
  - "check_only=true on /api/stop returns JSON without triggering shutdown — allows JS to preview protection status"
  - "Sell All button now routes through stopBotWithCheck() instead of triggerSellAll() directly"

patterns-established:
  - "Bracket status display: protected (green glow badge), unprotected (red pulsing badge), placing (yellow badge)"
  - "Exit settings feedback: inline message below button, green 3s auto-dismiss on success, red persistent on failure"

requirements-completed: [BRACKET-04, BRACKET-05]

# Metrics
duration: ~15min
completed: 2026-03-28
---

# Phase 01 Plan 04: Dashboard Bracket Visibility + Exit Settings Summary

**Dashboard positions table shows SL/TP prices and bracket status badges; Exit Settings panel updates stop-loss and take-profit percentages at runtime via POST /api/config/exits**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-28T18:30:00Z
- **Completed:** 2026-03-28T18:45:00Z
- **Tasks:** 3 of 3 complete (all tasks done, visual verification passed)
- **Files modified:** 3

## Accomplishments

- /api/positions now returns stop_loss_price, take_profit_price, and bracket_status for each position — derived from shared state bracket_info or computed from config percentages as fallback
- POST /api/config/exits validates percentage ranges (SL: 1-10%, TP: 2-20%) and mutates config.TRAILING_STOP_PCT / config.TAKE_PROFIT_PCT at runtime
- POST /api/stop with check_only=true returns shutdown bracket protection status without side effects
- Positions table gains Stop-Loss (red JetBrains Mono), Take-Profit (green JetBrains Mono), and Status badge columns
- Three badge variants: badge-protected (green glow), badge-unprotected (red pulsing animation), badge-sl-pending (yellow)
- Exit Settings panel added to controls column with SL% / TP% inputs initialized from account API and Apply Changes button
- Shutdown warning modal ("Stop Without Protection?") triggered via stopBotWithCheck() before any sell-all action
- All 17 bracket tests pass (13 pre-existing + 4 new API tests)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add bracket info to positions API + exit settings endpoint** - `73f8a80` (feat)
2. **Task 2: Add bracket UI components to dashboard HTML** - `2e8dc84` (feat)
3. **Task 3: Verify dashboard bracket UI visually** - CHECKPOINT APPROVED (human visual verification passed)

## Files Created/Modified

- `dashboard.py` - Enhanced /api/positions with bracket fields; added POST /api/config/exits; added POST /api/stop with check_only support; imported get_active_stop_loss_symbols and check_shutdown_stop_losses from safety
- `templates/index.html` - Added badge-protected/badge-unprotected/badge-sl-pending CSS; updated positions table headers (3 new columns); updated loadPositions() JS to render SL/TP prices and status badges; added Exit Settings panel; added shutdown warning modal; added applyExitSettings(), stopBotWithCheck(), placeStopLossesFirst(), stopBotAnyway(), actuallyStopBot() functions; initialized SL/TP inputs from account API
- `tests/test_bracket.py` - Added 4 new tests: test_positions_api_includes_sl_tp, test_positions_api_unprotected, test_config_exits_valid, test_config_exits_invalid_range; added app_client fixture using Flask test client

## Decisions Made

- UI sends percentages (e.g. 4.0 for 4%), config stores decimals (0.04) — /api/config/exits divides by 100 at the API boundary for clean UX
- check_only=true on /api/stop returns protection status JSON without triggering shutdown — allows JS to show the warning modal before any destructive action
- Sell All button now routes through stopBotWithCheck() to check bracket status first, falling back to actuallyStopBot() if all protected or API unreachable

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. All changes use existing Alpaca credentials and in-process config mutation.

## Next Phase Readiness

- BRACKET-04 and BRACKET-05 are fully implemented, tested, and visually verified
- Phase 01 safety-infrastructure is fully complete (all 4 plans done)
- Phase 02 (Prediction Engine + Stock Scanning) is unblocked and ready to begin

## Known Stubs

None — all data is wired. SL/TP prices display either from bracket_info in shared state (set by safety.py after real bracket orders) or fall back to computed values from config percentages applied to avg_entry_price.

## Self-Check: PASSED

- `dashboard.py` modified: FOUND
- `templates/index.html` modified: FOUND
- `tests/test_bracket.py` modified: FOUND
- Commit `73f8a80` (Task 1): FOUND
- Commit `2e8dc84` (Task 2): FOUND
- Task 3 human verify: APPROVED

---
*Phase: 01-safety-infrastructure*
*Completed: 2026-03-28*
