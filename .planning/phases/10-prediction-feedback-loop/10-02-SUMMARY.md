---
phase: 10-prediction-feedback-loop
plan: "02"
subsystem: prediction
tags: [signal-calibration, weights, scheduler, api-routes, hot-reload]

# Dependency graph
requires:
  - phase: 10-01
    provides: signal_calibration.py with run_recalibration, get_signal_stats, get_current_weights, get_accuracy_history

provides:
  - prediction.py loads calibrated weights from data/signal_weights.json at import time with fallback to hardcoded defaults
  - Sunday midnight recalibration scheduler hook with duplicate prevention and hot-reload
  - Weekend skip narrowed to Saturday-only (Sunday allowed through for recalibration)
  - Four API routes: /api/prediction-log/signal-accuracy, /api/prediction-log/signal-weights, /api/prediction-log/recalibrate, /api/prediction-log/accuracy-history

affects: [10-03, dashboard, prediction_scanner]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "File-based weight loading at module level with fallback to hardcoded defaults"
    - "Hot-reload pattern: update in-process dict after recalibration without restart"
    - "Duplicate-prevention via recalibration_date field in weights JSON file"

key-files:
  created: []
  modified:
    - prediction.py
    - prediction_scanner.py
    - routes/scanner.py

key-decisions:
  - "Use _load_weights() at module level so calibrated weights apply from first use"
  - "Keep DEFAULT_PRIMARY_WEIGHTS and DEFAULT_CONFIRM_BONUS as named constants for clarity and fallback"
  - "Use _os/_json aliases in prediction.py to avoid polluting the module namespace"
  - "Narrow weekend skip from weekday() >= 5 to weekday() == 5 (Saturday only) to allow Sunday recalibration"
  - "Hot-reload via dict.update() so running bot uses new weights without process restart"

patterns-established:
  - "File-based config override: load from JSON at import time, fall back to hardcoded defaults if file missing"
  - "In-process hot-reload: update module-level dict after recalibration rather than reimporting"

requirements-completed: []

# Metrics
duration: 18min
completed: "2026-05-26"
---

# Phase 10 Plan 02: Recalibration Wiring Summary

**File-based weight loading in prediction.py, Sunday midnight recalibration scheduler, and four signal-calibration API routes with hot-reload**

## Performance

- **Duration:** 18 min
- **Started:** 2026-05-26T20:10:00Z
- **Completed:** 2026-05-26T20:28:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- prediction.py now reads calibrated weights from `data/signal_weights.json` at import, falls back to hardcoded defaults if file absent, and logs which source was used
- _schedule_loop in prediction_scanner.py runs recalibration every Sunday midnight ET with duplicate prevention (checks recalibration_date in the JSON file), hot-reloads PRIMARY_WEIGHTS and CONFIRM_BONUS into the running process after recalibration, then skips regular scan/accuracy checks (markets closed on Sunday)
- Weekend guard narrowed from `weekday() >= 5` (skips Saturday AND Sunday) to `weekday() == 5` (Saturday only), allowing Sunday through for recalibration
- Four new API routes added to routes/scanner.py: signal-accuracy, signal-weights, recalibrate (POST with hot-reload), and accuracy-history

## Task Commits

Each task was committed atomically:

1. **Task 1: Make prediction.py load weights from config file with fallback to defaults** - `e4a0d55` (feat)
2. **Task 2: Add Sunday midnight recalibration with hot-reload and weekend-skip fix, plus three API routes** - `95c87a6` (feat)

## Files Created/Modified

- `prediction.py` - Renamed weight dicts to DEFAULT_*, added _load_weights() function, re-exports PRIMARY_WEIGHTS/CONFIRM_BONUS from file or defaults
- `prediction_scanner.py` - Weekend guard narrowed to Saturday-only, Sunday midnight recalibration block with duplicate prevention and hot-reload added
- `routes/scanner.py` - Four new API routes: /api/prediction-log/signal-accuracy, /api/prediction-log/signal-weights, /api/prediction-log/recalibrate (POST), /api/prediction-log/accuracy-history

## Decisions Made

- Used `_os` and `_json` aliases in prediction.py weight loading section to avoid namespace pollution since the module already has its own imports in scope
- Kept `DEFAULT_PRIMARY_WEIGHTS` and `DEFAULT_CONFIRM_BONUS` as module-level constants (not private) so routes/scanner.py can import them for the "show calibrated vs defaults" API response
- Duplicate prevention reads `recalibration_date` from the weights JSON rather than a separate lock file — simpler, and the field is already written by signal_calibration.py

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- `volume_profile` module (imported by prediction.py) is not tracked in the worktree — exists only as an untracked file in the main repo. This prevented running `python -c "from prediction import ..."` directly. Used AST parsing and text-pattern checks for all acceptance criteria verification instead. This is a pre-existing worktree isolation issue, not caused by Plan 02 changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Recalibration is fully wired: weights flow from signal_calibration.py → signal_weights.json → prediction.py → running bot on Sunday midnight
- API routes are available for the dashboard to display signal accuracy and allow manual recalibration
- Plan 03 (if any) can assume PRIMARY_WEIGHTS and CONFIRM_BONUS are always calibrated values when signal_weights.json exists

---
*Phase: 10-prediction-feedback-loop*
*Completed: 2026-05-26*
