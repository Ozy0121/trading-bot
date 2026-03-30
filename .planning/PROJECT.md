# Trading Bot v2

## What This Is

An automated swing-trading bot for a small ($500) Alpaca brokerage account constrained by PDT rules (3 trades per 5 business days). It scans for high-conviction stock setups across multiple strategies (momentum breakouts, mean reversion, catalyst-driven), executes 1-3 day holds, and incorporates simple options trading (buying calls/puts) to maximize returns with limited capital. Runs via a Flask dashboard with real-time data.

## Core Value

Maximize the value of each of the 3 allowed trades per week by finding the highest-conviction swing trade setups across stocks and options, with aggressive position sizing appropriate for a small growth-focused account.

## Requirements

### Validated

- ✓ Alpaca API integration for stock trading — existing
- ✓ Paper/live trading mode switching — existing
- ✓ Flask dashboard with real-time SSE updates — existing
- ✓ PDT tracking and protection — existing
- ✓ Trailing stop and take-profit exits — existing
- ✓ Losing streak position size reduction — existing
- ✓ News and sentiment data feeds — existing
- ✓ Kill switch and graceful shutdown — existing
- ✓ Server-side bracket orders (stop-loss + take-profit) on Alpaca — Phase 1
- ✓ Multi-strategy swing scanner (momentum, mean reversion, catalyst) — Phase 2
- ✓ Prediction engine with conviction scoring (technical + volume + sentiment + sector) — Phase 2
- ✓ News sentiment analysis on watchlist stocks — Phase 2
- ✓ Only execute trades above 5.8/10 conviction threshold with logged reasoning — Phase 2 (recalibrated from 7/10)
- ✓ Technical screener (breakouts, RSI, volume spikes) — Phase 2
- ✓ Sector/theme-based scanning (sector ETF momentum) — Phase 2
- ✓ Curated watchlist management (60 stocks across all GICS sectors) — Phase 2 (expanded from 20-30)

### Active

- [ ] Options trading via Alpaca API (simple calls/puts)
- [ ] Equal allocation between stock and options strategies
- [ ] Aggressive position sizing tuned for $500 account
- [ ] 1-3 day hold time targeting with appropriate exit signals
- [ ] Options chain analysis and strike/expiry selection
- [ ] AI Chart Analyst panel (Anthropic API) with plain-English analysis and recommendations
- [ ] Dashboard: predictions tab, conviction breakdowns, options P&L, trade reasoning logs

### Out of Scope

- Options spreads or multi-leg strategies — too complex for $500 account, simple calls/puts first
- Day trading strategies — PDT rule makes this impossible under $25k
- Crypto trading — focusing on equities and options
- Automated live trading without paper testing — must validate on paper first
- Social/copy trading features — single-user bot

## Context

- **Account**: ~$500 Alpaca brokerage, paper trading mode for development
- **PDT constraint**: Under $25k means max 3 day trades per 5 business days. Bot already has PDT tracking in `safety.py`
- **Current state**: Working bot with SMA crossover strategy, top-movers scanner, and Flask dashboard. Single strategy, stocks only
- **Alpaca options**: Supported via `alpaca-py` SDK — `OptionHistoricalDataClient`, `OptionDataStream`, options order requests
- **Existing architecture**: Modular Python — `bot.py` (loop), `scanner.py` (screening), `safety.py` (risk), `indicators.py` (technical), `catalysts.py` (signals), `dashboard.py` (Flask), `state.py` (shared state)
- **Known issues**: Broad exception handling, tight coupling to shared state dict
- **Phase 1 complete**: State persistence, bracket orders, options-aware liquidation, dashboard bracket UI
- **Phase 2 complete**: Multi-strategy scanner (momentum/mean-reversion/catalyst), conviction scoring, sentiment cache, 60-stock watchlist, multi-candidate selection, 88 tests

## Constraints

- **PDT**: Max 3 round-trip trades per 5 business days — every trade must count
- **Capital**: ~$500 — limits options to cheap contracts, small stock positions
- **Broker**: Alpaca API only — must use alpaca-py SDK for all trading
- **Hold time**: 1-3 days preferred — overnight holds acceptable
- **Risk**: Aggressive growth mode, but still respect daily loss limits

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Server-side bracket orders as primary protection | User can't monitor 24/7; Alpaca stops execute when bot is offline | Phase 1 |
| Equal stock/options allocation | Diversify strategy types with limited capital | — Pending |
| Simple calls/puts only (no spreads) | $500 account too small for multi-leg strategies | — Pending |
| Multi-method scanning (technical + sector + watchlist) | Maximize signal quality with limited trade count | Phase 2 |
| 5.8/10 conviction threshold for trade execution | Recalibrated from 7/10 — 7.0 passed only 0.4% of realistic combos | Phase 2 |
| Anthropic API (claude-sonnet-4-20250514) for AI analysis | Plain-English market analysis on dashboard | — Pending |
| Keep Alpaca as sole broker | Already integrated, supports options via same SDK | — Pending |
| Aggressive position sizing | Small account needs growth, not capital preservation | — Pending |
| 1-3 day hold targeting | Balances PDT constraints with active management | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-30 after Phase 2 completion — prediction engine, multi-strategy scanner, sentiment cache, 60-stock watchlist*
