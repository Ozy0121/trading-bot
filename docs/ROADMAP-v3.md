# Roadmap v3 — High-Turnover Probabilistic Core

**Created:** 2026-08-01
**Supersedes:** the v2.x roadmap (phases 8–17). Phases 12–17 of that roadmap are cancelled.
**Status:** planning

---

## Why this is a rewrite and not a continuation

The v2 roadmap was built on a premise that no longer holds:

> Maximize the value of each of the 3 allowed trades per week by finding the highest-conviction
> swing trade setups.

With the PDT constraint lifted, rationing three trades a week is no longer the problem to solve.
That single change invalidates most of the design:

| v2 design choice | Existed because | Status now |
|---|---|---|
| Conviction threshold (5.8) + letter-grade cutoffs | Only 3 trades/week — reject everything but the best | Obsolete. Turnover is cheap; thin edges compound. |
| Single "best buy" per cycle | One shot, make it count | Obsolete. Breadth beats selectivity when turnover is free. |
| Phase 13 Strategic PDT Management | Allocating a scarce trade budget | Cancelled. |
| 1–3 day hold preference | PDT forced overnight holds | Obsolete. Hold time should be whatever the edge decays at. |
| 2-of-4 primary signal gate | Hard filter to force selectivity | To be replaced by an expected-value threshold. |

The bot flips from **high-conviction, low-frequency** to **many-small-edges, high-frequency**.
That is a different machine, and it fails in a different way: not by missing the one good trade,
but by bleeding out through costs and by breaking while unsupervised.

Those two failure modes set the order of everything below.

---

## The two things that decide whether this works

### 1. Costs, which are currently unmodelled

`backtester.py` applies no commission, no bid/ask spread, and no slippage. Every backtest run to
date reports gross returns as if fills were free at the close.

That error is proportional to turnover. At three trades a week it was a rounding error. At
day-trading frequency it is the entire result. A strategy that turns over the account daily on a
$500 balance pays the spread ~250 times a year; on options with a $0.30/$0.40 market that is a
28% round-trip haircut per trade.

**No strategy work is worth doing until the backtest tells the truth about costs.** This is
Phase 1, and it is the measuring stick for every phase after it.

### 2. Unattended operation, which is an ops problem, not an algorithm problem

"Leave for a week" means the failure modes are: process dies at 2am, WebSocket reconnects into a
stale state, a restart double-submits an order, local state disagrees with the broker, or a bug
grinds the account down with nobody watching. None of those are solved by a better predictor.

Honest framing: no design guarantees you return to profit. The guarantee worth engineering is
**bounded loss** — the account cannot be down more than the configured drawdown when you get back,
because the bot flattens and halts on its own. Phase 3 buys that guarantee.

---

## Standing constraints

| Constraint | Value | Notes |
|---|---|---|
| Capital | ~$500 | Paper for now |
| Turnover ceiling | **Detected at runtime** | Margin <$25k → PDT (3 day trades/5d). Cash → T+1 settlement + GFV rules. Never assumed. |
| Assets | Equities + options; crypto optional | Only crypto is genuinely 24/7 |
| Hard stop | 20% total drawdown | Flatten all, halt, alert |
| Mode | Alpaca paper | Live is a later, explicit decision |

**On the turnover ceiling:** with ~$500, PDT applies in a margin account by definition — the
account size *is* the trigger condition. It lifts only in a cash account, where T+1 settlement
and Good Faith Violation rules apply instead (3 GFVs in 12 months → 90-day settled-cash-only
restriction). The bot detects which regime is live from Alpaca's account object rather than
trusting a config flag, so it is correct under either and cannot get the account flagged by a
wrong assumption.

---

## Phases

### Phase 1 — Honest Measurement

**Goal:** A backtest that a high-turnover strategy can be trusted against, and a truthful baseline
for what the current engine actually does.

**Depends on:** nothing.

**Build:**
1. `costs.py` — per-fill cost model:
   - Equities: bid/ask spread (from quote data, not assumed), slippage as a function of order
     size vs. average volume, SEC + TAF fees on sells.
   - Options: spread as % of mid (the dominant cost), OCC clearing fee, ORF, per-contract
     regulatory fees.
   - A pessimistic and a realistic profile, so results are reported as a range.
2. Rebuild the backtest harness with **walk-forward** evaluation — train/select on a window,
   evaluate out-of-sample on the next, roll forward. No full-sample fitting.
3. Apply the cost model to every simulated fill.
4. Re-run the existing engine through it and publish the honest baseline.

**Resolve the contradiction:** `README.md` claims a 90% win rate on logged directional
predictions; the v2 roadmap's own review states ~50% and attributes it to risk management rather
than prediction. Determine which is true from `prediction_log.py` data and correct whichever
document is wrong.

**Success criteria:**
1. Every backtested fill is charged spread + slippage + fees.
2. Backtests are walk-forward; no in-sample selection reported as a result.
3. A written baseline: current engine's net-of-cost return, win rate, and turnover sensitivity.
4. The win-rate discrepancy is resolved with evidence.

**Gate:** If the current engine is net-negative after honest costs, that is a finding, not a
failure — it means the edge was never there and the rebuild is justified rather than optional.

---

### Phase 2 — Turnover Governor & Risk Rails

**Goal:** The bot cannot exceed its real regulatory ceiling, and cannot lose more than the
configured bound, regardless of what the strategy layer asks for.

**Depends on:** nothing (parallel with Phase 1).

**Build:**
1. `governor.py` — detects account regime from Alpaca (`pattern_day_trader`, `daytrade_count`,
   cash vs margin, settled funds) and enforces the live ceiling:
   - Margin <$25k → day-trade budget, same as today's PDT logic.
   - Cash → settled-cash tracker; block buys that would use unsettled proceeds; count and warn on
     GFV risk before it happens.
2. Two-tier circuit breakers:
   - Daily loss limit → stop opening positions, keep managing open ones.
   - **20% total drawdown from high-water mark → flatten everything, halt, alert.**
3. Order idempotency via deterministic `client_order_id`, so a restart mid-submit cannot
   double-fill.
4. Portfolio-level exposure caps: max concurrent positions, max % in one symbol, max gross
   exposure — none of which exist today.

**Migrate, don't duplicate:** `safety.py` already has trailing stops, OCO exits, the protection
monitor, and kill switch. Those stay. The PDT-specific functions become one regime inside the
governor.

**Success criteria:**
1. Regime is detected at runtime, never assumed from config.
2. Cash-account mode blocks unsettled-funds buys and never generates a GFV.
3. 20% drawdown triggers flatten + halt + alert, verified by fault injection.
4. Restarting mid-order-submit produces exactly one order.

---

### Phase 3 — Unattended Operation

**Goal:** Survives a week alone, and reaches you if it can't.

**Depends on:** Phase 2.

**Build:**
1. Supervisor process with auto-restart and exponential backoff.
2. **Boot-time reconciliation:** on every start, the broker is the source of truth. Rebuild local
   state from Alpaca positions and orders; never trust the local state file where they disagree.
   (Today `safety.py` loads state from disk on boot with no reconciliation.)
3. Stale-data watchdog: no bars during market hours for N minutes → halt trading, alert.
4. Heartbeat + alerting (push/email/Telegram): daily summary, plus immediate alert on circuit
   breaker, crash loop, or reconciliation mismatch.
5. Remote read-only status page so you can check in from a phone.
6. Market calendar via Alpaca's API, not hardcoded clock times — DST-safe.

**Success criteria:**
1. `kill -9` at any point recovers to correct state with no duplicate or orphaned orders.
2. A 7-day unattended paper run completes with no manual intervention.
3. Every halt condition produces an alert within 60 seconds.
4. Killing the network for 10 minutes mid-session recovers cleanly.

**Gate:** A clean 7-day paper run is required before any live-money discussion.

---

### Phase 4 — Kronos Forecasting Core

**Goal:** Replace the hand-tuned scoring layer with a sampled distribution over future price
paths.

**Depends on:** Phase 1 (needs the cost model to be evaluable).

**Approach:** [Kronos](https://github.com/shiyu-coder/Kronos) (AAAI 2026, MIT) is a decoder-only
foundation model over OHLCV candlesticks — a Binary Spherical Quantizer discretizes K-lines into
hierarchical tokens, and a GPT-style transformer pretrained on 12B+ bars from 45+ exchanges
predicts them autoregressively. Kronos-small is 24.7M params, base is 102.3M, context 512 bars.

The useful property is not raw accuracy — it is that the model is **generative**. Sampling yields
N complete simulated OHLCV futures, i.e. a distribution, which is the object the current scoring
layer has been crudely approximating all along.

**Build:**
1. `kronos_engine.py` — model loading, batched sampling, caching. Works on both daily bars (swing)
   and 5-minute bars (intraday), since context is 512 bars of any interval.
2. `mc_bracket.py` — the core algorithm. For a candidate symbol:
   - Sample N≈64 paths over the intended horizon.
   - For each path, **simulate the exact bracket order the bot would place** — entry, stop,
     target, time exit — walking the path bar by bar. If a bar touches both stop and target,
     assume stop first (conservative).
   - **Charge Phase 1's cost model to every simulated fill.**
   - Aggregate to: `EV`, `p_win`, `CVaR₅`, `P(target before stop)`.
   - Rank by `EV / |CVaR₅|` — return per unit of tail risk.
3. **Per-trade bracket optimization:** re-simulating a different (stop, target) pair on paths you
   already have is nearly free. Grid-search a small set, pick the bracket maximizing EV/CVaR for
   this symbol today. This replaces the global `TRAILING_STOP_PCT` / `TAKE_PROFIT_PCT` constants
   with per-trade optima.
4. Measure inference cost on the actual machine; drop to Kronos-mini (4.1M) if the overnight and
   intraday budgets don't fit.

**Success criteria:**
1. N paths for ~50 symbols complete inside the scan budget on real hardware.
2. EV is expressed net of costs, in units comparable across symbols and asset classes.
3. Optimal bracket per candidate, not a global constant.

---

### Phase 5 — The Bake-Off

**Goal:** Find out whether any of this is better than what exists. This is the decision point.

**Depends on:** Phases 1 and 4.

**Build:** Walk-forward comparison over 2+ years on the same universe and candidate set:

| Arm | What it is |
|---|---|
| A | Current engine's ranking |
| B | Kronos EV/CVaR ranking |
| C | Random selection from the same survivors |
| D | Buy-and-hold SPY |

Report net-of-cost return, Sharpe, max drawdown, hit rate, and turnover sensitivity for each.
Arm C is not a joke — it establishes how much of any result is selection versus risk management,
which is the exact question the v2 review raised and never answered.

**Gate — the honest one:** Kronos must beat the current engine *and* random selection,
out-of-sample, net of costs. If it doesn't, we stop and the finding is that the edge is in the
risk layer. Everything downstream is conditional on passing this.

**Calibration, not just accuracy:** because the output is now a probability, track Brier score and
a reliability diagram — when it says 62%, does it happen 62% of the time? If systematically
overconfident, fit isotonic regression on logged outcomes. This is a principled replacement for
`signal_calibration.py`, and reuses the logging already built in Phase 10 of v2.

**Realistic expectation:** Kronos's headline "+93% RankIC" is *relative* to another foundation
model. Absolute cross-sectional IC in this literature typically lands 0.02–0.10 — a real but thin
*ranking* edge, not high directional accuracy. The repo states its own pipeline is "a
demonstration… not a production-ready quantitative trading system." Plan for a small edge that
needs low costs and many trades to compound, which is exactly why Phase 1 comes first.

---

### Phase 6 — Breadth & Multi-Horizon Execution

**Goal:** Exploit the lifted turnover constraint — trade many small edges concurrently instead of
one best pick per cycle.

**Depends on:** Phase 5 passing.

**Build:**
1. Portfolio construction: take every candidate above an EV threshold, sized by conviction and
   capped by Phase 2's exposure limits — replacing "single best buy."
2. Two horizons from one model: intraday (5-min bars, same-session exits) and swing (daily bars,
   multi-day), each with its own EV threshold, both governed by the same turnover ceiling.
3. Hold time chosen by measured edge decay rather than the inherited 1–3 day preference.
4. Correlation awareness — avoid five positions that are the same bet on one sector.

**Success criteria:**
1. Multiple concurrent positions within exposure caps.
2. Both horizons live, sharing one governor and one risk budget.
3. Position count and turnover respond to opportunity, not a fixed schedule.

---

### Phase 7 — Options on Sampled Paths

**Goal:** Trade options where the math actually supports it, and prove where it doesn't.

**Depends on:** Phase 6.

**The elegant part:** Kronos forecasts the *underlying*. Price the option along each of the N
simulated underlying paths (Black-Scholes with IV from the live chain), apply exit rules per path,
and the option's EV distribution falls out directly — handling the nonlinearity correctly instead
of approximating it.

**The honest part:** this will show that most cheap contracts on a $500 account are
negative-EV once the spread is charged. A $0.30/$0.40 market is a ~28% round-trip haircut; almost
no edge survives it. That is a feature of the analysis, not a flaw — it tells you which contracts
are tradeable rather than assuming they all are.

**Build:** chain fetch with hard liquidity filters (OI, spread % of mid, DTE window), path-based
option pricing, limit orders only — never market — and options-specific exits.

**Success criteria:**
1. Options EV computed from sampled underlying paths, net of real spread.
2. Hard liquidity gate rejects contracts whose spread eats the edge.
3. All options orders are limit orders.
4. Backtest demonstrates options add net value over the equity-only strategy, or they stay off.

---

### Phase 8 — Simplification

**Goal:** Delete what Kronos subsumed. This is the "it's too complicated" phase, done last —
after evidence, not before.

**Depends on:** Phase 5 passing and Phase 6 running.

**Method — prune empirically, not by taste.** Regress realized outcomes on
`[kronos_ev, rsi2, ibs, cvd_divergence, stoch_rsi, mfi, …]`. Any signal whose coefficient is
indistinguishable from zero *given* Kronos EV adds no information and goes. Any that survives has
earned its place. `active_signals` is already logged, so the data collection exists.

**Expected removals:** `DEFAULT_CONFIRM_BONUS` weight tables, the weekly weight-nudging job, the
2-of-4 primary gate, dual-path MR/momentum routing, letter-grade cutoffs, `tune_prediction.py`,
and most hand-tuned thresholds.

**Expected keeps:** `safety.py`, the scanner cascade, the data layer, the dashboard, catalyst and
sentiment as an override/veto (Kronos sees only OHLCV — it cannot know about earnings dates or
halts).

**Also rewrite `CLAUDE.md`.** Its stated core value, PDT constraints, and hold-time preference all
describe a bot that no longer exists.

---

## Optional track — Crypto

Only crypto is genuinely 24/7, and Kronos's pretraining corpus is heavily weighted toward exchange
K-lines, so zero-shot transfer is plausibly stronger there than on US equity dailies. No PDT, no
settlement constraint. If literal around-the-clock operation matters more than asset familiarity,
this becomes the primary track rather than an extension — worth revisiting after Phase 5 tells us
how well the model transfers.

---

## Dependency graph

```
Phase 1 (Honest Measurement) ─┬─→ Phase 4 (Kronos Core) ──→ Phase 5 (Bake-Off) ─┬─→ Phase 6 (Breadth)
                              │                                   │             │        └──→ Phase 7 (Options)
Phase 2 (Governor & Rails) ───┘                                   │             └──→ Phase 8 (Simplification)
      └──→ Phase 3 (Unattended Ops)                          [HARD GATE]
```

Phases 1 and 2 are independent and can run in parallel. Phase 5 is a hard gate: phases 6–8 are
conditional on it passing.

---

## Progress

| Phase | Status | Gate |
|---|---|---|
| 1. Honest Measurement | Not started | Costs charged, walk-forward, baseline published |
| 2. Turnover Governor & Risk Rails | Not started | Regime detected; 20% breaker verified by fault injection |
| 3. Unattended Operation | Not started | Clean 7-day paper run, no intervention |
| 4. Kronos Forecasting Core | Not started | Inference fits budget; EV net of costs |
| 5. The Bake-Off | Not started | **Beats current engine AND random, out-of-sample** |
| 6. Breadth & Multi-Horizon | Not started | — |
| 7. Options on Sampled Paths | Not started | — |
| 8. Simplification | Not started | — |

## Carried-over debt (from v2, still open)

These predate this roadmap and remain unfixed in `prediction.py` and friends. They only matter if
Phase 5 fails and the current engine stays the primary — but the Phase 1 baseline should be
measured against a working engine, so the dual-path fix is worth doing first regardless.

1. **Dual-path momentum is dead code.** `prediction.py:848` calls `_predict_momentum()` *after*
   the mean-reversion gate at line 635, so a momentum-only setup returns `None` before the
   momentum path runs. The merge at line 851 is unreachable. A written gap-closure plan
   (`11-04-PLAN.md`) was never executed.
2. `prediction_signals.py:160` — Stoch RSI score discontinuity at the 0.05 boundary.
3. `yf_limiter.py:240` — TOCTOU race in `get_sector_cached`.
4. `prediction_signals.py:470` — `down_2pct` holds only the −5%..−2% band; correct but misleading.
5. `volume_profile.py:151` — `_compute_value_area` divides by `total` with no internal guard.
6. `yf_limiter.py:267` — `flush_sector_cache()` is defined but never called; the sector cache
   loses up to 49 entries on every shutdown.
