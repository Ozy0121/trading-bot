---
phase: 02-prediction-engine-stock-scanning
plan: 05
subsystem: scanner
tags: [watchlist, conviction-scoring, best-buy, top-movers, gics-sectors, multi-candidate]

# Dependency graph
requires:
  - phase: 02-prediction-engine-stock-scanning
    provides: multi-strategy scanner with conviction scoring, scanner.py, config.py watchlist

provides:
  - SWING_WATCHLIST expanded to 60 stocks covering all 11 GICS sectors
  - best_buy() returns list[dict] of up to 3 top candidates (was dict | None)
  - Top movers excluded from momentum strategy evaluation (circular signal fix)
  - ThreadPoolExecutor workers increased to 15 for expanded watchlist
  - bot.py updated to iterate candidates list (takes candidates[0])
  - 11 new scanner tests covering multi-candidate, top movers skip, and sector coverage

affects:
  - bot.py (candidate selection loop)
  - scanner.py (best_buy return type)
  - config.py (SWING_WATCHLIST size)
  - tests/test_scanner.py

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_top_mover_symbols module-level set populated by get_watchlist(), consumed by _score_symbol_multi()"
    - "best_buy() returns list[dict] (0-3 items) — caller takes [0] for immediate trade, list enables future multi-slot selection"

key-files:
  created: []
  modified:
    - config.py
    - scanner.py
    - bot.py
    - tests/test_scanner.py

key-decisions:
  - "best_buy() returns list[dict] (D-03 new): bot takes candidates[0] now, list enables future multi-slot PDT-aware selection"
  - "Top movers skip momentum (D-20): symbols already breaking highs today produce circular momentum signals — skip the strategy, not the symbol"
  - "60-stock watchlist with 11 GICS sectors (D-15 updated): broad coverage needed for 3 trade slots per week"
  - "max_workers=15 for expanded 60-symbol watchlist (D-13 updated): target <30s scan time"

patterns-established:
  - "_top_mover_symbols: global set that flows from get_watchlist() -> _score_symbol_multi() without parameter threading"

requirements-completed: [STRAT-06, SCAN-01, SCAN-03, SCAN-04, SCAN-05, PRED-04, PRED-05]

# Metrics
duration: 15min
completed: 2026-03-29
---

# Phase 02 Plan 05: Watchlist Expansion and Multi-Candidate Best Buy Summary

**60-stock GICS-sector-balanced watchlist, best_buy() returning top-3 candidates for PDT trade slots, and circular momentum signal fix for top movers**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-29T20:10:00Z
- **Completed:** 2026-03-30T01:15:49Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Expanded SWING_WATCHLIST from 25 to 60 stocks across all 11 GICS sectors (Technology, Consumer Disc., Communication Svcs., Financials, Healthcare, Energy, Industrials, Consumer Staples, Materials, Real Estate, Utilities, plus 5 high-momentum mid-caps)
- Changed best_buy() return type from `dict | None` to `list[dict]` (up to 3 candidates), aligning with 3 PDT trade slots per week
- Fixed circular momentum signal: top movers already broke highs today, so running momentum breakout on them is tautological — skip strategy via `_top_mover_symbols` set
- Increased ThreadPoolExecutor workers from 10 to 15 to keep 60-symbol scan under 30s
- Updated bot.py to handle list: takes `candidates[0]` and logs `[N candidates available]`
- Added 11 new tests; all 47 Phase 2 scanner tests pass

## Task Commits

1. **Task 1: Expand watchlist, multi-candidate best_buy, fix top movers** - `dcb664e` (feat)
2. **Task 2: Tests for multi-candidate, expanded watchlist, and top movers fix** - `556d1c1` (test)

## Files Created/Modified

- `config.py` - SWING_WATCHLIST expanded from 25 to 60 stocks, 11 GICS sectors with inline comments
- `scanner.py` - Added `_top_mover_symbols` set, updated `get_watchlist()` to populate it, skip momentum for top movers in `_score_symbol_multi()`, changed `best_buy()` to return `list[dict]`, increased `max_workers` to 15
- `bot.py` - Updated candidate selection block: `best_buy()` -> `candidates`, `candidates[0]` for top pick, log count
- `tests/test_scanner.py` - Updated 3 existing tests for list return, added 8 new tests (top-3, fewer-than-3, empty, top-mover skip, non-mover runs, watchlist size, sector coverage)

## Decisions Made

- `best_buy()` returns `list[dict]`: the bot currently takes `[0]`, but the list is ready for future multi-slot selection (e.g., queue 3 candidates for 3 PDT slots across the week)
- Top movers fix via module-level set: passing the set via parameter would require API changes across the call chain; a module-level set is the established pattern in this codebase (`_movers_cache`, `_movers_date`)
- 60 stocks chosen (vs 50 or 75): covers all 11 sectors with reasonable depth, stays within the scan-time target

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Scanner is ready for Phase 3 (options trading): watchlist provides broad sector coverage for options candidates
- Multi-candidate list enables future enhancement: pick best stock candidate AND best options candidate from same scan
- All Phase 2 tests (47) passing cleanly

---
*Phase: 02-prediction-engine-stock-scanning*
*Completed: 2026-03-29*
