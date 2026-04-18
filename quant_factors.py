"""
quant_factors.py
----------------
Multi-factor quant scoring model for the expanded scanner tier 4.

Combines four factors into a weighted composite score (0-10):
  - Momentum  (30%) — cross-sectional percentile rank of 20-day return
  - Quality   (25%) — OBV slope + ADL slope (institutional accumulation)
  - SMC       (25%) — Smart Money Concepts detection (order blocks, BOS, etc.)
  - Volatility(20%) — ATR contraction signals tighter risk (higher = better)

Factor weights per research decision D-02 / A1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import obv, adl, atr
from smc_factors import compute_smc_score
from logger_setup import get_logger

log = get_logger()

# ── Factor weights (must sum to 1.0) ────────────────────────────────────────
_W_MOMENTUM = 0.30
_W_QUALITY = 0.25
_W_SMC = 0.25
_W_VOLATILITY = 0.20


def rank_momentum(bars_by_symbol: dict[str, pd.DataFrame]) -> dict[str, float]:
    """Compute cross-sectional momentum percentile ranks.

    For each symbol, calculates the 20-day return, then ranks all symbols
    relative to each other.  Returns dict mapping symbol -> percentile (0.0-1.0).
    Symbols with fewer than 20 bars are excluded.
    """
    returns: dict[str, float] = {}

    for sym, df in bars_by_symbol.items():
        if df is None or len(df) < 20:
            continue
        closes = df["close"]
        ret = (closes.iloc[-1] - closes.iloc[-20]) / closes.iloc[-20]
        returns[sym] = float(ret)

    if not returns:
        return {}

    symbols = list(returns.keys())
    vals = np.array([returns[s] for s in symbols])

    n = len(vals)
    if n == 1:
        return {symbols[0]: 0.5}

    # Rank using argsort-of-argsort, then normalise to 0-1
    order = np.argsort(np.argsort(vals))
    ranks = order / (n - 1)

    return {sym: round(float(ranks[i]), 4) for i, sym in enumerate(symbols)}


def _compute_quality(df: pd.DataFrame) -> float:
    """Quality factor: OBV slope + ADL slope over last 20 bars.

    Positive OBV slope  -> +5.0  (institutional buying)
    Positive ADL slope  -> +5.0  (accumulation)
    Returns 0.0-10.0.
    """
    if len(df) < 5:
        return 0.0

    score = 0.0
    window = min(20, len(df))

    try:
        obv_series = obv(df)
        obv_tail = obv_series.iloc[-window:].values
        if len(obv_tail) >= 2:
            obv_slope = np.polyfit(range(len(obv_tail)), obv_tail, 1)[0]
            if obv_slope > 0:
                score += 5.0
    except Exception as exc:
        log.warning("[quant] OBV slope failed: %s", exc)

    try:
        adl_series = adl(df)
        adl_tail = adl_series.iloc[-window:].values
        if len(adl_tail) >= 2:
            adl_slope = np.polyfit(range(len(adl_tail)), adl_tail, 1)[0]
            if adl_slope > 0:
                score += 5.0
    except Exception as exc:
        log.warning("[quant] ADL slope failed: %s", exc)

    return min(score, 10.0)


def _compute_volatility(df: pd.DataFrame) -> float:
    """Volatility factor: ATR contraction relative to 20-day average.

    Lower current ATR% relative to average = higher score (tighter risk).
    Returns 0.0-10.0, default 5.0 (neutral) if data insufficient.
    """
    try:
        atr_series = atr(df, period=14)
        closes = df["close"]
        if atr_series.empty or closes.empty:
            return 5.0

        atr_pct = atr_series.iloc[-1] / closes.iloc[-1]
        atr_20d_avg = atr_series.tail(20).mean() / closes.tail(20).mean()

        if atr_20d_avg > 0:
            vol_ratio = atr_pct / atr_20d_avg
        else:
            vol_ratio = 1.0

        return max(0.0, min(10.0, (2.0 - vol_ratio) * 5.0))
    except Exception as exc:
        log.warning("[quant] volatility calc failed: %s", exc)
        return 5.0


def compute_quant_score(
    symbol: str,
    df: pd.DataFrame,
    momentum_rank: float,
) -> dict:
    """Compute multi-factor quant score for a single symbol.

    Parameters
    ----------
    symbol : str
        Ticker symbol (passed through to output dict).
    df : pd.DataFrame
        OHLCV DataFrame with lowercase columns.
    momentum_rank : float
        Pre-computed cross-sectional percentile rank (0.0-1.0) from
        rank_momentum().

    Returns
    -------
    dict with keys: symbol, quant_score, momentum_score, quality_score,
    smc_score, volatility_score.  All scores are floats in [0.0, 10.0].
    """
    momentum_score = round(float(momentum_rank) * 10.0, 2)
    quality_score = round(_compute_quality(df), 2)
    smc_score = round(compute_smc_score(df), 2)
    volatility_score = round(_compute_volatility(df), 2)

    composite = (
        _W_MOMENTUM * momentum_score
        + _W_QUALITY * quality_score
        + _W_SMC * smc_score
        + _W_VOLATILITY * volatility_score
    )

    return {
        "symbol": symbol,
        "quant_score": round(min(composite, 10.0), 2),
        "momentum_score": momentum_score,
        "quality_score": quality_score,
        "smc_score": smc_score,
        "volatility_score": volatility_score,
    }
