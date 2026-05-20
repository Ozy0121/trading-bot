---
phase: 09-architecture-cleanup
reviewed: 2026-05-20T03:42:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - bot.py
  - dashboard.py
  - prediction_scanner.py
  - routes/__init__.py
  - routes/data.py
  - routes/scanner.py
  - routes/trading.py
  - safety.py
  - server.py
  - state.py
findings:
  critical: 1
  warning: 5
  info: 3
  total: 9
status: issues_found
---

# Phase 09: Code Review Report

**Reviewed:** 2026-05-20T03:42:00Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Phase 09 decomposed `dashboard.py` into Flask Blueprints (`routes/trading.py`, `routes/scanner.py`, `routes/data.py`), added `_globals_lock` to `safety.py`, added schema validation (`ValueError` on unknown keys) to `state.py`, and decomposed `run_bot()` into named phase functions. The Blueprint split is clean and the dependency injection pattern through `dashboard` module globals works correctly with lazy imports in route handlers.

Key concerns: a thread-safety gap in `state.snapshot()` allows concurrent mutation of nested collections, a phase execution ordering mismatch in `bot.py`, and the SSE stream captures the coordinator reference once per connection rather than per-tick.


## Critical Issues

### CR-01: Thread-unsafe shallow copy in state.snapshot() leaks mutable references

**File:** `state.py:200-206`
**Issue:** `snapshot()` does `dict(_state)` which is a shallow copy. Only `history` and `trade_log` (deques) are explicitly converted to lists. All other mutable nested values -- `predictions` (list of dicts), `watchlist` (list), `positions` (list), `trade_history` (list), `pnl_calendar` (dict), `bracket_info` (dict), `expanded_scan_results` (list), `heatmap_data` (list), `scan_funnel` (dict), `expanded_scan_funnel` (dict), `protection_status` (dict) -- are returned as shared references. Any code that mutates a snapshot's nested list/dict (e.g., `snap["predictions"].append(...)` or sorting in-place) corrupts the live state without holding the lock. Multiple routes in `routes/scanner.py` and `routes/trading.py` read these values via `snapshot()` and return them to Flask's `jsonify`, which is safe for read-only access. However, `prediction_scanner.py:91` sets `p._ev` on objects obtained from state, and `routes/scanner.py:82` does `shared_state.update(predictions=pred_dicts)` with new lists. The risk is real for any future code that modifies snapshot results in-place, and the current `record_trade()` directly mutates `_state["trade_history"]` (line 188-197) and `_state["pnl_calendar"]` (line 185) inside the lock, which is correct -- but callers of `snapshot()` holding references to those same objects can observe partial updates.

**Fix:**
```python
def snapshot() -> dict:
    """Return a JSON-serializable deep copy of current state."""
    import copy
    with _lock:
        s = dict(_state)
        s["history"]   = list(s["history"])
        s["trade_log"] = list(s["trade_log"])
        # Deep-copy mutable nested collections to prevent cross-thread mutation
        for key in ("predictions", "watchlist", "positions", "trade_history",
                    "pnl_calendar", "bracket_info", "expanded_scan_results",
                    "heatmap_data", "scan_funnel", "expanded_scan_funnel",
                    "protection_status", "scan_conviction_scores",
                    "_rsi_series", "_macd_series", "_macd_sig_series",
                    "_macd_hist_series", "_bb_upper_series", "_bb_lower_series"):
            if key in s and isinstance(s[key], (list, dict)):
                s[key] = copy.deepcopy(s[key])
    return s
```


## Warnings

### WR-01: Bot phase execution order does not match phase numbering

**File:** `bot.py:808-812`
**Issue:** Inside `run_bot()`, `_phase_13_push_history(ctx)` is called at line 809 -- before `_phase_11_sell_logic` (line 810) and `_phase_12_buy_logic` (line 813). The function names suggest phase 13 should run last, after sell/buy logic. This reordering means chart history is pushed before the sell/buy decision is made in the current cycle, so the chart will never reflect the current cycle's trade action. While not a crash, this is a logic error introduced during the decomposition -- the original monolithic `run_bot` likely had history push at the end.

**Fix:** Move `_phase_13_push_history(ctx)` to after the sell/buy logic block:
```python
            _phase_10_update_state(ctx)
            if _phase_11_sell_logic(ctx):
                _phase_13_push_history(ctx)      # push before sleep
                _interruptible_sleep(config.POLL_INTERVAL)
                continue
            _phase_12_buy_logic(ctx)
            _phase_13_push_history(ctx)
```

### WR-02: SSE stream captures coordinator once per connection, misses late initialization

**File:** `routes/data.py:43`
**Issue:** The `api_stream` route imports `_coordinator` from `dashboard` at the top of the `generate()` generator (line 43: `from dashboard import _coordinator`). This captures the module-level variable's value at connection time. If the coordinator is initialized after an SSE client connects (e.g., during startup race), that client will never see agent status data (`_coordinator` remains `None` for the lifetime of that SSE connection).

**Fix:** Move the import inside the loop so each tick re-reads the current value:
```python
def generate():
    try:
        while True:
            from dashboard import _coordinator   # re-read each tick
            snap = shared_state.snapshot()
            snap["_progress"] = progress.snapshot()
            snap["_scan_logs"] = progress.get_logs()
            if _coordinator:
                snap["_agents"] = _coordinator.get_agents_status()
            yield f"data: {_snap_json(snap)}\n\n"
            time.sleep(1)
    except GeneratorExit:
        pass
```

### WR-03: server.py has no __main__ guard -- importing triggers full startup

**File:** `server.py:23-230`
**Issue:** All startup logic (Alpaca client creation, background thread launches, Flask server start) runs at module level with no `if __name__ == "__main__"` guard. Any accidental `import server` from another module (test code, REPL, or a future refactor) would trigger the entire startup sequence including connecting to Alpaca, starting background threads, and blocking on Flask's `app.run()`.

**Fix:** Wrap everything from line 23 onward in:
```python
if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "paper"
    # ... rest of startup ...
```

### WR-04: api_order route does not validate symbol for injection-safe characters

**File:** `routes/trading.py:40`
**Issue:** The symbol from user input (`body.get("symbol", "").upper().strip()`) is passed directly to `_trading_client.submit_order()`. While Alpaca's SDK likely validates the symbol server-side, there is no client-side validation that the symbol contains only alphanumeric characters. A malformed symbol could cause confusing error messages or unexpected behavior. More importantly, the `qty` value (line 55: `qty = float(qty)`) has no upper bound check -- a user could submit an order for millions of shares.

**Fix:** Add basic validation:
```python
symbol = body.get("symbol", "").upper().strip()
if not symbol or not symbol.isalnum() or len(symbol) > 10:
    abort(400, "Invalid symbol.")
qty = float(qty)
if qty <= 0 or qty > 10000:
    abort(400, "Quantity must be between 1 and 10,000.")
```

### WR-05: prediction_scanner monkey-patches _ev attribute onto prediction objects

**File:** `prediction_scanner.py:91`
**Issue:** The line `p._ev = p.historical_accuracy * p.expected_move_pct ...` dynamically sets a private attribute on prediction objects for sorting. This is fragile because: (a) it mutates objects that may be used elsewhere, (b) `_ev` is not part of the prediction class contract, and (c) if the prediction class uses `__slots__`, this will raise `AttributeError`.

**Fix:** Use a local key function instead of mutating the objects:
```python
def _ev_key(p):
    if p.historical_accuracy > 0:
        return p.historical_accuracy * p.expected_move_pct
    return p.expected_move_pct * 0.5

high_confidence.sort(key=_ev_key, reverse=True)
```


## Info

### IN-01: Empty catch blocks silently swallow errors in bot signal handler

**File:** `bot.py:91-92`
**Issue:** The `except Exception: pass` in `_handle_signal` (line 91-92) silently swallows any error during the shutdown stop-loss check. While this is intentional (signal handlers should not raise), a `log.debug` would aid post-mortem analysis.

**Fix:** `except Exception as exc: log.debug("[bot] Shutdown stop-loss check failed: %s", exc)`

### IN-02: Unused import -- math in routes/trading.py

**File:** `routes/trading.py:8`
**Issue:** `math` is imported at line 8 and used only in `api_performance` at line 408 (`math.ceil`). This is technically used, but the import could be made local to reduce module-level coupling. Low priority.

**Fix:** No action required -- the import is used.

### IN-03: _start_office launches subprocesses with shell=True on Windows

**File:** `server.py:165-170`
**Issue:** The npm frontend subprocess is launched with `shell=True` (line 170). On Windows, `shell=True` passes the command through `cmd.exe`, which is necessary for `npm` (a batch script), but it also opens a minor command injection vector if `frontend_dir` were ever user-controlled. In this case `frontend_dir` is derived from `os.path.expanduser("~")` which is safe, so this is informational only.

**Fix:** No immediate action required. If the path ever becomes user-configurable, switch to `shell=False` with explicit `npm.cmd` on Windows.

---

_Reviewed: 2026-05-20T03:42:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
