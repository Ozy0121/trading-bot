---
phase: 09-architecture-cleanup
plan: 03
subsystem: bot, server, predictions
tags: [refactor, data-unification, resilience, decomposition]
dependency_graph:
  requires: ["09-01", "09-02"]
  provides: [unified-prediction-source, resilient-server-startup, decomposed-bot-loop]
  affects: [bot.py, server.py, prediction_scanner.py, routes/scanner.py, routes/trading.py]
tech_stack:
  added: [dataclasses]
  patterns: [cycle-context-dataclass, per-service-try-except-isolation, phase-function-extraction]
key_files:
  created: []
  modified:
    - bot.py
    - server.py
    - prediction_scanner.py
    - routes/scanner.py
    - routes/trading.py
decisions:
  - "Moved api_predictions_auto_trade fix to routes/trading.py (plan incorrectly specified routes/scanner.py)"
  - "Consolidated sell logic (trailing stop, take-profit, SMA signal) into single _phase_11_sell_logic returning bool"
  - "Moved push_history before sell logic in orchestrator to ensure chart data captured even when sell triggers early continue"
  - "Kept run_bot startup bracket check inline (one-time setup, not a cycle phase)"
metrics:
  duration: "7 min"
  completed: "2026-05-19"
  tasks: 3
  files: 5
---

# Phase 09 Plan 03: Prediction Unification, Server Isolation, Bot Decomposition Summary

Unified prediction data sources via shared_state (D-03), isolated all optional server startup services (D-05), and decomposed run_bot into 13 named phase functions with CycleContext dataclass.

## One-liner

Single prediction data source via shared_state, resilient server startup with per-service isolation, and run_bot decomposed into 13 named phase functions

## What Was Done

### Task 1: Unify prediction data sources to shared_state (D-03)

- Added `load_predictions_into_state()` to `prediction_scanner.py` -- loads today's disk predictions into shared_state on startup, skips stale data
- Changed `bot.py` `_get_prediction_candidate()` to read from `shared_state.snapshot()["predictions"]` instead of `get_latest_predictions()` disk reader
- Changed `routes/scanner.py` `api_overnight()` to read from `shared_state.snapshot()["overnight_predictions"]` instead of disk
- Changed `routes/trading.py` `api_predictions_auto_trade()` to read from `shared_state.snapshot()["predictions"]` instead of disk
- Added startup hydration call in `server.py` after `dashboard.set_dependencies()`

### Task 2: Isolate server.py startup failures (D-05)

Wrapped each optional service in its own try/except block with descriptive warning messages:

| Service | Log message on failure |
|---------|----------------------|
| Live stream | "continuing without live prices" |
| Sentiment feed | "continuing without sentiment" |
| Prediction hydration | "continuing without cached predictions" |
| Agent coordinator | "continuing without agents" |
| Claude Office | "continuing without pixel art" |
| Office bridge | "continuing without pixel art bridge" |
| Overnight scheduler | "continuing without overnight scans" |
| Expanded scanner daemon | "continuing without expanded scans" |
| Protection monitor | "continuing without stop-loss monitoring" |

Critical services remain unguarded (fail loud): TradingClient, StockHistoricalDataClient, validate_options_enabled, dashboard.set_dependencies, dashboard.run.

Moved `import subprocess` and `import atexit` inside `_start_office()` to avoid import side effects at module scope.

### Task 3: Extract run_bot phases into named functions

- Added `_CycleContext` dataclass with 22 fields for per-cycle state
- Extracted 13 phase functions: `_phase_1_scan_watchlist` through `_phase_13_push_history`
- `run_bot()` main loop body reduced to ~30 lines of phase function calls
- All existing behavior preserved -- mechanical extraction only
- `run_bot_from_server()` entry point unchanged

## Verification Results

| Check | Result |
|-------|--------|
| `load_predictions_into_state` callable | PASS |
| bot.py has no `get_latest_predictions` | PASS |
| routes/scanner.py has no `get_latest_predictions` | PASS |
| server.py has `load_predictions_into_state()` | PASS |
| server.py has 12 except handlers (9+ for optional services) | PASS |
| "continuing without live prices" in server.py | PASS |
| "continuing without sentiment" in server.py | PASS |
| "continuing without agents" in server.py | PASS |
| bot.py has 13 `_phase_*` functions | PASS |
| bot.py has `_CycleContext` dataclass | PASS |
| bot.py `run_bot` is 74 lines (loop body ~30 lines) | PASS |
| bot.py `run_bot_from_server` exists | PASS |
| bot.py syntax valid (AST parse clean) | PASS |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] api_predictions_auto_trade was in routes/trading.py, not routes/scanner.py**
- **Found during:** Task 1
- **Issue:** Plan specified `routes/scanner.py` contains `api_predictions_auto_trade()`, but it was actually in `routes/trading.py` (moved there by Plan 09-01 since it's a trading route)
- **Fix:** Applied the shared_state change to `routes/trading.py` instead, also updated the prediction list filtering since shared_state stores a flat list not a dict with "ready_tomorrow" key
- **Files modified:** routes/trading.py

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | 8532a62 | feat(09-03): unify prediction data sources to shared_state (D-03) |
| 2 | 40f8ff6 | feat(09-03): isolate server.py startup failures (D-05) |
| 3 | 14720d0 | refactor(09-03): extract run_bot phases into 13 named functions |

## Self-Check: PASSED

All 5 modified files verified on disk. All 3 commit hashes found in git log.
