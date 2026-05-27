# Roadmap: Trading Bot v2

## Overview

Starting from a working prediction bot with safety infrastructure, expanded scanning, and a Flask dashboard, this roadmap addresses critical bugs, architectural debt, and capability gaps identified by a full-team review (May 2026). The build order prioritizes fixing what's broken first, then making predictions actually accurate, then improving the trader experience, and finally expanding into options and AI analysis.

## Milestones

- :white_check_mark: **v1.0 Multi-Strategy Foundation** - Phases 1-2 (Complete)
- :white_check_mark: **v2.0 Intelligence Suite** - Phases 6-7 (Complete, Phases 8-11 superseded)
- :construction: **v2.1 Stability & Critical Fixes** - Phases 8-9 (Fix bugs that undermine prediction quality)
- :clipboard: **v2.2 Prediction Intelligence** - Phases 10-11 (Make predictions actually work)
- :clipboard: **v2.3 Trader Experience** - Phases 12-13 (UX that serves a 3-trade-per-week trader)
- :clipboard: **v3.0 Options & News** - Phases 14-15 (Expand asset types and data sources)
- :clipboard: **v3.1 AI & Reports** - Phases 16-17 (AI analyst and reporting)

## Completed Phases

<details>
<summary>v1.0 Multi-Strategy Foundation (Phases 1-2) — Complete</summary>

- [x] **Phase 1: Safety Infrastructure + Bracket Orders** — State persistence, bracket orders, OCC-aware PDT tracking (completed 2026-03-28)
- [x] **Phase 2: Prediction Engine + Stock Scanning** — Multi-strategy scoring, news sentiment, volume analysis, conviction filtering (completed 2026-03-30)

</details>

<details>
<summary>v2.0 Intelligence Suite (Phases 6-7) — Complete</summary>

- [x] **Phase 6: Score Recalibration** — Letter grades, hover breakdowns, config-driven thresholds (completed 2026-04-08)
- [x] **Phase 7: Expanded Scanner** — S&P 500 + NASDAQ 100 universe, four-tier cascade to ~50 survivors (completed 2026-04-19)

</details>

<details>
<summary>Quick Tasks Completed (ad-hoc work between phases)</summary>

| Date | Task | Commit |
|------|------|--------|
| 2026-03-28 | Dashboard UI redesign (glassmorphism dark theme) | b1c55ee |
| 2026-04-01 | Conviction scoring recalibration | 6aedc04 |
| 2026-04-02 | Fix stop-without-liquidate, wire agent coordinator | c7660c6 |
| 2026-04-26 | Pattern weight calibration from backtest results | 2f4466e |
| 2026-05-04 | Prediction engine v4 win rate improvement (51%->77%) | 0e3a788 |
| 2026-05-05 | Position sizing multiplier, regime filter improvements | -- |
| 2026-05-06 | Two-stage scan workflow, parallel scoring | -- |
| 2026-05-07 | Prediction filter relaxation (ADX 40->60, confluence 3->2) | -- |
| 2026-05-08 | Scan button tooltips, stream reconnection with backoff | -- |

</details>

---

## Active Roadmap

### v2.1 Stability & Critical Fixes

#### Phase 8: Critical Bug Fixes
**Goal**: Fix bugs that are actively undermining prediction quality, position sizing, and system reliability — the bot is producing predictions with broken scoring and dead safety guards

**Depends on**: None (urgent fixes)

**Bugs to fix** (from code review):

| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | CRITICAL | prediction.py:389-409 | **Dead veto branch** — `_get_confirmations()` always returns `vetoed=False`. CVD/AMT veto guard is dead code. Setups that should be rejected pass through silently. |
| 2 | CRITICAL | prediction.py:672-673 | **Accuracy always 0.0** — `historical_accuracy` and `historical_samples` are hardcoded to zero. Never queries actual prediction outcomes. Sorting by accuracy degenerates to confidence-only. |
| 3 | CRITICAL | dashboard.py:725 | **Broken deduplication** — `set.add()` inside list comprehension is a side-effect anti-pattern. Dedup intent works in CPython but is fragile and misleading. |
| 4 | HIGH | prediction.py:381 | **Position sizing overwrite** — `position_mult = 0.5` (assignment) instead of `*= 0.5`. SPY penalty silently discards SMA-slope penalty instead of compounding. |
| 5 | HIGH | stream.py:50-53 | **Backoff reset too early** — `backoff = 5` resets before `stream.run()` succeeds. Auth failures cause aggressive 5-second retry storm. |
| 6 | HIGH | bot.py | **daily_loss_exceeded never called** — Function exists in safety.py but bot.py never invokes it. Daily loss limit is a dead guard. |
| 7 | MEDIUM | prediction.py:31,36 | Unused imports (numpy, fetch_bars) |
| 8 | MEDIUM | prediction.py:714 | `callable` (lowercase) is not a valid type hint |

**Success Criteria**:
  1. Veto branch is live — CVD/AMT signals can reject bad setups
  2. Historical accuracy feeds from prediction_log into scoring
  3. Position sizing compounds penalties correctly (`*=` not `=`)
  4. Stream backoff only resets after confirmed stable connection
  5. Daily loss limit is actually enforced in the bot loop
  6. All unused imports removed, type hints corrected

**Plans:** 2 plans

Plans:
- [x] 08-01-PLAN.md — Fix prediction engine bugs (veto, accuracy, sizing, imports, type hint)
- [x] 08-02-PLAN.md — Fix dashboard dedup, stream backoff, verify daily loss guard

---

#### Phase 9: Architecture Cleanup
**Goal**: Reduce the risk of silent bugs and thread-safety issues by splitting the monolithic dashboard, adding state schema validation, and protecting shared mutable globals

**Depends on**: Phase 8

**Issues to fix** (from architecture review):

| # | Area | Issue |
|---|------|-------|
| 1 | dashboard.py (1084 lines) | Monolith handling REST, SSE, manual trading, scan orchestration, auto-trading, backtesting. Split into route modules. |
| 2 | safety.py globals | `_peak_prices`, `_positions_opened_today`, `_session_start_equity` mutated from multiple threads with no lock. `update_peak_price()` has read-then-write race. |
| 3 | state.py | Flat dict with 50+ keys, no schema validation. `update()` silently ignores unknown keys — typos produce silent bugs. |
| 4 | Prediction data divergence | Dashboard reads predictions from `shared_state`. Bot reads from `prediction_scanner.get_latest_predictions()` (disk). Two sources can diverge. |
| 5 | bot.py:run_bot (270 lines) | 14-phase monolith. Extract each phase into a function. |
| 6 | server.py startup | All imports/wiring inline with no error isolation. One failure blocks entire startup. |

**Success Criteria**:
  1. dashboard.py split into <=3 route modules (trading, scanner, data)
  2. safety.py globals protected by Lock — no unguarded cross-thread mutation
  3. state.py validates keys on `update()` — unknown keys raise ValueError
  4. Single prediction data source for both bot and dashboard
  5. run_bot phases extracted into named functions
  6. server.py startup failures isolated — scanner failure doesn't block dashboard

**Plans:** 3 plans

Plans:
- [ ] 09-01-PLAN.md — Split dashboard.py into three Flask Blueprint route modules
- [ ] 09-02-PLAN.md — Add state schema validation (ValueError) and safety.py thread locks
- [ ] 09-03-PLAN.md — Unify prediction data, isolate server startup, extract run_bot phases

---

### v2.2 Prediction Intelligence

#### Phase 10: Prediction Feedback Loop
**Goal**: Close the loop between predictions and outcomes — backtesting results and live trade outcomes feed back into confidence scoring, so the bot learns which signals actually work

**Depends on**: Phase 9

**Current state**: Backtesting (run_backtest_v3/v4) runs but results never feed into prediction.py. Prediction accuracy is tracked in prediction_log.py (50% actual win rate) but never read by the scoring engine. Confidence is computed from signal presence alone.

**What to build**:
  1. **Outcome tracker** — After each prediction, monitor the stock for 3 days and record actual outcome (direction correct? magnitude? timing?)
  2. **Signal-level accuracy** — Track which specific signals (RSI2 oversold, IBS<0.2, BB touch, etc.) correlated with correct predictions vs false signals
  3. **Adaptive confidence** — Weight signals by their historical accuracy, not fixed weights. RSI2 oversold showing 75% accuracy should weight more than consec_down at 45%
  4. **Backtest integration** — run_backtest results auto-update signal weights in prediction.py config
  5. **Dashboard accuracy display** — Show "Last 30 predictions: X correct (Y%)" prominently, per the CLAUDE.md identity

**Success Criteria**:
  1. Every prediction is tracked to resolution with predicted vs actual outcome
  2. Signal-level accuracy stats are maintained and queryable
  3. Confidence scoring uses historical signal accuracy, not hardcoded weights
  4. Backtest results automatically update signal weights
  5. Dashboard shows running prediction accuracy (overall and per-signal)

**Plans:** 3/3 plans complete

Plans:
- [x] 10-01-PLAN.md — Recalibration engine + unit tests, extend prediction logging with active_signals, wire outcome resolution into scheduler
- [x] 10-02-PLAN.md — File-based weight loading in prediction.py, Sunday midnight recalibration scheduler, three new API routes
- [x] 10-03-PLAN.md — Dashboard accuracy banner, per-signal stats table, trend sparkline, recalibrate button

---

#### Phase 11: Signal Expansion
**Goal**: Wire in the signals that are already coded but unused, and add the critical missing ones — the bot currently relies almost entirely on mean reversion with arbitrary thresholds

**Depends on**: Phase 10 (needs feedback loop to validate new signals)

**Already coded but not wired into prediction.py**:
  - VWAP (in agents/strategist.py)
  - Stochastic RSI (in agents/quant_analyst.py)
  - Money Flow Index (in agents/quant_analyst.py)
  - Keltner Channels (in indicators.py)
  - MACD Divergence (in indicators.py)

**Missing entirely**:
  - Sector rotation / relative strength vs SPY
  - Market internals (advance/decline, breadth thrust, put/call ratio)
  - Earnings volatility expansion (data in sentiment_cache, not used)
  - Support/resistance levels (swing point detection)
  - Re-entry logic after stop hit

**What to build**:
  1. Wire existing signals into prediction.py scoring pipeline
  2. Add sector relative strength as a prediction factor
  3. Add market breadth as a regime filter (not just SPY SMA)
  4. Add momentum breakout strategy alongside mean reversion
  5. Validate each new signal via backtest before enabling

**Success Criteria**:
  1. Prediction engine uses >=6 signal types (up from 2 primary + 3 confirmation)
  2. Both mean reversion AND momentum breakout strategies produce predictions
  3. Market breadth data informs regime filtering
  4. Each signal's contribution to accuracy is tracked independently
  5. Backtest win rate >=60% across combined signal set

---

### v2.3 Trader Experience

#### Phase 12: Dashboard UX Overhaul
**Goal**: Restructure the dashboard around the trader's decision loop (scan -> predict -> decide -> trade -> monitor -> exit) instead of the current back-office analysis layout

**Depends on**: Phase 9 (dashboard split)

**Current problems** (from UX review):
  - No at-a-glance risk summary (positions, account delta, PDT remaining)
  - No one-click position exit — requires: Positions tab -> find row -> click button
  - Manual order entry hidden in slide-out panel
  - Intelligence tab conflates predictions, scans, heatmap, and backtesting
  - No trade fill notifications (toasts/banners)
  - Chart toolbar has ~15 buttons across 4 groups — overwhelming
  - 6-column metric card grid too cramped on mobile

**What to build**:
  1. **Risk banner** — Always-visible bar showing: open positions with P&L, net account delta, PDT trades remaining, daily loss used
  2. **One-click exit** — "Close" button on every position card/row, visible from any tab
  3. **Trade notifications** — Toast/banner when orders fill, with sound option
  4. **Simplified chart presets** — "Swing" preset (daily, SMA+BB+Vol) replaces 15 toolbar buttons
  5. **Decision flow** — Reorganize tabs: Today's Picks -> Chart -> Trade -> Positions -> History
  6. **Promote order entry** — Quick-buy button on prediction cards ("Buy 1 share of NVDA")
  7. **Mobile optimization** — Risk banner collapses to essentials, swipe to close positions

**Success Criteria**:
  1. PDT remaining and net P&L visible from every tab without clicking
  2. Any position can be closed in <=2 clicks from any screen
  3. Order fills produce visible notification within 2 seconds
  4. New user can understand what the bot recommends within 10 seconds of loading
  5. Mobile layout shows risk + top pick above the fold

---

#### Phase 13: Strategic PDT Management
**Goal**: The bot doesn't just check PDT — it reasons about whether to spend a trade now or save it for a higher-conviction setup later in the week

**Depends on**: Phase 10 (needs prediction accuracy data)

**Current state**: PDT is binary — "can I trade?" yes/no. No strategic reasoning about trade allocation across the week.

**What to build**:
  1. **Trade budget planner** — Show remaining trades + days until reset, with "conviction threshold escalation" (if 1 trade left, only take A-grade setups)
  2. **Opportunity cost display** — "You used 2/3 trades. Remaining trade reserved for setups scoring >=8.0"
  3. **Weekly review** — After PDT window resets, show: trades used, outcomes, what was skipped and what it did
  4. **Save-for-later queue** — If a B-grade setup fires on a day with 1 trade remaining, queue it and alert if it becomes A-grade tomorrow

**Success Criteria**:
  1. Bot adjusts conviction threshold based on remaining weekly trades
  2. Dashboard shows trade budget with explicit "save vs spend" recommendation
  3. Weekly retrospective shows trade allocation efficiency

---

### v3.0 Options & News

#### Phase 14: Options Trading
**Goal**: Add options chain analysis and order execution — calls for bullish signals, puts for bearish, with hard liquidity filters and options-specific exit rules

**Depends on**: Phase 11 (needs momentum/bearish signals for puts)

**Success Criteria**:
  1. Options chain fetch returns contracts with DTE 7-21, OI>100, spread<15%
  2. Contract selection picks closest OTM strike with adequate liquidity
  3. All options orders are LIMIT only — never MARKET
  4. Calls for bullish, puts for bearish, no exceptions
  5. Auto-close when premium drops 50%, rises 75%, or DTE<=3

---

#### Phase 15: Multi-Source News & Overnight Scanner
**Goal**: Aggregate news from Finnhub, RSS, SEC EDGAR, and FRED calendar. Run overnight scans to produce "Tomorrow's Game Plan" with approve/reject UI.

**Depends on**: Phase 12 (needs UX for approve/reject workflow)

**Success Criteria**:
  1. Finnhub news with rate-aware batching (60 calls/min)
  2. RSS feeds parsed (Google News, MarketWatch, Reuters)
  3. SEC EDGAR 8-K with compliant User-Agent
  4. FRED economic calendar (FOMC, CPI, NFP dates)
  5. Common news format with dedup and per-source TTL caching
  6. Post-market scan produces ranked "Tomorrow's Game Plan"
  7. Dashboard shows approve/reject per symbol, decisions persist and expire after 18h

---

### v3.1 AI & Reports

#### Phase 16: AI Market Analyst
**Goal**: Claude-powered analysis panel that gives plain-English market commentary and per-stock trade recommendations

**Depends on**: Phase 15 (needs multi-source news data)

**Success Criteria**:
  1. AI brief (2-4 sentences) analyzes trend, dominant sector, VIX, macro events
  2. Per-stock "What should I do?" gives buy/sell/hold/wait with reasoning
  3. Analysis updates every 15 minutes, cached, graceful fallback if API unavailable

---

#### Phase 17: PDF Report
**Goal**: Downloadable professional report with account summary, positions, trade history, metrics, and embedded charts

**Depends on**: Phase 16

**Success Criteria**:
  1. GET /api/report/pdf returns downloadable PDF
  2. Includes: account summary, open positions, last 50 trades, performance metrics
  3. Embedded price charts via matplotlib, generated in-memory, under 3 seconds

---

## Progress

| Phase | Milestone | Status | Completed |
|-------|-----------|--------|-----------|
| 1. Safety Infrastructure | v1.0 | :white_check_mark: Complete | 2026-03-28 |
| 2. Prediction Engine | v1.0 | :white_check_mark: Complete | 2026-03-30 |
| 6. Score Recalibration | v2.0 | :white_check_mark: Complete | 2026-04-08 |
| 7. Expanded Scanner | v2.0 | :white_check_mark: Complete | 2026-04-19 |
| **8. Critical Bug Fixes** | **v2.1** | **Not started** | -- |
| 9. Architecture Cleanup | v2.1 | Not started | -- |
| 10. Prediction Feedback Loop | 3/3 | Complete   | 2026-05-27 |
| 11. Signal Expansion | v2.2 | Not started | -- |
| 12. Dashboard UX Overhaul | v2.3 | Not started | -- |
| 13. Strategic PDT Management | v2.3 | Not started | -- |
| 14. Options Trading | v3.0 | Not started | -- |
| 15. Multi-Source News & Overnight | v3.0 | Not started | -- |
| 16. AI Market Analyst | v3.1 | Not started | -- |
| 17. PDF Report | v3.1 | Not started | -- |

## Dependency Graph

```
Phase 8 (Bug Fixes)
  └── Phase 9 (Architecture Cleanup)
        ├── Phase 10 (Feedback Loop)
        │     ├── Phase 11 (Signal Expansion)
        │     │     └── Phase 14 (Options Trading)
        │     └── Phase 13 (Strategic PDT)
        └── Phase 12 (UX Overhaul)
              └── Phase 15 (News & Overnight)
                    └── Phase 16 (AI Analyst)
                          └── Phase 17 (PDF Report)
```

## Blockers/Concerns

- **Phase 11**: Adding signals without feedback loop = noise. Must have Phase 10 first.
- **Phase 14**: Options on $500 account limits contracts to ~$1-2 premium. Liquidity will be thin.
- **Phase 15**: Finnhub free tier 60 calls/min. SEC EDGAR requires specific User-Agent.
- **Phase 15**: DST boundary timing — use Alpaca calendar API, not hardcoded times.
- **Phase 16**: Anthropic API cost. Cache aggressively, 15-min TTL minimum.

## Key Insight from Review

> The bot's current ~50% win rate comes from risk management (small positions, trailing stops), NOT from prediction accuracy. The prediction engine is well-structured but has critical bugs (dead veto, broken accuracy tracking, overwritten sizing) and relies almost entirely on mean reversion with arbitrary thresholds. Fixing the feedback loop (Phase 10) is the single highest-leverage improvement — without it, adding more signals just adds noise.
