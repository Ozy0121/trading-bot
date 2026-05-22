---
phase: quick
plan: 260522-lgx
subsystem: routes
tags: [bugfix, concurrency, autotrade]
metrics:
  duration: "2 min"
  completed: "2026-05-22"
  tasks: 2
  files: 2
---

# Quick Task 260522-lgx: Fix Prediction Scan Concurrency and Autotrade Silent Failure

## One-liner

Added concurrency guard (409 on duplicate scan) and fixed autotrade pre-validation with relaxed stage filter

## What Was Done

### Task 1: Prediction scan concurrency guard

- Added `_prediction_running = threading.Event()` module-level flag in `routes/scanner.py`
- Endpoint returns 409 with "Prediction scan already running" if a scan is in progress
- Flag cleared in `finally` block to guarantee cleanup even on exceptions

### Task 2: Autotrade silent failure fix

- Removed `confidence >= 8` gate — trust stage classification instead
- Added `accumulation` stage as tradeable alongside `launch_zone` and `pre_breakout`
- Added pre-validation before spawning background thread: returns 400 with specific reason if no predictions exist or none qualify
- Added progress log messages so user can see results in scan log panel

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | d8eaf06 | fix(260522-lgx): add concurrency guard to prediction scan endpoint |
| 2 | d61a455 | fix(260522-lgx): fix autotrade silent failure with relaxed filter and pre-validation |
