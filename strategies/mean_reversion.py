"""
strategies/mean_reversion.py
----------------------------
Mean reversion strategy — fires when RSI < 35 and price at/below lower Bollinger Band.

STRAT-03: Catch oversold stocks likely to revert to mean.
"""

from __future__ import annotations

import pandas as pd

from indicators import bollinger_bands, rsi as calc_rsi
from logger_setup import get_logger

log = get_logger()

MIN_BARS     = 22       # minimum bars needed for RSI(14) + BB(20)
RSI_THRESHOLD = 35.0
BB_TOLERANCE  = 1.02    # within 2% above lower BB counts as "at support"


def scan(symbol: str, df: pd.DataFrame) -> dict:
    """
    Scan a symbol for mean reversion setup.

    Fires when:
      - RSI(14) < 35 (oversold)
      - Last close <= lower Bollinger Band * 1.02 (at/near support)

    Returns dict with keys: strategy, fired, technical_score, volume_ratio, details.
    """
    _empty = {
        "strategy": "mean_reversion",
        "fired": False,
        "technical_score": 0.0,
        "volume_ratio": 1.0,
        "details": {},
    }

    if df is None or len(df) < MIN_BARS:
        log.debug("[mean_reversion] %s: insufficient bars (%d)",
                  symbol, len(df) if df is not None else 0)
        return _empty

    closes = df["close"]

    rsi_series             = calc_rsi(closes)
    bb_upper, _, bb_lower  = bollinger_bands(closes)

    # Latest values
    rsi_val      = float(rsi_series.dropna().iloc[-1]) if len(rsi_series.dropna()) > 0 else None
    bb_lower_val = float(bb_lower.dropna().iloc[-1])   if len(bb_lower.dropna())  > 0 else None
    last_close   = float(closes.iloc[-1])

    if rsi_val is None or bb_lower_val is None:
        return _empty

    # Fire conditions
    rsi_oversold = rsi_val < RSI_THRESHOLD
    at_bb_lower  = last_close <= bb_lower_val * BB_TOLERANCE
    fired        = rsi_oversold and at_bb_lower

    # Technical score: RSI-derived 0-10, +2 support bonus
    # Exponential curve: RSI=30 -> ~3.0, RSI=25 -> ~5.5, RSI=20 -> ~7.5, RSI=15 -> ~8.0
    # Clamp gap to >= 0 before raising to fractional power to avoid complex numbers
    rsi_gap    = max(0.0, RSI_THRESHOLD - rsi_val)
    rsi_score  = (rsi_gap / RSI_THRESHOLD) ** 0.6 * 10
    tech_score = min(8.0, rsi_score)
    if fired:
        tech_score = min(10.0, tech_score + 2.0)

    if fired:
        log.info("[mean_reversion] %s OVERSOLD: RSI=%.1f, close=%.2f <= BB_lower=%.2f",
                 symbol, rsi_val, last_close, bb_lower_val)

    return {
        "strategy":        "mean_reversion",
        "fired":           fired,
        "technical_score": round(tech_score, 2),
        "volume_ratio":    1.0,
        "details": {
            "rsi":           round(rsi_val, 2),
            "bb_lower":      round(bb_lower_val, 4),
            "last_close":    round(last_close, 4),
            "rsi_oversold":  rsi_oversold,
            "at_bb_lower":   at_bb_lower,
        },
    }
