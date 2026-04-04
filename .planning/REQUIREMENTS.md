# Requirements: Trading Bot v2

**Defined:** 2026-03-27
**Core Value:** Maximize the value of each of the 3 allowed trades per week by finding the highest-conviction swing trade setups across stocks and options

## v1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Safety Infrastructure

- [x] **SAFE-01**: Bot persists position state (peak prices, entry dates, PDT history) to local file, survives restarts
- [x] **SAFE-02**: PDT tracker recognizes OCC-format options symbols and counts them toward the 3-trade limit
- [x] **SAFE-03**: Order submission polls for fill status with timeout, handles partial fills and rejections explicitly
- [ ] **SAFE-04**: `liquidate_all()` handles both stock positions and options positions (using OptionOrderRequest with LIMIT)
- [ ] **SAFE-05**: Bot validates options trading is enabled on the Alpaca account at startup, fails loudly if not

### Bracket Orders (Server-Side Protection)

- [x] **BRACKET-01**: Every stock buy immediately places a bracket order on Alpaca with stop-loss (3% below entry) and take-profit (6-8% above entry) that execute on Alpaca's servers even when bot is offline
- [x] **BRACKET-02**: On startup, bot checks all existing positions for active stop-loss orders on Alpaca — recreates missing ones
- [x] **BRACKET-03**: On shutdown, bot confirms all positions have active server-side stop-losses — warns user and offers to place them if missing
- [x] **BRACKET-04**: Dashboard shows stop-loss and take-profit prices for each open position
- [x] **BRACKET-05**: Stop-loss and take-profit percentages are adjustable from the dashboard

### Strategy Engine

- [x] **STRAT-01**: Strategy registry with BaseStrategy ABC — each strategy implements `scan(symbol, df) -> Candidate`
- [x] **STRAT-02**: MomentumStrategy detects price breaking N-day high on >2x average volume
- [x] **STRAT-03**: MeanReversionStrategy detects RSI < 35 at support levels (lower Bollinger Band)
- [x] **STRAT-04**: CatalystStrategy wraps existing ARK/analyst scoring from `catalysts.py`
- [ ] **STRAT-05**: Combined 0-10 conviction scoring system ranks candidates across all strategies with breakdown (technical, volume, sentiment, sector)
- [ ] **STRAT-06**: Scanner aggregates all strategy results into unified ranked list

### Prediction Engine

- [x] **PRED-01**: News sentiment analysis on headlines from Alpaca news API and financial RSS feeds — scored positive/negative/neutral per stock
- [ ] **PRED-02**: Unusual volume spike detection (2x+ normal volume) factored into conviction score
- [x] **PRED-03**: Earnings date awareness — factor approaching earnings into risk assessment
- [ ] **PRED-04**: Only trades with conviction score >= 7/10 are executed — lower scores skipped with logged reasoning
- [ ] **PRED-05**: Every trade entry and skip logged with full reasoning breakdown (which signals fired, which didn't, final score)

### Stock Scanning

- [ ] **SCAN-01**: Technical screener runs all strategies against watchlist using parallel bar fetching (ThreadPoolExecutor)
- [ ] **SCAN-02**: Sector/theme scanning tracks ETF performance (XLK, XLE, XLF, etc.) and picks leaders from top sectors
- [x] **SCAN-03**: Curated watchlist of 20-30 stocks always included in scans, user-manageable via config
- [ ] **SCAN-04**: Replace top-daily-movers with multi-day hold candidates scored for 1-3 day swing potential
- [ ] **SCAN-05**: Scan completes in under 15 seconds for 35-40 symbols

### Options Trading

- [ ] **OPT-01**: Options chain fetching via yfinance with filtering (DTE 7-21 days, OI > 100, bid-ask spread < 15%)
- [ ] **OPT-02**: Automated strike/expiry selection — closest OTM strike with adequate liquidity
- [ ] **OPT-03**: OCC symbol construction for Alpaca order submission
- [ ] **OPT-04**: Options orders always use LIMIT (never MARKET) to prevent catastrophic fills
- [ ] **OPT-05**: Simple calls when bullish, puts when bearish — directional trades only
- [ ] **OPT-06**: Options-specific exit rules: close at -50% premium, close at +75% profit, close at DTE <= 3

### Position Sizing & Allocation

- [ ] **SIZE-01**: Equal capital allocation — $250 stock bucket, $250 options bucket
- [ ] **SIZE-02**: Options contracts capped at $150 max premium per contract
- [ ] **SIZE-03**: Aggressive stock position sizing maximizing each of 3 weekly trades
- [ ] **SIZE-04**: Trade budget pre-allocation — hard 3-trade gate across both asset types per 5-day window

### Dashboard

- [ ] **DASH-01**: Dashboard displays options positions with premium, P&L (using 100x multiplier), DTE countdown
- [ ] **DASH-02**: Strategy tagging visible — which strategy triggered each position
- [ ] **DASH-03**: Scan results view showing ranked candidates with scores and strategy types
- [ ] **DASH-04**: Watchlist management UI — add/remove symbols from curated list
- [ ] **DASH-05**: Predictions tab showing conviction score breakdown (technical, volume, sentiment, sector) for each watchlist stock with reasoning
- [ ] **DASH-06**: Trade reasoning log visible — why the bot entered or skipped each trade

### AI Chart Analyst

- [ ] **AI-01**: AI assistant panel next to chart using Anthropic API (claude-sonnet-4-20250514) that analyzes price, RSI, MACD, SMA crossover, volume, and news for the selected stock
- [ ] **AI-02**: Plain English 2-3 sentence summary with bullish/bearish/neutral indicator and confidence score (X/10)
- [ ] **AI-03**: "What should I do?" button gives specific buy/sell/hold/wait recommendation with reasoning; "Explain more" expands detail
- [ ] **AI-04**: Analysis updates on symbol switch and every few minutes automatically

## v2.0 Requirements — Intelligence Suite

Requirements for milestone v2.0. Each maps to roadmap phases.

### Score Recalibration

- [ ] **SCORE-01**: Conviction scores display as letter grades (A/B/C/D/F) alongside numeric value, with grade cutoffs config-driven and relative to conviction threshold
- [ ] **SCORE-02**: Hovering a score shows tooltip breakdown of sub-scores (technical, volume, sentiment, sector) with per-component numeric values and strategy label

### Expanded Scanner

- [ ] **UNIV-01**: Scanner fetches S&P 500 + NASDAQ 100 constituents (cached daily) and deduplicates into a unified expanded watchlist
- [ ] **UNIV-02**: Top daily volume and unusual volume (>2x 20-day avg) stocks are added to the expanded watchlist
- [ ] **UNIV-03**: Hard pre-filters applied before deep scoring: price $5 to MAX_POSITION_VALUE, daily volume >500K, market cap >$100M, NYSE/NASDAQ only, no ETFs/preferred shares
- [ ] **UNIV-04**: Two-tier scan: bulk `yf.download()` pre-filter culls to ~50 survivors, then full conviction scoring on survivors only
- [ ] **UNIV-05**: Expanded universe scan runs only during overnight window — live 60s bot loop keeps existing watchlist

### Multi-Source News

- [ ] **NEWS-01**: News aggregator fetches from Finnhub company news API with rate-aware batching (60 calls/min limit, news only for scoring finalists)
- [ ] **NEWS-02**: RSS feeds parsed via `feedparser` from Google News, MarketWatch, and Reuters — handles both RSS 2.0 and Atom formats
- [ ] **NEWS-03**: SEC EDGAR 8-K RSS feed fetched with proper User-Agent header and 10 req/s rate limit, used as timing signal only (not scored)
- [ ] **NEWS-04**: FRED economic calendar provides macro event dates (FOMC, CPI, NFP) — static calendar with optional live API, graceful fallback if API key missing
- [ ] **NEWS-05**: All news items normalized to common format with headline, source attribution, URL, published date, and category
- [ ] **NEWS-06**: News deduplication by title similarity across sources, per-source TTL caching (stock news 15min, macro 30min, SEC 1hr, FRED 1day)

### Overnight Scanner

- [ ] **OVNT-01**: Post-market daemon thread runs after market close (time from Alpaca calendar, DST-safe), scans expanded watchlist on daily bars
- [ ] **OVNT-02**: Generates ranked "Tomorrow's Game Plan" with top 10 candidates showing symbol, score, strategy, key indicators, and top headlines
- [ ] **OVNT-03**: Dashboard UI panel shows pending game plan with per-symbol approve/reject buttons
- [ ] **OVNT-04**: Approved candidates get priority in morning scan — bot checks pre-queue before running live scan at open
- [ ] **OVNT-05**: Overnight plan decisions persist to JSON file, survive bot restarts, expire after 18 hours

### Intelligence Tab

- [ ] **INTEL-01**: Dedicated dashboard tab showing SPY/QQQ/DIA/IWM price, daily change %, and 5-day mini-charts
- [ ] **INTEL-02**: VIX gauge showing current level with classification (low/moderate/high/extreme) and 5-day history
- [ ] **INTEL-03**: Sector performance heatmap using existing scanner sector ETF data (promoted to public function), showing 5-day % change with color gradient
- [ ] **INTEL-04**: Market breadth indicators (advance/decline ratio, % above 200 SMA) cached daily
- [ ] **INTEL-05**: AI market brief (2-4 sentences) via Claude Sonnet analyzing market trend, dominant sector, VIX risk level, and notable macro events — cached 15 minutes
- [ ] **INTEL-06**: All intelligence data fetched on-demand via dedicated API routes, not pushed via SSE stream

### PDF Report

- [ ] **PDF-01**: Downloadable PDF via `/api/report/pdf` with account summary (equity, cash, buying power, daily P&L)
- [ ] **PDF-02**: Report includes open positions with entry price, current price, P&L, and stop/take-profit levels
- [ ] **PDF-03**: Report includes last 50 trades with date, symbol, side, entry, exit, P&L, win/loss
- [ ] **PDF-04**: Report includes performance metrics: win rate, avg gain/loss, consecutive losses, PDT usage
- [ ] **PDF-05**: Report includes 5-day price line charts for held symbols via matplotlib, embedded in reportlab PDF using BytesIO (never disk)
- [ ] **PDF-06**: PDF generated in-memory using `reportlab` (pure Python, no system deps) — generation completes in under 3 seconds

## Future Requirements

Deferred to future milestones. Tracked but not in current roadmap.

### Advanced Options (from v1.0)

- **OPT-V2-01**: Delta-based strike selection using Black-Scholes approximation (scipy)
- **OPT-V2-02**: IV rank filtering — prefer IV rank < 50th percentile
- **OPT-V2-03**: Earnings date avoidance — exclude 5 days before earnings
- **OPT-V2-04**: Options rolling — manually extend positions via dashboard

### Advanced Strategies (from v1.0)

- **STRAT-V2-01**: Hold-time-aware exit signals — tighten stops after 2+ days
- **STRAT-V2-02**: Strategy performance analytics — win rate, avg return per strategy type
- **STRAT-V2-03**: Backtesting engine for strategy validation

### Infrastructure (from v1.0)

- **INFRA-V2-01**: SQLite database for trade history and state persistence
- **INFRA-V2-02**: Specific exception handling (APIError, InsufficientFundsError) replacing broad catches

## Out of Scope

| Feature | Reason |
|---------|--------|
| Options spreads (multi-leg) | $500 account can't support margin requirements |
| Day trading strategies | PDT rule makes impossible under $25k |
| Options on illiquid stocks | Bid-ask spread destroys returns |
| Earnings plays | IV crush too risky for small account |
| Multiple simultaneous options positions | Too concentrated at $500 |
| Full Greeks dashboard | Overhead not worth it — simple display sufficient |
| Automated options rolling | Too complex for v1 |
| Crypto trading | Focusing on equities and options |
| Different broker integration | Alpaca supports everything needed |
| Real-time SEC EDGAR filing parsing | NLP complexity too high, 8-K used as timing signal only |
| FRED live API as hard dependency | Static calendar sufficient, API key optional |
| Full candlestick charts in PDF | Complex rendering, line charts sufficient |
| Sector heatmap drill-down | Disproportionate frontend complexity for personal bot |
| Push notifications (email/SMS/Slack) | Dashboard badge sufficient for personal bot |
| Historical backtesting in PDF | Completely different scope |
| Unusual options activity scanning | Requires paid data feed |
| Per-symbol RSS subscriptions in DB | No database in stack, config-based sources |

## Traceability

### v1.0 Requirements (Phases 1-5)

| Requirement | Phase | Status |
|-------------|-------|--------|
| SAFE-01 | Phase 1 | Complete |
| SAFE-02 | Phase 1 | Complete |
| SAFE-03 | Phase 1 | Complete |
| SAFE-04 | Phase 1 | Pending |
| SAFE-05 | Phase 1 | Pending |
| BRACKET-01 | Phase 1 | Complete |
| BRACKET-02 | Phase 1 | Complete |
| BRACKET-03 | Phase 1 | Complete |
| BRACKET-04 | Phase 1 | Complete |
| BRACKET-05 | Phase 1 | Complete |
| STRAT-01 | Phase 2 | Complete |
| STRAT-02 | Phase 2 | Complete |
| STRAT-03 | Phase 2 | Complete |
| STRAT-04 | Phase 2 | Complete |
| STRAT-05 | Phase 2 | Pending |
| STRAT-06 | Phase 2 | Pending |
| SCAN-01 | Phase 2 | Pending |
| SCAN-02 | Phase 2 | Pending |
| SCAN-03 | Phase 2 | Complete |
| SCAN-04 | Phase 2 | Pending |
| SCAN-05 | Phase 2 | Pending |
| PRED-01 | Phase 2 | Complete |
| PRED-02 | Phase 2 | Pending |
| PRED-03 | Phase 2 | Complete |
| PRED-04 | Phase 2 | Pending |
| PRED-05 | Phase 2 | Pending |
| OPT-01 | Phase 3 | Pending |
| OPT-02 | Phase 3 | Pending |
| OPT-03 | Phase 3 | Pending |
| OPT-04 | Phase 3 | Pending |
| OPT-05 | Phase 3 | Pending |
| OPT-06 | Phase 3 | Pending |
| SIZE-01 | Phase 4 | Pending |
| SIZE-02 | Phase 4 | Pending |
| SIZE-03 | Phase 4 | Pending |
| SIZE-04 | Phase 4 | Pending |
| DASH-01 | Phase 5 | Pending |
| DASH-02 | Phase 5 | Pending |
| DASH-03 | Phase 5 | Pending |
| DASH-04 | Phase 5 | Pending |
| DASH-05 | Phase 5 | Pending |
| DASH-06 | Phase 5 | Pending |
| AI-01 | Phase 5 | Pending |
| AI-02 | Phase 5 | Pending |
| AI-03 | Phase 5 | Pending |
| AI-04 | Phase 5 | Pending |

### v2.0 Requirements (Phases TBD — assigned by roadmapper)

| Requirement | Phase | Status |
|-------------|-------|--------|
| SCORE-01 | TBD | Pending |
| SCORE-02 | TBD | Pending |
| UNIV-01 | TBD | Pending |
| UNIV-02 | TBD | Pending |
| UNIV-03 | TBD | Pending |
| UNIV-04 | TBD | Pending |
| UNIV-05 | TBD | Pending |
| NEWS-01 | TBD | Pending |
| NEWS-02 | TBD | Pending |
| NEWS-03 | TBD | Pending |
| NEWS-04 | TBD | Pending |
| NEWS-05 | TBD | Pending |
| NEWS-06 | TBD | Pending |
| OVNT-01 | TBD | Pending |
| OVNT-02 | TBD | Pending |
| OVNT-03 | TBD | Pending |
| OVNT-04 | TBD | Pending |
| OVNT-05 | TBD | Pending |
| INTEL-01 | TBD | Pending |
| INTEL-02 | TBD | Pending |
| INTEL-03 | TBD | Pending |
| INTEL-04 | TBD | Pending |
| INTEL-05 | TBD | Pending |
| INTEL-06 | TBD | Pending |
| PDF-01 | TBD | Pending |
| PDF-02 | TBD | Pending |
| PDF-03 | TBD | Pending |
| PDF-04 | TBD | Pending |
| PDF-05 | TBD | Pending |
| PDF-06 | TBD | Pending |

**Coverage:**
- v1 requirements: 43 total (mapped to Phases 1-5)
- v2.0 requirements: 28 total (phase assignment pending)
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-27*
*Last updated: 2026-04-04 — Added v2.0 Intelligence Suite requirements (28 REQ-IDs across 6 categories)*
