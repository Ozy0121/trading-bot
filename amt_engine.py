"""
amt_engine.py
-------------
Auction Market Theory (AMT) engine for market state classification.

Uses Volume Profile output to determine:
  - Market balance: price rotating inside Value Area vs breaking out
  - Initiative vs responsive activity: who is driving price
  - Urgency: how strong is the directional conviction

AMT framework:
  - Balanced market: price accepted within Value Area, low urgency
  - Imbalanced market: price rejected from Value Area, initiative activity
  - Testing: price probing VA boundaries, watching for acceptance or rejection
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from volume_profile import compute_volume_profile
from logger_setup import get_logger

log = get_logger()

# ── Constants ──────────────────────────────────────────────────────────────

MIN_BARS = 20
ACCEPTANCE_BARS = 2  # closes beyond VA boundary = "accepted"


# ── Market state classification ────────────────────────────────────────────

def classify_market_state(df: pd.DataFrame, vp: dict | None = None) -> dict:
    """Classify current market state using Auction Market Theory.

    States:
      - balanced: price rotating inside Value Area
      - imbalanced_up: price broke above VAH and accepted (2+ closes above)
      - imbalanced_down: price broke below VAL and accepted
      - testing_high: probing above VAH, not yet accepted
      - testing_low: probing below VAL, not yet accepted

    Returns dict with state, initiative, urgency, description, va_width_pct.
    """
    if df is None or len(df) < MIN_BARS:
        return _neutral_state()

    if vp is None:
        vp = compute_volume_profile(df)

    if vp["total_volume"] <= 0 or vp["vah"] <= vp["val"]:
        return _neutral_state()

    current_price = float(df["close"].iloc[-1])
    vah = vp["vah"]
    val = vp["val"]
    poc = vp["poc_price"]

    va_width = vah - val
    va_width_pct = (va_width / poc * 100) if poc > 0 else 0

    recent_closes = df["close"].iloc[-5:].values.astype(float)
    recent_volumes = df["volume"].iloc[-5:].values.astype(float)
    prior_volumes = df["volume"].iloc[-15:-5].values.astype(float)

    # Count closes above/below VA boundaries
    closes_above_vah = sum(1 for c in recent_closes if c > vah)
    closes_below_val = sum(1 for c in recent_closes if c < val)

    # Volume trend: increasing volume = initiative, decreasing = responsive
    avg_recent_vol = float(np.mean(recent_volumes)) if len(recent_volumes) > 0 else 0
    avg_prior_vol = float(np.mean(prior_volumes)) if len(prior_volumes) > 0 else 1
    vol_ratio = avg_recent_vol / avg_prior_vol if avg_prior_vol > 0 else 1.0

    # Classify state
    if current_price > vah:
        if closes_above_vah >= ACCEPTANCE_BARS:
            state = "imbalanced_up"
            initiative = "buyers"
            urgency = min(5, 3 + int(vol_ratio > 1.3) + int(closes_above_vah >= 3))
            description = f"Price accepted above Value Area (${vah:.2f}), initiative buying"
        else:
            state = "testing_high"
            initiative = "buyers" if vol_ratio > 1.2 else "neutral"
            urgency = 2
            description = f"Probing above VAH ${vah:.2f} — watching for acceptance or rejection"
    elif current_price < val:
        if closes_below_val >= ACCEPTANCE_BARS:
            state = "imbalanced_down"
            initiative = "sellers"
            urgency = min(5, 3 + int(vol_ratio > 1.3) + int(closes_below_val >= 3))
            description = f"Price accepted below Value Area (${val:.2f}), initiative selling"
        else:
            state = "testing_low"
            initiative = "sellers" if vol_ratio > 1.2 else "neutral"
            urgency = 2
            description = f"Probing below VAL ${val:.2f} — watching for bounce or breakdown"
    else:
        state = "balanced"
        pos_in_va = (current_price - val) / va_width if va_width > 0 else 0.5
        if pos_in_va < 0.3:
            initiative = "buyers" if vol_ratio > 1.1 else "neutral"
            urgency = 2 if vol_ratio > 1.2 else 1
            description = f"Balanced near VAL ${val:.2f} — responsive buyers expected"
        elif pos_in_va > 0.7:
            initiative = "sellers" if vol_ratio > 1.1 else "neutral"
            urgency = 2 if vol_ratio > 1.2 else 1
            description = f"Balanced near VAH ${vah:.2f} — responsive sellers expected"
        else:
            initiative = "neutral"
            urgency = 1
            description = "Balanced mid-range — no directional edge"

    return {
        "state": state,
        "initiative": initiative,
        "urgency": urgency,
        "description": description,
        "va_width_pct": round(va_width_pct, 2),
    }


def _neutral_state() -> dict:
    return {
        "state": "balanced",
        "initiative": "neutral",
        "urgency": 1,
        "description": "Insufficient data for AMT classification",
        "va_width_pct": 0.0,
    }


# ── AMT scoring ────────────────────────────────────────────────────────────

def score_amt(df: pd.DataFrame, vp: dict | None = None) -> dict:
    """Score 0-10 for long entry attractiveness using AMT framework.

    Scoring matrix:
      - balanced + near VAL: 7-8 (mean reversion long at value area low)
      - imbalanced_up: 8-10 (breakout confirmed, momentum long)
      - testing_low + signs of rejection: 6-7 (responsive buying, bounce)
      - balanced + mid-range: 4-5 (no edge)
      - imbalanced_down: 0-2 (sellers in control, avoid longs)
      - testing_high: 3-5 (risky — could reject)
    """
    if df is None or len(df) < MIN_BARS:
        return {"score": 5.0, "state": "balanced", "initiative": "neutral",
                "setup_type": "none", "description": "Insufficient data"}

    if vp is None:
        vp = compute_volume_profile(df)

    ms = classify_market_state(df, vp)
    state = ms["state"]
    initiative = ms["initiative"]
    urgency = ms["urgency"]

    val = vp["val"]
    vah = vp["vah"]
    va_width = vah - val
    current_price = float(df["close"].iloc[-1])

    score = 5.0
    setup_type = "none"

    if state == "imbalanced_up":
        score = 7.0 + min(3.0, urgency * 0.6)
        setup_type = "breakout_long"
    elif state == "imbalanced_down":
        score = max(0.0, 2.0 - urgency * 0.4)
        setup_type = "avoid"
    elif state == "testing_high":
        score = 4.0 if initiative == "buyers" else 3.0
        setup_type = "risky_breakout"
    elif state == "testing_low":
        # Check for rejection candle (close above open in last bar)
        last_open = float(df["open"].iloc[-1])
        if current_price > last_open:
            score = 6.5 + min(0.5, urgency * 0.1)
            setup_type = "bounce_long"
        else:
            score = 3.0
            setup_type = "breakdown_risk"
    elif state == "balanced":
        if va_width > 0:
            pos_in_va = (current_price - val) / va_width
            if pos_in_va < 0.3:
                score = 7.0 + min(1.0, (0.3 - pos_in_va) * 10)
                setup_type = "value_area_long"
            elif pos_in_va < 0.5:
                score = 5.5
                setup_type = "neutral"
            else:
                score = 4.0 - (pos_in_va - 0.5) * 2
                setup_type = "near_resistance"

    score = round(max(0.0, min(10.0, score)), 2)

    return {
        "score": score,
        "state": state,
        "initiative": initiative,
        "setup_type": setup_type,
        "description": ms["description"],
    }
