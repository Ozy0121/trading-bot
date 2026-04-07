# Phase 6: Score Recalibration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-07
**Phase:** 06-score-recalibration
**Areas discussed:** Grade display style, Tooltip breakdown, Grade thresholds

---

## Grade Display Style

| Option | Description | Selected |
|--------|-------------|----------|
| Colored badge + number | Letter grade in colored pill + numeric score next to it (e.g. [A] 8.2) | ✓ |
| Grade replaces number | Show only letter grade, hide raw number (hover for numeric) | |
| You decide | Let Claude pick based on existing dashboard style | |

**User's choice:** Colored badge + number
**Notes:** User liked the mockup with green/yellow/red pills

---

| Option | Description | Selected |
|--------|-------------|----------|
| Watchlist table only | Grades only in scan results table | |
| Everywhere scores appear | Apply grades wherever conviction score is shown | |
| You decide | Claude determines where grades add value | ✓ |

**User's choice:** You decide
**Notes:** None

---

## Tooltip Breakdown

| Option | Description | Selected |
|--------|-------------|----------|
| Labeled bars + numbers | Horizontal mini-bars with labels and numeric values per sub-score | ✓ |
| Simple numbers only | Just labels with numeric values, no bars | |
| You decide | Claude picks tooltip format | |

**User's choice:** Labeled bars + numbers
**Notes:** User liked the visual bar representation for quick scanning

---

| Option | Description | Selected |
|--------|-------------|----------|
| All fired strategies | Show all strategies that produced a signal | ✓ |
| Primary strategy only | Show only the highest-scoring strategy | |
| You decide | Claude picks | |

**User's choice:** All fired strategies
**Notes:** Data already exists in conviction.strategies_fired

---

## Grade Thresholds

| Option | Description | Selected |
|--------|-------------|----------|
| Threshold = B/C boundary | A: 8.0+, B: 5.8+, C: 4.0+, D: 2.5+, F: <2.5 | ✓ |
| Evenly spaced | A: 8+, B: 6+, C: 4+, D: 2+, F: <2 | |
| You decide | Claude determines boundaries | |

**User's choice:** Threshold = B/C boundary
**Notes:** Intuitive mapping: B+ = tradeable, C- = skip

---

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-adjust from threshold | Grade boundaries computed from CONVICTION_THRESHOLD | ✓ |
| Independent config constants | Each grade cutoff is its own config constant | |
| You decide | Claude picks simpler approach | |

**User's choice:** Auto-adjust from threshold
**Notes:** Change one number, all grades follow

---

## Claude's Discretion

- Color palette for grade badges
- Tooltip CSS styling, positioning, animation
- Grade computation location (Python vs JS)
- Where beyond watchlist grades add value

## Deferred Ideas

- Scoring calibration tune-up — scanner rarely buys, threshold may be too high relative to typical scores. User noted this during discussion but agreed it's a separate task from display changes.
