# Requirements: Trading Bot v2

**Defined:** 2026-03-27
**Core Value:** Maximize the value of each of the 3 allowed trades per week by finding the highest-conviction swing trade setups across stocks and options

## v1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Safety Infrastructure

- [ ] **SAFE-01**: Bot persists position state (peak prices, entry dates, PDT history) to local file, survives restarts
- [ ] **SAFE-02**: PDT tracker recognizes OCC-format options symbols and counts them toward the 3-trade limit
- [ ] **SAFE-03**: Order submission polls for fill status with timeout, handles partial fills and rejections explicitly
- [ ] **SAFE-04**: `liquidate_all()` handles both stock positions and options positions (using OptionOrderRequest with LIMIT)
- [ ] **SAFE-05**: Bot validates options trading is enabled on the Alpaca account at startup, fails loudly if not

### Strategy Engine

- [ ] **STRAT-01**: Strategy registry with BaseStrategy ABC — each strategy implements `scan(symbol, df) -> Candidate`
- [ ] **STRAT-02**: MomentumStrategy detects price breaking N-day high on >2x average volume
- [ ] **STRAT-03**: MeanReversionStrategy detects RSI < 35 at support levels (lower Bollinger Band)
- [ ] **STRAT-04**: CatalystStrategy wraps existing ARK/analyst scoring from `catalysts.py`
- [ ] **STRAT-05**: Combined 0-100 scoring system ranks candidates across all strategies
- [ ] **STRAT-06**: Scanner aggregates all strategy results into unified ranked list

### Stock Scanning

- [ ] **SCAN-01**: Technical screener runs all strategies against watchlist using parallel bar fetching (ThreadPoolExecutor)
- [ ] **SCAN-02**: Sector/theme scanning tracks ETF performance (XLK, XLE, XLF, etc.) and picks leaders from top sectors
- [ ] **SCAN-03**: Curated watchlist of 20-30 stocks always included in scans, user-manageable via config
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

## v2 Requirements

Deferred to future milestone. Tracked but not in current roadmap.

### Advanced Options

- **OPT-V2-01**: Delta-based strike selection using Black-Scholes approximation (scipy)
- **OPT-V2-02**: IV rank filtering — prefer IV rank < 50th percentile
- **OPT-V2-03**: Earnings date avoidance — exclude 5 days before earnings
- **OPT-V2-04**: Options rolling — manually extend positions via dashboard

### Advanced Strategies

- **STRAT-V2-01**: Hold-time-aware exit signals — tighten stops after 2+ days
- **STRAT-V2-02**: Strategy performance analytics — win rate, avg return per strategy type
- **STRAT-V2-03**: Backtesting engine for strategy validation

### Infrastructure

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

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SAFE-01 | Phase 1 | Pending |
| SAFE-02 | Phase 1 | Pending |
| SAFE-03 | Phase 1 | Pending |
| SAFE-04 | Phase 1 | Pending |
| SAFE-05 | Phase 1 | Pending |
| STRAT-01 | Phase 2 | Pending |
| STRAT-02 | Phase 2 | Pending |
| STRAT-03 | Phase 2 | Pending |
| STRAT-04 | Phase 2 | Pending |
| STRAT-05 | Phase 2 | Pending |
| STRAT-06 | Phase 2 | Pending |
| SCAN-01 | Phase 2 | Pending |
| SCAN-02 | Phase 2 | Pending |
| SCAN-03 | Phase 2 | Pending |
| SCAN-04 | Phase 2 | Pending |
| SCAN-05 | Phase 2 | Pending |
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

**Coverage:**
- v1 requirements: 27 total
- Mapped to phases: 27
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-27*
*Last updated: 2026-03-27 after initial definition*
