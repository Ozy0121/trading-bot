# Quick Task 260402-e9l: Fix stop-without-liquidate and wire up agent coordinator

**Completed:** 2026-04-02
**Status:** Done

## Changes

### Task 1: Fix /api/stop and signal handler to stop without liquidating

**Files:** `dashboard.py`, `bot.py`

- Removed `liquidate_all()` call from `/api/stop` route — now only calls `request_shutdown()` and sets status to stopped
- Removed `liquidate_all()` call from `_handle_signal` (SIGINT/SIGTERM) — keeps the bracket protection warning but no longer sells positions
- `/api/sell_all` is unchanged and still liquidates all positions (the only way to force-sell)
- Updated bot.py docstring to reflect new behavior

### Task 2: Wire coordinator.run_cycle() into bot.py main loop

**Files:** `bot.py`, `server.py`

- Added `_coordinator` module-level variable and `set_coordinator()` function to bot.py
- `coordinator.startup_sequence()` runs after bracket check, before the main loop
- `coordinator.run_cycle()` runs each iteration after step 7 (watchlist scan), executing the full 6-agent pipeline: Quant + News (parallel) -> Strategist -> Risk Manager -> Executor
- `coordinator.shutdown_sequence()` runs after the main loop exits
- `server.py` now calls `bot.set_coordinator(coordinator)` to wire it in
- Existing manual trading logic still runs as fallback alongside the coordinator

## Verification

- `/api/stop` route contains no `liquidate_all` reference
- `/api/sell_all` still contains `liquidate_all` (unchanged)
- Signal handler `_handle_signal` contains no `liquidate_all`
- `bot.py` contains `run_cycle`, `startup_sequence`, `shutdown_sequence` calls
- `server.py` contains `bot.set_coordinator(coordinator)`
- Both modules import without error
