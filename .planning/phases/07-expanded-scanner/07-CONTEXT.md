# Phase 7: Expanded Scanner - Context

**Gathered:** 2026-04-16
**Status:** Ready for planning

<domain>
## Phase Boundary

The scanner discovers high-conviction candidates from a universe of 2,500+ stocks using a four-tier pre-filter pipeline (price → volume → momentum → heavy quant) that culls to ~50 survivors, then ranks them with a quant-only scoring system. The expanded scan runs only during the overnight window (triggered via Alpaca calendar), separate from the live 60-second bot loop. Results persist to state + JSON for dashboard display and restart survival.

</domain>

<decisions>
## Implementation Decisions

### Pre-filter Pipeline
- **D-01:** Four-tier cascading pipeline: (1) Price gate $5-$200 + market cap >$100M, (2) Volume gate avg daily volume >500K, (3) Momentum gate — positive 5-day return OR volume >1.5x 20-day avg, (4) Heavy quant multi-factor model (momentum, value, quality, volatility factors)
- **D-02:** Heavy quant multi-factor model for tier 4 — researcher should investigate open-source Python quant libraries (pandas-ta, ta-lib, quantitative factor models) and GitHub strategy repos for reusable implementations
- **D-03:** Target ~50 survivors after full pipeline for deep ranking (matches UNIV-04)
- **D-04:** Expanded scanner does NOT affect the live 60s scanner — they are separate pipelines. Both can share utility functions but run independently.

### Overnight Timing
- **D-05:** Trigger via Alpaca trading calendar API — scan starts 15 minutes after market close. DST-safe, handles early closes and holidays automatically.
- **D-06:** Hard 2-hour timeout on expanded scan. If not done, save partial results (whatever survived the pipeline so far) and stop. Live scanner resumes normally at open regardless.
- **D-07:** Add dashboard button for manual on-demand expanded scan trigger. Useful for testing, weekends, or mid-day runs.

### Universe Composition
- **D-08:** Keep full 2,500+ stock universe (S&P 500, NASDAQ 100, Russell 2000 proxy, top volume, leveraged ETFs, sector ETFs, discovery scans). 500+ was a floor, not a ceiling.
- **D-09:** ETFs are filtered out in the hard pre-filter gate (UNIV-03 compliance). No special exemptions — ETFs removed during tier 1 filtering.

### Scanner Integration
- **D-10:** Quant-only ranking for overnight survivors — do NOT reuse the conviction scoring engine. Survivors are ranked purely by multi-factor quant scores from the pre-filter pipeline. This is a separate ranking system from the live scanner's tech/volume/sentiment/sector breakdown.
- **D-11:** Results stored in shared_state (for dashboard display) AND persisted to JSON file (survives restarts). Dashboard shows ranked candidates. Phase 9 later adds approve/reject UI on top.

### Claude's Discretion
- Batch size for bulk `yf.download()` calls (suggested ~200 per batch)
- Specific quant factor weights and thresholds (to be determined during research/planning)
- JSON file location and format for persisted results
- Thread pool worker count for overnight scan (previously reduced to 5 for live; overnight can potentially use more since it's not competing with the live loop)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Scanner Architecture
- `scanner.py` — Current conviction scoring pipeline (tech 40%, vol 20%, sentiment 20%, sector 20%). Expanded scanner shares utilities but uses separate quant-only ranking.
- `stock_universe.py` — Full universe builder (2,500+ stocks). Already has S&P 500, NASDAQ 100, Russell 2000, top volume, discovery, ETFs with daily caching.
- `openbb_data.py` — Unified data layer (yfinance + FMP fallback). `fetch_bulk_bars()` is the key function for bulk pre-filtering.

### Indicators and Strategies
- `indicators.py` — Existing technical indicators: RSI, MACD, Bollinger Bands, Keltner Channels, OBV, ADL, ATR. Base for quant factor calculations.
- `strategies.py` — Strategy registry with MomentumStrategy, MeanReversionStrategy, CatalystStrategy.

### Infrastructure
- `state.py` — Shared state with thread-safe Lock. Overnight scan results will be stored here.
- `yf_limiter.py` — Rate limiter for yfinance calls. Critical for 2,500+ symbol bulk downloads.
- `config.py` — Configuration constants. MAX_POSITION_VALUE used for price gate upper bound.

### Requirements
- `.planning/REQUIREMENTS.md` §UNIV-01 through §UNIV-05 — The five success criteria for this phase.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `stock_universe.get_full_universe()` — Already builds the 2,500+ symbol list with deduplication and funnel stats
- `stock_universe.get_funnel_stats()` / `get_scan_summary()` — Dashboard-ready funnel reporting
- `openbb_data.fetch_bulk_bars()` — Bulk bar download for pre-filter tiers 1-3
- `indicators.rsi()`, `indicators.macd()`, `indicators.bollinger_bands()`, `indicators.atr()`, `indicators.obv()` — Building blocks for quant factor model
- `yf_limiter.rate_limited_yf()` — Rate limiting infrastructure

### Established Patterns
- Daily caching with `_cache` / `_date` / `_lock` pattern (used throughout `stock_universe.py`)
- `ThreadPoolExecutor` with `as_completed` for parallel fetching (used in `scanner.py` and `stock_universe.py`)
- Shared state via `state.update()` / `state.snapshot()` with threading.Lock
- Graceful fallbacks on API failure (return cached data or empty list)

### Integration Points
- `state.py` — New keys needed for overnight scan results (ranked candidates, scan timestamp, funnel stats)
- `dashboard.py` — New API route for scan results display + manual trigger button
- `server.py` — Overnight daemon thread startup alongside existing threads
- `config.py` — New constants for scan timing, timeout, batch size

</code_context>

<specifics>
## Specific Ideas

- User wants to research premade quant strategies from GitHub and open-source libraries during planning — researcher agent should evaluate pandas-ta, ta-lib, and quantitative factor model repos
- Heavy quant approach chosen deliberately — user wants a sophisticated multi-factor model, not just simple indicator checks
- Quant-only ranking is intentionally different from conviction scoring — overnight results should feel like a separate "discovery" system

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 07-expanded-scanner*
*Context gathered: 2026-04-16*
