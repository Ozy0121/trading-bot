"""
smc_factors.py
--------------
Smart Money Concepts (SMC) layer detection for overnight quant scoring.

Uses the smartmoneyconcepts package to detect institutional order flow
patterns: Order Blocks, Liquidity Sweeps, Break of Structure / Change of
Character, and Fair Value Gaps.  Each pattern contributes to a 0-10 composite
score used as one factor in the multi-factor quant model (quant_factors.py).

Requires: smartmoneyconcepts>=0.0.27
Input:    DataFrame with lowercase columns (open, high, low, close, volume)
Output:   Float score 0.0-10.0
"""

from __future__ import annotations

import pandas as pd
import smartmoneyconcepts.smc as smc

from logger_setup import get_logger

log = get_logger()

# ── Minimum bars required for meaningful SMC analysis ────────────────────────
_MIN_BARS = 20


def compute_smc_score(df: pd.DataFrame) -> float:
    """Return a 0-10 SMC score from OHLCV daily bars.

    Scoring breakdown (max 10.0):
      - Order Blocks (bullish in last 5 bars):  up to 4.0
      - Liquidity Sweeps (last 10 bars):        up to 3.0
      - BOS / CHoCH (bullish in last 5 bars):   up to 2.0
      - Fair Value Gaps (bullish in last 5):     up to 1.0
    """
    if df is None or df.empty or len(df) < _MIN_BARS:
        return 0.0

    # ── Swings ───────────────────────────────────────────────────────────────
    try:
        swings = smc.swing_highs_lows(df, swing_length=5)
    except Exception as exc:
        log.warning("[smc] swing_highs_lows failed: %s", exc)
        return 0.0

    if swings["HighLow"].notna().sum() < 2:
        return 0.0

    total = 0.0

    # ── Order Blocks ─────────────────────────────────────────────────────────
    try:
        ob_result = smc.ob(df, swings, close_mitigation=False)
        bullish_ob_count = int((ob_result["OB"].tail(5) == 1).sum())
        total += min(bullish_ob_count * 1.5, 4.0)
    except Exception as exc:
        log.warning("[smc] ob() failed: %s", exc)

    # ── Liquidity Sweeps ─────────────────────────────────────────────────────
    try:
        liq_result = smc.liquidity(df, swings, range_percent=0.005)
        swept_count = int(liq_result["Swept"].tail(10).notna().sum())
        total += min(swept_count * 1.0, 3.0)
    except Exception as exc:
        log.warning("[smc] liquidity() failed: %s", exc)

    # ── BOS / CHoCH ──────────────────────────────────────────────────────────
    try:
        bos_result = smc.bos_choch(df, swings, close_break=True)
        tail5 = bos_result.tail(5)
        if (tail5["BOS"] == 1).any():
            total += 2.0
        elif (tail5["CHOCH"] == 1).any():
            total += 1.0
    except Exception as exc:
        log.warning("[smc] bos_choch() failed: %s", exc)

    # ── Fair Value Gaps ──────────────────────────────────────────────────────
    try:
        fvg_result = smc.fvg(df, join_consecutive=False)
        bullish_fvg_count = int((fvg_result["FVG"].tail(5) == 1).sum())
        total += min(bullish_fvg_count * 0.5, 1.0)
    except Exception as exc:
        log.warning("[smc] fvg() failed: %s", exc)

    return round(min(total, 10.0), 2)
