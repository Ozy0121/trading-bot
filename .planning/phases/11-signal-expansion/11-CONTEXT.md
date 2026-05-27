# Phase 11: Signal Expansion - Context

**Gathered:** 2026-05-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Expand the prediction engine from 4 primary + 4 confirmation signals to a comprehensive multi-signal system. Wire in 5 existing-but-unused signals (VWAP, Stochastic RSI, MFI, Keltner Channels, MACD Divergence), add new signals (sector relative strength, support/resistance, re-entry logic), add market breadth regime filtering, and create a dual-path prediction architecture supporting both mean reversion AND momentum breakout strategies.

</domain>

<decisions>
## Implementation Decisions

### Signal Architecture
- **D-01:** All 5 existing-but-unused signals (VWAP, Stochastic RSI, MFI, Keltner Channels, MACD Divergence) are wired as **confirmation signals** — they boost score but do not gate entries. The 4 proven primary signals (RSI2, IBS, consec_down, BB lower) remain the entry gate requiring 2+ to fire.
- **D-02:** All new signals start with initial weight **0.5** in `DEFAULT_CONFIRM_BONUS`. Phase 10's weekly recalibration system will adjust weights based on actual accuracy data over 3-4 weeks. No manual weight tuning.
- **D-03:** Each new signal follows the existing `PatternResult` pattern — returns `(name, detected, score, category, details)`.

### Stochastic RSI Confirmation
- **D-04:** Detects Stochastic RSI < 0.10 as deeply oversold confirmation. Adapt calculation from `agents/quant_analyst.py:_calc_stochastic_rsi()`. When combined with RSI(2) < 10, documented bounce rate is 82%+. Initial weight: 0.5.

### Money Flow Index (MFI) Confirmation
- **D-05:** Detects MFI < 20 as selling exhaustion confirmation. Volume-weighted RSI confirms money is flowing out heavily before a bounce. Adapt from `agents/quant_analyst.py:_calc_mfi()`. Initial weight: 0.5.

### VWAP Confirmation
- **D-06:** Price below multi-day VWAP confirms discounted entry. Less useful for daily swing trading (designed for intraday), so starts with lowest weight (0.5). Adapt from `agents/quant_analyst.py:_calc_vwap()`.

### Keltner Channel Confirmation
- **D-07:** Price at or below lower Keltner Channel confirms extended volatility move. Uses ATR-based bands (vs BB's standard deviation). Partially redundant with BB lower touch but adds ATR context. Use existing `indicators.py:keltner_channels()`. Initial weight: 0.5.

### MACD Divergence Confirmation
- **D-08:** Bullish divergence (price makes new low, MACD histogram doesn't) is one of the strongest reversal confirmation signals. For momentum path: bearish divergence catches exhaustion. Must compute divergence from existing `indicators.py:macd()` output. Initial weight: 0.5.

### Momentum Breakout Strategy (Dual-Path)
- **D-09:** `prediction.py` gains a dual-path architecture: both mean-reversion and momentum analysis run for each symbol. Each path has its own primary signals and scoring. Final output picks the stronger setup or returns both if different symbols qualify.
- **D-10:** Momentum breakout definition: price breaking 20-day high on >1.5x average volume, with ADX > 25 confirming trend strength. Uses existing `strategies/momentum.py` logic as foundation.
- **D-11:** Momentum path primary signals: N-day high breakout, volume surge, ADX trend confirmation. Confirmation signals: MACD cross, Keltner upper breakout, relative sector strength.

### Sector Relative Strength
- **D-12:** Compute stock's sector ETF 20-day return vs SPY 20-day return. Positive spread = leading sector = full position sizing. Negative spread = lagging sector = reduced sizing. Sector ETF mapping: XLK (tech), XLE (energy), XLF (financials), XLV (healthcare), XLC (comms), XLI (industrial), XLY (consumer disc), XLP (consumer staples), XLU (utilities), XLRE (real estate), XLB (materials).
- **D-13:** Data source: yfinance (already in stack). Cache sector ETF bars daily to avoid repeated fetches.

### Market Breadth Regime Filter
- **D-14:** Breadth data adjusts **position sizing** (full / half / quarter) rather than blocking trades. Bad breadth = smaller positions, not zero positions. Mean reversion works best when markets are weak — hard gating would kill the best opportunities.
- **D-15:** Breadth signal: aggregate sector ETF performance. If majority of sector ETFs are down >2% over 5 days = weak breadth (half sizing). If majority down >5% = very weak (quarter sizing). Otherwise full sizing.
- **D-16:** Breadth check integrates into `_passes_regime_filter()` alongside existing SMA-200 and ADX checks.

### Support/Resistance Levels
- **D-17:** Swing point detection: identify local highs (resistance) and lows (support) over 20-bar lookback window. A local low is a bar whose low is lower than the 2 bars before and after it. Same logic inverted for highs.
- **D-18:** Use support levels for better stop-loss placement (stop below nearest support rather than fixed ATR). Use resistance levels for take-profit targets.
- **D-19:** Price near a support level is a confirmation signal for mean reversion entries (bouncing off known support). Initial weight: 0.5.

### Re-Entry After Stop Hit
- **D-20:** If a prediction's stop-loss was hit but primary signals are still firing (2+ primaries active), allow re-entry with tighter risk parameters: 50% position size, tighter stop (1.0 ATR vs 1.5 ATR).
- **D-21:** Maximum 1 re-entry per symbol per setup. If the second entry also stops out, the setup is invalidated.

### Signal Validation Approach
- **D-22:** No manual backtesting gate. All new signals start with weight 0.5 and Phase 10's weekly recalibration adjusts weights based on actual prediction accuracy over real data. This is genuinely data-driven rather than overfitting to historical backtests.
- **D-23:** Each new signal is tracked in `active_signals` so the recalibration system can compute per-signal accuracy from day one.

### Claude's Discretion
- Detection thresholds for each signal (e.g., exact Stoch RSI cutoff, MFI cutoff) — Claude calibrates based on what gives best separation between winning and losing setups
- Scoring curves within each signal detector (how to map raw indicator values to 0-10 scores)
- How to integrate MACD divergence detection (lookback window, minimum divergence threshold)
- Internal code organization — whether new detectors go in prediction.py or a separate signals.py module

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Prediction Pipeline
- `prediction.py` — Current prediction engine, PatternResult pattern, scoring architecture, regime filter
- `signal_calibration.py` — Recalibration system, signal_weights.json format, per-signal accuracy computation
- `prediction_log.py` — Prediction logging with active_signals field

### Existing Signal Implementations
- `agents/quant_analyst.py` — Stochastic RSI (`_calc_stochastic_rsi`), MFI (`_calc_mfi`), VWAP (`_calc_vwap`)
- `indicators.py` — Keltner Channels (`keltner_channels`), MACD (`macd`), RSI, Bollinger Bands
- `strategies/momentum.py` — Momentum breakout scanner (N-day high + volume)

### Configuration & Weights
- `data/signal_weights.json` — Calibrated signal weights file
- `config.py` — Trading configuration, watchlist, parameters

### Dashboard
- `templates/index.html` — Dashboard UI (prediction accuracy display from Phase 10)
- `routes/scanner.py` — Scanner API routes including signal weights endpoint

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `PatternResult` dataclass: All signal detectors return this — name, detected, score, category, details
- `agents/quant_analyst.py`: Has full implementations of Stochastic RSI, MFI, VWAP ready to adapt
- `indicators.py:keltner_channels()`: Fully implemented, returns upper/mid/lower channels
- `indicators.py:macd()`: Returns macd_line, signal_line, histogram — divergence detection builds on this
- `strategies/momentum.py:scan()`: Full momentum breakout detector with volume confirmation
- `signal_calibration.py`: Recalibration system auto-discovers signals from active_signals field

### Established Patterns
- Primary signals gate entries (need 2+ to fire), confirmation signals boost score
- `_detect_*()` functions return `PatternResult` with boolean detected, 0-10 score, and details dict
- `_load_weights()` reads from `data/signal_weights.json` with fallback to `DEFAULT_*` dicts
- Regime filter in `_passes_regime_filter()` returns (bool, reason, position_multiplier)

### Integration Points
- New confirmation detectors plug into `predict()` after line ~602 (confirmation layer)
- Momentum path needs a parallel entry point in `predict()` alongside the mean reversion path
- `DEFAULT_CONFIRM_BONUS` dict needs new signal keys
- `signal_calibration.py:SIGNALS` list needs new signal names for recalibration
- Sector ETF data needs caching alongside existing bar data fetching

</code_context>

<specifics>
## Specific Ideas

- Stochastic RSI < 0.10 combined with RSI(2) < 10 has documented 82%+ bounce rate — this is the highest-value new signal
- MACD divergence is the strongest reversal confirmation signal in quantitative trading literature — critical for both mean reversion (bullish divergence) and momentum (bearish divergence detection)
- Sector relative strength is a well-documented factor (Fama-French research) — stocks in leading sectors bounce faster and break out harder

</specifics>

<deferred>
## Deferred Ideas

- Market internals via advance/decline data (fragile scraping, better as a future enhancement with a paid data source)
- Earnings volatility expansion (data exists in sentiment_cache but integration is complex — separate phase)
- Put/call ratio as a sentiment overlay (requires options data feed)

</deferred>

---

*Phase: 11-signal-expansion*
*Context gathered: 2026-05-27*
