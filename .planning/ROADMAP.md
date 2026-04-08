# Roadmap: Trading Bot v2

## Overview

Starting from a working single-strategy stock bot, this roadmap extends it into a multi-strategy swing trading system with options execution and AI-powered analysis. The build order prioritizes capital protection first (bracket orders for offline safety), then smarter entries (prediction engine), then options expansion, and finally AI-assisted analysis. The user cannot monitor the bot 24/7, so server-side protection is the #1 priority.

## Milestones

- :construction: **v1.0 Multi-Strategy Options Bot** - Phases 1-5 (Phases 1-2 complete, 3-5 pending)
- :clipboard: **v2.0 Intelligence Suite** - Phases 6-11 (planned)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>v1.0 Multi-Strategy Options Bot (Phases 1-5)</summary>

- [x] **Phase 1: Safety Infrastructure + Bracket Orders** - State persistence, order fill handling, and server-side bracket orders that protect positions when the bot is offline (completed 2026-03-28)
- [x] **Phase 2: Prediction Engine + Stock Scanning** - Multi-strategy scoring with news sentiment, volume analysis, and conviction-based trade filtering (completed 2026-03-30)
- [ ] **Phase 3: Options Trading** - Add options chain analysis and order execution
- [ ] **Phase 4: Position Sizing & Allocation** - Enforce dual capital buckets and trade budget gate
- [ ] **Phase 5: Dashboard + Predictions + AI Analyst** - Predictions tab, conviction breakdowns, watchlist management, and AI chart analysis via Anthropic API

</details>

### v2.0 Intelligence Suite (Phases 6-11)

- [ ] **Phase 6: Score Recalibration** - Letter grades, hover breakdowns, and config-driven grade thresholds for conviction scores
- [ ] **Phase 7: Expanded Scanner** - S&P 500 + NASDAQ 100 universe with hard pre-filters and two-tier scan architecture
- [ ] **Phase 8: Multi-Source News** - Finnhub, RSS feeds, SEC EDGAR, FRED calendar aggregated with deduplication and per-source caching
- [ ] **Phase 9: Overnight Scanner** - Post-market daemon that generates Tomorrow's Game Plan with approve/reject UI and morning pre-queue
- [ ] **Phase 10: Intelligence Tab** - Market overview dashboard with index charts, VIX gauge, sector heatmap, breadth indicators, and AI brief
- [ ] **Phase 11: PDF Report** - Downloadable professional report with account summary, positions, trade history, metrics, and embedded charts

## Phase Details

<details>
<summary>v1.0 Phase Details (Phases 1-5)</summary>

### Phase 1: Safety Infrastructure + Bracket Orders
**Goal**: The bot survives restarts without losing state, handles order fills explicitly, and — critically — places server-side bracket orders (stop-loss + take-profit) on Alpaca for every position so the user is protected even when the bot is offline
**Depends on**: Nothing (first phase)
**Requirements**: SAFE-01, SAFE-02, SAFE-03, SAFE-04, SAFE-05, BRACKET-01, BRACKET-02, BRACKET-03, BRACKET-04, BRACKET-05
**Success Criteria** (what must be TRUE):
  1. Bot restarts and restores peak prices, entry dates, and PDT history without data loss
  2. An options round-trip using an OCC-format symbol counts against the 3-trade PDT limit
  3. Order submission polls for fill status and handles partial fills and rejections with explicit log messages — not silent success
  4. `liquidate_all()` closes both stock positions and open options positions cleanly
  5. Bot refuses to start in live mode if options trading is not enabled on the Alpaca account
  6. Every stock buy is immediately followed by a bracket order (stop-loss + take-profit) that lives on Alpaca's servers
  7. On startup, bot verifies all existing positions have active stop-loss orders — missing ones are recreated
  8. On shutdown, bot confirms all positions have active server-side stop-losses before allowing exit
  9. Dashboard shows stop-loss and take-profit prices for each position
  10. Stop-loss and take-profit percentages are adjustable from the dashboard
**Plans:** 4/4 plans complete
Plans:
- [x] 01-01-PLAN.md — State persistence + OCC detection + test scaffold
- [x] 01-02-PLAN.md — Bracket orders + fill polling + startup/shutdown checks
- [x] 01-03-PLAN.md — Options-aware liquidation + startup validation
- [x] 01-04-PLAN.md — Dashboard bracket UI + exit settings panel

### Phase 2: Prediction Engine + Stock Scanning
**Goal**: Scanner produces a unified ranked candidate list using multi-strategy scoring (technical + volume + news sentiment + sector momentum), only takes trades above a configurable conviction threshold (~5.8/10), and logs reasoning for every entry and skip decision
**Depends on**: Phase 1
**Requirements**: STRAT-01, STRAT-02, STRAT-03, STRAT-04, STRAT-05, STRAT-06, SCAN-01, SCAN-02, SCAN-03, SCAN-04, SCAN-05, PRED-01, PRED-02, PRED-03, PRED-04, PRED-05
**Success Criteria** (what must be TRUE):
  1. Each candidate carries a 0-10 conviction score with breakdown (technical, volume, sentiment, sector)
  2. Scanner evaluates momentum breakout, mean reversion, and catalyst signals independently before combining
  3. News sentiment analysis scores headlines as positive/negative/neutral and factors into conviction
  4. Unusual volume spikes (2x+ normal) are detected and boost conviction scores
  5. Sector ETF performance surfaces leaders from top-performing sectors
  6. Only trades with conviction >= threshold are executed — lower scores are skipped with logged reasoning
  7. Every trade entry and skip is logged with full reasoning breakdown
  8. Curated watchlist of 50-75 symbols covering all GICS sectors, editable via config
  9. Full scan of 50-75 symbols completes in under 30 seconds
**Plans:** 5/5 plans complete
Plans:
- [x] 02-01-PLAN.md — Strategy foundation: config + state extensions, 3 strategy modules + registry
- [x] 02-02-PLAN.md — Sentiment cache: news scoring + earnings penalty
- [x] 02-03-PLAN.md — Scanner orchestrator rewrite + bot integration + tests
- [x] 02-04-PLAN.md — Scoring recalibration: threshold, sentiment overhaul, volume fairness, market regime filter
- [x] 02-05-PLAN.md — Watchlist expansion, multi-candidate best_buy, top movers circular logic fix

### Phase 3: Options Trading
**Goal**: Bot can analyze options chains, select appropriate contracts with hard liquidity filters, construct valid OCC symbols, and submit LIMIT-only options orders with options-specific exit rules enforced
**Depends on**: Phase 2
**Requirements**: OPT-01, OPT-02, OPT-03, OPT-04, OPT-05, OPT-06
**Success Criteria** (what must be TRUE):
  1. Options chain fetch returns only contracts with DTE 7-21 days, OI > 100, and bid-ask spread < 15% — illiquid contracts are hard-rejected
  2. Automated contract selection picks the closest OTM strike with adequate liquidity and constructs a valid OCC symbol
  3. All options orders are submitted as LIMIT orders — MARKET orders are never used for options
  4. Calls are selected for bullish signals and puts for bearish signals with no exceptions
  5. Open options positions are auto-closed when premium drops 50%, rises 75%, or DTE reaches 3 days or fewer
**Plans**: TBD
**UI hint**: yes

### Phase 4: Position Sizing & Allocation
**Goal**: Capital is hard-split into stock and options buckets, options contracts stay within the premium cap, stock positions are sized aggressively for 3-trade-per-week rhythm, and a 3-trade gate enforces the PDT budget across both asset types
**Depends on**: Phase 3
**Requirements**: SIZE-01, SIZE-02, SIZE-03, SIZE-04
**Success Criteria** (what must be TRUE):
  1. Stock and options each operate from a separate $250 capital bucket — spending from one does not affect the other
  2. No options contract is purchased if the premium (times 100 multiplier) exceeds $150
  3. Stock positions are sized to use available stock budget aggressively within each of the 3 allowed weekly trades
  4. Bot enforces a hard 3-trade ceiling per 5-business-day window across both stocks and options combined — a 4th trade is blocked
**Plans**: TBD

### Phase 5: Dashboard + Predictions + AI Analyst
**Goal**: Dashboard shows options positions, conviction score breakdowns for all watchlist stocks, a Predictions tab with the bot's outlook and reasoning, watchlist management, and an AI Chart Analyst panel powered by the Anthropic API that gives plain-English analysis and trade recommendations
**Depends on**: Phase 4
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, DASH-06, AI-01, AI-02, AI-03, AI-04
**Success Criteria** (what must be TRUE):
  1. Options positions display premium paid, current P&L using the 100x multiplier, and days to expiry countdown
  2. Every open position shows which strategy triggered it (momentum, reversion, or catalyst)
  3. A scan results view shows all ranked candidates with their composite scores and strategy types
  4. User can add or remove symbols from the curated watchlist through the dashboard without editing config files
  5. Predictions tab shows conviction score breakdown (technical, volume, sentiment, sector) for each watchlist stock with reasoning
  6. AI Chart Analyst panel uses Claude claude-sonnet-4-20250514 to analyze current price action, indicators, and news, producing a 2-3 sentence summary with bullish/bearish/neutral indicator and confidence score
  7. AI analysis updates on symbol switch and every few minutes
  8. "What should I do?" button gives specific buy/sell/hold/wait recommendation with reasoning
**Plans**: TBD
**UI hint**: yes

</details>

### Phase 6: Score Recalibration
**Goal**: Conviction scores are immediately interpretable through letter grades and hover breakdowns, so the user understands at a glance why each candidate scored the way it did
**Depends on**: Phase 2 (existing conviction scoring system)
**Requirements**: SCORE-01, SCORE-02
**Success Criteria** (what must be TRUE):
  1. Every conviction score displays as a letter grade (A/B/C/D/F) alongside the numeric value, with grade cutoffs driven by config constants relative to the conviction threshold
  2. Hovering over any score reveals a tooltip breakdown showing each sub-score (technical, volume, sentiment, sector) with numeric values and the strategy label that produced the signal
**Plans:** 2 plans
Plans:
- [x] 06-01-PLAN.md — Expose conviction_threshold in state + test scaffold for grade logic
- [x] 06-02-PLAN.md — Grade pill CSS/JS, tooltip with sub-score bars, stale dot cleanup
**UI hint**: yes

### Phase 7: Expanded Scanner
**Goal**: The scanner discovers high-conviction candidates from a universe of 500+ stocks (S&P 500, NASDAQ 100, top volume, unusual volume) using a two-tier architecture that pre-filters before deep scoring
**Depends on**: Phase 6
**Requirements**: UNIV-01, UNIV-02, UNIV-03, UNIV-04, UNIV-05
**Success Criteria** (what must be TRUE):
  1. Scanner fetches S&P 500 and NASDAQ 100 constituents daily (cached) and merges them into a deduplicated expanded watchlist
  2. Stocks with daily volume >2x their 20-day average are automatically added to the expanded watchlist
  3. Hard pre-filters reject stocks outside $5-MAX_POSITION_VALUE price range, below 500K daily volume, below $100M market cap, off NYSE/NASDAQ, or that are ETFs/preferred shares — before any scoring runs
  4. Bulk yf.download() pre-filter culls the full universe to ~50 survivors, then existing conviction scoring runs only on survivors
  5. The expanded universe scan runs only during the overnight window — the live 60-second bot loop continues using the existing curated watchlist
**Plans**: TBD

### Phase 8: Multi-Source News
**Goal**: News from multiple sources (Finnhub, RSS feeds, SEC EDGAR, FRED) is aggregated, deduplicated, and cached with per-source TTLs, giving the bot and user broader market awareness
**Depends on**: Phase 6
**Requirements**: NEWS-01, NEWS-02, NEWS-03, NEWS-04, NEWS-05, NEWS-06
**Success Criteria** (what must be TRUE):
  1. Finnhub company news API returns headlines for scoring finalists with rate-aware batching that stays under 60 calls/minute
  2. RSS feeds from Google News, MarketWatch, and Reuters are parsed via feedparser, handling both RSS 2.0 and Atom formats without silent failures
  3. SEC EDGAR 8-K RSS feed is fetched with a compliant User-Agent header and 10 req/s rate limit, and items appear as timing signals (not scored)
  4. FRED economic calendar provides FOMC, CPI, and NFP dates — works with or without a FRED API key (static fallback when key is missing)
  5. All news items from all sources share a common format: headline, source, URL, published date, and category — with deduplication by title similarity and per-source TTL caching

**Plans**: TBD

### Phase 9: Overnight Scanner
**Goal**: After market close, the bot automatically scans the expanded universe and presents a ranked "Tomorrow's Game Plan" that the user can approve or reject from the dashboard, so morning trades are deliberate rather than reactive
**Depends on**: Phase 7, Phase 8
**Requirements**: OVNT-01, OVNT-02, OVNT-03, OVNT-04, OVNT-05
**Success Criteria** (what must be TRUE):
  1. A post-market daemon thread triggers after market close (time from Alpaca calendar, DST-safe) and scans the expanded watchlist on daily bars
  2. The overnight scan produces a ranked "Tomorrow's Game Plan" showing top 10 candidates with symbol, score, strategy, key indicators, and top headlines
  3. Dashboard shows the pending game plan with per-symbol approve/reject buttons that persist decisions immediately
  4. Approved candidates get priority in the morning scan — the bot checks the pre-queue before running its live scan at open
  5. Overnight plan decisions persist to a JSON file, survive bot restarts, and automatically expire after 18 hours
**Plans**: TBD
**UI hint**: yes

### Phase 10: Intelligence Tab
**Goal**: A dedicated dashboard tab gives the user market-wide context (index performance, volatility, sector rotation, breadth) plus a plain-English AI brief, so trade decisions are informed by macro conditions
**Depends on**: Phase 8
**Requirements**: INTEL-01, INTEL-02, INTEL-03, INTEL-04, INTEL-05, INTEL-06
**Success Criteria** (what must be TRUE):
  1. Intelligence tab shows SPY, QQQ, DIA, and IWM with current price, daily change %, and 5-day mini-charts
  2. VIX gauge displays current level with a classification label (low/moderate/high/extreme) and 5-day history
  3. Sector performance heatmap shows all 11 GICS sectors with 5-day % change and color gradient, reusing existing scanner sector ETF data
  4. Market breadth indicators (advance/decline ratio, % above 200 SMA) are displayed and cached daily
  5. An AI market brief (2-4 sentences via Claude Sonnet) analyzes market trend, dominant sector, VIX risk, and notable macro events — cached for 15 minutes, with graceful fallback if API key is missing
**Plans**: TBD
**UI hint**: yes

### Phase 11: PDF Report
**Goal**: The user can download a professional PDF report summarizing account status, positions, trade history, and performance metrics with embedded charts — generated in-memory with no disk I/O
**Depends on**: Phase 10
**Requirements**: PDF-01, PDF-02, PDF-03, PDF-04, PDF-05, PDF-06
**Success Criteria** (what must be TRUE):
  1. GET /api/report/pdf returns a downloadable PDF with account summary (equity, cash, buying power, daily P&L)
  2. Report includes all open positions with entry price, current price, P&L, and stop/take-profit levels
  3. Report includes last 50 trades with date, symbol, side, entry, exit, P&L, and win/loss status
  4. Report includes performance metrics: win rate, average gain/loss, consecutive losses, and PDT usage
  5. Report includes 5-day price line charts for held symbols rendered via matplotlib into BytesIO and embedded in the reportlab PDF — never written to disk, generated in under 3 seconds
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10 -> 11

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Safety Infrastructure + Bracket Orders | v1.0 | 4/4 | Complete | 2026-03-28 |
| 2. Prediction Engine + Stock Scanning | v1.0 | 5/5 | Complete | 2026-03-30 |
| 3. Options Trading | v1.0 | 0/? | Not started | - |
| 4. Position Sizing & Allocation | v1.0 | 0/? | Not started | - |
| 5. Dashboard + Predictions + AI Analyst | v1.0 | 0/? | Not started | - |
| 6. Score Recalibration | v2.0 | 0/2 | Planning complete | - |
| 7. Expanded Scanner | v2.0 | 0/? | Not started | - |
| 8. Multi-Source News | v2.0 | 0/? | Not started | - |
| 9. Overnight Scanner | v2.0 | 0/? | Not started | - |
| 10. Intelligence Tab | v2.0 | 0/? | Not started | - |
| 11. PDF Report | v2.0 | 0/? | Not started | - |
