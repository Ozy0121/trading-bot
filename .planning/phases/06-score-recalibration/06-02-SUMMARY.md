---
phase: 06-score-recalibration
plan: 02
subsystem: dashboard-ui
tags: [grade-pills, tooltips, conviction-breakdown, watchlist-ui]
dependency_graph:
  requires: [06-01]
  provides: [grade_pill_ui, conviction_tooltip, score_visualization]
  affects: []
tech_stack:
  added: []
  patterns: [css-component-classes, js-helper-functions, sse-data-binding]
key_files:
  created: []
  modified:
    - templates/index.html
decisions:
  - "Grade pills show letter + numeric score (e.g. 'B 5.9') in colored badges"
  - "Tooltip shows 4 sub-score bars (Technical, Volume, Sentiment, Sector) with strategy footer"
  - "Grade boundaries auto-adjust from d.conviction_threshold in SSE state (fallback 5.8)"
  - "Stale conviction dots (conv-icons, conv-dot, cvKeys) removed entirely"
metrics:
  completed: 2026-04-08
  tasks_completed: 2
  tasks_total: 2
  tests_added: 0
  tests_total: 153
---

## Summary

Added grade pill badges and hover tooltips to the dashboard watchlist table, replacing raw numeric conviction scores with colored letter-grade pills (A/B/C/D/F) and interactive sub-score breakdowns.

## What Changed

### CSS Additions
- `.grade-pill` base class with `.grade-a` through `.grade-f` color variants (sage → clay red spectrum)
- `.score-cell` wrapper with relative positioning for tooltip anchoring
- `.score-tooltip` with hover reveal (visibility + opacity transition)
- Tooltip internals: `.tt-header`, `.tt-divider`, `.tt-row`, `.tt-label`, `.tt-bar-track`, `.tt-bar-fill`, `.tt-val`, `.tt-footer`

### JS Additions
- `scoreToGrade(score, threshold)` — maps numeric score to letter grade using threshold-relative boundaries
- `gradeCell(r, threshold)` — renders full `<td>` with grade pill + tooltip containing 4 sub-score bars and strategy footer

### Watchlist Row Template
- Replaced raw `<td>${(r.score||0).toFixed(1)}</td>` with `${gradeCell(r, _threshold)}`
- Removed stale `cvKeys`, `cvDots`, `conv-icons` code
- Threshold read from `d.conviction_threshold` with `|| 5.8` fallback

### CSS Removals
- Removed `.conv-icons`, `.conv-dot`, `.conv-ok`, `.conv-fail` (stale conviction dot styles)

## Verification
- Visual verification: User approved grade pills and tooltips rendering correctly
- All existing tests pass
