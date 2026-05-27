---
phase: 10-prediction-feedback-loop
plan: 01
subsystem: prediction
tags: [signal-calibration, prediction-tracking, accuracy-history, json, pytest, recalibration]

requires:
  - phase: prior (prediction_log.py, prediction.py, prediction_scanner.py already existed)
    provides: PredictionRecord, log_prediction, check_outcomes, _schedule_loop, _log_predictions

provides:
  - signal_calibration.py with run_recalibration(), weight clamping, daily accuracy snapshots
  - active_signals field on PredictionRecord (machine-readable signal names per prediction)
  - active_signals parameter on log_prediction() for callers to pass signal names
  - _log_predictions() in prediction.py now extracts and passes PatternResult names
  - check_outcomes() wired into daily 9:35 AM ET scheduler in prediction_scanner.py
  - 10 unit tests covering all recalibration behaviors

affects:
  - 10-02 (dashboard API routes for signal accuracy — reads signal_accuracy_stats.json and signal_weights.json)
  - 10-03 (dashboard UI — accuracy trend sparkline reads accuracy_history.json)
  - prediction_scanner.py Sunday midnight recalibration scheduler (phase 10-02 or 10-03)

tech-stack:
  added: []
  patterns:
    - "Weight recalibration: default_weight * (accuracy_pct / 50.0) clamped to [1.0, 6.0]"
    - "Accuracy history: append-with-dedup pattern (replace same-date entry, trim to 90 entries)"
    - "TDD: tests/test_signal_calibration.py created first (RED), then signal_calibration.py (GREEN)"
    - "Monkeypatch module constants for isolated file I/O tests"

key-files:
  created:
    - signal_calibration.py
    - tests/test_signal_calibration.py
  modified:
    - prediction_log.py
    - prediction.py
    - prediction_scanner.py

key-decisions:
  - "MIN_SAMPLES=10 per signal before recalibrating — below this, keep default weight (discretion D-06)"
  - "check_outcomes() runs inside the existing accuracy_time block alongside check_prediction_accuracy() — same 9:35 AM ET trigger"
  - "accuracy_history.json deduplicates by date (same-day calls replace the entry, not append)"

patterns-established:
  - "Recalibration engine reads prediction_history.json, writes signal_accuracy_stats.json + signal_weights.json"
  - "Daily accuracy snapshots in accuracy_history.json with per-signal breakdown for trend sparkline"

requirements-completed: []

duration: 18min
completed: 2026-05-26
---

# Phase 10 Plan 01: Prediction Tracking and Recalibration Infrastructure Summary

**Signal recalibration engine with per-signal accuracy tracking stored on PredictionRecord, daily accuracy snapshots, and 10 unit tests enforcing weight clamp [1.0, 6.0] and 20-prediction skip threshold**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-05-26T20:00:00Z
- **Completed:** 2026-05-26T20:18:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Created `signal_calibration.py` with `run_recalibration()` (per-signal accuracy, weight formula, skip threshold, daily snapshots), `_compute_new_weight()`, `get_signal_stats()`, `get_current_weights()`, `get_accuracy_history()`
- Extended `PredictionRecord` with `active_signals: list[str]` field and `log_prediction()` with matching parameter — every new prediction now stores machine-readable signal names for recalibration attribution
- Wired `prediction_log.check_outcomes()` into the existing 9:35 AM ET daily scheduler so pending predictions are resolved automatically (previously only manual API calls triggered resolution)
- Updated `_log_predictions()` in `prediction.py` to extract `PatternResult` names from `Prediction.patterns` and pass them as `active_signals` — closes the data pipeline from signal detection to weight feedback
- All 10 unit tests pass covering: weight clamp, baseline accuracy, skip threshold, empty active_signals exclusion, min-samples guard, full recalibration formula, stats/weights/history file output, and deduplication

## Task Commits

1. **Task 1: Create signal_calibration.py (TDD)** - `28c7b79` (feat)
2. **Task 2: Extend prediction logging and wire scheduler** - `a5b7c45` (feat)

## Files Created/Modified

- `signal_calibration.py` — recalibration engine: run_recalibration(), weight formula, accuracy_history snapshots, accessor functions
- `tests/test_signal_calibration.py` — 10 unit tests covering all specified behaviors
- `prediction_log.py` — added `active_signals` field to `PredictionRecord`, added `active_signals` parameter to `log_prediction()`
- `prediction.py` — `_log_predictions()` now extracts `[pat.name for pat in p.patterns if pat.detected]` and passes to `log_prediction()`
- `prediction_scanner.py` — `_schedule_loop()` now calls `check_outcomes()` inside the 9:35 AM ET accuracy block

## Decisions Made

- `last_accuracy_date = today` moved to after both `check_prediction_accuracy()` and `check_outcomes()` calls, so both run on the same daily trigger even if one raises an exception (each wrapped in its own try/except)
- Records with empty `active_signals` (old records pre-deployment) are excluded from recalibration per-signal stats — self-healing within 30 days as new predictions accumulate
- Weight formula uses 50% as the "no change" baseline — matches the RESEARCH.md recommendation and is documented in `_compute_new_weight()` docstring

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- `test_prediction.py` fails to import due to pre-existing `volume_profile` module not found — this is a pre-existing issue unrelated to this plan. Our `test_signal_calibration.py` tests pass cleanly.

## Known Stubs

None — all data flows in this plan are functional. `signal_calibration.py` reads real files and writes real output. The weekly Sunday recalibration scheduler hook is deferred to a subsequent task (plan references it as out of scope for 10-01).

## Threat Flags

None — no new network endpoints, auth paths, or external-facing surfaces added. All data flows are internal JSON file reads/writes as assessed in the plan's threat model.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `signal_calibration.py` ready for API route exposure (signal-accuracy, signal-weights, trigger-recalibrate endpoints)
- `accuracy_history.json` schema established for dashboard trend sparkline
- Sunday midnight recalibration scheduler hook still needs wiring into `prediction_scanner._schedule_loop()` (not in 10-01 scope)
- Pre-existing 315+ pending predictions in `prediction_history.json` will resolve on next 9:35 AM ET scheduler run now that `check_outcomes()` is wired in

---
*Phase: 10-prediction-feedback-loop*
*Completed: 2026-05-26*
