"""
prediction_signals.py
---------------------
New confirmation signal detectors for the prediction engine (Phase 11).

Implements 6 new confirmation signals that expand the confirmation layer
from 4 signals to 10 signals:
  - Stochastic RSI (D-04): extreme oversold on momentum oscillator
  - MFI (D-05): Money Flow Index — smart money selling exhaustion
  - VWAP (D-06): price below multi-day VWAP cost basis
  - Keltner Lower (D-07): price at/below lower Keltner channel
  - MACD Divergence (D-08): bullish divergence — lower price high, higher MACD low
  - Support Level (D-19): price near swing low support zone

Also provides swing point detection utilities used by the above:
  - _find_swing_lows: local price minima in lookback window
  - _find_swing_highs: local price maxima in lookback window

All detectors return PatternResult as defined in prediction.py.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from prediction import PatternResult
from indicators import (
    rsi as calc_rsi,
    keltner_channels,
    macd as calc_macd,
)
from logger_setup import get_logger

log = get_logger()


# ── Swing point detection ────────────────────────────────────────────────────

def _find_swing_lows(df: pd.DataFrame, lookback: int = 20, n: int = 2) -> list[float]:
    """Find local price minima (swing lows) in the last `lookback` bars.

    A bar is a swing low if its `low` is lower than the `n` bars before AND
    the `n` bars after it.

    Args:
        df: OHLCV DataFrame.
        lookback: How many recent bars to search within.
        n: Number of neighboring bars on each side to compare.

    Returns:
        List of swing low prices (float), may be empty.
    """
    if len(df) < n * 2 + 1:
        return []

    lows = df["low"].values
    start = max(n, len(lows) - lookback - n)
    end = len(lows) - n

    swing_lows = []
    for i in range(start, end):
        bar_low = lows[i]
        before = lows[i - n:i]
        after = lows[i + 1:i + n + 1]
        if all(bar_low <= b for b in before) and all(bar_low <= a for a in after):
            swing_lows.append(float(bar_low))

    return swing_lows


def _find_swing_highs(df: pd.DataFrame, lookback: int = 20, n: int = 2) -> list[float]:
    """Find local price maxima (swing highs) in the last `lookback` bars.

    A bar is a swing high if its `high` is higher than the `n` bars before AND
    the `n` bars after it.

    Args:
        df: OHLCV DataFrame.
        lookback: How many recent bars to search within.
        n: Number of neighboring bars on each side to compare.

    Returns:
        List of swing high prices (float), may be empty.
    """
    if len(df) < n * 2 + 1:
        return []

    highs = df["high"].values
    start = max(n, len(highs) - lookback - n)
    end = len(highs) - n

    swing_highs = []
    for i in range(start, end):
        bar_high = highs[i]
        before = highs[i - n:i]
        after = highs[i + 1:i + n + 1]
        if all(bar_high >= b for b in before) and all(bar_high >= a for a in after):
            swing_highs.append(float(bar_high))

    return swing_highs


# ── Confirmation detectors ───────────────────────────────────────────────────

def _detect_stoch_rsi(df: pd.DataFrame) -> PatternResult:
    """Stochastic RSI — extreme oversold on RSI momentum oscillator (D-04).

    Computes RSI(14), then normalizes RSI over a 14-period rolling window:
      stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min)

    Detection threshold: stoch_rsi < 0.10 (bottom 10% of RSI range).
    Scoring: < 0.05 → 10.0, < 0.10 → 8.0 (scaled), < 0.20 → 4.0 (scaled), else 0.0.

    Minimum bars: 28 (14 for RSI + 14 for stoch rolling window).
    """
    min_bars = 28
    if len(df) < min_bars:
        return PatternResult("stoch_rsi", False, 0.0, "momentum",
                             {"stoch_rsi_value": None})

    closes = df["close"]
    rsi_series = calc_rsi(closes, period=14)
    rsi_clean = rsi_series.dropna()

    if len(rsi_clean) < 14:
        return PatternResult("stoch_rsi", False, 0.0, "momentum",
                             {"stoch_rsi_value": None})

    rsi_min = rsi_clean.rolling(14).min()
    rsi_max = rsi_clean.rolling(14).max()
    denom = rsi_max - rsi_min

    # When denominator is 0, RSI is pinned at a constant value.
    # If pinned at very low RSI (< 10), treat stoch_rsi as 0.0 (maximally oversold).
    # If pinned at high RSI, treat stoch_rsi as 1.0 (not oversold).
    last_rsi_val = float(rsi_clean.iloc[-1])
    last_denom = float(denom.iloc[-1]) if not pd.isna(denom.iloc[-1]) else 0.0

    if last_denom == 0.0:
        # RSI is flat — pinned value determines the state
        stoch_val = 0.0 if last_rsi_val < 10.0 else 1.0
    else:
        stoch = (rsi_clean - rsi_min) / denom.replace(0, np.nan)
        stoch_val_raw = stoch.dropna()
        if len(stoch_val_raw) == 0:
            return PatternResult("stoch_rsi", False, 0.0, "momentum",
                                 {"stoch_rsi_value": None})
        stoch_val = float(stoch_val_raw.iloc[-1])

    detected = stoch_val < 0.10
    if stoch_val < 0.05:
        score = 10.0
    elif stoch_val < 0.10:
        # Linear scale: 0.10 → 8.0, 0.05 → 10.0
        score = 8.0 + (0.10 - stoch_val) / 0.05 * 2.0
    elif stoch_val < 0.20:
        # Linear scale: 0.10 → 8.0, 0.20 → 4.0
        score = 4.0 + (0.20 - stoch_val) / 0.10 * 4.0
    else:
        score = 0.0

    score = min(10.0, round(score, 1))
    return PatternResult("stoch_rsi", detected, score, "momentum",
                         {"stoch_rsi_value": round(stoch_val, 4)})


def _detect_mfi(df: pd.DataFrame, period: int = 14) -> PatternResult:
    """Money Flow Index — smart money selling exhaustion (D-05).

    MFI < 20 = oversold by money flow (analogous to RSI but volume-weighted).
    Formula: typical_price = (H+L+C)/3; MFI = 100 - 100/(1 + pos_flow/neg_flow).

    Detection threshold: MFI < 20.
    Scoring: < 10 → 10.0, < 15 → 8.0, < 20 → 6.0, else 0.0.
    Minimum bars: period + 1.
    """
    min_bars = period + 1
    if len(df) < min_bars:
        return PatternResult("mfi", False, 0.0, "volume", {"mfi_value": None})

    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    money_flow = typical * df["volume"]
    delta = typical.diff()

    pos_flow = (money_flow * (delta > 0)).rolling(period).sum()
    neg_flow = (money_flow * (delta < 0)).rolling(period).sum().abs()

    ratio = pos_flow / neg_flow.replace(0, np.nan)
    mfi_series = 100 - (100 / (1 + ratio))

    mfi_clean = mfi_series.dropna()
    if len(mfi_clean) == 0:
        return PatternResult("mfi", False, 0.0, "volume", {"mfi_value": None})

    mfi_val = float(mfi_clean.iloc[-1])

    detected = mfi_val < 20
    if mfi_val < 10:
        score = 10.0
    elif mfi_val < 15:
        score = 8.0
    elif mfi_val < 20:
        score = 6.0
    else:
        score = 0.0

    return PatternResult("mfi", detected, score, "volume",
                         {"mfi_value": round(mfi_val, 2)})


def _detect_vwap(df: pd.DataFrame) -> PatternResult:
    """VWAP — price below multi-day cumulative VWAP cost basis (D-06).

    Uses cumulative VWAP across the full DataFrame (not an intraday reset).
    Detection: current close < VWAP value.
    Score: > 3% below → 8.0, > 1% below → 5.0, at VWAP → 2.0.
    Minimum bars: 10.
    """
    min_bars = 10
    if len(df) < min_bars:
        return PatternResult("vwap", False, 0.0, "volume",
                             {"vwap_value": None, "pct_below_vwap": None,
                              "note": "insufficient data"})

    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_tp_vol = (typical * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    vwap_series = cum_tp_vol / cum_vol.replace(0, np.nan)

    vwap_clean = vwap_series.dropna()
    if len(vwap_clean) == 0:
        return PatternResult("vwap", False, 0.0, "volume",
                             {"vwap_value": None, "pct_below_vwap": None,
                              "note": "multi-day VWAP (not intraday reset)"})

    vwap_val = float(vwap_clean.iloc[-1])
    current_price = float(df["close"].iloc[-1])

    if vwap_val <= 0:
        return PatternResult("vwap", False, 0.0, "volume",
                             {"vwap_value": vwap_val, "pct_below_vwap": None,
                              "note": "multi-day VWAP (not intraday reset)"})

    pct_below = (vwap_val - current_price) / vwap_val * 100.0
    detected = current_price < vwap_val

    if pct_below > 3.0:
        score = 8.0
    elif pct_below > 1.0:
        score = 5.0
    elif pct_below >= 0.0:
        score = 2.0
    else:
        score = 0.0

    return PatternResult("vwap", detected, score, "volume",
                         {"vwap_value": round(vwap_val, 4),
                          "pct_below_vwap": round(pct_below, 2),
                          "note": "multi-day VWAP (not intraday reset)"})


def _detect_keltner_lower(df: pd.DataFrame) -> PatternResult:
    """Keltner lower channel — price at/below lower Keltner band (D-07).

    Uses indicators.keltner_channels(df) which returns (upper, mid, lower).
    Detection: current close <= lower Keltner channel value.
    Score: at channel → 6.0, 1% below → 8.0, 2%+ below → 10.0.
    Minimum bars: 20 (EMA period for Keltner).
    """
    min_bars = 20
    if len(df) < min_bars:
        return PatternResult("keltner_lower", False, 0.0, "volatility",
                             {"keltner_lower": None, "price": None})

    try:
        _, _, lower = keltner_channels(df)
    except Exception as exc:
        log.warning("[prediction_signals] keltner_channels error: %s", exc)
        return PatternResult("keltner_lower", False, 0.0, "volatility",
                             {"keltner_lower": None, "price": None})

    lower_clean = lower.dropna()
    if len(lower_clean) == 0:
        return PatternResult("keltner_lower", False, 0.0, "volatility",
                             {"keltner_lower": None, "price": None})

    lower_val = float(lower_clean.iloc[-1])
    current_price = float(df["close"].iloc[-1])

    if lower_val <= 0:
        return PatternResult("keltner_lower", False, 0.0, "volatility",
                             {"keltner_lower": lower_val, "price": current_price})

    pct_below = (lower_val - current_price) / lower_val * 100.0
    detected = current_price <= lower_val

    if pct_below >= 2.0:
        score = 10.0
    elif pct_below >= 1.0:
        score = 8.0
    elif pct_below >= 0.0:
        score = 6.0
    else:
        score = 0.0

    return PatternResult("keltner_lower", detected, score, "volatility",
                         {"keltner_lower": round(lower_val, 4),
                          "price": round(current_price, 4)})


def _detect_macd_divergence(df: pd.DataFrame, lookback: int = 20) -> PatternResult:
    """MACD bullish divergence — price lower low but MACD histogram higher low (D-08).

    Looks for two local price lows in last `lookback` bars where:
      - Price second low is at least 1% below first low (filter noise)
      - At least 5 bars between the two lows (per RESEARCH.md Pitfall 3)
      - MACD histogram at second low is higher than at first low (divergence)

    Score: 8.0 if detected, 0.0 otherwise.
    Minimum bars: lookback + 30 (MACD needs 26-period EMA warmup).
    """
    min_bars = lookback + 30
    if len(df) < min_bars:
        return PatternResult("macd_divergence", False, 0.0, "momentum",
                             {"divergence_type": "none"})

    try:
        _, _, histogram = calc_macd(df["close"])
    except Exception as exc:
        log.warning("[prediction_signals] macd error: %s", exc)
        return PatternResult("macd_divergence", False, 0.0, "momentum",
                             {"divergence_type": "none"})

    hist_arr = histogram.values
    low_arr  = df["low"].values
    n = len(low_arr)

    # Search in last `lookback` bars for local lows (2-bar neighbors)
    search_start = max(2, n - lookback - 2)
    search_end   = n - 2

    local_lows: list[tuple[int, float, float]] = []  # (index, price_low, hist_val)
    for i in range(search_start, search_end):
        bar_low = low_arr[i]
        if (bar_low <= low_arr[i - 1] and bar_low <= low_arr[i - 2] and
                bar_low <= low_arr[i + 1] and bar_low <= low_arr[i + 2]):
            hist_val = float(hist_arr[i]) if not np.isnan(hist_arr[i]) else 0.0
            local_lows.append((i, float(bar_low), hist_val))

    if len(local_lows) < 2:
        return PatternResult("macd_divergence", False, 0.0, "momentum",
                             {"divergence_type": "none"})

    # Check all pairs from oldest to most recent for bullish divergence
    detected = False
    best_details: dict = {}

    for a_idx in range(len(local_lows) - 1):
        for b_idx in range(a_idx + 1, len(local_lows)):
            i_a, price_a, hist_a = local_lows[a_idx]
            i_b, price_b, hist_b = local_lows[b_idx]

            # Require at least 5 bars between lows
            if i_b - i_a < 5:
                continue

            # Require price second low at least 1% below first (not noise)
            if price_b > price_a * 0.99:
                continue

            # Bullish divergence: price made lower low but histogram made higher low
            if hist_b > hist_a:
                detected = True
                best_details = {
                    "divergence_type": "bullish",
                    "price_low_1": round(price_a, 4),
                    "price_low_2": round(price_b, 4),
                    "hist_low_1":  round(hist_a, 6),
                    "hist_low_2":  round(hist_b, 6),
                }
                break
        if detected:
            break

    if not detected:
        return PatternResult("macd_divergence", False, 0.0, "momentum",
                             {"divergence_type": "none"})

    return PatternResult("macd_divergence", True, 8.0, "momentum", best_details)


def _detect_support_level(df: pd.DataFrame) -> PatternResult:
    """Support level — price near recent swing low support zone (D-19).

    Calls _find_swing_lows(df) and checks if current close is within 1.5%
    of any identified support level.

    Score: within 0.5% → 8.0, within 1.0% → 6.0, within 1.5% → 4.0.
    Minimum bars: 25 (per RESEARCH.md Pitfall 7).
    """
    min_bars = 25
    if len(df) < min_bars:
        return PatternResult("support_level", False, 0.0, "structure",
                             {"nearest_support": None, "distance_pct": None})

    support_levels = _find_swing_lows(df)
    if not support_levels:
        return PatternResult("support_level", False, 0.0, "structure",
                             {"nearest_support": None, "distance_pct": None})

    current_price = float(df["close"].iloc[-1])
    if current_price <= 0:
        return PatternResult("support_level", False, 0.0, "structure",
                             {"nearest_support": None, "distance_pct": None})

    # Find nearest support level
    nearest = min(support_levels, key=lambda s: abs(current_price - s))
    distance_pct = abs(current_price - nearest) / nearest * 100.0

    detected = distance_pct <= 1.5
    if distance_pct <= 0.5:
        score = 8.0
    elif distance_pct <= 1.0:
        score = 6.0
    elif distance_pct <= 1.5:
        score = 4.0
    else:
        score = 0.0

    return PatternResult("support_level", detected, score, "structure",
                         {"nearest_support": round(nearest, 4),
                          "distance_pct": round(distance_pct, 2)})
