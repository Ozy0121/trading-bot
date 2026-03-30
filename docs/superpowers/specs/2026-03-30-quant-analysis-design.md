# Quantitative Analysis Engine — Design Spec

## Summary

Add professional-grade quantitative analysis to the trading bot's decision engine. Three new pure-math modules (`volatility.py`, `risk.py`, `probability.py`) compute volatility metrics, risk/sizing recommendations, and trade probabilities. Results feed into the existing scanner scoring system and upgrade `safety.py` with ATR-based stops and Kelly Criterion position sizing.

## Scope

### In Scope (This Phase)
- **Volatility Analysis:** Historical Volatility (20d/60d), ATR(14), Beta vs SPY, Correlation to SPY
- **Risk Math:** VaR (95%/99%), Max Drawdown, Sortino Ratio, Kelly Criterion (half-Kelly), ATR-based stop-losses
- **Probability Math:** Move probabilities (1/3/5 day), expected value per trade, profit factor
- **Position Sizing Overhaul:** Half-Kelly sizing, percentage-based caps that scale with equity, total exposure cap
- **Stop-Loss Overhaul:** ATR-based stops (default), flat % fallback, clamped bounds
- **Shared State:** All quant data populated for future dashboard/AI consumption

### Deferred
- IV, IV Rank, IV Percentile — Phase 3 (Options Trading) when options chain data is available
- Quant Dashboard Tab — Phase 5 (Dashboard overhaul)
- Claude API reasoning over quant data — Phase 5 (AI Analyst)
- Advanced indicators (ROC, MFI, OBV, %B, StochRSI, VWAP) — future phase
- Market regime detection enhancements (ADX, VIX, breadth) — future phase

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | 3 focused modules | Matches existing `indicators.py` pattern. Each ~150-200 lines, independently testable. |
| Behavioral code location | ATR stops in `safety.py`, Kelly sizing in `safety.py` | Stop logic and sizing logic already live there. New modules provide the math, existing modules apply it. |
| Bar data for quant | Daily bars (60-90 days) via yfinance batch download | 5-min intraday bars are wrong timeframe for volatility/risk metrics. yfinance batch = 1 API call for all symbols. |
| Kelly activation | Minimum 30 trades | Kelly with small samples produces unstable fractions. Existing sizing logic until enough data. |
| Position cap style | % of equity (not fixed dollar) | Scales with account growth. $500 today, $5,000 later — sizing grows automatically. |
| Aggressiveness | 40% per trade, 90% total exposure, half-Kelly | Small account ($500) prioritizes growth. Safety nets (Kelly modulation, ATR stops, EV gate, daily loss limit) prevent blowup. |
| EV gate | Hard filter — skip negative EV trades | No point taking a trade where the math says you lose on average. |
| ATR stop bounds | Floor 1.5%, ceiling 8% | Prevents too-tight stops (noise shakeout) and too-loose stops (excessive loss). |

## Module Specifications

### 1. `volatility.py` — Volatility Metrics

**Interface:**
```python
def compute_volatility(df: pd.DataFrame, spy_df: pd.DataFrame | None = None) -> dict:
    """
    Compute volatility metrics from daily OHLCV bars.

    Args:
        df: Daily OHLCV DataFrame (60-90 days minimum)
        spy_df: SPY daily bars for beta/correlation (optional)

    Returns dict with:
        hv_20: float       — 20-day historical volatility (annualized)
        hv_60: float       — 60-day historical volatility (annualized)
        atr_14: float      — 14-period Average True Range (dollars)
        atr_pct: float     — ATR as % of current price
        beta: float | None — Beta vs SPY (None if no spy_df)
        correlation_spy: float | None — Pearson correlation to SPY
    """
```

**Calculations:**
- **HV:** `std(log(close[t]/close[t-1])) * sqrt(252)` over 20 and 60 day windows
- **ATR:** Wilder's True Range = `max(high-low, |high-prev_close|, |low-prev_close|)`, 14-period EMA
- **Beta:** `cov(stock_returns, spy_returns) / var(spy_returns)` over 60 days
- **Correlation:** Pearson correlation of daily returns vs SPY over 60 days

**Data requirements:** Always fetch 90 days of daily bars. Minimum 60 bars for full results (all metrics). Minimum 20 bars for partial results (hv_20 and ATR only, no beta/hv_60/correlation). Fewer than 20 bars returns empty dict.

### 2. `risk.py` — Risk Metrics & Sizing

**Interface:**
```python
def compute_risk(df: pd.DataFrame) -> dict:
    """
    Compute risk metrics from daily OHLCV bars.

    Returns dict with:
        var_95: float          — Daily VaR at 95% confidence (%, negative)
        var_99: float          — Daily VaR at 99% confidence (%, negative)
        max_drawdown: float    — Largest peak-to-trough drop (%, negative)
        max_drawdown_days: int — Duration of worst drawdown in trading days
        sortino: float         — Annualized Sortino ratio
    """

def compute_kelly(trade_history: list[dict]) -> dict:
    """
    Compute Kelly Criterion from bot's trade history.

    Args:
        trade_history: List of trade dicts with 'pnl' and 'win' keys

    Returns dict with:
        win_rate: float        — Historical win rate (0-1)
        avg_win: float         — Average winning trade (%)
        avg_loss: float        — Average losing trade (%, negative)
        kelly_fraction: float  — Full Kelly optimal fraction (floored at 0)
        half_kelly: float      — Half Kelly (what we use)
        sample_size: int       — Number of trades in history
        active: bool           — True if sample_size >= MIN_KELLY_TRADES
    """

def compute_atr_stop(price: float, atr: float, multiplier: float = 2.0) -> dict:
    """
    Compute ATR-based stop-loss price.

    Returns dict with:
        stop_price: float  — Suggested stop price
        stop_pct: float    — Stop distance as % (clamped to floor/ceiling)
        used_fallback: bool — True if clamped or fell back to flat %
    """
```

**Calculations:**
- **VaR:** Sort historical daily returns ascending. 95th percentile = `returns[int(n * 0.05)]`. Interpretation: "95% of days, your loss won't exceed this %."
- **Max Drawdown:** Walk price series tracking running peak. `drawdown = (price - peak) / peak`. Track worst.
- **Sortino:** `(annualized_return) / (std of negative returns only * sqrt(252))`. Only penalizes downside, unlike Sharpe.
- **Kelly:** `W - (1 - W) / R` where W = win rate, R = avg_win / |avg_loss|. Floored at 0. Half-Kelly = result / 2.
- **ATR Stop:** `stop_price = price - (multiplier * atr)`. `stop_pct` clamped to [1.5%, 8.0%]. If ATR unavailable, returns flat TRAILING_STOP_PCT as fallback.

### 3. `probability.py` — Move Probabilities & Expected Value

**Interface:**
```python
def compute_probabilities(
    df: pd.DataFrame,
    stop_pct: float,
    target_pct: float
) -> dict:
    """
    Compute historical move probabilities and expected value.

    Args:
        df: Daily OHLCV bars (60+ days)
        stop_pct: Stop-loss distance (%) for EV calculation
        target_pct: Take-profit target (%) for EV calculation

    Returns dict with:
        prob_up_1d: float          — P(positive return) over 1 day
        prob_up_3d: float          — P(positive return) over 3 days
        prob_up_5d: float          — P(positive return) over 5 days
        avg_win_pct: float         — Mean gain on winning 3-day holds
        avg_loss_pct: float        — Mean loss on losing 3-day holds (negative)
        expected_value_pct: float  — EV per trade (%)
        win_rate_3d: float         — 3-day historical win rate
        profit_factor: float       — Gross wins / gross losses
        positive_ev: bool | None   — True if EV > 0, None if insufficient data
    """
```

**Calculations:**
- **Move probabilities:** For each historical window of N days, compute forward return. Count positive vs total. `prob_up_3d = count(3d_return > 0) / total_windows`.
- **Avg win/loss:** Separate 3-day returns into positive and negative. Mean of each group.
- **Expected value:** `(win_rate * avg_win) + ((1 - win_rate) * avg_loss)`. Positive = edge exists.
- **Profit factor:** `sum(positive_returns) / abs(sum(negative_returns))`. Above 1.0 = historically profitable.
- **Minimum data:** 60 daily bars required. If fewer, `positive_ev = None` (inconclusive, scanner treats as neutral).

## Integration Points

### Scanner (`scanner.py`)

In `_score_symbol_multi()`, after existing strategy/sentiment/sector scoring:

```python
# Fetch daily bars (batch, cached per scan cycle)
daily_bars = _get_daily_bars(symbol)  # from pre-fetched batch
spy_daily = _get_daily_bars("SPY")    # cached, shared

# Compute quant metrics
vol_metrics = compute_volatility(daily_bars, spy_daily)
risk_metrics = compute_risk(daily_bars)
prob_metrics = compute_probabilities(daily_bars, atr_stop_pct, take_profit_pct)

# EV hard gate
if prob_metrics["positive_ev"] is False:
    log.info("[scanner] SKIP %s: negative expected value (EV=%.2f%%)", symbol, prob_metrics["expected_value_pct"])
    return None  # candidate rejected

# Attach quant data to result (for state/dashboard/AI)
result["quant"] = {**vol_metrics, **risk_metrics, **prob_metrics}
```

Daily bars fetched via `yf.download(symbols, period="90d")` — single batch API call at scan start, ~2-3 seconds. Results cached for the scan cycle.

### Safety (`safety.py`)

**Position sizing — `calculate_safe_qty()` updated:**
```python
# Kelly sizing (if enough trade history)
kelly = compute_kelly(trade_history)
if kelly["active"]:
    fraction = kelly["half_kelly"]
else:
    fraction = get_dynamic_fraction(consecutive_losses)  # existing fallback

# Percentage-based cap (scales with equity)
max_value = equity * POSITION_CAP_PCT  # 40% of equity

# Total exposure check
current_exposure = sum(position_values)
remaining_capacity = (equity * MAX_TOTAL_EXPOSURE_PCT) - current_exposure
max_value = min(max_value, remaining_capacity)

qty = min(max_value / price, equity * fraction / price)
```

**ATR stop-loss — `trailing_stop_triggered()` updated:**
```python
# Get ATR from quant data (computed during scan)
atr = quant_data.get(symbol, {}).get("atr_14")
if atr and atr > 0:
    stop_info = compute_atr_stop(peak_price, atr)
    stop_pct = stop_info["stop_pct"]
else:
    stop_pct = TRAILING_STOP_PCT  # flat 3% fallback

triggered = (peak - price) / peak >= (stop_pct / 100)
```

### Config (`config.py`)

New parameters:
```python
# Position sizing (scales with equity)
POSITION_CAP_PCT         = _float("POSITION_CAP_PCT", 0.40)       # 40% of equity per trade
MAX_TOTAL_EXPOSURE_PCT   = _float("MAX_TOTAL_EXPOSURE_PCT", 0.90) # 90% total exposure
MIN_KELLY_TRADES         = _int("MIN_KELLY_TRADES", 30)           # Trades before Kelly activates

# ATR stop-loss
ATR_STOP_MULTIPLIER      = _float("ATR_STOP_MULTIPLIER", 2.0)    # Stop at 2x ATR
ATR_STOP_FLOOR_PCT       = _float("ATR_STOP_FLOOR_PCT", 1.5)     # Minimum stop distance %
ATR_STOP_CEIL_PCT        = _float("ATR_STOP_CEIL_PCT", 8.0)      # Maximum stop distance %
```

### State (`state.py`)

New state keys:
```python
"quant_data": {},          # {symbol: {hv_20, atr_14, var_95, kelly_half, ev_pct, ...}}
"kelly_info": {},          # Latest Kelly calculation {win_rate, half_kelly, active, ...}
"position_sizing_method": "default",  # "kelly" or "default"
```

### Shared State for Future Phases

All quant metrics are stored in `state["quant_data"][symbol]` as a flat dict. Phase 5 dashboard reads this directly. Phase 5 Claude API receives it as context in the analysis prompt. No re-computation needed.

## Performance Budget

| Operation | Cost | Frequency |
|-----------|------|-----------|
| yfinance batch download (60 symbols, 90 days daily) | ~2-3s, 1 API call | Once per scan cycle |
| SPY daily bars | ~0.5s, 1 API call | Once per scan cycle (cached) |
| compute_volatility() per symbol | <5ms (numpy math) | 60x per scan |
| compute_risk() per symbol | <5ms (numpy math) | 60x per scan |
| compute_probabilities() per symbol | <5ms (numpy math) | 60x per scan |
| **Total added scan time** | **~3-4 seconds** | Within 30s target |

All three compute functions are pure numpy/pandas math on pre-fetched data. The bottleneck is the single yfinance batch download, not the calculations.

## Testing Strategy

Each module gets its own test file with deterministic inputs:

- `tests/test_volatility.py` — Known price series with pre-calculated HV, ATR, beta
- `tests/test_risk.py` — Known returns with pre-calculated VaR, drawdown, Sortino, Kelly
- `tests/test_probability.py` — Known price series with pre-calculated move probabilities, EV
- `tests/test_scanner.py` (updated) — EV gate filtering, quant data attachment
- `tests/test_safety.py` (updated) — ATR stop logic, Kelly sizing, exposure cap

## File Summary

| File | Action | Lines (est.) |
|------|--------|-------------|
| `volatility.py` | New | ~150 |
| `risk.py` | New | ~180 |
| `probability.py` | New | ~150 |
| `config.py` | Edit | +15 |
| `scanner.py` | Edit | +60 |
| `safety.py` | Edit | +80 |
| `state.py` | Edit | +10 |
| `tests/test_volatility.py` | New | ~120 |
| `tests/test_risk.py` | New | ~140 |
| `tests/test_probability.py` | New | ~120 |
| `tests/test_scanner.py` | Edit | +40 |
| `tests/test_safety.py` | Edit | +60 |
