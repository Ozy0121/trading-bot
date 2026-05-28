"""
order_flow.py
-------------
Approximated order flow analysis using OHLCV bar data.

Provides:
  - Cumulative Volume Delta (CVD) using close-location-value method
  - CVD divergence detection (bullish/bearish)
  - Delta direction and flip detection
  - Bar-level delta classification

Close-Location-Value method:
  buy_volume  = volume * (close - low)  / (high - low)
  sell_volume = volume * (high - close) / (high - low)
  delta       = buy_volume - sell_volume

This is the same approximation used by TradingView, Thinkorswim, and most
retail platforms without Level 2 data. ~70-80% accurate vs real order flow.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from logger_setup import get_logger

log = get_logger()

# ── CVD calculation ──────────────────────────────────────────────────────────


def compute_cvd(df: pd.DataFrame) -> pd.Series:
    """Compute Cumulative Volume Delta from OHLCV bars.

    Returns a Series aligned with the input DataFrame index.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"].astype(float)

    bar_range = high - low
    bar_range = bar_range.replace(0, np.nan)

    buy_pct = (close - low) / bar_range
    buy_pct = buy_pct.fillna(0.5)

    delta = volume * (2 * buy_pct - 1)  # buy_vol - sell_vol
    cvd = delta.cumsum()
    return cvd


def compute_bar_delta(df: pd.DataFrame) -> pd.Series:
    """Per-bar delta (not cumulative). Positive = net buying."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"].astype(float)

    bar_range = (high - low).replace(0, np.nan)
    buy_pct = ((close - low) / bar_range).fillna(0.5)
    return volume * (2 * buy_pct - 1)


# ── Delta flip detection ────────────────────────────────────────────────────


def detect_delta_flips(df: pd.DataFrame, lookback: int = 3) -> list[dict]:
    """Detect points where cumulative delta flips direction.

    A flip is when the short-term delta trend reverses sign.
    Returns list of {index, price, direction, strength}.
    """
    delta = compute_bar_delta(df)
    smoothed = delta.rolling(lookback, min_periods=1).mean()

    flips = []
    prev_sign = 0
    for i in range(1, len(smoothed)):
        curr_sign = 1 if smoothed.iloc[i] > 0 else -1
        if prev_sign != 0 and curr_sign != prev_sign:
            strength = abs(float(smoothed.iloc[i]))
            avg_vol = float(df["volume"].iloc[max(0, i - 10):i].mean()) or 1
            norm_strength = min(10.0, strength / avg_vol * 10)

            flips.append({
                "bar_index": i,
                "price": float(df["close"].iloc[i]),
                "direction": "bullish" if curr_sign > 0 else "bearish",
                "strength": round(norm_strength, 2),
                "timestamp": str(df.index[i]) if hasattr(df.index[i], "isoformat") else str(df.index[i]),
            })
        prev_sign = curr_sign

    return flips


# ── CVD divergence detection ────────────────────────────────────────────────


def detect_cvd_divergence(df: pd.DataFrame, window: int = 10) -> dict:
    """Detect bullish/bearish CVD divergences.

    Bullish: price makes lower lows but CVD makes higher lows (hidden buying).
    Bearish: price makes higher highs but CVD makes lower highs (weak buying).

    Returns {
        "type": "bullish" | "bearish" | "none" | "confirming",
        "strength": 0-10,
        "price_slope": float,
        "cvd_slope": float,
        "description": str,
    }
    """
    if len(df) < window + 5:
        return {"type": "none", "strength": 0, "price_slope": 0, "cvd_slope": 0,
                "description": "Insufficient data"}

    cvd = compute_cvd(df)
    close = df["close"]

    recent = slice(-window, None)
    price_vals = close.iloc[recent].values.astype(float)
    cvd_vals = cvd.iloc[recent].values.astype(float)

    x = np.arange(len(price_vals))
    price_slope = float(np.polyfit(x, price_vals, 1)[0])
    cvd_slope = float(np.polyfit(x, cvd_vals, 1)[0])

    # Normalize slopes relative to their own scale
    price_range = float(price_vals.max() - price_vals.min()) or 1.0
    cvd_range = float(cvd_vals.max() - cvd_vals.min()) or 1.0
    norm_price = price_slope / price_range * window
    norm_cvd = cvd_slope / cvd_range * window

    # Detect divergence type
    threshold = 0.15
    div_type = "none"
    strength = 0.0
    description = "No divergence"

    if norm_price < -threshold and norm_cvd > threshold:
        div_type = "bullish"
        strength = min(10.0, abs(norm_cvd - norm_price) * 5)
        description = "Price falling but CVD rising — hidden buying pressure"
    elif norm_price > threshold and norm_cvd < -threshold:
        div_type = "bearish"
        strength = min(10.0, abs(norm_price - norm_cvd) * 5)
        description = "Price rising but CVD falling — buyers weakening"
    elif (norm_price > threshold and norm_cvd > threshold) or \
         (norm_price < -threshold and norm_cvd < -threshold):
        div_type = "confirming"
        strength = min(10.0, abs(norm_price + norm_cvd) * 3)
        description = "CVD confirms price direction — trend is healthy"

    return {
        "type": div_type,
        "strength": round(strength, 2),
        "price_slope": round(price_slope, 6),
        "cvd_slope": round(cvd_slope, 2),
        "description": description,
    }


# ── Composite order flow score ──────────────────────────────────────────────


def score_order_flow(df: pd.DataFrame) -> dict:
    """Compute a 0-10 order flow score for a stock.

    Components:
      - CVD trend direction (is buying pressure increasing?)
      - CVD divergence (hidden accumulation or distribution?)
      - Recent delta flips (momentum shifts at key levels?)

    Returns dict with score and breakdown.
    """
    if len(df) < 15:
        return {"score": 5.0, "cvd_trend": "neutral", "divergence": "none",
                "delta_flips": 0, "details": {}}

    cvd = compute_cvd(df)
    divergence = detect_cvd_divergence(df)
    flips = detect_delta_flips(df, lookback=3)
    recent_flips = [f for f in flips if f["bar_index"] >= len(df) - 5]

    # CVD trend: slope of last 10 bars
    cvd_recent = cvd.iloc[-10:].values.astype(float)
    x = np.arange(len(cvd_recent))
    cvd_slope = float(np.polyfit(x, cvd_recent, 1)[0])
    cvd_range = float(cvd_recent.max() - cvd_recent.min()) or 1.0
    cvd_norm = cvd_slope / cvd_range * 10

    # CVD direction score: 0-10 (5 = neutral)
    cvd_dir_score = 5.0 + min(5.0, max(-5.0, cvd_norm * 3))

    # Divergence bonus/penalty
    div_adj = 0.0
    if divergence["type"] == "bullish":
        div_adj = divergence["strength"] * 0.3
    elif divergence["type"] == "bearish":
        div_adj = -divergence["strength"] * 0.3
    elif divergence["type"] == "confirming":
        div_adj = divergence["strength"] * 0.15

    # Delta flip bonus: recent bullish flips at support
    flip_adj = 0.0
    for f in recent_flips:
        if f["direction"] == "bullish":
            flip_adj += 0.5 * f["strength"] / 10
        else:
            flip_adj -= 0.5 * f["strength"] / 10

    score = round(max(0.0, min(10.0, cvd_dir_score + div_adj + flip_adj)), 2)
    cvd_trend = "bullish" if cvd_dir_score > 6 else "bearish" if cvd_dir_score < 4 else "neutral"

    return {
        "score": score,
        "cvd_trend": cvd_trend,
        "cvd_direction_score": round(cvd_dir_score, 2),
        "divergence": divergence["type"],
        "divergence_strength": divergence["strength"],
        "divergence_desc": divergence["description"],
        "delta_flips": len(recent_flips),
        "recent_flips": recent_flips[-3:],
        "details": divergence,
    }
