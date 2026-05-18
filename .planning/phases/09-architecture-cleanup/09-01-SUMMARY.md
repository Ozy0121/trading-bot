---
phase: 09-architecture-cleanup
plan: 01
subsystem: dashboard
tags: [refactor, flask, blueprints, architecture]
dependency_graph:
  requires: []
  provides: [blueprint-routing, modular-dashboard]
  affects: [dashboard.py, server.py]
tech_stack:
  added: [flask-blueprints]
  patterns: [lazy-import-dependency-injection, blueprint-registration]
key_files:
  created:
    - routes/__init__.py
    - routes/trading.py
    - routes/scanner.py
    - routes/data.py
  modified:
    - dashboard.py
decisions:
  - "Used lazy imports inside route handlers for dashboard globals to avoid circular imports"
  - "Kept _snap_json helper in routes/data.py since only data routes use it"
  - "Moved overnight/run route to scanner_bp (prediction-related, not in original plan route list but logically belongs there)"
metrics:
  duration: "5 min"
  completed: "2026-05-18"
  tasks: 2
  files: 5
---

# Phase 09 Plan 01: Dashboard Blueprint Split Summary

Split monolithic dashboard.py (1,086 lines, 35+ routes) into three Flask Blueprint modules with a thin coordinator.

## One-liner

Dashboard decomposed into 3 Flask Blueprints (trading, scanner, data) with lazy-import dependency injection pattern

## What Was Done

### Task 1: Create three Blueprint route modules

Created `routes/` package with three Blueprint modules:

- **routes/trading.py** (`trading_bp`): 14 routes -- orders, bot start/stop/kill, sell all, exit config, positions, account, performance, backtest, auto-trade
- **routes/scanner.py** (`scanner_bp`): 15 routes -- predictions, overnight scanner, expanded scan, scan, intelligence, heatmaps (market + positions), scan logs, prediction log accuracy, expanded scan cancel
- **routes/data.py** (`data_bp`): 6 routes -- index page, state snapshot, SSE stream, health, quote, bars, agent status

All dashboard globals (`_trading_client`, `_data_client`, `_kill_fn`, `_start_fn`, `_coordinator`) are accessed via lazy imports inside handler functions, avoiding circular imports per RESEARCH.md Pitfall 1.

### Task 2: Slim dashboard.py to coordinator

Reduced dashboard.py from 1,086 lines to 66 lines. Now contains only:
- Flask app creation
- 5 dependency injection globals
- `set_dependencies()` and `set_coordinator()` functions
- Blueprint registration (3 blueprints)
- `run()` entry point

Zero `@app.route` decorators remain in dashboard.py.

## Verification Results

| Check | Result |
|-------|--------|
| All blueprints import without error | PASS |
| Route count (37 registered, 35+ required) | PASS |
| Zero @app.route in dashboard.py | PASS |
| No top-level dashboard imports in routes/*.py | PASS |
| dashboard.py under 150 lines (66 actual) | PASS |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing] Added overnight/run and expanded-scan/cancel routes to scanner_bp**
- **Found during:** Task 1
- **Issue:** Plan route list for scanner_bp omitted `/api/overnight/run` and `/api/expanded-scan/cancel` which existed in dashboard.py
- **Fix:** Included both routes in scanner_bp since they logically belong with the scanner/prediction routes
- **Files modified:** routes/scanner.py

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | 2eaf403 | feat(09-01): create three Flask Blueprint route modules |
| 2 | 1f7d61a | refactor(09-01): slim dashboard.py to thin Blueprint coordinator |

## Self-Check: PASSED

All 5 created/modified files verified on disk. Both commit hashes found in git log.
