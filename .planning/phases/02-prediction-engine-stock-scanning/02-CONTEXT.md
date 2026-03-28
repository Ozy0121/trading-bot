# Phase 2: Prediction Engine + Stock Scanning - Context

**Gathered:** 2026-03-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Scanner produces a unified ranked candidate list using multi-strategy scoring (technical + volume + news sentiment + sector momentum), only takes trades above a 7/10 conviction threshold, and logs reasoning for every entry and skip decision. This replaces the current single-strategy SMA crossover scanner with a multi-strategy system.

Requirements: STRAT-01 through STRAT-06, SCAN-01 through SCAN-05, PRED-01 through PRED-05 (16 total).

</domain>

<decisions>
## Implementation Decisions

### Strategy Registry (STRAT-01)
- **D-01:** Use lightweight strategy functions (not ABC class hierarchy). The existing codebase is entirely functional — `scanner.py`, `strategy.py`, `indicators.py` all export plain functions. A `strategies/` directory with one module per strategy, each exporting a `scan(symbol, df) -> Candidate` function, keeps the pattern consistent. A simple registry dict maps strategy names to scan functions.
- **D-02:** Three strategies: MomentumStrategy (STRAT-02), MeanReversionStrategy (STRAT-03), CatalystStrategy wrapping existing `catalysts.py` (STRAT-04).

### Conviction Score Composition (STRAT-05)
- **D-03:** 0-10 composite conviction score using weighted average: technical 40%, volume 20%, sentiment 20%, sector 20%. Each sub-score is 0-10 independently, then combined.
- **D-04:** Weights stored in config (env vars) for tuning without code changes.
- **D-05:** Conviction breakdown dict included with every candidate: `{"technical": 7.5, "volume": 8.0, "sentiment": 5.0, "sector": 6.0, "composite": 6.7}`.

### News Sentiment (PRED-01)
- **D-06:** Use Alpaca news API (already have API keys in .env) as primary source for per-stock headlines. Supplement with existing Yahoo RSS feed from `sentiment.py`.
- **D-07:** Simple keyword/phrase scoring for positive/negative/neutral — no ML model, no external NLP API. Count bullish/bearish keywords in headlines, compute net sentiment score.
- **D-08:** Cache sentiment per symbol with 30-minute TTL to avoid hammering APIs during scan cycles.

### Earnings Date Awareness (PRED-03)
- **D-09:** Use yfinance (already a dependency) `Ticker.calendar` for earnings dates. Cache per day.
- **D-10:** Earnings within 3 days reduces conviction score (risk factor), not a hard block. The reduction amount is Claude's discretion.

### Sector Scanning (SCAN-02)
- **D-11:** Track sector ETF performance using a fixed list: XLK, XLE, XLF, XLV, XLI, XLC, XLY, XLP, XLU, XLRE, XLB. Map each watchlist stock to its sector ETF.
- **D-12:** Sector momentum is measured as ETF % change over last 5 days. Top 3 sectors get a boost in sector sub-score for their member stocks.

### Scan Performance (SCAN-01, SCAN-05)
- **D-13:** Use ThreadPoolExecutor for parallel bar fetching across the watchlist (35-40 symbols). Target < 15 seconds total scan time.
- **D-14:** yfinance remains the bar data source for scanning (Alpaca data client used only in the main bot loop for the active symbol).

### Watchlist Management (SCAN-03)
- **D-15:** Curated watchlist of 20-30 stocks in config (env var), same pattern as existing WATCHLIST. This phase adds the config mechanism — dashboard UI for editing comes in Phase 5.

### Trade Logging (PRED-04, PRED-05)
- **D-16:** Every scan cycle logs: all candidates with scores, which signals fired/didn't fire, final composite score, and whether the candidate passed the 7/10 threshold.
- **D-17:** Skip reasoning logged at INFO level: "Skipped AAPL (6.2/10): technical=7, volume=3, sentiment=8, sector=6 — volume sub-score below threshold."

### Claude's Discretion
- Exact scoring formulas within each sub-score (how RSI maps to 0-10, how volume ratio maps to 0-10, etc.)
- Earnings date proximity penalty amount
- ThreadPoolExecutor max_workers count
- Whether to keep the existing `_score_symbol()` function or fully replace it
- Internal module organization (single file vs strategies/ directory)
- How to handle symbols that fail to fetch (skip silently vs log warning)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Scanner & Strategy Code
- `scanner.py` — Current single-strategy scanner with `_score_symbol()`, `scan()`, `best_buy()`, yfinance bar fetching
- `strategy.py` — SMA crossover logic, Alpaca bar fetching for active symbol
- `indicators.py` — RSI, MACD, Bollinger Bands (pure pandas/numpy)
- `catalysts.py` — ARK buys + analyst upgrade detection with caching

### Sentiment & Data
- `sentiment.py` — Existing Fear & Greed + Yahoo RSS + StockTwits background thread
- `config.py` — All config patterns, env var loading, watchlist definition

### Safety Integration
- `safety.py` — PDT checking, position sizing, daily loss limits — scanner must respect these
- `bot.py` — Main loop that calls scanner and acts on results — integration point

### Requirements
- `.planning/REQUIREMENTS.md` §Strategy Engine (STRAT-01 through STRAT-06)
- `.planning/REQUIREMENTS.md` §Prediction Engine (PRED-01 through PRED-05)
- `.planning/REQUIREMENTS.md` §Stock Scanning (SCAN-01 through SCAN-05)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `indicators.py:rsi()`, `macd()`, `bollinger_bands()` — Pure calculation functions, no side effects, directly reusable for all strategies
- `catalysts.py:fetch_ark_buys()`, `has_analyst_upgrade()` — Cache-backed catalyst lookups, wrap directly into CatalystStrategy
- `scanner.py:fetch_bars_yf()` — yfinance bar fetcher with interval mapping, reuse for parallel scanning
- `scanner.py:_score_symbol()` — Current scoring logic, reference for new multi-strategy scorer
- `sentiment.py` — Background sentiment thread pattern, reusable for news sentiment polling

### Established Patterns
- Module-level caches with date/timestamp guards (`_movers_cache`, `_ark_cache`, `_upgrade_cache`)
- Config via env vars loaded at import time (`config.py` pattern)
- Logging with module prefix: `log.info("[scanner] ...")`
- Functions return dicts for complex data (scanner results pattern)
- Background threads as daemon threads updating shared state

### Integration Points
- `bot.py` main loop calls `scanner.scan()` and `scanner.best_buy()` — new scanner must maintain this interface
- `state.py` stores scan results for dashboard display — new results must be compatible
- `dashboard.py` serves scan results via API — response format must be backward-compatible or dashboard updated

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches. The user wants the same discuss→plan→execute workflow as Phase 1.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 02-prediction-engine-stock-scanning*
*Context gathered: 2026-03-28*
