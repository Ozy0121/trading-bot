# Phase 11: Signal Expansion - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-27
**Phase:** 11-signal-expansion
**Areas discussed:** Signal wiring priority, Momentum breakout strategy, Market breadth regime filter, Signal validation approach

---

## Signal Wiring Priority

### Signal Role
| Option | Description | Selected |
|--------|-------------|----------|
| All as confirmation signals (Recommended) | Add all 5 as confirmation/bonus signals. Keeps proven primary gate intact. | ✓ |
| Mix: some primary, some confirmation | Promote 1-2 strong signals to primary status. More entries but more noise. | |
| Start all with low weight, let recalibration decide | Add all as confirmation with weight 0.5. Phase 10 recalibration adjusts. | |

**User's choice:** All as confirmation signals
**Notes:** User agreed that keeping the proven primary gate (2+ of RSI2/IBS/consec_down/BB must fire) is the safest approach.

### Scope
| Option | Description | Selected |
|--------|-------------|----------|
| Wire existing + add sector rotation only (Recommended) | Wire 5 existing signals plus sector relative strength. | |
| Wire existing only | Just the 5 signals already coded. | |
| Wire existing + all missing signals | Full scope: sector rotation, market breadth, support/resistance, re-entry logic. | ✓ |

**User's choice:** Wire existing + all missing signals
**Notes:** User chose full scope to complete the phase entirely.

---

## Momentum Breakout Strategy

### Strategy Coexistence
| Option | Description | Selected |
|--------|-------------|----------|
| Dual-path prediction (Recommended) | Both mean-reversion and momentum run for each symbol. Each has own scoring. | ✓ |
| Strategy router | Regime detector picks one strategy based on market conditions. | |
| Separate prediction files | Keep prediction.py for MR, create prediction_momentum.py for breakouts. | |

**User's choice:** Dual-path prediction
**Notes:** N/A

### Breakout Definition
| Option | Description | Selected |
|--------|-------------|----------|
| Price + volume breakout (Recommended) | Price breaking N-day high on >1.5x volume, ADX > 25 confirming trend. | ✓ |
| Multi-signal momentum | Combine price breakout + MACD cross + Stoch RSI + Keltner breakout. | |
| You decide | Claude picks based on available signals and literature. | |

**User's choice:** Price + volume breakout
**Notes:** Uses existing strategies/momentum.py as foundation.

---

## Market Breadth Regime Filter

**User delegated all decisions to Claude.** Rationale: "I don't know anything about stocks or how to analyze. I want you to decide — make sure you're thinking things through for highest win rate."

### Claude's Researched Decisions

**Breadth mode:** Sizing adjustment (not hard gate). Mean reversion performs better during market weakness — hard gating kills best opportunities. Reduced sizing manages risk without missing setups.

**Data source:** Sector ETF relative strength via yfinance. Free, reliable, already in stack. Scraping advance/decline is fragile.

---

## Signal Validation Approach

**User delegated to Claude.** Same rationale as above.

### Claude's Researched Decision

**Approach:** Add all new signals with initial weight 0.5, let Phase 10 recalibration system adjust based on real accuracy data. Avoids overfitting to historical backtests. Genuinely data-driven.

---

## Claude's Discretion

- Detection thresholds for each signal
- Scoring curves (raw indicator value → 0-10 score mapping)
- MACD divergence detection parameters
- Internal code organization

## Deferred Ideas

- Market internals via advance/decline data (fragile scraping)
- Earnings volatility expansion (complex integration)
- Put/call ratio as sentiment overlay (needs options data feed)
