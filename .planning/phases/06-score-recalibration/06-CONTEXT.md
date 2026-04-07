# Phase 6: Score Recalibration - Context

**Gathered:** 2026-04-07
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase makes conviction scores instantly interpretable by adding letter grades (A/B/C/D/F) and hover tooltips with sub-score breakdowns. It does NOT change the scoring math, weights, or threshold — only how scores are displayed to the user.

</domain>

<decisions>
## Implementation Decisions

### Grade Display Style
- **D-01:** Scores display as a colored pill/badge with the letter grade followed by the numeric score (e.g. `[A] 8.2`). Green for A, yellow-green for B, yellow for C, orange for D, red for F.
- **D-02:** Claude's Discretion on where grades appear beyond the watchlist table — apply grades wherever a conviction score is rendered if it adds value (e.g. trade log, sentiment section).

### Tooltip Breakdown
- **D-03:** Hovering over a score shows a tooltip with horizontal mini-bars for each sub-score (Technical, Volume, Sentiment, Sector) — each bar proportional to 10, with the numeric value displayed alongside.
- **D-04:** Tooltip header shows the letter grade and composite score (e.g. "Conviction: A (8.2/10)").
- **D-05:** Tooltip footer shows ALL strategies that fired (from `conviction.strategies_fired`), not just the primary. Format: e.g. "Strategy: Momentum + Catalyst".

### Grade Thresholds
- **D-06:** Grade cutoffs are anchored to `CONVICTION_THRESHOLD` (currently 5.8). The B/C boundary equals the threshold. Specific mapping:
  - A: threshold + 2.2 (currently >= 8.0)
  - B: threshold (currently >= 5.8)
  - C: threshold - 1.8 (currently >= 4.0)
  - D: threshold - 3.3 (currently >= 2.5)
  - F: below D cutoff (currently < 2.5)
- **D-07:** Grade cutoffs auto-adjust when `CONVICTION_THRESHOLD` changes — computed from the threshold value, not independent config constants.

### Claude's Discretion
- Color palette for grade badges (should fit the existing dark dashboard theme)
- Tooltip CSS styling, positioning, animation
- Whether to add a helper function in Python or compute grades purely in JS
- Where beyond the watchlist table grades add value

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Scoring System
- `scanner.py` — `_score_symbol_multi()` produces the conviction breakdown dict with technical, volume, sentiment, sector sub-scores and strategies_fired list
- `config.py` lines 118-119 — `CONVICTION_THRESHOLD` and conviction weight constants

### Dashboard
- `templates/index.html` lines 2281-2296 — Current watchlist table rendering with conviction dots and score display
- `state.py` lines 103-106 — `scan_results` and `scan_conviction_scores` state structure

### Prior Calibration Work
- `.planning/phases/02-prediction-engine-stock-scanning/02-CONTEXT.md` — Phase 2 scoring decisions (weights, threshold, sentiment overhaul)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `conviction` dict already has all sub-scores (technical, volume, sentiment, sector) plus `composite` and `strategies_fired` — no new data fetching needed
- `scan_results` in state already stores full conviction breakdown per symbol
- Existing CSS variables for the dark dashboard theme (var(--outline), var(--ghost-border), etc.)
- Signal pill styling (`.signal-pill`) can be adapted for grade badges

### Established Patterns
- Watchlist rows rendered via JS template literals in `index.html` (lines 2281-2296)
- CSS tooltip pattern not currently in use — will need to add
- Config values loaded at module level from env with `_float()` helpers

### Integration Points
- Grade computation: either in `scanner.py` (Python-side, added to conviction dict) or in JS (client-side from score value)
- Tooltip: added to watchlist table TD elements via CSS hover or JS event
- Config: grade thresholds computed from `CONVICTION_THRESHOLD` in `config.py`

</code_context>

<specifics>
## Specific Ideas

- Grade badge mockup: `[A] 8.2` with colored pill, matching the existing signal pill pattern
- Tooltip with mini-bars using block/shade characters rendered in HTML/CSS
- User wants to quickly see WHY a score is high or low at a glance

</specifics>

<deferred>
## Deferred Ideas

- **Scoring calibration tune-up** — Scanner rarely buys, most candidates get skipped. Likely threshold (5.8) is too high relative to typical composite scores. Should be addressed as a separate quick task after Phase 6 provides visibility into score distributions via grades.

</deferred>

---

*Phase: 06-score-recalibration*
*Context gathered: 2026-04-07*
