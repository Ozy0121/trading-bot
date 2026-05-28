"""
volume_profile.py
-----------------
Volume Profile computation from OHLCV bars.

Provides:
  - POC (Point of Control): price level with highest traded volume
  - VAH/VAL (Value Area High/Low): 70% of volume range centered on POC
  - HVN/LVN (High/Low Volume Nodes): thick vs thin price levels
  - Composite scoring for prediction engine integration

Uses close-location-value method to distribute bar volume across price bins,
matching the approach in order_flow.py for consistency.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from logger_setup import get_logger

log = get_logger()

# ── Constants ──────────────────────────────────────────────────────────────

DEFAULT_NUM_BINS = 50
VALUE_AREA_PCT = 0.70
HVN_THRESHOLD = 1.5   # bins with volume > 1.5x median
LVN_THRESHOLD = 0.5   # bins with volume < 0.5x median
MIN_BARS = 20


# ── Volume Profile computation ─────────────────────────────────────────────

def compute_volume_profile(df: pd.DataFrame, num_bins: int = DEFAULT_NUM_BINS) -> dict:
    """Compute Volume Profile from OHLCV bars.

    Distributes each bar's volume across price bins using close-location-value
    weighting (more volume allocated near the close price).

    Returns dict with poc_price, vah, val, hvn, lvn, profile, total_volume.
    """
    if df is None or len(df) < MIN_BARS:
        return _empty_profile()

    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    volume = df["volume"].values.astype(float)

    price_min = float(np.nanmin(low))
    price_max = float(np.nanmax(high))

    if price_max <= price_min or price_max <= 0:
        return _empty_profile()

    bin_size = (price_max - price_min) / num_bins
    if bin_size <= 0:
        return _empty_profile()

    bin_edges = np.linspace(price_min, price_max, num_bins + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    bin_volumes = np.zeros(num_bins, dtype=float)

    for i in range(len(df)):
        bar_low = low[i]
        bar_high = high[i]
        bar_close = close[i]
        bar_vol = volume[i]
        bar_range = bar_high - bar_low

        if bar_range <= 0 or bar_vol <= 0:
            continue

        first_bin = max(0, int((bar_low - price_min) / bin_size))
        last_bin = min(num_bins - 1, int((bar_high - price_min) / bin_size))

        for b in range(first_bin, last_bin + 1):
            bin_low = bin_edges[b]
            bin_high = bin_edges[b + 1]
            overlap_low = max(bar_low, bin_low)
            overlap_high = min(bar_high, bin_high)

            if overlap_high <= overlap_low:
                continue

            overlap_pct = (overlap_high - overlap_low) / bar_range
            center = (overlap_low + overlap_high) / 2
            close_dist = abs(center - bar_close) / bar_range
            clv_weight = 1.0 + (1.0 - close_dist) * 0.5

            bin_volumes[b] += bar_vol * overlap_pct * clv_weight

    total_volume = float(bin_volumes.sum())
    if total_volume <= 0:
        return _empty_profile()

    # POC: bin with highest volume
    poc_idx = int(np.argmax(bin_volumes))
    poc_price = float(bin_centers[poc_idx])

    # Value Area: expand from POC until 70% of volume captured
    vah_idx, val_idx = _compute_value_area(bin_volumes, poc_idx, VALUE_AREA_PCT)
    vah = float(bin_edges[min(vah_idx + 1, num_bins)])
    val = float(bin_edges[val_idx])

    # HVN/LVN detection
    nonzero = bin_volumes[bin_volumes > 0]
    median_vol = float(np.median(nonzero)) if len(nonzero) > 0 else 0.0

    hvn = []
    lvn = []
    if median_vol > 0:
        for b in range(num_bins):
            if bin_volumes[b] > median_vol * HVN_THRESHOLD:
                hvn.append(float(bin_centers[b]))
            elif 0 < bin_volumes[b] < median_vol * LVN_THRESHOLD:
                lvn.append(float(bin_centers[b]))

    profile = []
    for b in range(num_bins):
        profile.append({
            "price": round(float(bin_centers[b]), 4),
            "volume": round(float(bin_volumes[b]), 0),
            "pct_of_total": round(float(bin_volumes[b]) / total_volume * 100, 2) if total_volume > 0 else 0,
        })

    return {
        "poc_price": round(poc_price, 4),
        "vah": round(vah, 4),
        "val": round(val, 4),
        "hvn": [round(h, 4) for h in hvn],
        "lvn": [round(l, 4) for l in lvn],
        "profile": profile,
        "total_volume": round(total_volume, 0),
    }


def _compute_value_area(bin_volumes: np.ndarray, poc_idx: int, target_pct: float) -> tuple[int, int]:
    """Expand from POC bin alternately adding higher-volume adjacent bin."""
    total = bin_volumes.sum()
    if total <= 0:
        return poc_idx, poc_idx

    cumulative = bin_volumes[poc_idx]
    upper = poc_idx
    lower = poc_idx
    n = len(bin_volumes)

    while cumulative / total < target_pct:
        up_vol = bin_volumes[upper + 1] if upper + 1 < n else -1
        dn_vol = bin_volumes[lower - 1] if lower - 1 >= 0 else -1

        if up_vol < 0 and dn_vol < 0:
            break

        if up_vol >= dn_vol:
            upper += 1
            cumulative += bin_volumes[upper]
        else:
            lower -= 1
            cumulative += bin_volumes[lower]

    return upper, lower


def _empty_profile() -> dict:
    return {
        "poc_price": 0.0,
        "vah": 0.0,
        "val": 0.0,
        "hvn": [],
        "lvn": [],
        "profile": [],
        "total_volume": 0.0,
    }


# ── Volume Profile scoring ─────────────────────────────────────────────────

def score_volume_profile(df: pd.DataFrame, num_bins: int = DEFAULT_NUM_BINS) -> dict:
    """Score 0-10 based on Volume Profile signals for long entry.

    Components:
      - POC proximity (0-3): price near POC = key level interaction
      - Value Area position (0-3): below VAL = undervalued, above VAH = breakout
      - LVN proximity (0-2): near thin air = fast move expected
      - Profile shape (0-2): single POC trending vs multi-modal ranging
    """
    vp = compute_volume_profile(df, num_bins)

    if vp["total_volume"] <= 0 or vp["poc_price"] <= 0:
        return {"score": 5.0, "poc_price": 0, "vah": 0, "val": 0,
                "position": "unknown", "nearest_lvn": None,
                "profile_shape": "unknown", "details": {}}

    current_price = float(df["close"].iloc[-1])
    poc = vp["poc_price"]
    vah = vp["vah"]
    val = vp["val"]

    # Position classification
    if current_price < val:
        position = "below_value"
    elif current_price > vah:
        position = "above_value"
    else:
        position = "in_value"

    # POC proximity score (0-3)
    poc_dist_pct = abs(current_price - poc) / poc * 100 if poc > 0 else 100
    if poc_dist_pct < 0.5:
        poc_score = 3.0
    elif poc_dist_pct < 1.0:
        poc_score = 2.5
    elif poc_dist_pct < 2.0:
        poc_score = 1.5
    elif poc_dist_pct < 3.0:
        poc_score = 0.8
    else:
        poc_score = 0.0

    # Value Area position score (0-3)
    va_score = 0.0
    if position == "below_value":
        dist_below = (val - current_price) / val * 100 if val > 0 else 0
        if dist_below < 2.0:
            va_score = 3.0  # just below VA — mean reversion long
        elif dist_below < 4.0:
            va_score = 2.0
        else:
            va_score = 1.0  # too far below, might keep falling
    elif position == "above_value":
        # Check if it's a fresh breakout (close above VAH in last 2 bars)
        recent_closes = df["close"].iloc[-3:].values.astype(float)
        bars_above = sum(1 for c in recent_closes if c > vah)
        if bars_above <= 2:
            va_score = 2.5  # fresh breakout
        else:
            va_score = 1.0  # extended above value
    else:
        # In value area — near VAL is better for longs
        va_width = vah - val
        if va_width > 0:
            pos_in_va = (current_price - val) / va_width
            if pos_in_va < 0.3:
                va_score = 2.5  # near bottom of VA
            elif pos_in_va < 0.5:
                va_score = 1.5
            else:
                va_score = 0.5  # near top of VA, less upside

    # LVN proximity score (0-2)
    lvn_score = 0.0
    nearest_lvn = None
    if vp["lvn"]:
        above_lvns = [l for l in vp["lvn"] if l > current_price]
        if above_lvns:
            nearest_lvn = min(above_lvns)
            lvn_dist_pct = (nearest_lvn - current_price) / current_price * 100
            if lvn_dist_pct < 2.0:
                lvn_score = 2.0  # thin air just above — fast move likely
            elif lvn_dist_pct < 4.0:
                lvn_score = 1.0

    # Profile shape score (0-2)
    shape_score = 0.0
    profile_shape = "unknown"
    if vp["profile"]:
        volumes = [p["volume"] for p in vp["profile"] if p["volume"] > 0]
        if volumes:
            max_vol = max(volumes)
            peaks = sum(1 for v in volumes if v > max_vol * 0.7)
            if peaks <= 3:
                profile_shape = "trending"
                shape_score = 2.0
            else:
                profile_shape = "ranging"
                shape_score = 0.5

    total_score = round(min(10.0, poc_score + va_score + lvn_score + shape_score), 2)

    return {
        "score": total_score,
        "poc_price": round(poc, 2),
        "vah": round(vah, 2),
        "val": round(val, 2),
        "position": position,
        "nearest_lvn": round(nearest_lvn, 2) if nearest_lvn else None,
        "profile_shape": profile_shape,
        "details": {
            "poc_score": round(poc_score, 2),
            "va_score": round(va_score, 2),
            "lvn_score": round(lvn_score, 2),
            "shape_score": round(shape_score, 2),
            "poc_dist_pct": round(poc_dist_pct, 2),
            "current_price": round(current_price, 2),
        },
    }
