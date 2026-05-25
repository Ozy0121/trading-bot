# Phase 10: Prediction Feedback Loop - Context

**Gathered:** 2026-05-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Close the loop between predictions and outcomes. Track every prediction to resolution, compute per-signal accuracy stats, and auto-recalibrate signal weights weekly so the prediction engine improves over time without manual intervention.

This phase includes Level 1 auto-recalibration: weekly weight updates based on signal accuracy data, saved to config files. No ML, no code rewriting — just stat-driven weight adjustments.

</domain>

<decisions>
## Implementation Decisions

### Outcome Tracking
- **D-01:** A prediction counts as a "win" when the stock reaches the predicted target price within 3 days. Binary pass/fail — no partial credit.
- **D-02:** The outcome tracker monitors each prediction for 3 trading days after it's generated. After 3 days, it records: predicted target hit (yes/no), actual max price reached, actual close price on day 3, which primary/confirmation signals were active.
- **D-03:** Outcome checking runs alongside the existing overnight accuracy check at 9:35 AM ET. Predictions are checked daily until they either hit target or expire after 3 days.

### Auto-Recalibration
- **D-04:** Weekly recalibration runs Sunday at midnight ET (before Monday open).
- **D-05:** Recalibration looks at the last 30 days of resolved predictions (minimum 20 predictions required — skip recalibration if fewer).
- **D-06:** For each signal (rsi2, ibs, consec_down, bb_lower, volume_profile, order_flow, amt_state, volume_spike), compute: total predictions where signal was active, wins where signal was active, signal-specific accuracy percentage.
- **D-07:** New weights are computed proportional to signal accuracy: signals with higher accuracy get higher weights. Weights are clamped to [1.0, 6.0] range to prevent any single signal from dominating or being zeroed out.
- **D-08:** Updated weights are saved to a config file (not hardcoded in prediction.py). prediction.py reads from this file at startup, falling back to current hardcoded defaults if the file doesn't exist.
- **D-09:** Recalibration logs a summary: "Weekly recalibration: RSI(2) weight 4.0->4.6, consec_down 3.0->2.1" etc. Dashboard should show when last recalibration happened.

### Dashboard Accuracy Display
- **D-10:** Always-visible accuracy banner in the prediction section: "Last 50 predictions: 34 correct (68%)" — updates whenever predictions resolve.
- **D-11:** Full stats section (collapsible or dedicated area) showing: per-signal accuracy table (signal name, sample count, accuracy %), accuracy trend over time, best/worst performing signals, current calibrated weights vs defaults.
- **D-12:** Stats section includes a "last recalibrated" timestamp and what changed.

### Claude's Discretion
- **Storage format:** Claude decides between JSON files or SQLite based on what integrates best with the existing prediction_log.py pattern. The existing codebase uses JSON files in data/ directory — follow that pattern unless there's a strong reason for SQLite.
- **Accuracy trend visualization:** Claude decides chart type (line chart, sparkline, etc.) for showing accuracy over time.
- **Minimum sample sizes:** Claude decides minimum samples per signal before including in recalibration (to avoid weight swings from small sample noise).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Prediction Engine
- `prediction.py` — PRIMARY_WEIGHTS and CONFIRM_BONUS dicts (lines 63-74), scoring logic (lines 593-615)
- `prediction_log.py` — Existing outcome tracking and accuracy checking infrastructure
- `prediction_scanner.py` — Orchestrates prediction runs and stores results

### Data Layer
- `data_provider.py` — Market data fetching for outcome price checks
- `state.py` — Shared state where prediction data is stored for dashboard

### Dashboard
- `templates/index.html` — Current prediction section UI (scan buttons, prediction cards)
- `routes/scanner.py` — Prediction scan and overnight scheduler endpoints

### Backtesting
- `run_backtest_v3.py` — Existing backtester (results currently not fed back)
- `run_backtest_v4.py` — Newer backtester variant

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `prediction_log.py`: Already logs predictions to disk and checks next-day accuracy at 9:35 AM ET. Extend this for multi-day tracking and per-signal breakdown.
- `prediction_scanner.py:start_scheduler()`: Already runs overnight scans on a schedule. Add weekly recalibration to this scheduler.
- `PRIMARY_WEIGHTS` / `CONFIRM_BONUS` dicts in prediction.py: Current hardcoded weights that recalibration will replace with data-driven values.

### Established Patterns
- JSON files in `data/` directory for persistence (prediction_log uses this)
- Background daemon threads with `threading.Timer` for scheduled tasks
- Shared state updates via `state.update()` for dashboard data

### Integration Points
- `prediction.py` scoring loop (lines 597-607): Where weights are applied — needs to read from calibrated weights file instead of hardcoded dicts
- `templates/index.html` prediction section: Where accuracy banner and stats display go
- `routes/scanner.py`: Where new API endpoints for accuracy stats would live
- `prediction_scanner.py`: Where the recalibration scheduler gets wired in

</code_context>

<specifics>
## Specific Ideas

- The accuracy banner text should match the CLAUDE.md identity: "Last 30 predictions: 21 correct (70%)"
- Log entries for recalibration should be clear and human-readable in the console
- The recalibration is "Level 1" autonomous — just weight adjustment, not strategy changes

</specifics>

<deferred>
## Deferred Ideas

- Level 2 auto-enable/disable of signals based on accuracy thresholds — Phase 11 or later
- Level 3 autonomous strategy evolution with hypothesis generation — future milestone
- Backtest integration where run_backtest results auto-update weights — could be added to this phase but keep scope tight first

</deferred>

---

*Phase: 10-prediction-feedback-loop*
*Context gathered: 2026-05-25*
