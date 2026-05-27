---
phase: 10
plan: "03"
subsystem: dashboard-ui
tags: [dashboard, prediction-accuracy, ui, chart-js, recalibration]
depends_on:
  requires: ["10-02"]
  provides: ["accuracy-banner-ui", "signal-stats-ui", "recalibrate-button"]
  affects: ["templates/index.html"]
tech_stack:
  added: []
  patterns: ["lazy-load on details expand", "Chart.js line chart for signal comparison", "event-driven banner refresh"]
key_files:
  created: []
  modified:
    - templates/index.html
decisions:
  - "Used IIFE for toggle event listener attachment to avoid polluting global scope before DOM is ready"
  - "Reused existing showToast() and @keyframes spin — no new utilities needed"
  - "Accuracy trend sparkline shows per-signal accuracy (not time-series) since no daily snapshot endpoint exists yet"
metrics:
  duration: "~18 minutes"
  completed: "2026-05-27T05:57:38Z"
  tasks_completed: 1
  tasks_pending: 1
  files_changed: 1
---

# Phase 10 Plan 03: Dashboard Prediction Accuracy UI Summary

**One-liner:** Always-visible accuracy banner, collapsible 8-signal stats table with Chart.js sparkline, and recalibrate button wired to `/api/prediction-log/recalibrate`.

---

## Status

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | Add accuracy banner, per-signal stats section, and recalibrate button | COMPLETE | 335a220 |
| 2 | Verify dashboard prediction accuracy UI | CHECKPOINT-PENDING | — |

---

## What Was Built

### Task 1 — Dashboard UI Implementation (335a220)

Added the following to `templates/index.html`:

**HTML additions inside `#scorecard-section`:**
- `#accuracy-banner` / `#accuracy-banner-text` — always-visible banner above the 6-stat grid showing "Last N resolved predictions: X correct (Y%)" with Space Grotesk 700 20px stat values
- `#recalib-btn` — RECALIBRATE NOW button with spinning `refresh` Material Symbol icon, placed next to CHECK ACCURACY in the header
- `#signal-stats-details` — collapsible `<details>` element with summary label "SIGNAL ACCURACY BREAKDOWN"
- `#signal-stats-table` — per-signal accuracy table (8 signals: rsi2, ibs, consec_down, bb_lower, volume_profile, order_flow, amt_state, volume_spike) with columns: Signal, Samples, Accuracy, mini progress bar, Default weight, Calibrated weight
- `#accuracy-trend-chart` — Chart.js canvas (120px height) showing per-signal accuracy comparison
- `#recalib-metadata` — recalibration timestamp or "Not yet recalibrated" message
- `#weight-changes` — weight change log (old → new with directional coloring)

**JavaScript additions:**
- `loadAccuracyBanner()` — fetches `/api/prediction-log/accuracy`, renders banner text with color-coded accuracy
- `fetchSignalStats()` — parallel fetches `/api/prediction-log/signal-accuracy` + `/api/prediction-log/signal-weights`, calls render functions, sets `signalStatsLoaded = true`
- `renderSignalTable(stats, weights)` — builds HTML table with color coding: >=60% `#66bb6a`, 40-59% `#ffa726`, <40% `var(--error)`, <10 samples shows `(low sample)` and `—` for accuracy
- `renderRecalibMetadata(weights)` — shows recalibration date and weight changes (old in `var(--outline)`, new colored by direction)
- `renderAccuracyTrend(stats)` — Chart.js line chart with `#c8c8b0` line, 0.08 opacity fill, no legend
- `triggerRecalibration()` — POSTs to `/api/prediction-log/recalibrate`, handles skipped/success/error with toast messages, refreshes banner and signal stats on success

**Wiring:**
- `loadAccuracyBanner()` added to `loadIntelligenceTab()` — fires on tab open
- `loadAccuracyBanner()` added to `checkLiveAccuracy()` — refreshes after CHECK ACCURACY
- IIFE attaches toggle listener to `#signal-stats-details` for lazy first-load of signal stats

---

## Deviations from Plan

### Auto-reused Existing Utilities

**[Rule 2 - Reuse] Used existing showToast() and @keyframes spin**
- Found during: Task 1
- Issue: Plan specified adding these if absent; both already exist (`showToast` at line 4364, `@keyframes spin` at line 927)
- Fix: Reused existing implementations, no additions needed
- Files modified: none

### Minor Deviation: IIFE for Event Listener

**[Rule 2 - Correctness] Used IIFE instead of bare document.getElementById() at module level**
- Found during: Task 1
- Issue: Plan's inline `document.getElementById(...).addEventListener(...)` pattern would error if element not yet in DOM when script runs
- Fix: Wrapped in IIFE `(function() { const details = ...; if (details) details.addEventListener(...); })()` for safe null-guard
- Files modified: templates/index.html

---

## Known Stubs

None. All data is fetched from live API endpoints. The accuracy trend sparkline shows per-signal accuracy comparison rather than a time-series because no daily snapshot endpoint exists yet — this is intentional and documented in the chart's comment. The chart is functional with whatever signal data the API returns.

---

## Threat Flags

None. All new JS fetches are same-origin (`/api/prediction-log/*`). No new network surface introduced beyond what Plan 02 already defined. Display-only — no user input written to any store.

---

## Checkpoint: Task 2 Pending Human Verification

Task 2 is a `checkpoint:human-verify` gate requiring manual browser verification. The orchestrator should present these verification steps:

1. Start the dashboard: `py server.py paper`
2. Open http://localhost:5000 and navigate to the Intelligence tab
3. Verify accuracy banner is visible above the 6-stat grid (shows "No resolved predictions yet" or live count)
4. Verify RECALIBRATE NOW button appears next to CHECK ACCURACY
5. Click "SIGNAL ACCURACY BREAKDOWN" to expand — verify 8-signal table renders with correct columns
6. Verify Chart.js line chart renders inside the collapsible section
7. Click RECALIBRATE NOW — verify spinning icon, then toast message (skipped or success)
8. Click CHECK ACCURACY — verify banner text refreshes

**Expected with no resolved predictions:** Banner shows "No resolved predictions yet — outcomes checked daily at 9:35 AM ET", signal table shows all 8 rows with 0 samples and `—` accuracy, sparkline shows flat/empty, metadata shows "Not yet recalibrated".

---

## Self-Check

- [x] `templates/index.html` modified — confirmed (git status shows M, 199 insertions)
- [x] Commit 335a220 exists — confirmed via `git rev-parse --short HEAD`
- [x] All 16 acceptance criteria pass — verified by Python assertion script (ALL PASS)

## Self-Check: PASSED
