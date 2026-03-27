# Project Research Summary

**Project:** Trading Bot v2 — Options + Multi-Strategy Swing Trading
**Domain:** Automated swing trading with options on a PDT-constrained small account ($500)
**Researched:** 2026-03-27
**Confidence:** MEDIUM

## Executive Summary

This project adds two capabilities to an existing Python/Alpaca stock-trading bot: multi-strategy swing scanning (momentum breakout, mean reversion, catalyst) and single-leg directional options execution. The recommended approach requires no new frameworks — the existing alpaca-py SDK already contains full options support, yfinance already handles chain discovery, and `pandas-ta` closes the only real gap in indicator coverage. The architectural change is a strategy registry refactor: replace the current single-strategy `strategy.py` with a `strategies/` package where each strategy is a self-contained class, and `scanner.py` becomes a pure aggregator that fans out to all active strategies and returns a unified ranked candidate list.

The defining constraint throughout is the $500 account size combined with PDT rules. This forces hard capital segregation ($250 stock / $250 options), a strict 3-trade-per-week ceiling across both asset classes, and options contracts capped at $50-$150 each. Every feature decision flows from these constraints — multi-leg options spreads, earnings plays, and simultaneous multi-options positions are all explicitly out of scope. The sequencing pressure is also clear: options execution must not be built until the PDT tracker, OCC symbol handling, and emergency liquidation function are all updated to handle options.

The most underestimated risk is that three existing medium-priority issues in CONCERNS.md — no order-fill confirmation, no state persistence across restarts, and a `liquidate_all()` that only handles stocks — become critical blockers once options are in the system. Options LIMIT orders may sit unfilled, options positions with expiry dates will be lost on restart, and a panic liquidation would silently leave options open. These must be addressed before or during the options integration phase, not deferred afterward.

---

## Key Findings

### Recommended Stack

No new major framework is needed. The existing stack (alpaca-py, pandas, yfinance, Flask) handles everything. The only required addition is `pandas-ta` for the new indicators that swing strategies need: ATR (volatility filter), ADX (trend strength), and Stochastic. TA-Lib is explicitly avoided — it requires a compiled C extension that routinely fails on Windows. `scipy` is deferred; a simple 5%-OTM heuristic is sufficient for first-pass strike selection. `scipy` only becomes relevant if delta-based strike selection is added later.

The split-source pattern for options data is the key design decision: use yfinance to discover the chain (free, includes OI/IV, no tier requirement), then execute through Alpaca. Do not use Alpaca's chain data API for primary discovery — paper accounts may not return usable chain data at all.

**Core technologies:**
- `alpaca-py >= 0.13.0`: stock and options execution — already contains `OptionHistoricalDataClient`, `OptionOrderRequest`, `OptionDataStream`
- `pandas-ta >= 0.3.14b`: ATR, ADX, Stochastic, EMA — extends existing `indicators.py` cleanly
- `yfinance >= 0.2.40`: options chain discovery (strike, expiry, OI, IV, bid/ask) — existing dep, new use
- `pandas >= 2.0.0`: unchanged — verify pandas-ta pandas 2.x compatibility before merging
- `scipy >= 1.11.0`: Black-Scholes delta approximation — **deferred**, only if delta-based strike selection is implemented

**Explicitly excluded:**
- TA-Lib, mibian, py_vollib (C extensions or unmaintained)
- backtrader, zipline-reloaded, vectorbt (conflicting execution models)
- alpaca-trade-api (deprecated v1 SDK)

### Expected Features

**Must have (table stakes):**
- Multi-strategy scanner with momentum breakout, mean reversion, and catalyst detection
- Combined 0-100 scoring system that ranks candidates across all strategies
- Options chain analysis: automated strike/expiry selection using DTE 7-21 days, OI > 100, bid-ask spread < 15%
- Options liquidity filter: hard-reject illiquid contracts before execution
- PDT counter extended to cover options round-trips (OCC symbol recognition)
- Dashboard options display: positions, P&L with correct 100x multiplier, expiry countdown

**Should have (competitive advantage):**
- Sector/theme scanning via ETF performance (XLK, XLE, XLF, XLY, XBI) — pick leaders within winning sectors
- Curated watchlist of 20-30 user-managed stocks always included in scan
- Equal capital allocation: automatic split of buying power between stock and options budgets
- Strategy tagging: tag each trade record with the strategy that triggered it for post-hoc analysis
- Hold-time-aware exits: tighten stops after 2+ days held, force exit before options expiry

**Defer to v2+:**
- Options spreads (multi-leg) — margin requirements incompatible with $500 account
- Automated options rolling — too complex for v1, manual via dashboard instead
- Full Greeks dashboard — overhead not justified at this stage
- Earnings plays — IV crush risk is well-documented; too risky for small account
- Day trading strategies — PDT rule forecloses these under $25k

### Architecture Approach

The core structural change is replacing the single-strategy `strategy.py` with a `strategies/` package implementing a `BaseStrategy` ABC. Each strategy implements `scan(symbol, df) -> Candidate | None` and is self-contained. `scanner.py` becomes the aggregator: it fans out to all active strategies using a `ThreadPoolExecutor` (6 workers), collects `Candidate` objects, and returns a unified ranked list. `bot.py` sees only `Candidate` objects and has no knowledge of which strategy fired. Options execution is a separate concern: it is triggered only when a candidate scores above threshold AND the options budget is available, and it is managed by a new `options_chain.py` module and `options_risk.py` module.

State management requires explicit separation: `state.position` (stock, existing) and `state.options_positions` (list, new) must remain distinct fields. Merging them would propagate conditional logic throughout every consumer. Capital separation is enforced via two hard-coded budget buckets: `stock_budget = $250` and `options_budget = $250`.

**Major components:**
1. `strategies/` package (`momentum.py`, `reversion.py`, `catalyst.py`) — each implements `BaseStrategy`, returns `Candidate | None`
2. `scanner.py` (refactored) — fans out to all strategies + sector scan, aggregates and ranks candidates
3. `options_chain.py` (new) — fetches chain via yfinance, filters by liquidity, selects contract, builds OCC symbol
4. `options_risk.py` (new) — enforces dual budget buckets, premium-based stops, DTE guards, earnings avoidance
5. `safety.py` (extended) — PDT counter updated for OCC symbols, `liquidate_all()` updated for options
6. `dashboard.py` (extended) — options P&L with 100x multiplier, expiry countdown, strategy scores

### Critical Pitfalls

1. **PDT tracker misses options round-trips** — OCC symbols (`TSLA250117C00250000`) are not recognized by the existing stock-ticker-based PDT counter. This will silently allow PDT violations. Fix: extend `safety.py` to detect OCC symbols and count options round-trips against the same 3-trade limit. Must be solved before any options execution.

2. **100x contract multiplier absent from position sizing** — `calculate_safe_qty()` sizes by share price. A $1.50 options premium = $150 actual cost. Without the multiplier the bot will size positions 100x wrong. Fix: create separate options sizing logic that always multiplies premium by 100. Never reuse stock sizing for options.

3. **Three existing MEDIUM issues become CRITICAL with options** — no order-fill confirmation (options LIMIT orders may sit unfilled, creating phantom positions), no state persistence across restarts (options with expiry dates will be lost), and `liquidate_all()` using `MarketOrderRequest` (options positions survive emergency liquidation silently). All three must be addressed before or during options integration.

4. **OCC symbol format breaks all existing symbol lookups** — `safety.py`, `bot.py`, and `state.py` all look up positions by ticker string. OCC symbols will be invisible to trailing stops, kill switch, and liquidation logic. Fix: use `state.options_positions` as a completely separate field and never mix OCC symbols into stock-oriented lookups.

5. **Theta decay and bid-ask spread make naive options entries structurally unprofitable** — buying options with <5 DTE loses $0.10-0.30/day in time value alone. Illiquid options with 10-40% bid-ask spreads create immediate 20%+ unrealized losses on entry. Fix: enforce DTE 7-21 days, OI > 100, volume > 50, bid-ask spread < 15% of mid — all as hard filters, not soft preferences.

---

## Implications for Roadmap

Based on research, dependencies force a clear build order. Options execution cannot come before PDT/safety infrastructure is updated, and scanner refactoring is the natural prerequisite for everything else since the existing single-strategy loop is the starting point.

### Phase 1: Safety Infrastructure Updates
**Rationale:** Three existing CONCERNS.md issues escalate from MEDIUM to CRITICAL the moment options orders exist. Fixing these first means every subsequent phase builds on solid foundations. The PDT extension and OCC symbol separation must also land before any options order can be safely submitted.
**Delivers:** PDT counter that recognizes options, `liquidate_all()` that handles both asset types, order-fill confirmation polling, state persistence across restarts
**Addresses:** Pitfalls 1, 3, 4 (PDT tracker, liquidation, phantom positions, state loss)
**Avoids:** Building options execution on top of a broken safety layer

### Phase 2: Strategy Registry Refactor
**Rationale:** No new APIs needed, pure logic refactor. This is the natural starting point for new capabilities — the strategy registry enables momentum and mean reversion without touching execution. Delivers value independently of options.
**Delivers:** `strategies/` package with `BaseStrategy` ABC, `MomentumStrategy`, `MeanReversionStrategy`, `CatalystStrategy` (wraps existing `catalysts.py`), refactored `scanner.py` as aggregator with parallel scanning and unified scoring
**Addresses:** Multi-strategy stock scanner, momentum breakout detection, mean reversion detection, combined scoring system
**Uses:** `pandas-ta` (new dependency), existing yfinance for ETF sector data
**Avoids:** Pitfall 15 (scores stocks and options independently via budget buckets, not raw score comparison)

### Phase 3: Options Chain Selection
**Rationale:** Chain fetching and contract selection is purely analytical — no execution, no order submission. Can be built and tested in isolation before any live trading risk is introduced.
**Delivers:** `options_chain.py` with yfinance-based chain fetching, liquidity filtering (OI > 100, spread < 15%, volume > 50), DTE 7-21 day filter, strike selection, OCC symbol construction
**Addresses:** Options chain analysis, options liquidity filter
**Uses:** yfinance (existing), OCC symbol builder from STACK.md research
**Avoids:** Pitfalls 3 and 4 (theta decay, bid-ask spread) — these are addressed here as hard filters

### Phase 4: Options Execution and Risk Management
**Rationale:** Builds on chain selection (Phase 3) and safe infrastructure (Phase 1). Introduces actual options order submission and the dual-bucket capital system.
**Delivers:** `options_risk.py` with $250 stock / $250 options budget buckets, premium-based stops (-50% / +75%), DTE <= 3 auto-close, earnings date avoidance, options order submission via `OptionOrderRequest` with LIMIT-only enforcement
**Addresses:** Options execution, aggressive small-account position sizing, hold-time-aware exits, equal stock/options allocation
**Uses:** `alpaca-py` options order classes (already available in installed SDK)
**Avoids:** Pitfalls 2 (100x multiplier), 5 (LIMIT order only), 9 (over-trading budget)

### Phase 5: Dashboard and Monitoring Updates
**Rationale:** All backend logic is stable by this point. Dashboard updates are purely additive — new endpoints and UI components that display data the system already tracks.
**Delivers:** Options positions display with P&L using 100x multiplier, expiry countdown, strategy score view for all candidates, sector scan results, watchlist management UI
**Addresses:** Dashboard options display, strategy tagging, curated watchlist management
**Avoids:** Pitfall 14 (P&L math using correct multiplier)

### Phase Ordering Rationale

- Safety infrastructure must precede options execution — the existing CONCERNS.md issues are currently tolerable for stocks but become account-breaking with options
- Strategy registry precedes options execution because the combined scoring system is the decision gate that determines when options are appropriate (score >= 70 threshold)
- Chain selection precedes order submission — test the analytical path before adding real execution risk
- Dashboard is last because it is purely additive and depends on all data being available from earlier phases

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1 (Safety Infrastructure):** Order-fill confirmation polling design needs specific Alpaca API behavior verified — timeout values, partial fill handling, and whether paper mode order status is reliable
- **Phase 4 (Options Execution):** Alpaca paper account options behavior needs validation — confirm whether paper mode allows options order submission and whether `OptionHistoricalDataClient` returns usable chain data in paper mode (open question from STACK.md)

Phases with standard patterns (can skip research-phase):
- **Phase 2 (Strategy Registry):** Strategy registry pattern is well-documented; all indicators exist in pandas-ta with clear API
- **Phase 3 (Chain Selection):** yfinance options chain API is stable and well-documented; filter thresholds are established practice
- **Phase 5 (Dashboard):** Flask SSE + new endpoints is standard pattern already in use in the codebase

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | alpaca-py options classes confirmed available; pandas-ta is the clear winner for indicators; yfinance chain pattern is established practice |
| Features | HIGH | Feature set is tightly constrained by the $500 / PDT context — little ambiguity about what's in/out |
| Architecture | MEDIUM | Derived from codebase analysis + established trading system patterns; build order is clear but component interfaces will need validation during implementation |
| Pitfalls | HIGH | All critical pitfalls are concrete and code-specific (existing function names, known bugs in CONCERNS.md) — not hypothetical |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **Alpaca paper account options eligibility:** Whether `OptionHistoricalDataClient` returns usable data in paper mode is unconfirmed. If it does not, yfinance is the sole chain source even for production. Validate early in Phase 3.
- **pandas-ta + pandas 2.x compatibility:** Research flagged this as a potential issue. Check PyPI for known issues before Phase 2 begins — if pandas-ta has pandas 2.x breakage, an alternative indicator approach is needed.
- **PDT + options on Alpaca paper accounts:** Whether options round-trips increment the PDT counter in paper mode needs verification. The code should enforce the limit correctly regardless, but paper testing may not catch violations.
- **Alpaca live options approval:** The bot will work in paper mode without options approval. Add a startup validation check that fails loudly if live mode is detected and options trading is not enabled on the account.

---

## Sources

### Primary (HIGH confidence)
- `.planning/research/STACK.md` — alpaca-py options classes, yfinance chain pattern, pandas-ta indicator API, OCC symbol construction
- `.planning/research/PITFALLS.md` — PDT tracker gaps, 100x multiplier requirement, liquidation function issues, existing CONCERNS.md escalation
- `.planning/research/FEATURES.md` — feature set, anti-features, dependency graph
- `.planning/research/ARCHITECTURE.md` — strategy registry pattern, component boundaries, build order, state management approach

### Secondary (MEDIUM confidence)
- `.planning/codebase/ARCHITECTURE.md` — existing bot structure (basis for all architecture recommendations)
- `.planning/codebase/STRUCTURE.md` — current file layout
- `.planning/PROJECT.md` — project goals and account constraints

### Tertiary (needs validation)
- Alpaca paper account options data availability — flagged as open question; verify in Phase 3
- pandas-ta pandas 2.x compatibility — verify before Phase 2

---
*Research completed: 2026-03-27*
*Ready for roadmap: yes*
