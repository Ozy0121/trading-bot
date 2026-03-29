# Phase 2: Prediction Engine + Stock Scanning - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-29
**Phase:** 02-prediction-engine-stock-scanning
**Areas discussed:** Threshold & technical scores, Sentiment overhaul, Volume fairness, Market regime filter, Stock universe/watchlist
**Mode:** Interactive (recalibration update — Phase 2 already built with 40 tests passing)

---

## Threshold & Technical Scores

| Option | Description | Selected |
|--------|-------------|----------|
| Lower threshold to 5.5-6.0 | Keep formulas, lower the bar. 5.5 passes 35%, 6.0 passes 15% | ✓ |
| Rescale technical formulas | Make breakouts score higher, keep threshold at 7.0 | |
| Both — rescale AND lower | Fix formulas AND lower threshold | |

**User's choice:** Lower threshold to 5.5-6.0
**Notes:** User is not an experienced trader — technical scoring details delegated to Claude.

### Exact threshold value

| Option | Description | Selected |
|--------|-------------|----------|
| 5.5 — more trades | ~35% pass rate, trades more often | |
| 6.0 — balanced | ~15% pass rate, meaningful filter | |
| You decide | Claude picks based on data | ✓ |

**User's choice:** You decide
**Notes:** Claude's discretion within 5.5-6.0 range.

### Candidate count

| Option | Description | Selected |
|--------|-------------|----------|
| Top 3 candidates | Return up to 3 ranked, matches 3 PDT slots | ✓ |
| Keep single best | Current behavior, one per scan | |
| Configurable count | Config var for count | |

**User's choice:** Top 3 candidates

---

## Sentiment Overhaul, Volume Fairness, Market Regime Filter

These three areas were presented together after user indicated they are not an experienced trader and would prefer Claude handle the trading details.

| Option | Description | Selected |
|--------|-------------|----------|
| Sounds good, you decide the details | Claude makes all technical trading decisions for these areas | ✓ |
| Tell me more first | Deeper explanation before deciding | |
| I have specific thoughts | User has opinions | |

**User's choice:** Sounds good, you decide the details
**Notes:** User explicitly stated "I honestly am NOT an experienced trader, so I have no idea what this means." All three areas delegated to Claude's discretion with goals explained in plain language.

---

## Stock Universe / Watchlist

User asked: "Why can't you just look at all the stocks available and pick from those?"

Explained the practical constraint (~8,000 stocks, ~15s for 35-40, would take hours for all). Presented tiered filtering approach used by professional bots.

| Option | Description | Selected |
|--------|-------------|----------|
| Expand watchlist to 50-75 | Bigger curated list, all sectors, no circular logic | ✓ |
| Keep both, fix circular logic | Top movers for discovery, different strategies | |
| You decide | Claude picks best approach | |

**User's choice:** Expand watchlist to 50-75
**Notes:** User also asked how other trading bots handle stock selection. Explained pre-filter → detailed scan → signal generation pattern. Top movers circular logic delegated to Claude.

---

## Narrative/Thematic Analysis (Scope Expansion → Deferred)

User shared a specific example: caught Micron (MU) before 2x move by connecting AI demand → RAM prices → Micron. Asked if the bot could do this.

Explained this is narrative analysis (connecting macro trends to specific stocks), which is fundamentally different from technical analysis. Partially achievable with trending topic detection (article volume spikes), fully achievable only with AI reasoning (Phase 5).

| Option | Description | Selected |
|--------|-------------|----------|
| Note for future | Defer to Phase 5 / v2 | ✓ (both selected) |
| Improve sentiment now | Add trending topic detection in Phase 2 | ✓ (both selected) |
| You decide | Claude decides scope | |

**User's choice:** Both — note for future AND improve sentiment now
**Notes:** Full narrative analysis deferred to Phase 5 (AI Analyst) and v2 (social media sentiment). Trending topic detection (article count weighting) added to Phase 2 sentiment overhaul scope.

---

## Claude's Discretion

- Exact conviction threshold value within 5.5-6.0
- Sentiment scoring formula changes (more opinionated keyword scoring)
- Trending topic detection implementation (article count baseline)
- Volume fairness per-strategy handling
- Market regime filter (SPY trend detection + dampening)
- Watchlist expansion stock selection
- Top movers circular logic fix
- All technical trading parameter decisions

## Deferred Ideas

- Narrative/thematic analysis (AI connecting macro trends to stocks) — Phase 5 / v2
- Social media sentiment (Reddit, Twitter/X) — v2 milestone
- Full stock universe pre-filter via Polygon.io or Alpaca screener — v2
