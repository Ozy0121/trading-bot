# Roadmap: Trading Bot v2

## Overview

Starting from a working single-strategy stock bot, this roadmap extends it into a multi-strategy swing trading system with options execution and AI-powered analysis. The build order prioritizes capital protection first (bracket orders for offline safety), then smarter entries (prediction engine), then options expansion, and finally AI-assisted analysis. The user cannot monitor the bot 24/7, so server-side protection is the #1 priority.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Safety Infrastructure + Bracket Orders** - State persistence, order fill handling, and server-side bracket orders that protect positions when the bot is offline
- [ ] **Phase 2: Prediction Engine + Stock Scanning** - Multi-strategy scoring with news sentiment, volume analysis, and conviction-based trade filtering
- [ ] **Phase 3: Options Trading** - Add options chain analysis and order execution
- [ ] **Phase 4: Position Sizing & Allocation** - Enforce dual capital buckets and trade budget gate
- [ ] **Phase 5: Dashboard + Predictions + AI Analyst** - Predictions tab, conviction breakdowns, watchlist management, and AI chart analysis via Anthropic API

## Phase Details

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
**Plans**: TBD

### Phase 2: Prediction Engine + Stock Scanning
**Goal**: Scanner produces a unified ranked candidate list using multi-strategy scoring (technical + volume + news sentiment + sector momentum), only takes trades above a 7/10 conviction threshold, and logs reasoning for every entry and skip decision
**Depends on**: Phase 1
**Requirements**: STRAT-01, STRAT-02, STRAT-03, STRAT-04, STRAT-05, STRAT-06, SCAN-01, SCAN-02, SCAN-03, SCAN-04, SCAN-05, PRED-01, PRED-02, PRED-03, PRED-04, PRED-05
**Success Criteria** (what must be TRUE):
  1. Each candidate carries a 0-10 conviction score with breakdown (technical, volume, sentiment, sector)
  2. Scanner evaluates momentum breakout, mean reversion, and catalyst signals independently before combining
  3. News sentiment analysis scores headlines as positive/negative/neutral and factors into conviction
  4. Unusual volume spikes (2x+ normal) are detected and boost conviction scores
  5. Sector ETF performance surfaces leaders from top-performing sectors
  6. Only trades with conviction >= 7/10 are executed — lower scores are skipped with logged reasoning
  7. Every trade entry and skip is logged with full reasoning breakdown
  8. Curated watchlist of 20-30 symbols always included in scans, editable via config
  9. Full scan of 35-40 symbols completes in under 15 seconds
**Plans**: TBD

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

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Safety Infrastructure + Bracket Orders | 0/? | Not started | - |
| 2. Prediction Engine + Stock Scanning | 0/? | Not started | - |
| 3. Options Trading | 0/? | Not started | - |
| 4. Position Sizing & Allocation | 0/? | Not started | - |
| 5. Dashboard + Predictions + AI Analyst | 0/? | Not started | - |
