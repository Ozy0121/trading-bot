# Features Research: Swing Trading Bot with Options

**Research Date:** 2026-03-27
**Domain:** Automated swing trading + options for small accounts (<$25k, PDT-constrained)

## Table Stakes (Must-Have)

These are required for the bot to be functional with the new strategy.

### Multi-Strategy Stock Scanner
- **What:** Replace top-daily-movers approach with multi-candidate scanner that finds multi-day hold candidates
- **Complexity:** Medium — refactor existing `scanner.py`
- **Dependencies:** Indicator library, data feeds

### Momentum Breakout Detection
- **What:** Detect price breaking N-day high on above-average volume — classic swing entry
- **Complexity:** Low — new scoring function in scanner
- **Dependencies:** Historical bar data

### Mean Reversion Detection
- **What:** RSI < 35 at support levels, Bollinger Band touches — oversold bounce plays
- **Complexity:** Low — new scoring function, `indicators.py` already has RSI and Bollinger
- **Dependencies:** Existing indicator functions

### Combined Scoring System
- **What:** 0-100 score across all strategies — momentum, mean reversion, catalyst. Rank candidates by combined conviction
- **Complexity:** Medium — new scoring architecture replacing single-strategy approach
- **Dependencies:** All scanner strategies

### PDT Counter Extended for Options
- **What:** Options day trades also count toward PDT limit. Existing PDT tracker in `safety.py` must cover options round-trips
- **Complexity:** Low — extend existing tracking
- **Dependencies:** Options order tracking

### Options Chain Analysis
- **What:** Automated strike and expiry selection — find optimal call/put for a given directional thesis
- **Complexity:** High — new module, needs options data from Alpaca
- **Dependencies:** Alpaca options API, Greeks understanding

### Options Liquidity Filter
- **What:** Filter options by open interest (>100), bid-ask spread (<15%), daily volume — avoid illiquid traps
- **Complexity:** Medium — API calls + filtering logic
- **Dependencies:** Options chain data

### Dashboard Options Display
- **What:** Show options positions, P&L, Greeks summary, and expiry countdown on dashboard
- **Complexity:** Medium — new dashboard endpoints + frontend components
- **Dependencies:** Options position tracking, state updates

## Differentiators (Competitive Advantage)

### Sector/Theme Scanning
- **What:** Track hot sectors via ETF performance (XLK, XLE, XLF, etc.), then pick leaders within winning sectors
- **Complexity:** Medium — new scanning layer
- **Dependencies:** ETF data, sector mapping

### Curated Watchlist Management
- **What:** Maintain a 20-30 stock watchlist of well-known names. User can add/remove via dashboard. Scanned alongside dynamic candidates
- **Complexity:** Low — config + dashboard UI
- **Dependencies:** Dashboard endpoints

### Equal Stock/Options Allocation
- **What:** Automatic capital allocation — split available buying power between stock and options strategies
- **Complexity:** Medium — new allocation logic in position sizing
- **Dependencies:** Account balance, options pricing

### Aggressive Small-Account Position Sizing
- **What:** Options contracts capped at $50-$150 each for $500 account. Stock positions sized to maximize each of 3 weekly trades
- **Complexity:** Low — config tuning + sizing formulas
- **Dependencies:** Account size, PDT counter

### Strategy Tagging
- **What:** Tag each trade with strategy type (momentum/reversion/catalyst/options) for post-hoc performance analysis
- **Complexity:** Low — metadata on trade records
- **Dependencies:** Trade logging

### Hold-Time-Aware Exit Signals
- **What:** Exit signals that factor in how long a position has been held. Tighten stops after 2+ days, force exit before options expiry
- **Complexity:** Medium — time-based exit logic
- **Dependencies:** Position entry timestamps

## Anti-Features (Deliberately NOT Building)

| Feature | Reason |
|---------|--------|
| Options spreads (multi-leg) | $500 account can't support the margin requirements |
| Day trading strategies | PDT rule makes this impossible under $25k |
| Options on illiquid stocks | Bid-ask spread destroys returns on small positions |
| Earnings plays | IV crush is well-documented — too risky for small account |
| Multiple simultaneous options positions | Too concentrated at $500 — one bad position wipes out capital |
| Full Greeks dashboard | Overhead not worth it at this stage — simple delta/theta display sufficient |
| Automated options rolling | Too complex for v1 — manual decision via dashboard instead |

## Feature Dependencies

```
Momentum Detection ──┐
Mean Reversion ──────┤
Catalyst Detection ──┼──→ Combined Scoring ──→ Trade Execution
Sector Scanning ─────┤                              │
Watchlist ───────────┘                              ├──→ Stock Orders
                                                    └──→ Options Orders
                                                              │
Options Chain Analysis ──→ Strike/Expiry Selection ───────────┘
Options Liquidity Filter ─┘

PDT Counter (extended) ──→ Gates ALL trade execution
Position Sizing ──→ Allocation between stocks/options
```
