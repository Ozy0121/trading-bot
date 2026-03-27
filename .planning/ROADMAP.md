# Roadmap: Trading Bot v2

## Overview

Starting from a working single-strategy stock bot, this roadmap extends it into a multi-strategy swing trading system with options execution. The build order is forced by dependency: safety infrastructure must be solid before any options order can be submitted, the strategy registry must exist before scanning can be multi-dimensional, options chain analysis must be validated before execution risk is introduced, and the dashboard updates are purely additive once all backend data exists.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Safety Infrastructure** - Harden the bot's foundation to handle options before any options code is added
- [ ] **Phase 2: Strategy Engine + Stock Scanning** - Replace single-strategy loop with multi-strategy registry and smarter scanner
- [ ] **Phase 3: Options Trading** - Add options chain analysis and order execution
- [ ] **Phase 4: Position Sizing & Allocation** - Enforce dual capital buckets and trade budget gate
- [ ] **Phase 5: Dashboard Updates** - Expose options positions, strategy scores, and watchlist management in the UI

## Phase Details

### Phase 1: Safety Infrastructure
**Goal**: The bot survives restarts without losing state, recognizes options symbols in PDT tracking, handles order fills and rejections explicitly, and can emergency-liquidate both stocks and options
**Depends on**: Nothing (first phase)
**Requirements**: SAFE-01, SAFE-02, SAFE-03, SAFE-04, SAFE-05
**Success Criteria** (what must be TRUE):
  1. Bot restarts and restores peak prices, entry dates, and PDT history without data loss
  2. An options round-trip using an OCC-format symbol counts against the 3-trade PDT limit
  3. Order submission polls for fill status and handles partial fills and rejections with explicit log messages — not silent success
  4. `liquidate_all()` closes both stock positions and open options positions cleanly
  5. Bot refuses to start in live mode if options trading is not enabled on the Alpaca account
**Plans**: TBD

### Phase 2: Strategy Engine + Stock Scanning
**Goal**: Scanner produces a unified ranked candidate list from three distinct strategies plus sector scanning and a curated watchlist, replacing the top-daily-movers approach
**Depends on**: Phase 1
**Requirements**: STRAT-01, STRAT-02, STRAT-03, STRAT-04, STRAT-05, STRAT-06, SCAN-01, SCAN-02, SCAN-03, SCAN-04, SCAN-05
**Success Criteria** (what must be TRUE):
  1. Each candidate in the ranked list carries a 0-100 composite score and a strategy tag (momentum, reversion, or catalyst)
  2. Scanner evaluates momentum breakout, mean reversion, and catalyst signals independently before combining scores
  3. Sector ETF performance (XLK, XLE, XLF, etc.) surfaces leaders from top-performing sectors in the candidate list
  4. A curated watchlist of 20-30 symbols is always included in scans and is editable via config
  5. Full scan of 35-40 symbols completes in under 15 seconds
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

### Phase 5: Dashboard Updates
**Goal**: Dashboard shows options positions with correct P&L math, surfaces which strategy triggered each trade, displays ranked scan candidates with scores, and lets the user manage the watchlist from the UI
**Depends on**: Phase 4
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04
**Success Criteria** (what must be TRUE):
  1. Options positions display premium paid, current P&L using the 100x multiplier, and days to expiry countdown
  2. Every open position shows which strategy triggered it (momentum, reversion, or catalyst)
  3. A scan results view shows all ranked candidates with their composite scores and strategy types
  4. User can add or remove symbols from the curated watchlist through the dashboard without editing config files
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Safety Infrastructure | 0/? | Not started | - |
| 2. Strategy Engine + Stock Scanning | 0/? | Not started | - |
| 3. Options Trading | 0/? | Not started | - |
| 4. Position Sizing & Allocation | 0/? | Not started | - |
| 5. Dashboard Updates | 0/? | Not started | - |
