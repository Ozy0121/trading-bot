# Phase 11: Signal Expansion - Research

**Researched:** 2026-05-27
**Domain:** Quantitative signal integration, dual-path prediction architecture, sector relative strength
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Signal Architecture**
- D-01: All 5 existing-but-unused signals (VWAP, Stochastic RSI, MFI, Keltner Channels, MACD Divergence) are wired as confirmation signals — they boost score but do not gate entries. The 4 proven primary signals (RSI2, IBS, consec_down, BB lower) remain the entry gate requiring 2+ to fire.
- D-02: All new signals start with initial weight 0.5 in DEFAULT_CONFIRM_BONUS. Phase 10's weekly recalibration system will adjust weights based on actual accuracy data over 3-4 weeks. No manual weight tuning.
- D-03: Each new signal follows the existing PatternResult pattern — returns (name, detected, score, category, details).

**Stochastic RSI Confirmation**
- D-04: Detects Stochastic RSI < 0.10 as deeply oversold confirmation. Adapt calculation from agents/quant_analyst.py:_calc_stochastic_rsi(). When combined with RSI(2) < 10, documented bounce rate is 82%+. Initial weight: 0.5.

**Money Flow Index (MFI) Confirmation**
- D-05: Detects MFI < 20 as selling exhaustion confirmation. Volume-weighted RSI confirms money is flowing out heavily before a bounce. Adapt from agents/quant_analyst.py:_calc_mfi(). Initial weight: 0.5.

**VWAP Confirmation**
- D-06: Price below multi-day VWAP confirms discounted entry. Less useful for daily swing trading (designed for intraday), so starts with lowest weight (0.5). Adapt from agents/quant_analyst.py:_calc_vwap().

**Keltner Channel Confirmation**
- D-07: Price at or below lower Keltner Channel confirms extended volatility move. Uses ATR-based bands (vs BB's standard deviation). Partially redundant with BB lower touch but adds ATR context. Use existing indicators.py:keltner_channels(). Initial weight: 0.5.

**MACD Divergence Confirmation**
- D-08: Bullish divergence (price makes new low, MACD histogram doesn't) is one of the strongest reversal confirmation signals. For momentum path: bearish divergence catches exhaustion. Must compute divergence from existing indicators.py:macd() output. Initial weight: 0.5.

**Momentum Breakout Strategy (Dual-Path)**
- D-09: prediction.py gains a dual-path architecture: both mean-reversion and momentum analysis run for each symbol. Each path has its own primary signals and scoring. Final output picks the stronger setup or returns both if different symbols qualify.
- D-10: Momentum breakout definition: price breaking 20-day high on >1.5x average volume, with ADX > 25 confirming trend strength. Uses existing strategies/momentum.py logic as foundation.
- D-11: Momentum path primary signals: N-day high breakout, volume surge, ADX trend confirmation. Confirmation signals: MACD cross, Keltner upper breakout, relative sector strength.

**Sector Relative Strength**
- D-12: Compute stock's sector ETF 20-day return vs SPY 20-day return. Positive spread = leading sector = full position sizing. Negative spread = lagging sector = reduced sizing. Sector ETF mapping: XLK (tech), XLE (energy), XLF (financials), XLV (healthcare), XLC (comms), XLI (industrial), XLY (consumer disc), XLP (consumer staples), XLU (utilities), XLRE (real estate), XLB (materials).
- D-13: Data source: yfinance (already in stack). Cache sector ETF bars daily to avoid repeated fetches.

**Market Breadth Regime Filter**
- D-14: Breadth data adjusts position sizing (full / half / quarter) rather than blocking trades. Bad breadth = smaller positions, not zero positions.
- D-15: Breadth signal: aggregate sector ETF performance. If majority of sector ETFs are down >2% over 5 days = weak breadth (half sizing). If majority down >5% = very weak (quarter sizing). Otherwise full sizing.
- D-16: Breadth check integrates into _passes_regime_filter() alongside existing SMA-200 and ADX checks.

**Support/Resistance Levels**
- D-17: Swing point detection: identify local highs (resistance) and lows (support) over 20-bar lookback window. A local low is a bar whose low is lower than the 2 bars before and after it. Same logic inverted for highs.
- D-18: Use support levels for better stop-loss placement (stop below nearest support rather than fixed ATR). Use resistance levels for take-profit targets.
- D-19: Price near a support level is a confirmation signal for mean reversion entries (bouncing off known support). Initial weight: 0.5.

**Re-Entry After Stop Hit**
- D-20: If a prediction's stop-loss was hit but primary signals are still firing (2+ primaries active), allow re-entry with tighter risk parameters: 50% position size, tighter stop (1.0 ATR vs 1.5 ATR).
- D-21: Maximum 1 re-entry per symbol per setup. If the second entry also stops out, the setup is invalidated.

**Signal Validation Approach**
- D-22: No manual backtesting gate. All new signals start with weight 0.5 and Phase 10's weekly recalibration adjusts weights based on actual prediction accuracy over real data.
- D-23: Each new signal is tracked in active_signals so the recalibration system can compute per-signal accuracy from day one.

### Claude's Discretion
- Detection thresholds for each signal (e.g., exact Stoch RSI cutoff, MFI cutoff) — Claude calibrates based on what gives best separation between winning and losing setups
- Scoring curves within each signal detector (how to map raw indicator values to 0-10 scores)
- How to integrate MACD divergence detection (lookback window, minimum divergence threshold)
- Internal code organization — whether new detectors go in prediction.py or a separate signals.py module

### Deferred Ideas (OUT OF SCOPE)
- Market internals via advance/decline data (fragile scraping, better as a future enhancement with a paid data source)
- Earnings volatility expansion (data exists in sentiment_cache but integration is complex — separate phase)
- Put/call ratio as a sentiment overlay (requires options data feed)

</user_constraints>

---

## Summary

Phase 11 expands the prediction engine from a single mean-reversion path to a comprehensive dual-path system. All 5 existing-but-unwired signals already exist as working Python implementations in `agents/quant_analyst.py` and `indicators.py` — this phase is fundamentally a wiring exercise with careful architecture decisions, not an implementation-from-scratch effort. The primary risk is not code complexity but scoring coherence: the momentum path must not pollute the mean-reversion scoring system, and the new confirmation signals must integrate cleanly with the existing `DEFAULT_CONFIRM_BONUS` dict and `signal_calibration.py` auto-discovery.

The sector relative strength system (D-12/D-13) has an existing caching foundation in `yf_limiter.py` via `get_sector_cached()`, but that returns a string label, not ETF bars. A new `get_sector_etf_bars()` function caching bar DataFrames is needed. The 11 sector ETF tickers map directly to yfinance symbols and go through `fetch_bars()` already in the data_provider layer.

The critical architectural decision for the planner is module organization: where do the new `_detect_*` functions live? Putting all 5 new confirmation detectors and the momentum path logic into `prediction.py` will push it to ~1500+ lines. A dedicated `prediction_signals.py` (or `signals.py`) module that `prediction.py` imports is the standard approach for this scale.

**Primary recommendation:** Create `prediction_signals.py` as the new home for all signal detector functions. The `predict()` function in `prediction.py` stays as the orchestrator — it calls into `prediction_signals.py`. This keeps the main predict() function readable while allowing each signal implementation to grow independently.

---

## Standard Stack

### Core (already installed, verified in codebase)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | >=2.0.0 | Series/DataFrame for signal computation | Already used throughout; all indicator functions take pd.Series |
| numpy | >=1.24.0 | Array ops for divergence detection | Required for np.sign, roll ops in quant_analyst.py |
| yfinance | latest | Sector ETF bar fetching (via data_provider) | Already in stack with rate limiter; fetch_bars() handles it |

[VERIFIED: codebase grep — all packages already imported in production files]

### No new dependencies required
All signal implementations (Stochastic RSI, MFI, VWAP, Keltner Channels, MACD divergence) use only pandas and numpy, which are already installed. The sector ETF data goes through the existing `fetch_bars()` / `get_spy_history()` pattern in `yf_limiter.py`.

**Installation:** No new packages needed.

---

## Architecture Patterns

### Recommended Module Structure

```
prediction.py               # orchestrator — predict(), predict_batch() stay here
prediction_signals.py       # NEW: all _detect_*() functions (existing + new)
yf_limiter.py               # ADD: get_sector_etf_bars() alongside get_spy_history()
signal_calibration.py       # UPDATE: DEFAULT_PRIMARY/DEFAULT_CONFIRM to include new signals
data/signal_weights.json    # UPDATE: new confirm signal keys initialized to 0.5
```

[VERIFIED: codebase inspection — prediction.py is already 872 lines; adding 5+ detectors + dual-path pushes it to ~1400+ lines without extraction]

### Pattern 1: Signal Detector Functions (existing pattern, extend it)

Every detector in `prediction.py` follows this exact signature and return:

```python
# Source: prediction.py lines 188-327
def _detect_stoch_rsi(df: pd.DataFrame) -> PatternResult:
    """Stochastic RSI < 0.10 deeply oversold — adapted from agents/quant_analyst.py."""
    closes = df["close"]
    if len(closes) < 28:   # needs RSI(14) + stoch(14) window
        return PatternResult("stoch_rsi", False, 0.0, "momentum")

    rsi_series = calc_rsi(closes, period=14)
    rsi_clean = rsi_series.dropna()
    period = 14
    rsi_min = rsi_clean.rolling(period).min()
    rsi_max = rsi_clean.rolling(period).max()
    denom = rsi_max - rsi_min
    stoch = (rsi_clean - rsi_min) / denom.replace(0, np.nan)
    stoch_val = float(stoch.dropna().iloc[-1]) if len(stoch.dropna()) > 0 else 0.5

    detected = stoch_val < 0.10
    if stoch_val < 0.05:
        score = 10.0
    elif stoch_val < 0.10:
        score = 8.0 - (stoch_val - 0.05) * 40.0
    elif stoch_val < 0.20:
        score = 4.0 - (stoch_val - 0.10) * 20.0
    else:
        score = 0.0

    return PatternResult("stoch_rsi", detected, round(score, 1), "momentum",
                         {"stoch_rsi_value": round(stoch_val, 4)})
```

### Pattern 2: MACD Divergence Detection

MACD divergence requires comparing price lows to MACD histogram troughs over a lookback window. The algorithm: find local price minima in the last N bars, find corresponding MACD histogram values, check if price made lower low while MACD made higher low (bullish divergence).

```python
# Source: derived from indicators.py:macd() — ASSUMED pattern for divergence
def _detect_macd_divergence(df: pd.DataFrame, lookback: int = 20) -> PatternResult:
    """Bullish MACD divergence: price lower low, histogram higher low."""
    closes = df["close"]
    if len(closes) < lookback + 30:
        return PatternResult("macd_divergence", False, 0.0, "momentum")

    _, _, histogram = macd(closes)
    hist = histogram.dropna()
    if len(hist) < lookback:
        return PatternResult("macd_divergence", False, 0.0, "momentum")

    # Last N bars
    price_window = closes.iloc[-lookback:]
    hist_window = hist.iloc[-lookback:]

    # Find the two lowest price points in window
    price_min_idx = price_window.idxmin()
    price_second_min = price_window.drop(price_min_idx).idxmin()

    # Compare corresponding MACD histogram values
    price_made_lower_low = float(price_window[price_min_idx]) < float(price_window[price_second_min])
    hist_made_higher_low = float(hist_window[price_min_idx]) > float(hist_window[price_second_min])

    detected = price_made_lower_low and hist_made_higher_low
    score = 8.0 if detected else 0.0

    return PatternResult("macd_divergence", detected, score, "momentum",
                         {"divergence": detected})
```

[ASSUMED — Claude will refine lookback window and detection logic based on false-positive rate during implementation]

### Pattern 3: Dual-Path Prediction Architecture

The `predict()` function gains a parallel path. Both paths run, the stronger result (by confidence score) is returned. If both fire, they're returned separately:

```python
# Source: prediction.py structure — proposed extension
def predict(symbol, df, sector_etf="SPY", spy_df=None) -> Prediction | None:
    # ... existing mean-reversion path ...

    # NEW: momentum path runs in parallel
    momentum_result = _predict_momentum(symbol, df, spy_df)

    # Return higher-confidence result
    if momentum_result and not mean_rev_result:
        return momentum_result
    if mean_rev_result and not momentum_result:
        return mean_rev_result
    if both_fire:
        return max(mean_rev_result, momentum_result, key=lambda p: p.confidence)
```

[VERIFIED: prediction.py lines 561-756 — existing mean-reversion path structure; momentum path mirrors this]

### Pattern 4: Sector ETF Caching

Extend `yf_limiter.py` alongside the existing `get_spy_history()` pattern:

```python
# Source: yf_limiter.py lines 91-118 (get_spy_history pattern)
_sector_etf_cache: dict[str, tuple[date, pd.DataFrame]] = {}
_sector_etf_lock = threading.Lock()

SECTOR_ETF_MAP = {
    "XLK": "Technology", "XLE": "Energy", "XLF": "Financials",
    "XLV": "Healthcare", "XLC": "Communication Services",
    "XLI": "Industrials", "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples", "XLU": "Utilities",
    "XLRE": "Real Estate", "XLB": "Materials",
}

def get_sector_etf_bars(etf: str, period: str = "30d") -> pd.DataFrame | None:
    """Fetch sector ETF bars, cached daily. Same pattern as get_spy_history()."""
    today = date.today()
    with _sector_etf_lock:
        cached = _sector_etf_cache.get(etf)
        if cached and cached[0] == today:
            return cached[1].copy()
    try:
        df = rate_limited_yf(lambda: yf.Ticker(etf).history(period=period, interval="1d"))
        if df is None or df.empty:
            return None
        df.columns = [c.lower() for c in df.columns]
        with _sector_etf_lock:
            _sector_etf_cache[etf] = (today, df)
        return df.copy()
    except Exception as exc:
        log.warning("[yf_limiter] Sector ETF %s fetch failed: %s", etf, exc)
        return None
```

[VERIFIED: yf_limiter.py lines 86-118 — get_spy_history() is the exact template to copy]

### Pattern 5: Swing Point Support/Resistance Detection

```python
# Source: D-17 from CONTEXT.md — local minima/maxima algorithm
def _find_swing_lows(df: pd.DataFrame, lookback: int = 20, n: int = 2) -> list[float]:
    """Find local lows where low[i] < low[i-n] and low[i] < low[i+n]."""
    lows = df["low"].values
    swing_lows = []
    for i in range(n, len(lows) - n):
        if all(lows[i] < lows[i-j] for j in range(1, n+1)) and \
           all(lows[i] < lows[i+j] for j in range(1, n+1)):
            swing_lows.append(float(lows[i]))
    return sorted(swing_lows)[-lookback:]  # keep most recent
```

[ASSUMED — exact n-bar window and lookback depth Claude will tune during implementation]

### Pattern 6: Breadth Regime Integration

The existing `_passes_regime_filter()` returns `(bool, str, float)`. The breadth multiplier feeds into the existing `position_mult` float:

```python
# Source: prediction.py lines 373-414 — _passes_regime_filter() structure
def _passes_regime_filter(df, spy_df=None):
    # ... existing SMA-200, ADX, SPY checks ...

    # NEW: breadth check at the end
    breadth_mult = _compute_breadth_multiplier()  # 1.0 / 0.5 / 0.25
    position_mult *= breadth_mult

    return True, f"SMA({sma_period}) OK, ADX {adx:.0f}{spy_note}", position_mult
```

[VERIFIED: prediction.py lines 373-414 — position_mult is computed additively; breadth multiplier plugs in cleanly]

### Pattern 7: Re-Entry Tracking

Re-entry state must survive across prediction cycles. A simple module-level dict keyed by symbol works within the existing pattern:

```python
# Source: prediction.py _hist_cache pattern (lines 140-141)
_reentry_tracker: dict[str, dict] = {}
# {symbol: {"stop_hit": True, "reentry_count": 1, "stop_hit_date": "2026-05-27"}}
```

[VERIFIED: prediction.py line 140 — _hist_cache uses same thread-unsafe dict pattern (acceptable for single-threaded predict() calls)]

### Anti-Patterns to Avoid

- **Putting momentum path results into mean-reversion active_signals:** The `_log_predictions()` function already logs `source="mean_reversion"`. Momentum predictions must use `source="momentum_breakout"` so signal_calibration can separate accuracy by strategy.
- **Fetching sector ETF bars inside predict():** `predict()` can be called in ThreadPoolExecutor (predict_batch). Sector ETF bars must be pre-fetched and passed in (like spy_df) or read from cache.
- **Adding new signal names to signal_calibration.py DEFAULT_PRIMARY:** New signals are confirmation signals only. They belong in `DEFAULT_CONFIRM`, not `DEFAULT_PRIMARY`.
- **Using `all_signals = list(DEFAULT_PRIMARY) + list(DEFAULT_CONFIRM)` without updating it:** signal_calibration.py line 194 hardcodes `all_signals` from the two dicts. Adding new keys to DEFAULT_CONFIRM automatically includes them — but the dicts in signal_calibration.py must match the dicts in prediction.py exactly.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Stochastic RSI calculation | Custom RSI normalization | Copy `_calc_stochastic_rsi()` from agents/quant_analyst.py | Already tested, handles edge cases |
| MFI calculation | Custom money flow formula | Copy `_calc_mfi()` from agents/quant_analyst.py | Correct typical price / positive flow formula already implemented |
| VWAP calculation | Custom cumulative avg | Copy `_calc_vwap()` from agents/quant_analyst.py | Handles cumsum division by zero with .replace() |
| Keltner Channel bounds | Hand-rolled EMA+ATR | `indicators.py:keltner_channels()` | Already returns (upper, mid, lower) tuple |
| MACD values | Recompute MACD | `indicators.py:macd()` which returns (macd_line, signal_line, histogram) | One call, three series returned |
| Sector ETF daily cache | Per-call yfinance fetch | Extend `yf_limiter.get_spy_history()` pattern | Rate limiter already handles yfinance throttling |
| ADX for momentum confirmation | Recompute ADX | `prediction.py:_compute_adx()` already exists | Can be imported or called directly |

**Key insight:** 4 out of 5 "new" signals are literally copy-paste from agents/quant_analyst.py with PatternResult wrapping. The implementation work is the wiring and the dual-path architecture, not the math.

---

## Common Pitfalls

### Pitfall 1: signal_calibration.py DEFAULT_CONFIRM Drift
**What goes wrong:** New signals added to `DEFAULT_CONFIRM_BONUS` in `prediction.py` but not in `signal_calibration.py:DEFAULT_CONFIRM`. The recalibration system won't track them.
**Why it happens:** The two dicts are defined independently in two files (lines 70-75 in prediction.py, lines 34-45 in signal_calibration.py).
**How to avoid:** After adding any new key to either dict, immediately update the corresponding dict in the other file. Treat them as a synchronized pair.
**Warning signs:** A new signal fires in predictions (appears in active_signals) but its accuracy never appears in signal_accuracy_stats.json.

### Pitfall 2: VWAP on Daily Bars is Not True Intraday VWAP
**What goes wrong:** The `_calc_vwap()` implementation in quant_analyst.py computes cumulative VWAP over the entire bar history — not the standard reset-each-session intraday VWAP. On daily bars this becomes a multi-month average price, which is actually useful (it shows whether current price is above/below long-term average cost), but the signal detection threshold must account for this.
**Why it happens:** True VWAP resets daily; the implementation uses cumsum without resetting at session boundaries.
**How to avoid:** Label this signal "multi-day VWAP" in the details dict. The detection condition "price below VWAP" still works as a discounted-vs-average-cost signal, just not intraday VWAP.
**Warning signs:** VWAP value appears to be the stock's 6-month average price, not close to today's price.

### Pitfall 3: MACD Divergence False Positives in Trending Markets
**What goes wrong:** Divergence detection fires on random noise in strongly trending markets, producing low-quality confirmation signals that reduce prediction accuracy.
**Why it happens:** Price makes "lower lows" constantly in a downtrend; MACD histogram also fluctuates. The algorithm can find spurious divergence.
**How to avoid:** Require minimum divergence magnitude (price second low must be at least 1% lower than first low) and require that the divergence window spans at least 5 bars between the two reference points.
**Warning signs:** `macd_divergence` signal appears in nearly every prediction regardless of market conditions.

### Pitfall 4: Momentum Path Polluting Mean Reversion Regime Filter
**What goes wrong:** Mean reversion requires ADX < 60 (range-bound). Momentum breakout works best when ADX > 25 (trending). If both paths share the same `_passes_regime_filter()`, momentum setups get filtered out by the ADX ceiling check.
**Why it happens:** The existing ADX_MAX = 60 check blocks anything above ADX 60 for mean reversion. Momentum needs no such ceiling.
**How to avoid:** The momentum path uses its own `_passes_momentum_regime()` function that checks ADX > 25 (confirming trend) instead of ADX < 60 (confirming range). They are separate regime filters, not shared.
**Warning signs:** Momentum breakout signals fire (volume + N-day high conditions met) but predict() returns None.

### Pitfall 5: Sector ETF Fetch Inside ThreadPoolExecutor
**What goes wrong:** `predict_batch()` runs `_predict_one()` in a ThreadPoolExecutor with 8 workers. If sector ETF bars are fetched inside `_predict_one()`, 8 threads hit yfinance simultaneously for the same ETF, bypassing the rate limiter intent.
**Why it happens:** The cache in `get_sector_etf_bars()` uses a threading.Lock, but the first call from each thread before cache population creates a stampede.
**How to avoid:** Pre-fetch all sector ETF bars before the ThreadPoolExecutor loop in `predict_batch()`, the same way `spy_df` is fetched before the executor (prediction.py line 773). Pass sector ETF bars as a pre-populated dict into `predict()`.
**Warning signs:** yfinance 429 rate limit errors during batch prediction scans.

### Pitfall 6: Re-Entry Tracker State Accumulation
**What goes wrong:** The `_reentry_tracker` dict grows unboundedly if never cleared. After weeks of operation it holds stale entries for hundreds of symbols that stopped being scanned.
**Why it happens:** Python module-level dicts persist for the process lifetime.
**How to avoid:** Prune entries older than 7 days in `_reentry_tracker` at the start of each `predict()` call for a symbol, or clear on every `predict_batch()` invocation.
**Warning signs:** `_reentry_tracker` dict has thousands of entries after a week of operation.

### Pitfall 7: Swing Point Detection With Insufficient Lookback
**What goes wrong:** `_find_swing_lows()` with n=2 (must be lower than 2 bars before and after) requires at least 4+lookback bars. With only 30-35 bars available for some symbols, the function finds no swing points.
**Why it happens:** The 20-bar lookback for swing detection requires 20 bars of recent data plus the 2-bar neighborhood check.
**How to avoid:** Check `len(df) < 25` at the start of the detector and return `PatternResult(..., detected=False)`. The `detected=False` case is already handled gracefully by the scoring system.
**Warning signs:** Support/resistance detector always returns detected=False for all symbols.

---

## Code Examples

### Adding New Signal Keys to Both DEFAULT_CONFIRM Dicts

In `prediction.py` (or `prediction_signals.py`):
```python
# Source: prediction.py lines 70-75 — extend this dict
DEFAULT_CONFIRM_BONUS = {
    "volume_profile": 1.5,
    "order_flow":     1.0,
    "amt_state":      1.0,
    "volume_spike":   1.5,
    # Phase 11 additions — start at 0.5, recalibration adjusts
    "stoch_rsi":       0.5,
    "mfi":             0.5,
    "vwap":            0.5,
    "keltner_lower":   0.5,
    "macd_divergence": 0.5,
    "support_level":   0.5,
}
```

In `signal_calibration.py` (keep in sync):
```python
# Source: signal_calibration.py lines 41-45 — must mirror prediction.py
DEFAULT_CONFIRM = {
    "volume_profile": 1.5,
    "order_flow":     1.0,
    "amt_state":      1.0,
    "volume_spike":   1.5,
    # Phase 11 additions
    "stoch_rsi":       0.5,
    "mfi":             0.5,
    "vwap":            0.5,
    "keltner_lower":   0.5,
    "macd_divergence": 0.5,
    "support_level":   0.5,
}
```

### How New Confirmations Plug Into predict()

```python
# Source: prediction.py lines 603-610 — after existing _get_confirmations() call
# Add new confirmation detectors here (after Step 3)
confirms.append(_detect_stoch_rsi(df))
confirms.append(_detect_mfi(df))
confirms.append(_detect_vwap(df))
confirms.append(_detect_keltner_lower(df))
confirms.append(_detect_macd_divergence(df))
confirms.append(_detect_support_level(df))

# vol_spike already added at line 607 — keep that intact
vol_spike = _detect_volume_spike(df)
confirms.append(vol_spike)
```

### Momentum Path Entry Point Structure

```python
# Source: prediction.py lines 561-604 — predict() function; momentum path mirrors this
def _predict_momentum(symbol: str, df: pd.DataFrame,
                       spy_df: pd.DataFrame | None = None,
                       sector_etf_bars: dict | None = None) -> Prediction | None:
    """Momentum breakout prediction path."""
    if df is None or len(df) < 35:
        return None

    # Momentum primaries: N-day high, volume surge, ADX
    breakout = _detect_momentum_breakout(df)   # from strategies/momentum.py
    vol_surge = _detect_volume_surge(df)        # 1.5x avg vol (not 1.5x capitulation)
    adx_trend = _detect_adx_trend(df)          # ADX > 25

    primaries = [breakout, vol_surge, adx_trend]
    active_primaries = [p for p in primaries if p.detected]
    if len(active_primaries) < 2:
        return None

    # Regime: momentum works IN trends (opposite of mean reversion)
    passes, reason, position_mult = _passes_momentum_regime(df, spy_df)
    if not passes:
        return None

    # Confirmations: MACD cross, Keltner upper, relative sector strength
    confirms = [
        _detect_macd_cross(df),
        _detect_keltner_upper(df),
        _detect_sector_strength(symbol, sector_etf_bars),
    ]
    # ... score and build Prediction ...
    return Prediction(
        ...,
        source="momentum_breakout",   # tracked separately from mean_reversion
    )
```

### Breadth Multiplier Computation

```python
# Source: D-14, D-15 from CONTEXT.md — new function called from _passes_regime_filter()
def _compute_breadth_multiplier(sector_etf_bars: dict[str, pd.DataFrame] | None) -> float:
    """Compute position sizing multiplier from sector breadth.

    Returns: 1.0 (normal), 0.5 (weak breadth), 0.25 (very weak breadth).
    """
    if not sector_etf_bars:
        return 1.0   # no data, don't penalize

    etfs = list(sector_etf_bars.keys())
    if not etfs:
        return 1.0

    down_2pct = 0
    down_5pct = 0
    for etf, df in sector_etf_bars.items():
        if df is None or len(df) < 6:
            continue
        five_day_return = (float(df["close"].iloc[-1]) - float(df["close"].iloc[-6])) / float(df["close"].iloc[-6])
        if five_day_return < -0.05:
            down_5pct += 1
        elif five_day_return < -0.02:
            down_2pct += 1

    majority = len(etfs) // 2 + 1
    if down_5pct >= majority:
        return 0.25   # very weak breadth
    if down_2pct + down_5pct >= majority:
        return 0.5    # weak breadth
    return 1.0
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single mean-reversion path | Dual-path: MR + momentum | Phase 11 | Bot can now predict both bounces and breakouts |
| 4 primary + 4 confirmation signals | 4 primary + 10 confirmation signals | Phase 11 | Richer scoring; recalibration has more levers |
| SPY SMA-200 only for regime | SPY SMA-200 + sector breadth (11 ETFs) | Phase 11 | Position sizing reflects broader market health |
| ATR-based stop loss only | ATR-based + nearest support level | Phase 11 | Stops placed at meaningful price levels |
| No re-entry logic | 1 allowed re-entry per setup at 50% size | Phase 11 | Captures setups that dip before bouncing |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | MACD divergence detection algorithm: find two local price lows, compare corresponding MACD histogram values | Code Examples | Could produce too many false positives; Claude tunes lookback during implementation (D-08 discretion) |
| A2 | `_reentry_tracker` as module-level dict is thread-safe enough (same pattern as `_hist_cache` in prediction.py) | Architecture Patterns | If predict() is called concurrently for the same symbol, there could be a race; acceptable for current single-bot design |
| A3 | Stochastic RSI < 0.10 threshold for detection (per D-04) gives good separation; scoring curve Claude calibrates | Code Examples | If threshold too tight, signal almost never fires and adds no value; recalibration will handle over 3-4 weeks |
| A4 | Sector ETF bars pre-fetched in predict_batch() before executor loop (same pattern as spy_df) | Pitfall 5 | If caller changes how predict_batch() works, the sector bar pre-fetch may be missed |
| A5 | Signal for "keltner upper breakout" as momentum confirmation is distinct from "keltner lower touch" as MR confirmation | Don't Hand-Roll | Both use keltner_channels() but one detects upper breach (momentum), one detects lower breach (MR) |

---

## Open Questions

1. **Where exactly do new detector functions live?**
   - What we know: prediction.py is already 872 lines. Adding 6+ new detectors + momentum path adds ~400 more lines.
   - What's unclear: User preference for file structure was left as Claude's discretion (D-03 implies PatternResult pattern but not file location).
   - Recommendation: Create `prediction_signals.py`. The planner should create Wave 0 task to establish this file with the PatternResult import, then each subsequent wave wires signals into it.

2. **Does the Prediction dataclass need a `strategy_path` field?**
   - What we know: `_log_predictions()` logs `source="mean_reversion"` for all predictions. Momentum predictions need `source="momentum_breakout"`.
   - What's unclear: The Prediction dataclass has no `source` or `strategy_path` field — it's not serialized to the dashboard.
   - Recommendation: Add `source: str = "mean_reversion"` to the Prediction dataclass (default preserves backward compatibility). The `_log_predictions()` function passes it to `log_prediction()` which already has a `source` parameter.

3. **Should momentum predictions also log to prediction_log.py?**
   - What we know: prediction_log.py tracks direction ("up"/"down"), source, and active_signals. Momentum breakouts are "up" predictions with different primary signals.
   - What's unclear: D-23 says "each new signal is tracked in active_signals so the recalibration system can compute per-signal accuracy from day one" — this implies yes.
   - Recommendation: Yes. Log momentum predictions with source="momentum_breakout" and active_signals=["momentum_breakout", "volume_surge", "adx_trend"] etc.

---

## Environment Availability

Step 2.6: External dependencies are already available — all sector ETF tickers (XLK, XLE, etc.) are standard yfinance symbols handled by the existing fetch_bars() stack. No new external services required.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| yfinance | Sector ETF bars (D-13) | Yes | Already installed | FMP fallback via data_provider.py |
| pandas | All signal detectors | Yes | >=2.0.0 | None needed |
| numpy | MFI, Stoch RSI, divergence | Yes | >=1.24.0 | None needed |
| pytest | Test infrastructure | Yes | 9.0.2 | None needed |

**No missing dependencies.**

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | None (rootdir: C:\Users\btuo1\trading-bot) |
| Quick run command | `python -m pytest tests/test_prediction_signals.py -x -q` |
| Full suite command | `python -m pytest tests/ --ignore=tests/test_pattern_backtester.py -q` |

**Known pre-existing failures (not Phase 11's fault):**
- `tests/test_pattern_backtester.py` — imports `detect_keltner_squeeze` from prediction.py which doesn't exist yet. Phase 11 will likely add it, fixing this test.
- `tests/test_scanner.py::test_scan_sorted` — pre-existing failure unrelated to Phase 11.
- `tests/test_sentiment_cache.py::test_trending_topic_amplification` — pre-existing TypeError, unrelated.

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SIG-01 | Stochastic RSI detector returns PatternResult, detected=True when stoch_rsi < 0.10 | unit | `python -m pytest tests/test_prediction_signals.py::test_stoch_rsi_detection -x` | No — Wave 0 |
| SIG-02 | MFI detector returns detected=True when MFI < 20 | unit | `python -m pytest tests/test_prediction_signals.py::test_mfi_detection -x` | No — Wave 0 |
| SIG-03 | VWAP detector returns detected=True when price below multi-day VWAP | unit | `python -m pytest tests/test_prediction_signals.py::test_vwap_detection -x` | No — Wave 0 |
| SIG-04 | Keltner lower detector returns detected=True when price at/below lower channel | unit | `python -m pytest tests/test_prediction_signals.py::test_keltner_lower_detection -x` | No — Wave 0 |
| SIG-05 | MACD divergence detector returns detected=True on valid bullish divergence | unit | `python -m pytest tests/test_prediction_signals.py::test_macd_divergence -x` | No — Wave 0 |
| SIG-06 | predict() returns Prediction with 6+ pattern entries in .patterns list | integration | `python -m pytest tests/test_prediction_signals.py::test_predict_includes_new_signals -x` | No — Wave 0 |
| SIG-07 | Sector relative strength computes correct ETF-vs-SPY spread | unit | `python -m pytest tests/test_prediction_signals.py::test_sector_strength -x` | No — Wave 0 |
| SIG-08 | Breadth multiplier returns 0.5 when majority ETFs down >2% over 5 days | unit | `python -m pytest tests/test_prediction_signals.py::test_breadth_multiplier -x` | No — Wave 0 |
| SIG-09 | Support/resistance swing point detection finds correct local lows | unit | `python -m pytest tests/test_prediction_signals.py::test_swing_points -x` | No — Wave 0 |
| SIG-10 | Momentum predict path returns Prediction with source="momentum_breakout" | unit | `python -m pytest tests/test_prediction_signals.py::test_momentum_path -x` | No — Wave 0 |
| SIG-11 | signal_calibration DEFAULT_CONFIRM contains all new signal keys | unit | `python -m pytest tests/test_prediction_signals.py::test_calibration_sync -x` | No — Wave 0 |
| SIG-12 | Re-entry logic returns 50% position size when stop previously hit | unit | `python -m pytest tests/test_prediction_signals.py::test_reentry_sizing -x` | No — Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_prediction_signals.py -x -q`
- **Per wave merge:** `python -m pytest tests/ --ignore=tests/test_pattern_backtester.py --ignore=tests/test_scanner.py -q`
- **Phase gate:** Full suite green (ignoring pre-existing failures) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_prediction_signals.py` — covers SIG-01 through SIG-12
- [ ] `prediction_signals.py` — new module housing all detector functions

---

## Security Domain

Security enforcement applies to all phases. This phase has no authentication, external API endpoints, or secrets handling. The relevant ASVS categories for this phase:

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | Yes (light) | df length checks before indicator computation — already follows this pattern in all existing detectors |
| V6 Cryptography | No | No cryptographic operations |
| V2 Authentication | No | No new endpoints or auth |
| V3 Session Management | No | No session changes |
| V4 Access Control | No | No permission model changes |

No security concerns specific to this phase. Signal computation is pure in-process math using market data from already-trusted providers.

---

## Sources

### Primary (HIGH confidence)
- `prediction.py` (codebase) — PatternResult pattern, DEFAULT_CONFIRM_BONUS dict, predict() architecture, _passes_regime_filter() structure [VERIFIED]
- `agents/quant_analyst.py` (codebase) — _calc_stochastic_rsi(), _calc_mfi(), _calc_vwap() implementations to adapt [VERIFIED]
- `indicators.py` (codebase) — keltner_channels(), macd() return signatures [VERIFIED]
- `strategies/momentum.py` (codebase) — scan() implementation, LOOKBACK, MIN_VOLUME_RATIO constants [VERIFIED]
- `signal_calibration.py` (codebase) — DEFAULT_CONFIRM dict, all_signals construction on line 194, how new signals must be registered [VERIFIED]
- `yf_limiter.py` (codebase) — get_spy_history() caching pattern to replicate for sector ETFs [VERIFIED]
- `prediction_log.py` (codebase) — source parameter, active_signals field [VERIFIED]

### Secondary (MEDIUM confidence)
- CONTEXT.md decisions D-01 through D-23 — locked architectural decisions from discuss phase [VERIFIED: file read]

### Tertiary (LOW confidence — ASSUMED)
- MACD divergence lookback window (20 bars) and minimum divergence threshold — standard practice from quantitative trading literature but not verified against this bot's specific bar frequency [ASSUMED]
- Stochastic RSI 0.10 threshold giving "best separation" claim — per D-04 this is the locked detection threshold, confidence stated as 82%+ bounce rate but not independently verified in this session [ASSUMED]

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in production use; no new dependencies
- Architecture: HIGH — based on direct codebase inspection; patterns are extrapolations of verified existing patterns
- Signal detector logic: MEDIUM — math is verified in existing implementations; integration points assumed from pattern inspection
- Pitfalls: HIGH — identified from direct code reading of threading model, dict synchronization requirements, and ADX filter conflicts

**Research date:** 2026-05-27
**Valid until:** 2026-06-27 (30 days — stable codebase, no fast-moving external dependencies)
