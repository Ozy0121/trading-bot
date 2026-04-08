---
phase: 06-score-recalibration
plan: 01
subsystem: state-plumbing
tags: [conviction-threshold, grade-logic, tdd, state, dashboard]
dependency_graph:
  requires: []
  provides: [conviction_threshold_in_state, grade_reference_impl]
  affects: [06-02]
tech_stack:
  added: []
  patterns: [tdd-red-green, reference-implementation-in-tests]
key_files:
  created:
    - tests/test_score_grades.py
  modified:
    - state.py
    - dashboard.py
decisions:
  - "Grade computation reference impl lives in test file (production logic is JS in Plan 02)"
  - "conviction_threshold initialized to 0.0 in state, set from config on bot start"
  - "conviction_threshold exposed via both SSE stream (continuous) and api_account (page load)"
metrics:
  duration: 167s
  completed: 2026-04-08
  tasks_completed: 1
  tasks_total: 1
  tests_added: 4
  tests_total: 153
---

# Phase 06 Plan 01: State Plumbing + Grade Test Scaffold Summary

Expose CONVICTION_THRESHOLD through shared state to SSE stream and create unit tests validating grade computation logic with TDD.

## What Was Done

### Task 1: Add conviction_threshold to state + expose from dashboard + write tests (TDD)

**RED phase** (commit `de59f41`): Created `tests/test_score_grades.py` with 4 tests. Three grade computation tests passed immediately (pure Python reference impl). One state plumbing test failed as expected (key not yet in state.py).

**GREEN phase** (commit `12bf9a4`):
- Added `"conviction_threshold": 0.0` to `state.py` `_state` dict after `scan_conviction_scores`
- Added `"conviction_threshold": config.CONVICTION_THRESHOLD` to `dashboard.py` `api_account()` response
- Added `conviction_threshold=config.CONVICTION_THRESHOLD` to `shared_state.update()` call in bot start handler

All 4 tests pass. Full suite: 153 passed, 0 failed.

## Test Coverage

| Test | Requirement | Validates |
|------|-------------|-----------|
| `test_grade_thresholds` | SCORE-01 | A/B/C/D/F grades correct at threshold=5.8 |
| `test_grade_auto_adjusts` | SCORE-01 | Grades shift correctly when threshold=7.0 (D-07) |
| `test_grade_boundary_exact` | SCORE-01 | Exact boundary values get higher grade (>= semantics) |
| `test_conviction_threshold_in_state` | SCORE-02 | Key exists in state, flows through update/snapshot |

## Commits

| Commit | Type | Description |
|--------|------|-------------|
| `de59f41` | test | Add failing test for conviction_threshold in state (RED) |
| `12bf9a4` | feat | Expose conviction_threshold through state and dashboard (GREEN) |

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all data flows are wired (config -> state -> SSE stream and api_account).

## Self-Check: PASSED

- [x] tests/test_score_grades.py exists (4 test functions)
- [x] state.py contains conviction_threshold key
- [x] dashboard.py contains conviction_threshold (2 occurrences: api_account + bot start)
- [x] Commit de59f41 exists (RED)
- [x] Commit 12bf9a4 exists (GREEN)
- [x] 06-01-SUMMARY.md created
