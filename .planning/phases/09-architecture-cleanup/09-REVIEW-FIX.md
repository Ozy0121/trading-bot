---
phase: 09-architecture-cleanup
fixed_at: 2026-05-22T00:00:00Z
review_path: .planning/phases/09-architecture-cleanup/09-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 09: Code Review Fix Report

**Fixed at:** 2026-05-22T00:00:00Z
**Source review:** .planning/phases/09-architecture-cleanup/09-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6
- Fixed: 6
- Skipped: 0

## Fixed Issues

### CR-01: Thread-unsafe shallow copy in state.snapshot() leaks mutable references

**Files modified:** `state.py`
**Commit:** 35b93b1
**Applied fix:** Added `copy.deepcopy()` for all mutable nested collections (predictions, watchlist, positions, trade_history, pnl_calendar, bracket_info, expanded_scan_results, heatmap_data, scan_funnel, expanded_scan_funnel, protection_status, scan_conviction_scores, and series data) inside the lock in `snapshot()`. The existing `history` and `trade_log` deque-to-list conversions are preserved.

### WR-01: Bot phase execution order does not match phase numbering

**Files modified:** `bot.py`
**Commit:** 375bc7d
**Applied fix:** Moved `_phase_13_push_history(ctx)` from before sell/buy logic to after. It now runs after `_phase_11_sell_logic` (before continue on sell) and after `_phase_12_buy_logic`, ensuring chart history reflects the current cycle's trade action.

### WR-02: SSE stream captures coordinator once per connection, misses late initialization

**Files modified:** `routes/data.py`
**Commit:** d6c1c5f
**Applied fix:** Moved `from dashboard import _coordinator` from outside the `generate()` function to inside the `while True` loop, so each SSE tick re-reads the current coordinator value. Clients that connect before coordinator initialization will pick it up on the next tick.

### WR-03: server.py has no __main__ guard -- importing triggers full startup

**Files modified:** `server.py`
**Commit:** 50d001d
**Applied fix:** Wrapped all startup logic (mode parsing, env loading, client creation, background thread launches, Flask server start) inside a `_main()` function with `if __name__ == "__main__": _main()` guard. Accidental imports of `server` no longer trigger the full startup sequence.

### WR-04: api_order route does not validate symbol for injection-safe characters

**Files modified:** `routes/trading.py`
**Commit:** 8551ae1
**Applied fix:** Replaced bare `if not symbol` check with `if not symbol or not symbol.isalnum() or len(symbol) > 10` validation. Added quantity bounds check (`qty <= 0 or qty > 10000`) after float conversion.

### WR-05: prediction_scanner monkey-patches _ev attribute onto prediction objects

**Files modified:** `prediction_scanner.py`
**Commit:** b066071
**Applied fix:** Replaced the `for p in high_confidence: p._ev = ...` mutation loop and `lambda p: p._ev` sort key with a local `_ev_key(p)` function used directly as the sort key. No prediction objects are mutated.

---

_Fixed: 2026-05-22T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
