# Phase 6: Score Recalibration - Research

**Researched:** 2026-04-07
**Domain:** Dashboard UI — conviction score display, CSS tooltip patterns, grade badge styling
**Confidence:** HIGH

## Summary

Phase 6 is a pure UI/display enhancement. It does not touch the scoring math in `scanner.py`. All conviction sub-score data (`technical`, `volume`, `sentiment`, `sector`, `composite`, `strategies_fired`) is already present in the `conviction` dict stored in `scan_results` in shared state and already flowing to the dashboard via the SSE stream. The dashboard's watchlist table at lines 2278-2296 renders each row from `r.conviction` and `r.score` but currently only shows the raw numeric score (`r.score.toFixed(1)`) and four conviction "dots" keyed on stale fields (`sma_buy`, `rsi_ok`, etc.) that no longer exist in the conviction dict.

The work splits neatly into three deliverables: (1) a grade-computation helper (pure JS or Python helper added to the conviction dict), (2) a grade badge replacing or wrapping the raw score cell in the watchlist table, and (3) a CSS hover tooltip attached to the score cell. Grade thresholds are computed from `CONVICTION_THRESHOLD` (currently 5.8) per D-06/D-07 — no new config constants needed.

**Primary recommendation:** Compute grades client-side in JS using `CONVICTION_THRESHOLD` passed through the SSE state snapshot. Add `conviction_threshold` to the shared state so JS can compute grades without hardcoding the value. Implement tooltips with pure CSS (`position: relative` + `:hover` visibility toggle) using the existing dark theme variables.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Scores display as a colored pill/badge with the letter grade followed by the numeric score (e.g. `[A] 8.2`). Green for A, yellow-green for B, yellow for C, orange for D, red for F.
- **D-02:** Claude's Discretion on where grades appear beyond the watchlist table — apply grades wherever a conviction score is rendered if it adds value (e.g. trade log, sentiment section).
- **D-03:** Hovering over a score shows a tooltip with horizontal mini-bars for each sub-score (Technical, Volume, Sentiment, Sector) — each bar proportional to 10, with the numeric value displayed alongside.
- **D-04:** Tooltip header shows the letter grade and composite score (e.g. "Conviction: A (8.2/10)").
- **D-05:** Tooltip footer shows ALL strategies that fired (from `conviction.strategies_fired`), not just the primary. Format: e.g. "Strategy: Momentum + Catalyst".
- **D-06:** Grade cutoffs are anchored to `CONVICTION_THRESHOLD` (currently 5.8):
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

### Deferred Ideas (OUT OF SCOPE)

- **Scoring calibration tune-up** — Scanner rarely buys, most candidates get skipped. Likely threshold (5.8) is too high relative to typical composite scores. Should be addressed as a separate quick task after Phase 6 provides visibility into score distributions via grades.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SCORE-01 | Conviction scores display as letter grades (A/B/C/D/F) alongside numeric value, with grade cutoffs config-driven and relative to conviction threshold | Grade JS helper reads `d.conviction_threshold` from SSE state; badge renders in watchlist score cell |
| SCORE-02 | Hovering a score shows tooltip breakdown of sub-scores (technical, volume, sentiment, sector) with per-component numeric values and strategy label | CSS hover tooltip attached to watchlist score `<td>`; uses `r.conviction.technical/volume/sentiment/sector` and `r.conviction.strategies_fired` already in SSE payload |
</phase_requirements>

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Vanilla JS | ES2020 in-browser | Grade computation, tooltip rendering | Already the only JS in use — no build step |
| Pure CSS | In `<style>` block | Tooltip styling, badge colors | All existing UI is inline CSS, no framework |
| Python (config.py) | 3.14 | Expose `CONVICTION_THRESHOLD` in SSE state | Needed so JS doesn't hardcode threshold value |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| CSS custom properties (`var(--*)`) | Native | Badge color palette | All theme colors already defined as CSS vars |
| Template literals (JS) | ES6 | Watchlist row HTML generation | Already the pattern at lines 2278-2296 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pure CSS tooltip | JS-positioned tooltip (mousemove) | JS gives more control over clipping at table edges; CSS is simpler and no JS event listeners needed — CSS preferred |
| Grade in JS only | Grade added to conviction dict in Python | Python side requires scanner.py change + retest; JS side is zero backend risk — JS preferred for this phase |

**Installation:** No new packages — zero dependency changes.

---

## Architecture Patterns

### Existing Data Flow (verified by reading scanner.py + bot.py + state.py)

```
scanner._score_symbol_multi()
  → returns conviction dict: {technical, volume, sentiment, sector, composite, strategies_fired, earnings_penalty, regime_multiplier}
  → stored in scan_results list (df stripped)

bot.py line 349
  → shared_state.update(watchlist=[{k:v for k,v in r.items() if k != "df"} ...])
  → conviction dict IS included in state.watchlist entries

state.snapshot() → dashboard SSE stream → JS receives d.watchlist[]
  → each entry r has r.conviction.technical, r.conviction.volume, etc.
  → r.score = r.conviction.composite
```

[VERIFIED: read scanner.py lines 457-489, bot.py lines 349-352, state.py lines 103-106]

### Current Conviction Dot Bug (important for planner)

The current `cvKeys = ['sma_buy','rsi_ok','volume_spike','macd_pos']` at line 2285 of `index.html` references keys that do NOT exist in the Phase 2 conviction dict. The conviction dict has `technical`, `volume`, `sentiment`, `sector`, `composite`, `strategies_fired` — not those four keys. The dots always render as grey (`conv-fail`). Phase 6 should replace this with the new grade badge. [VERIFIED: read scanner.py conviction dict, index.html line 2285]

### Recommended Project Structure (changes)

```
config.py          — no changes needed (CONVICTION_THRESHOLD already exists)
state.py           — add conviction_threshold to _state snapshot OR expose via config in JS
dashboard.py       — add conviction_threshold to SSE state snapshot OR pass via /api/account
templates/index.html
  <style>          — add .grade-pill variants, .score-tooltip CSS
  watchlist rows   — replace score TD with grade badge + tooltip wrapper
```

### Pattern 1: Grade Computation in JS

**What:** A pure JS function `scoreToGrade(score, threshold)` maps composite score to letter + color class.

**When to use:** Computed client-side on each SSE update so grades auto-update if threshold changes in config (as long as `conviction_threshold` is in state snapshot).

**Example:**
```javascript
// Source: [ASSUMED — standard JS grade mapping pattern]
function scoreToGrade(score, threshold) {
  if (score >= threshold + 2.2) return { letter: 'A', cls: 'grade-a' };
  if (score >= threshold)       return { letter: 'B', cls: 'grade-b' };
  if (score >= threshold - 1.8) return { letter: 'C', cls: 'grade-c' };
  if (score >= threshold - 3.3) return { letter: 'D', cls: 'grade-d' };
  return { letter: 'F', cls: 'grade-f' };
}
```

**Threshold exposure:** Add `conviction_threshold: config.CONVICTION_THRESHOLD` to `state.py`'s `_state` dict so it flows through `snapshot()` to the SSE stream. [VERIFIED: state.py structure read — _state dict accepts arbitrary keys]

### Pattern 2: CSS Tooltip (hover-reveal)

**What:** A `<div class="score-tooltip">` inside the score `<td>` that is `visibility: hidden; opacity: 0` by default, revealed on `td:hover` or via a wrapper `.score-cell:hover .score-tooltip`.

**When to use:** Avoids JS event listeners. Works on desktop (mouse). Appropriate for this dashboard — no mobile requirement noted.

**Key CSS pattern:**
```css
/* Source: [ASSUMED — standard CSS tooltip pattern] */
.score-cell { position: relative; }
.score-tooltip {
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  visibility: hidden;
  opacity: 0;
  transition: opacity 0.15s linear;
  z-index: 200;
  pointer-events: none;
}
.score-cell:hover .score-tooltip {
  visibility: visible;
  opacity: 1;
}
```

**Positioning concern:** Watchlist table is the topmost scrollable section. Tooltip positioned `bottom: 100%` opens upward — safe for all rows. The last row of a long watchlist could clip at the top of the panel; if this is a concern the planner can specify `top: 100%` for rows where bottom-opening clips.

### Pattern 3: Mini-bar Sub-score Display

**What:** Each sub-score rendered as a labeled row with a colored bar proportional to value/10.

**Example markup (inline template literal):**
```javascript
// Source: [ASSUMED — adapted from existing inline CSS patterns]
function subBar(label, value) {
  const pct = Math.round((value / 10) * 100);
  return `<div class="tt-row">
    <span class="tt-label">${label}</span>
    <div class="tt-bar-track"><div class="tt-bar-fill" style="width:${pct}%"></div></div>
    <span class="tt-val">${value.toFixed(1)}</span>
  </div>`;
}
```

### Pattern 4: Strategy Label in Tooltip Footer

**What:** `strategies_fired` is a list of strings (e.g. `["momentum"]` or `["momentum","catalyst"]`). Join with " + " and title-case for display.

**Example:**
```javascript
// Source: [VERIFIED: scanner.py line 404-404 — strategies_fired is list of _name strings]
const stratLabel = (conv.strategies_fired || [])
  .map(s => s.charAt(0).toUpperCase() + s.slice(1))
  .join(' + ') || 'None';
```

### Anti-Patterns to Avoid

- **Hardcoding grade thresholds in JS:** `threshold + 2.2` must use the `d.conviction_threshold` from state, not `5.8` literally — otherwise it breaks when config changes (violates D-07).
- **Reading `cv.sma_buy` / `cv.rsi_ok`:** These keys do not exist in Phase 2's conviction dict. The existing conv-dot code is already dead. Replace it entirely.
- **Adding tooltip via JS `addEventListener('mouseover')`:** Adds complexity. Pure CSS `:hover` is sufficient and matches the project's existing pattern (all hover effects are CSS).
- **Modifying scanner.py for grade computation:** Grade is a display concern, not a scoring concern. Phase boundary is explicit: no scoring math changes.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CSS tooltip | Custom JS positioning engine | Pure CSS `position: absolute` + `:hover` | Sufficient for this use case; no library needed |
| Color palette | Arbitrary hex colors | Existing CSS vars (`--primary`, `--error`, `--secondary`, `--tertiary`) + two new grade-specific vars | Ensures dark theme consistency per D-01 |
| Grade bar chart | Canvas / Chart.js | CSS `div` with `width: X%` | Lightweight, no additional script load, matches "horizontal mini-bar" requirement (D-03) |

**Key insight:** Every sub-score (technical, volume, sentiment, sector) is already a 0-10 float in the SSE payload. No new Python computation needed for display — the full conviction dict flows through state.

---

## Common Pitfalls

### Pitfall 1: Tooltip Clips at Table Boundary

**What goes wrong:** If the tooltip is taller than the space above the row, it clips behind the table header or the nav bar.
**Why it happens:** `position: absolute` within the table cell; parent containers have `overflow: hidden` or the viewport boundary is near.
**How to avoid:** Default to opening upward (`bottom: 100%`). Add `z-index: 200` (above watchlist row hover). Verify the watchlist panel does not have `overflow: hidden` on its container. [VERIFIED: `.panel` CSS at line 440-447 has no overflow property set — safe]
**Warning signs:** Tooltip visible but cut off at the top.

### Pitfall 2: Threshold Not Available in JS

**What goes wrong:** Grade JS helper uses a hardcoded `5.8` and does not react to `CONVICTION_THRESHOLD` changes in `.env`.
**Why it happens:** `CONVICTION_THRESHOLD` is not currently in `state._state` dict.
**How to avoid:** Add `conviction_threshold: config.CONVICTION_THRESHOLD` to `state._state` so it appears in every `snapshot()` call and flows via SSE. JS reads `d.conviction_threshold` before computing grades.
**Warning signs:** Grades compute as if threshold were 5.8 even after a config change; B/C boundary is wrong.

### Pitfall 3: Stale Conv-Dot Keys Remain

**What goes wrong:** The existing `cvKeys = ['sma_buy','rsi_ok','volume_spike','macd_pos']` line stays in the template; dots always show grey (all undefined = falsy).
**Why it happens:** Developer adds grade badge alongside but forgets to remove the old dot code.
**How to avoid:** The planner task for the watchlist row rewrite must explicitly remove lines 2285-2286 and the `.conv-icons` span.
**Warning signs:** Four grey dots still appear next to the symbol name.

### Pitfall 4: Tooltip Flicker on Row Hover

**What goes wrong:** Hovering anywhere on the row triggers `:hover` on the `<tr>`, which changes background, while only hovering on the score `<td>` reveals the tooltip — creates visual jump.
**Why it happens:** The watchlist row has `cursor: pointer` and `:hover` background, the score cell has a separate hover. On a narrow score column the mouse transitions quickly in/out of the cell.
**How to avoid:** Attach the tooltip to the score `<td>` wrapper (`position: relative`), not the `<tr>`. The row `:hover` background change is independent and compatible.

### Pitfall 5: strategies_fired Is Empty Array

**What goes wrong:** When no strategy fired (`raw_signal = "HOLD"`), `strategies_fired` is `[]`. The tooltip footer shows "Strategy: " with nothing after it, or throws on `.join()`.
**Why it happens:** Normal for non-buy candidates. `strategies_fired = [r["_name"] for r in fired_results]` is empty when no strategy fires.
**How to avoid:** Guard in JS: `(conv.strategies_fired || []).length > 0 ? ... : 'None fired'`.

---

## Code Examples

Verified patterns from the codebase:

### Current Score Column (to be replaced)

```javascript
// Source: templates/index.html line 2294 [VERIFIED]
<td>${(r.score||0).toFixed(1)}</td>
```

### Existing Signal Pill CSS (adapt for grade badge)

```css
/* Source: templates/index.html lines 322-339 [VERIFIED] */
.signal-pill {
  display: inline-block; padding: 5px 18px; border-radius: 0;
  font-family: 'Space Grotesk', sans-serif;
  font-size: 12px; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase;
}
.signal-BUY {
  background: rgba(200, 200, 176, 0.10); color: var(--primary);
  border: 1px solid rgba(200, 200, 176, 0.20);
}
```

### Existing CSS Variables for Grade Color Palette

```css
/* Source: templates/index.html lines 21-49 [VERIFIED] */
--primary:   #c8c8b0;   /* sage green — use for grade A */
--secondary: #9f9d9d;   /* grey — use for grade C */
--error:     #ed7f64;   /* clay red — use for grade F */
--tertiary:  #f5f5dc;   /* cream — candidate for grade B (yellow-green) */
/* No existing orange var — grade D needs a new custom color or rgba mix */
```

**Recommended grade color mapping (Claude's Discretion):**
```css
.grade-a { background: rgba(200,200,176,0.12); color: #c8c8b0; border: 1px solid rgba(200,200,176,0.22); }  /* sage green */
.grade-b { background: rgba(180,210,140,0.10); color: #a8c878; border: 1px solid rgba(180,210,140,0.20); }  /* yellow-green (new) */
.grade-c { background: rgba(210,190,100,0.10); color: #c8b440; border: 1px solid rgba(210,190,100,0.20); }  /* yellow (new) */
.grade-d { background: rgba(237,160, 80,0.10); color: #e09840; border: 1px solid rgba(237,160, 80,0.20); }  /* orange (new) */
.grade-f { background: rgba(237,127,100,0.10); color: #ed7f64; border: 1px solid rgba(237,127,100,0.20); }  /* clay red = --error */
```

### State Key Addition

```python
# Source: state.py lines 103-106 pattern [VERIFIED] — adding alongside scan_results
"scan_results":           [],
"last_scan_time":         None,
"scan_conviction_scores": {},
"conviction_threshold":   0.0,   # ADD: exposes config.CONVICTION_THRESHOLD to JS
```

Then in `bot.py` or `dashboard.py`, update state on startup:
```python
# Source: [ASSUMED — initialization pattern, mirrors other config-driven state keys]
import config
shared_state.update(conviction_threshold=config.CONVICTION_THRESHOLD)
```

Or simpler: initialize directly in `state.py _state` using `config.CONVICTION_THRESHOLD` (import config in state.py — check if that creates circular import first).

### Full Grade Badge Template (draft)

```javascript
// Source: [ASSUMED — builds on existing template literal pattern at index.html:2287]
function gradeCell(r, threshold) {
  const score = r.score || 0;
  const conv  = r.conviction || {};
  const grade = scoreToGrade(score, threshold);
  const strategies = (conv.strategies_fired || [])
    .map(s => s.charAt(0).toUpperCase() + s.slice(1)).join(' + ') || 'None';

  const bars = [
    ['Technical', conv.technical || 0],
    ['Volume',    conv.volume    || 0],
    ['Sentiment', conv.sentiment || 0],
    ['Sector',    conv.sector    || 0],
  ].map(([lbl, val]) => `
    <div class="tt-row">
      <span class="tt-label">${lbl}</span>
      <div class="tt-bar-track"><div class="tt-bar-fill" style="width:${Math.round(val*10)}%"></div></div>
      <span class="tt-val">${val.toFixed(1)}</span>
    </div>`).join('');

  return `<td class="score-cell" style="text-align:right;position:relative">
    <span class="grade-pill ${grade.cls}">${grade.letter} ${score.toFixed(1)}</span>
    <div class="score-tooltip">
      <div class="tt-header">Conviction: ${grade.letter} (${score.toFixed(1)}/10)</div>
      ${bars}
      <div class="tt-footer">Strategy: ${strategies}</div>
    </div>
  </td>`;
}
```

---

## Runtime State Inventory

Step 2.5: SKIPPED — This is a greenfield UI addition, not a rename/refactor/migration phase.

---

## Environment Availability

Step 2.6: SKIPPED — Phase 6 is purely frontend HTML/CSS/JS changes with one trivial Python state key addition. No new external tools, services, or CLIs are required. The existing `py server.py paper` dev loop is sufficient.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | none — pytest discovers from `tests/` |
| Quick run command | `py -m pytest tests/test_scanner.py -x -q` |
| Full suite command | `py -m pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SCORE-01 | Grade thresholds compute correctly from threshold value | unit | `py -m pytest tests/test_score_grades.py -x -q` | Wave 0 (new file) |
| SCORE-02 | Tooltip data fields present in state snapshot | unit | `py -m pytest tests/test_score_grades.py::test_conviction_threshold_in_state -x -q` | Wave 0 (new file) |

**Note:** UI rendering (grade badge HTML, tooltip CSS behavior) is not programmatically testable with pytest. Visual verification via browser is the validation mechanism for the CSS/HTML aspects of SCORE-01 and SCORE-02.

### Sampling Rate

- **Per task commit:** `py -m pytest tests/test_score_grades.py -x -q`
- **Per wave merge:** `py -m pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_score_grades.py` — covers grade threshold computation logic (SCORE-01) and state key presence (SCORE-02)

---

## Security Domain

This phase makes no network calls, handles no user input, adds no API routes, and performs no authentication. No ASVS categories apply. V5 input validation: conviction scores come from internal scanner computation, not user input.

Security domain: NOT APPLICABLE for this phase.

---

## Open Questions

1. **Circular import risk: `state.py` importing `config.py`**
   - What we know: `state.py` currently has no imports from `config.py`. `config.py` does not import `state.py`. The import would be one-directional and safe.
   - What's unclear: Whether the team prefers to keep `state.py` dependency-free (it currently only imports `threading` and `collections`).
   - Recommendation: Do NOT import config in state.py. Instead, initialize `conviction_threshold` in state from `bot.py` or via `/api/account` already returned to the frontend (simpler: read it from `d.conviction_threshold` if added to state, OR just pass it as a JS constant derived from the account endpoint which already returns other config values). The cleanest path: update `api_account` in `dashboard.py` to include `conviction_threshold`, then set it once in JS on page load.

2. **Grade badge layout: pill width in narrow score column**
   - What we know: Current score column renders `4.2` (3 chars). Grade badge `[A] 4.2` is wider. The `watchlist-table` uses `th:not(:first-child) { text-align: right }`.
   - What's unclear: Whether the wider badge causes column reflow or overlaps adjacent columns.
   - Recommendation: Planner should specify a minimum column width on the score `<th>` (e.g. `min-width: 80px`) and test at typical watchlist row counts.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | CSS `:hover` tooltip is sufficient for desktop-only dashboard (no touch/mobile requirement) | Architecture Patterns | If mobile support is needed, JS-based tooltip with touchstart events required |
| A2 | Initializing `conviction_threshold` in state from `dashboard.py` `api_account` route avoids circular import and is the cleanest path | Open Questions | If state.py importing config is acceptable, even simpler — initialize directly in state module-level |
| A3 | The existing `.panel` container for the watchlist does not clip absolute-positioned tooltips | Common Pitfalls | If `overflow: hidden` is added to panel CSS in future, tooltips will clip — needs `overflow: visible` on score cell parent chain |

---

## Sources

### Primary (HIGH confidence)

- `scanner.py` lines 457-466 — conviction dict structure (verified keys: technical, volume, sentiment, sector, composite, strategies_fired, earnings_penalty, regime_multiplier)
- `state.py` lines 103-106 — scan_results state structure
- `templates/index.html` lines 2278-2296 — current watchlist row template literal
- `templates/index.html` lines 13-49 — CSS custom property palette
- `templates/index.html` lines 322-339 — signal-pill CSS pattern to adapt
- `config.py` lines 118-119 — CONVICTION_THRESHOLD and weight constants
- `bot.py` lines 349-352 — how scan_results (with conviction) flow into shared state watchlist
- `tests/` directory — pytest infrastructure confirmed, test_scanner.py exists with 32 tests

### Secondary (MEDIUM confidence)

- CSS tooltip positioning pattern — standard web technique, well-established browser behavior

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified by reading codebase; zero new dependencies
- Architecture: HIGH — data flow verified through scanner.py → bot.py → state.py → SSE → JS
- Pitfalls: HIGH — identified by reading actual template code (stale conv-dot keys confirmed)
- Grade computation: HIGH — formulas directly from D-06/D-07 in CONTEXT.md

**Research date:** 2026-04-07
**Valid until:** 2026-05-07 (stable HTML/CSS/JS domain, no fast-moving dependencies)
