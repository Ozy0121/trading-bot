"""
strategies/momentum.py
----------------------
Momentum breakout strategy — fires when price breaks N-day high on 2x+ volume.

STRAT-02: Detect stocks making new 20-day highs with significantly elevated volume.
"""

from __future__ import annotations

import pandas as pd

from indicators import bollinger_bands, rsi
from logger_setup import get_logger

log = get_logger()

LOOKBACK = 20      # N-day high window
MIN_VOLUME_RATIO = 2.0


def scan(symbol: str, df: pd.DataFrame) -> dict:
    """
    Scan a symbol for momentum breakout setup.

    Fires when:
      - Last close > rolling 20-day high (excluding last bar)
      - Current volume >= 2x average volume over last 20 bars

    Returns dict with keys: strategy, fired, technical_score, volume_ratio, details.
    """
    _empty = {
        "strategy": "momentum",
        "fired": False,
        "technical_score": 0.0,
        "volume_ratio": 0.0,
        "details": {},
    }

    if df is None or len(df) < LOOKBACK + 1:
        log.debug("[momentum] %s: insufficient bars (%d)", symbol, len(df) if df is not None else 0)
        return _empty

    closes  = df["close"]
    volumes = df["volume"]

    last_close  = float(closes.iloc[-1])
    last_volume = float(volumes.iloc[-1])

    # Rolling 20-day high excluding the current bar
    prior_closes = closes.iloc[-(LOOKBACK + 1):-1]
    n_day_high   = float(prior_closes.max())

    # Volume ratio vs 20-bar average (excluding last bar)
    prior_vols   = volumes.iloc[-(LOOKBACK + 1):-1]
    avg_volume   = float(prior_vols.mean()) if len(prior_vols) > 0 else 1.0
    volume_ratio = last_close / 1.0  # placeholder reset below
    volume_ratio = last_volume / avg_volume if avg_volume > 0 else 0.0

    # Breakout condition
    broke_high = last_close > n_day_high
    vol_ok     = volume_ratio >= MIN_VOLUME_RATIO
    fired      = broke_high and vol_ok

    # Technical score: proximity to N-day high (0–10), +2 breakout bonus
    proximity_score = max(0.0, (last_close - n_day_high) / n_day_high * 100) if n_day_high > 0 else 0.0
    # Clamp proximity contribution to 0-8
    tech_score = min(8.0, proximity_score)
    if fired:
        tech_score = min(10.0, tech_score + 2.0)

    if fired:
        log.info("[momentum] %s BREAKOUT: close=%.2f > %.2f high, vol_ratio=%.1fx",
                 symbol, last_close, n_day_high, volume_ratio)

    return {
        "strategy":        "momentum",
        "fired":           fired,
        "technical_score": round(tech_score, 2),
        "volume_ratio":    round(volume_ratio, 2),
        "details": {
            "last_close":   round(last_close, 4),
            "n_day_high":   round(n_day_high, 4),
            "broke_high":   broke_high,
            "avg_volume":   round(avg_volume, 0),
            "last_volume":  round(last_volume, 0),
        },
    }
