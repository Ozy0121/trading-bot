# Phase 2: Prediction Engine + Stock Scanning - Context

**Gathered:** 2026-03-29 (updated — recalibration pass)
**Status:** Ready for replanning

<domain>
## Phase Boundary

Scanner produces a unified ranked candidate list using multi-strategy scoring (technical + volume + news sentiment + sector momentum), only takes trades above a configurable conviction threshold, and logs reasoning for every entry and skip decision. This update recalibrates the scoring math — the multi-strategy architecture, strategy registry, and parallel scanning are already built and passing 40 tests. The recalibration fixes 9 identified flaws in scoring formulas, threshold reachability, and signal quality.

Requirements: STRAT-01 through STRAT-06, SCAN-01 through SCAN-05, PRED-01 through PRED-05 (16 total).

</domain>

<decisions>
## Implementation Decisions

### Conviction Threshold (STRAT-05, PRED-04) — UPDATED
- **D-01 (updated):** Lower conviction threshold from 7.0 to the 5.5-6.0 range. Current 7.0 passes only 0.4% of realistic parameter combinations — bot almost never trades. Claude's discretion on exact value within 5.5-6.0, targeting ~10-20% pass rate. Threshold remains configurable via `CONVICTION_THRESHOLD` env var.
- **D-02 (updated):** Keep existing technical score formulas as-is (momentum proximity, mean reversion RSI-based). The threshold reduction is sufficient to make the system usable without rescaling formulas.

### Candidate Selection (PRED-04, PRED-05) — NEW
- **D-03 (new):** `best_buy()` returns top 3 candidates (not just 1) to match the 3 PDT trade slots per week. Bot can pick the best available when ready to trade. Return type changes from `dict | None` to `list[dict]` (0-3 items).

### Sentiment Overhaul (PRED-01) — UPDATED
- **D-06 (updated):** Make keyword sentiment scoring more opinionated — current formula returns 4.5-5.5 for nearly everything (noise). Claude's discretion on implementation, but the goal is: clearly bullish news should produce scores >7, clearly bearish <3, and neutral stays at 5.
- **D-07 (updated):** Add trending topic detection — weight stocks appearing in more articles than usual. A stock with 10x its normal headline volume is a signal that something is building. This is article *count* weighting, not narrative analysis.
- **D-08 (unchanged):** Cache sentiment per symbol with 30-minute TTL. Thread-safe with lock.

### Volume Fairness — NEW
- **D-18 (new):** Per-strategy volume handling — don't penalize strategies on dimensions irrelevant to them. Mean reversion catches oversold bounces on normal/low volume; it should not lose 20% of its composite because volume_ratio=1.0 maps to score 2.0/10. Claude's discretion on implementation: options include strategy-specific weight overrides, neutral default for non-volume strategies, or removing volume from the composite for strategies that don't use it.

### Market Regime Filter — NEW
- **D-19 (new):** Add a macro health check using SPY trend. If the S&P 500 (SPY) is in a clear downtrend, reduce confidence in all buy signals. Claude's discretion on implementation: could be a multiplier on the composite (e.g., 0.7x in bearish regime), a separate gate, or an adjustment to the threshold. The goal is "the whole market is crashing, be more cautious."

### Watchlist Expansion (SCAN-03, SCAN-04) — UPDATED
- **D-15 (updated):** Expand curated SWING_WATCHLIST from 25 to 50-75 stocks covering all major sectors. Claude's discretion on exact stock selection — should cover large-cap leaders across all 11 GICS sectors, plus high-momentum mid-caps.
- **D-20 (new):** Top movers fetcher has circular logic with momentum strategy (selects today's gainers, then checks if they broke highs — tautological). Claude's discretion on fix: options include removing top movers entirely in favor of the expanded watchlist, keeping top movers but excluding them from momentum evaluation, or merging a pre-filtered discovery set. Goal is no circular signal generation.

### Strategy Registry (STRAT-01) — UNCHANGED
- **D-01 (original):** Lightweight strategy functions, not ABC class hierarchy. Already implemented.
- **D-02 (original):** Three strategies: momentum, mean_reversion, catalyst. Already implemented.

### Conviction Score Composition (STRAT-05) — UNCHANGED
- **D-03 (original):** 0-10 composite conviction score using weighted average: technical 40%, volume 20%, sentiment 20%, sector 20%. Each sub-score 0-10 independently.
- **D-04 (original):** Weights stored in config (env vars) for tuning.
- **D-05 (original):** Conviction breakdown dict with every candidate.

### Sector Scanning (SCAN-02) — UNCHANGED
- **D-11 (original):** Track sector ETF performance using fixed 11-ETF list.
- **D-12 (original):** Sector momentum = 5-day % change, linearly ranked.

### Scan Performance (SCAN-01, SCAN-05) — UPDATED
- **D-13 (updated):** ThreadPoolExecutor for parallel bar fetching. With expanded watchlist (50-75 symbols), target < 30 seconds total scan time (relaxed from 15s).
- **D-14 (unchanged):** yfinance remains bar data source for scanning.

### Earnings Date Awareness (PRED-03) — UNCHANGED
- **D-09 (original):** yfinance for earnings dates. Cache per day.
- **D-10 (original):** Earnings within 3 days reduces conviction (risk factor).

### Trade Logging (PRED-04, PRED-05) — UNCHANGED
- **D-16 (original):** Every scan cycle logs all candidates with scores and breakdowns.
- **D-17 (original):** Skip reasoning logged at INFO level with full breakdown.

### Thread Safety — NEW
- **D-21 (new):** Add threading.Lock to `_sector_cache` in scanner.py. Currently written from ThreadPoolExecutor workers without synchronization.

### Claude's Discretion
- Exact conviction threshold value within 5.5-6.0 range
- How to make sentiment scoring more opinionated (formula changes, keyword list expansion, weighting)
- Trending topic detection implementation (article count baseline, threshold for "unusual")
- Volume fairness implementation (per-strategy weights, neutral defaults, or weight overrides)
- Market regime filter implementation (SPY trend detection method, how to apply the dampening)
- Watchlist stock selection (50-75 stocks across sectors)
- Top movers circular logic fix approach
- ThreadPoolExecutor worker count for expanded watchlist

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Scanner & Strategy Code
- `scanner.py` — Current multi-strategy scanner with `_score_symbol_multi()`, `scan()`, `best_buy()`, sector ETF scoring, volume scoring, parallel execution
- `strategies/__init__.py` — Strategy registry mapping names to scan functions
- `strategies/momentum.py` — Momentum breakout strategy (20-day high + 2x volume)
- `strategies/mean_reversion.py` — Mean reversion strategy (RSI < 35 + lower BB)
- `strategies/catalyst.py` — Catalyst strategy (ARK buys + analyst upgrades)
- `sentiment_cache.py` — News sentiment scoring with keyword counting and earnings penalty

### Indicators & Data
- `indicators.py` — RSI, MACD, Bollinger Bands (pure pandas/numpy)
- `catalysts.py` — ARK buys + analyst upgrade detection with caching

### Integration Points
- `bot.py` — Main loop calls `scan()` and `best_buy()` — must update for new `best_buy()` return type (list)
- `config.py` — CONVICTION_THRESHOLD, weights, SWING_WATCHLIST — all need updates
- `state.py` — Stores scan results for dashboard display

### Requirements
- `.planning/REQUIREMENTS.md` §Strategy Engine (STRAT-01 through STRAT-06)
- `.planning/REQUIREMENTS.md` §Prediction Engine (PRED-01 through PRED-05)
- `.planning/REQUIREMENTS.md` §Stock Scanning (SCAN-01 through SCAN-05)

### Scoring Analysis
- Session analysis (2026-03-29) demonstrated threshold unreachability: 256 realistic parameter combos, 0.4% pass at 7.0. Target pass rate: 10-20%.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scanner.py:_volume_ratio_to_score()` — Volume formula, may need per-strategy override path
- `scanner.py:_fetch_sector_scores()` — Sector ETF scoring, working correctly
- `scanner.py:_score_symbol_multi()` — Main scoring orchestrator, central point for all recalibration changes
- `sentiment_cache.py:_score_headlines()` — Keyword scoring formula, needs overhaul for more opinionated results
- `sentiment_cache.py:_fetch_alpaca_news()` — Alpaca news fetcher, can be extended for article count tracking
- `config.py` — All weights and thresholds already configurable via env vars

### Established Patterns
- Module-level caches with date/timestamp guards (reuse for market regime cache)
- Config via env vars loaded at import time
- Strategy functions return standardized dict with `fired`, `technical_score`, `volume_ratio`, `details`
- ThreadPoolExecutor with `as_completed` for parallel scanning

### Integration Points
- `bot.py:487` — calls `best_buy(scan_results)` expecting `dict | None`, must handle new `list[dict]` return
- `bot.py:339` — calls `scan(watchlist, catalysts=catalysts)`, interface unchanged
- `state.py` — `scan_results` and `scan_conviction_scores` fields updated by scanner

</code_context>

<specifics>
## Specific Ideas

- User caught Micron (MU) before a 2x move by reading news about AI driving RAM demand — this kind of thematic/narrative analysis is the aspirational goal. Current keyword sentiment can't do this, but trending topic detection (article volume spikes) gets partway there.
- User is not an experienced trader — technical trading decisions should be made by Claude with sound defaults. User cares about the bot actually working and finding good trades, not about RSI thresholds.

</specifics>

<deferred>
## Deferred Ideas

### Narrative/Thematic Analysis (Phase 5 / v2)
- Full narrative analysis: connecting macro trends (e.g., "AI demand rising") to specific stocks (e.g., "Micron makes RAM") — requires AI reasoning, not keyword matching. Natural fit for Phase 5's AI Analyst feature using Claude API.
- Social media sentiment (Reddit, Twitter/X) — detecting emerging narratives before they hit mainstream financial news. Would require new API integrations. v2 milestone candidate.

### Smarter Discovery (v2)
- Use Polygon.io or Alpaca screener API for a fast pre-filter of the full stock universe (~100-500 candidates), then detailed scan the top matches. Solves "why can't we scan all stocks?" without per-stock API calls.

</deferred>

---

*Phase: 02-prediction-engine-stock-scanning*
*Context gathered: 2026-03-29 (recalibration update)*
