"""
prediction.py
-------------
Pre-spike prediction engine v2 — improved accuracy over v1's retail patterns.

Key improvements over v1 (33% accuracy):
  1. Trend filter: rejects downtrending stocks (SMA20 < SMA50)
  2. Keltner-within-Bollinger squeeze: more reliable than BB-only
  3. OBV/ADL divergence: detects real institutional money flow
  4. ATR-based stops: tighter, volatility-adjusted
  5. Weighted scoring: patterns ranked by predictive value
  6. Volume gate: requires at least one volume signal to confirm
  7. Market structure shift: detects trend reversals via swing highs

Pattern library (weighted by predictive value):
  1. Keltner squeeze (weight 2.0): KC inside BB = extreme compression
  2. OBV divergence (weight 1.8): OBV rising while price flat = stealth buying
  3. ADL divergence (weight 1.5): money flow positive while price quiet
  4. Volume accumulation (weight 1.5): volume building while price flat
  5. Higher lows + market structure (weight 1.3): coiling with structure shift
  6. MACD launch zone (weight 1.0): histogram converging, RSI in sweet spot
  7. Relative strength (weight 0.8): outperforming SPY quietly
"""

from __future__ import annotations

import threading
from datetime import date
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd
import yfinance as yf

from indicators import (
    rsi as calc_rsi,
    macd as calc_macd,
    bollinger_bands,
    keltner_channels,
    atr as calc_atr,
    obv as calc_obv,
    adl as calc_adl,
)
from logger_setup import get_logger
from yf_limiter import rate_limited_yf, get_spy_history

log = get_logger()

# ── Constants ────────────────────────────────────────────────────────────────

# Trend filter: SMA periods
TREND_SMA_FAST = 20
TREND_SMA_SLOW = 50

# Keltner squeeze: KC inside BB = extreme compression
KC_SQUEEZE_LOOKBACK = 20   # bars to check for squeeze condition

# OBV divergence: OBV slope vs price slope
OBV_LOOKBACK = 10          # bars to measure OBV slope
OBV_MIN_DIVERGENCE = 0.5   # OBV slope must be this much steeper (normalized)

# ADL divergence
ADL_LOOKBACK = 10

# Volume accumulation: volume rising while price stays flat
VOL_ACCUM_DAYS = 5
VOL_ACCUM_PRICE_RANGE = 0.03    # price range < 3% = "flat"
VOL_ACCUM_MIN_INCREASE = 1.3    # avg volume last 3 days >= 1.3x prior 10

# Higher lows (coiling) + market structure shift
COIL_MIN_LOWS = 3
COIL_LOOKBACK = 20

# MACD launch zone
MACD_HIST_FLAT_THRESHOLD = 0.15
MACD_RSI_LOW = 40.0
MACD_RSI_HIGH = 55.0

# Relative strength
REL_STRENGTH_DAYS = 5

# Historical pattern matching
HIST_LOOKBACK_DAYS = 365
HIST_MIN_SAMPLES = 10
HIST_FORWARD_DAYS = 3
HIST_WIN_THRESHOLD = 0.03  # 3%+ gain = a "win"

# Overall prediction
MIN_CONFIDENCE = 5          # out of 10; below this we skip
MIN_HISTORICAL_ACCURACY = 0.50  # lowered from 0.60 — let confidence scoring handle quality

# ATR-based stop loss
STOP_ATR_MULTIPLIER = 1.5  # stop = entry - 1.5 * ATR

# Fair Value Gaps
FVG_MAX_AGE_BARS = 20       # ignore FVGs older than this
FVG_PROXIMITY_PCT = 2.0     # price must be within 2% of FVG midpoint

# Multi-timeframe confirmation
MTF_WEEKLY_MA = 10           # 10-week moving average for weekly trend

# Pattern weights: how much each pattern contributes to final score
PATTERN_WEIGHTS = {
    "keltner_squeeze":     2.0,
    "obv_divergence":      1.8,
    "adl_divergence":      1.5,
    "volume_accumulation": 1.5,
    "higher_lows":         1.3,
    "fair_value_gap":      1.2,
    "macd_launch_zone":    1.0,
    "relative_strength":   0.8,
}

# Cache for historical analysis
_hist_cache: dict[str, tuple[date, dict]] = {}
_hist_lock = threading.Lock()


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class PatternResult:
    """Result from a single pattern detector."""
    name: str
    detected: bool
    score: float          # 0-10 contribution to prediction
    category: str = ""    # "volume", "price", "momentum" — for gate checks
    details: dict = field(default_factory=dict)


@dataclass
class Prediction:
    """Complete prediction output for a stock."""
    symbol: str
    predicted_spike: bool
    confidence: int                  # 1-10
    stage: str
    expected_move_pct: float
    entry_low: float
    entry_high: float
    target_price: float
    stop_loss: float
    historical_accuracy: float
    historical_samples: int
    patterns: list[PatternResult] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    timeframe: str = "1-3 days"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["patterns"] = [asdict(p) for p in self.patterns]
        return d


# ── Trend filter ─────────────────────────────────────────────────────────────

def _is_uptrending(df: pd.DataFrame) -> bool:
    """
    Reject stocks in downtrends. Requires:
    1. SMA20 > SMA50 (short-term trend above long-term)
    2. Price above SMA20 (not pulling back too far)
    """
    closes = df["close"]
    if len(closes) < TREND_SMA_SLOW + 5:
        return False

    sma_fast = closes.rolling(TREND_SMA_FAST).mean()
    sma_slow = closes.rolling(TREND_SMA_SLOW).mean()

    current_price = float(closes.iloc[-1])
    sma_f = float(sma_fast.iloc[-1])
    sma_s = float(sma_slow.iloc[-1])

    # SMA20 must be above SMA50 and price must be near or above SMA20
    return sma_f > sma_s and current_price >= sma_f * 0.97


# ── Pattern detectors ────────────────────────────────────────────────────────

def detect_keltner_squeeze(df: pd.DataFrame) -> PatternResult:
    """
    Keltner Channel squeeze within Bollinger Bands.
    When KC fits entirely inside BB, volatility is extremely compressed.
    More reliable than BB squeeze alone — filters out false squeezes.
    """
    if len(df) < KC_SQUEEZE_LOOKBACK + 10:
        return PatternResult("keltner_squeeze", False, 0.0, "price")

    closes = df["close"]
    bb_upper, _, bb_lower = bollinger_bands(closes)
    kc_upper, _, kc_lower = keltner_channels(df)

    # Check last few bars for squeeze condition (KC inside BB)
    squeeze_bars = 0
    check_range = min(5, len(df))
    for i in range(-check_range, 0):
        bb_u = float(bb_upper.iloc[i]) if not pd.isna(bb_upper.iloc[i]) else 0
        bb_l = float(bb_lower.iloc[i]) if not pd.isna(bb_lower.iloc[i]) else 0
        kc_u = float(kc_upper.iloc[i]) if not pd.isna(kc_upper.iloc[i]) else 0
        kc_l = float(kc_lower.iloc[i]) if not pd.isna(kc_lower.iloc[i]) else 0

        if bb_u > 0 and kc_u > 0:
            if kc_l > bb_l and kc_u < bb_u:
                squeeze_bars += 1

    detected = squeeze_bars >= 3  # squeeze present in at least 3 of last 5 bars

    # Score based on squeeze intensity and duration
    score = 0.0
    if detected:
        # Measure how tight: 1 - (KC width / BB width); closer to 1.0 = tighter
        bb_width = float(bb_upper.iloc[-1] - bb_lower.iloc[-1])
        kc_width = float(kc_upper.iloc[-1] - kc_lower.iloc[-1])
        if bb_width > 0:
            tightness = 1.0 - (kc_width / bb_width)
            score = min(10.0, 5.0 + tightness * 4.0 + squeeze_bars * 0.5)

    return PatternResult(
        "keltner_squeeze",
        detected,
        round(score, 1),
        "price",
        {
            "squeeze_bars": squeeze_bars,
            "check_range": check_range,
        },
    )


def detect_obv_divergence(df: pd.DataFrame) -> PatternResult:
    """
    OBV (On-Balance Volume) divergence: OBV trending up while price flat/down.
    This means big buyers are accumulating shares quietly.
    """
    if len(df) < OBV_LOOKBACK + 5:
        return PatternResult("obv_divergence", False, 0.0, "volume")

    obv_series = calc_obv(df)
    closes = df["close"]

    # Compute slopes over lookback period using linear regression
    x = np.arange(OBV_LOOKBACK, dtype=float)
    obv_window = obv_series.iloc[-OBV_LOOKBACK:].values.astype(float)
    price_window = closes.iloc[-OBV_LOOKBACK:].values.astype(float)

    # Normalize by mean absolute value to avoid amplification when start is near zero
    obv_denom = float(np.abs(obv_window).mean()) or 1.0
    price_denom = float(np.abs(price_window).mean()) or 1.0
    obv_norm = (obv_window - obv_window[0]) / obv_denom
    price_norm = (price_window - price_window[0]) / price_denom

    # Linear regression slopes
    obv_slope = float(np.polyfit(x, obv_norm, 1)[0])
    price_slope = float(np.polyfit(x, price_norm, 1)[0])

    # Divergence: OBV rising while price flat or slightly down
    divergence = obv_slope - price_slope
    price_flat = abs(price_slope) < 0.005  # less than 0.5% per bar
    obv_rising = obv_slope > 0.002

    detected = obv_rising and (price_flat or price_slope < 0) and divergence > OBV_MIN_DIVERGENCE

    score = 0.0
    if detected:
        score = min(10.0, 5.0 + divergence * 5.0)

    return PatternResult(
        "obv_divergence",
        detected,
        round(score, 1),
        "volume",
        {
            "obv_slope": round(obv_slope, 4),
            "price_slope": round(price_slope, 4),
            "divergence": round(divergence, 4),
        },
    )


def detect_adl_divergence(df: pd.DataFrame) -> PatternResult:
    """
    Accumulation/Distribution Line divergence: ADL rising while price flat.
    ADL uses intrabar position (close relative to high-low range) so it
    captures institutional buying even when price doesn't move much.
    """
    if len(df) < ADL_LOOKBACK + 5:
        return PatternResult("adl_divergence", False, 0.0, "volume")

    adl_series = calc_adl(df)
    closes = df["close"]

    x = np.arange(ADL_LOOKBACK, dtype=float)
    adl_window = adl_series.iloc[-ADL_LOOKBACK:].values.astype(float)
    price_window = closes.iloc[-ADL_LOOKBACK:].values.astype(float)

    adl_denom = float(np.abs(adl_window).mean()) or 1.0
    price_denom = float(np.abs(price_window).mean()) or 1.0
    adl_norm = (adl_window - adl_window[0]) / adl_denom
    price_norm = (price_window - price_window[0]) / price_denom

    adl_slope = float(np.polyfit(x, adl_norm, 1)[0])
    price_slope = float(np.polyfit(x, price_norm, 1)[0])

    divergence = adl_slope - price_slope
    price_flat = abs(price_slope) < 0.005
    adl_rising = adl_slope > 0.002

    detected = adl_rising and (price_flat or price_slope < 0) and divergence > 0.3

    score = 0.0
    if detected:
        score = min(10.0, 5.0 + divergence * 4.0)

    return PatternResult(
        "adl_divergence",
        detected,
        round(score, 1),
        "volume",
        {
            "adl_slope": round(adl_slope, 4),
            "price_slope": round(price_slope, 4),
            "divergence": round(divergence, 4),
        },
    )


def detect_volume_accumulation(df: pd.DataFrame) -> PatternResult:
    """
    Volume building over 3-5 days while price stays flat.
    Big players quietly buying before a move.
    """
    if len(df) < VOL_ACCUM_DAYS + 10:
        return PatternResult("volume_accumulation", False, 0.0, "volume")

    closes = df["close"].iloc[-(VOL_ACCUM_DAYS + 10):]
    volumes = df["volume"].iloc[-(VOL_ACCUM_DAYS + 10):]

    recent_closes = closes.iloc[-VOL_ACCUM_DAYS:]
    price_range = (float(recent_closes.max()) - float(recent_closes.min())) / float(recent_closes.mean())
    price_flat = price_range < VOL_ACCUM_PRICE_RANGE

    recent_vol = float(volumes.iloc[-3:].mean())
    prior_vol = float(volumes.iloc[-13:-3].mean()) if len(volumes) >= 13 else float(volumes.mean())
    vol_increase = recent_vol / prior_vol if prior_vol > 0 else 1.0

    last_5_vols = volumes.iloc[-VOL_ACCUM_DAYS:]
    vol_trending_up = 0
    for i in range(1, len(last_5_vols)):
        if float(last_5_vols.iloc[i]) > float(last_5_vols.iloc[i - 1]):
            vol_trending_up += 1
    vol_trend_pct = vol_trending_up / max(1, len(last_5_vols) - 1)

    detected = price_flat and vol_increase >= VOL_ACCUM_MIN_INCREASE

    score = 0.0
    if detected:
        score = min(10.0, 5.0 + (vol_increase - 1.0) * 5.0 + vol_trend_pct * 3.0)

    return PatternResult(
        "volume_accumulation",
        detected,
        round(score, 1),
        "volume",
        {
            "price_range_pct": round(price_range * 100, 2),
            "price_flat": price_flat,
            "vol_increase_ratio": round(vol_increase, 2),
            "vol_trend_pct": round(vol_trend_pct * 100, 1),
        },
    )


def detect_higher_lows(df: pd.DataFrame) -> PatternResult:
    """
    Price making higher lows — coiling for breakout.
    Enhanced with market structure shift detection: if the most recent
    swing high is broken, it confirms the trend reversal.
    """
    if len(df) < COIL_LOOKBACK + 2:
        return PatternResult("higher_lows", False, 0.0, "price")

    lows = df["low"].iloc[-COIL_LOOKBACK:]
    highs = df["high"].iloc[-COIL_LOOKBACK:]

    # Find swing lows
    swing_lows = []
    for i in range(1, len(lows) - 1):
        if float(lows.iloc[i]) < float(lows.iloc[i - 1]) and float(lows.iloc[i]) < float(lows.iloc[i + 1]):
            swing_lows.append(float(lows.iloc[i]))

    if len(swing_lows) < COIL_MIN_LOWS:
        return PatternResult("higher_lows", False, 0.0, "price")

    ascending_count = 0
    for i in range(1, len(swing_lows)):
        if swing_lows[i] > swing_lows[i - 1]:
            ascending_count += 1
    ascending_pct = ascending_count / max(1, len(swing_lows) - 1)

    detected = ascending_pct >= 0.6

    # Market structure shift bonus: check if recent price broke above
    # the most recent swing high (confirms trend reversal)
    swing_highs = []
    for i in range(1, len(highs) - 1):
        if float(highs.iloc[i]) > float(highs.iloc[i - 1]) and float(highs.iloc[i]) > float(highs.iloc[i + 1]):
            swing_highs.append(float(highs.iloc[i]))

    mss_bonus = 0.0
    if swing_highs:
        last_swing_high = swing_highs[-1]
        current_close = float(df["close"].iloc[-1])
        if current_close > last_swing_high:
            mss_bonus = 2.0  # market structure shift confirmed

    score = 0.0
    if detected:
        score = min(10.0, ascending_pct * 8.0 + mss_bonus)

    return PatternResult(
        "higher_lows",
        detected,
        round(score, 1),
        "price",
        {
            "swing_lows_found": len(swing_lows),
            "ascending_pct": round(ascending_pct * 100, 1),
            "last_3_lows": [round(l, 4) for l in swing_lows[-3:]],
            "mss_confirmed": mss_bonus > 0,
        },
    )


def detect_macd_launch_zone(df: pd.DataFrame) -> PatternResult:
    """
    MACD histogram flattening near zero and about to cross while RSI 40-55.
    """
    closes = df["close"]
    if len(closes) < 30:
        return PatternResult("macd_launch_zone", False, 0.0, "momentum")

    rsi_series = calc_rsi(closes)
    _, _, hist = calc_macd(closes)

    rsi_val = float(rsi_series.dropna().iloc[-1]) if len(rsi_series.dropna()) > 0 else 50.0
    hist_vals = hist.dropna()
    if len(hist_vals) < 5:
        return PatternResult("macd_launch_zone", False, 0.0, "momentum")

    current_hist = float(hist_vals.iloc[-1])
    prev_hist = float(hist_vals.iloc[-2])

    # Normalize threshold by price so it works for $5 and $500 stocks alike
    current_price = float(closes.iloc[-1])
    hist_threshold = current_price * 0.003 if current_price > 0 else MACD_HIST_FLAT_THRESHOLD
    hist_flat = abs(current_hist) < hist_threshold
    hist_improving = current_hist > prev_hist

    last3 = [abs(float(hist_vals.iloc[i])) for i in range(-3, 0)]
    converging = all(last3[i] >= last3[i + 1] for i in range(len(last3) - 1))

    rsi_in_zone = MACD_RSI_LOW <= rsi_val <= MACD_RSI_HIGH

    detected = (hist_flat or converging) and hist_improving and rsi_in_zone

    score = 0.0
    if detected:
        rsi_center_dist = abs(rsi_val - 47.5) / 7.5
        score = min(10.0, 7.0 + (1.0 - rsi_center_dist) * 3.0)
        if converging:
            score = min(10.0, score + 1.0)

    return PatternResult(
        "macd_launch_zone",
        detected,
        round(score, 1),
        "momentum",
        {
            "rsi": round(rsi_val, 1),
            "macd_hist": round(current_hist, 4),
            "hist_improving": hist_improving,
            "hist_converging": converging,
            "rsi_in_zone": rsi_in_zone,
        },
    )


def detect_relative_strength(
    df: pd.DataFrame,
    sector_etf: str = "SPY",
    spy_df: pd.DataFrame | None = None,
) -> PatternResult:
    """Stock quietly outperforming SPY for 3+ days."""
    if len(df) < REL_STRENGTH_DAYS + 2:
        return PatternResult("relative_strength", False, 0.0, "momentum")

    try:
        spy = spy_df if spy_df is not None else get_spy_history(period="10d", interval="1d")
        if spy is None or len(spy) < REL_STRENGTH_DAYS:
            return PatternResult("relative_strength", False, 0.0, "momentum")
    except Exception:
        return PatternResult("relative_strength", False, 0.0, "momentum")

    stock_closes = df["close"].iloc[-REL_STRENGTH_DAYS:]
    spy_closes = spy["close"].iloc[-REL_STRENGTH_DAYS:]

    if len(stock_closes) < REL_STRENGTH_DAYS or len(spy_closes) < REL_STRENGTH_DAYS:
        return PatternResult("relative_strength", False, 0.0, "momentum")

    stock_returns = stock_closes.pct_change().dropna()
    spy_returns = spy_closes.pct_change().dropna()

    min_len = min(len(stock_returns), len(spy_returns))
    if min_len < 3:
        return PatternResult("relative_strength", False, 0.0, "momentum")

    outperform_days = 0
    for i in range(min_len):
        if float(stock_returns.iloc[i]) > float(spy_returns.iloc[i]):
            outperform_days += 1

    outperform_pct = outperform_days / min_len
    detected = outperform_days >= 3

    stock_cum = float((1 + stock_returns.iloc[:min_len]).prod() - 1)
    spy_cum = float((1 + spy_returns.iloc[:min_len]).prod() - 1)
    relative_return = stock_cum - spy_cum

    score = 0.0
    if detected:
        score = min(10.0, 5.0 + outperform_pct * 5.0 + max(0, relative_return) * 50)

    return PatternResult(
        "relative_strength",
        detected,
        round(score, 1),
        "momentum",
        {
            "outperform_days": outperform_days,
            "total_days": min_len,
            "stock_return_pct": round(stock_cum * 100, 2),
            "benchmark_return_pct": round(spy_cum * 100, 2),
            "relative_return_pct": round(relative_return * 100, 2),
        },
    )


def detect_fair_value_gap(df: pd.DataFrame) -> PatternResult:
    """
    Fair Value Gap (FVG): gap between bar[i-1].high and bar[i+1].low.
    These imbalanced zones tend to fill (~65% within 5 sessions).
    Bullish signal when price is near an unfilled bullish FVG.
    """
    if len(df) < FVG_MAX_AGE_BARS + 3:
        return PatternResult("fair_value_gap", False, 0.0, "price")

    current_price = float(df["close"].iloc[-1])
    recent = df.iloc[-FVG_MAX_AGE_BARS:]

    best_fvg = None
    best_score = 0.0

    for i in range(1, len(recent) - 1):
        gap_bottom = float(recent["high"].iloc[i - 1])
        gap_top = float(recent["low"].iloc[i + 1])

        if gap_top <= gap_bottom:
            continue  # no gap

        fvg_mid = (gap_top + gap_bottom) / 2
        fvg_size_pct = (gap_top - gap_bottom) / float(recent["close"].iloc[i]) * 100

        # Check if FVG is still unfilled (price hasn't fully closed the gap)
        filled = False
        for j in range(i + 2, len(recent)):
            if float(recent["low"].iloc[j]) <= gap_bottom:
                filled = True
                break

        if filled:
            continue

        # Proximity: is current price near this FVG?
        distance_pct = abs(current_price - fvg_mid) / fvg_mid * 100
        if distance_pct > FVG_PROXIMITY_PCT:
            continue

        # Check volume on the impulse candle (bar i)
        avg_vol = float(df["volume"].iloc[-20:].mean())
        impulse_vol = float(recent["volume"].iloc[i])
        vol_confirm = impulse_vol > avg_vol * 1.5

        score = min(10.0, fvg_size_pct * 5.0)
        if vol_confirm:
            score = min(10.0, score + 2.0)

        if score > best_score:
            best_score = score
            best_fvg = {
                "fvg_bottom": round(gap_bottom, 2),
                "fvg_top": round(gap_top, 2),
                "fvg_mid": round(fvg_mid, 2),
                "fvg_size_pct": round(fvg_size_pct, 2),
                "distance_pct": round(distance_pct, 2),
                "vol_confirmed": vol_confirm,
                "bars_ago": len(recent) - 1 - i,
            }

    detected = best_fvg is not None and best_score >= 3.0

    return PatternResult(
        "fair_value_gap",
        detected,
        round(best_score, 1) if detected else 0.0,
        "price",
        best_fvg or {},
    )


def _weekly_trend_modifier(df: pd.DataFrame) -> float:
    """
    Multi-timeframe confirmation: weekly trend alignment as a score modifier.
    Returns a bonus/penalty: +1.5 if weekly trend aligned, -1.5 if against.
    """
    if len(df) < MTF_WEEKLY_MA * 5 + 5:  # need ~50 daily bars for 10 weekly bars
        return 0.0

    # Resample daily to weekly
    weekly = df.resample("W").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()

    if len(weekly) < MTF_WEEKLY_MA + 1:
        return 0.0

    weekly_ma = weekly["close"].rolling(MTF_WEEKLY_MA).mean()
    current_weekly = float(weekly["close"].iloc[-1])
    ma_val = float(weekly_ma.iloc[-1]) if not pd.isna(weekly_ma.iloc[-1]) else 0

    if ma_val <= 0:
        return 0.0

    above_weekly_ma = current_weekly > ma_val
    weekly_green = float(weekly["close"].iloc[-1]) > float(weekly["close"].iloc[-2])

    # Weekly RSI overbought check
    weekly_rsi = calc_rsi(weekly["close"])
    w_rsi_val = float(weekly_rsi.dropna().iloc[-1]) if len(weekly_rsi.dropna()) > 0 else 50.0

    if above_weekly_ma and weekly_green:
        bonus = 1.5
        if w_rsi_val > 70:
            bonus -= 1.0  # overbought on weekly reduces bonus
        return bonus
    elif not above_weekly_ma:
        return -1.5  # against weekly trend
    return 0.0


# ── Historical pattern matching ──────────────────────────────────────────────

def _compute_historical_accuracy(
    symbol: str,
    current_patterns: list[PatternResult],
    bar_df: pd.DataFrame | None = None,
) -> dict:
    """
    Look back at historical data: when similar patterns appeared, what happened?
    """
    today = date.today()

    with _hist_lock:
        cached = _hist_cache.get(symbol)
        if cached and cached[0] == today:
            return cached[1]

    try:
        if bar_df is not None and len(bar_df) >= 60:
            hist = bar_df
        else:
            hist = rate_limited_yf(
                lambda: yf.Ticker(symbol).history(period="1y", interval="1d")
            )
            if hist is None or len(hist) < 60:
                return {"accuracy": 0.0, "samples": 0, "avg_move": 0.0, "expected_move": 0.0}
            hist.columns = [c.lower() for c in hist.columns]

        closes = hist["close"]
        volumes = hist["volume"]

        bb_upper, bb_mid, bb_lower = bollinger_bands(closes)
        bandwidth = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)
        rsi_series = calc_rsi(closes)
        _, _, macd_hist = calc_macd(closes)

        active_pattern_names = {p.name for p in current_patterns if p.detected}
        if not active_pattern_names:
            result = {"accuracy": 0.0, "samples": 0, "avg_move": 0.0, "expected_move": 0.0}
            with _hist_lock:
                _hist_cache[symbol] = (today, result)
            return result

        wins = 0
        total = 0
        moves = []

        for i in range(35, len(closes) - HIST_FORWARD_DAYS):
            match_count = 0
            patterns_to_check = len(active_pattern_names)

            if "keltner_squeeze" in active_pattern_names or "bb_squeeze" in active_pattern_names:
                bw_window = bandwidth.iloc[max(0, i - 20):i + 1].dropna()
                if len(bw_window) >= 10:
                    current_bw = float(bw_window.iloc[-1])
                    pctile = float((bw_window < current_bw).sum() / len(bw_window) * 100)
                    if pctile <= 20:
                        match_count += 1

            if "macd_launch_zone" in active_pattern_names:
                rsi_val = float(rsi_series.iloc[i]) if not pd.isna(rsi_series.iloc[i]) else 50
                hist_val = float(macd_hist.iloc[i]) if not pd.isna(macd_hist.iloc[i]) else 0
                if MACD_RSI_LOW <= rsi_val <= MACD_RSI_HIGH and abs(hist_val) < MACD_HIST_FLAT_THRESHOLD:
                    match_count += 1

            if "volume_accumulation" in active_pattern_names or "obv_divergence" in active_pattern_names:
                if i >= 10:
                    recent_v = float(volumes.iloc[i - 2:i + 1].mean())
                    prior_v = float(volumes.iloc[i - 10:i - 2].mean())
                    price_rng = float(closes.iloc[i - 5:i + 1].max() - closes.iloc[i - 5:i + 1].min())
                    price_avg = float(closes.iloc[i - 5:i + 1].mean())
                    if prior_v > 0 and price_avg > 0:
                        if recent_v / prior_v >= VOL_ACCUM_MIN_INCREASE and price_rng / price_avg < VOL_ACCUM_PRICE_RANGE:
                            match_count += 1

            if match_count >= max(1, patterns_to_check // 2):
                future_price = float(closes.iloc[i + HIST_FORWARD_DAYS])
                current_price = float(closes.iloc[i])
                if current_price > 0:
                    fwd_return = (future_price - current_price) / current_price
                    moves.append(fwd_return)
                    total += 1
                    if fwd_return >= HIST_WIN_THRESHOLD:
                        wins += 1

        accuracy = wins / total if total > 0 else 0.0
        avg_move = sum(moves) / len(moves) if moves else 0.0
        winning_moves = [m for m in moves if m >= HIST_WIN_THRESHOLD]
        avg_win = sum(winning_moves) / len(winning_moves) if winning_moves else 0.0
        expected_move = accuracy * avg_win

        result = {
            "accuracy": round(accuracy, 3),
            "samples": total,
            "avg_move": round(avg_move * 100, 2),
            "expected_move": round(expected_move * 100, 2),
            "avg_winning_move": round(avg_win * 100, 2),
        }

        with _hist_lock:
            _hist_cache[symbol] = (today, result)

        return result

    except Exception as exc:
        log.warning("[prediction] Historical analysis failed for %s: %s", symbol, exc)
        return {"accuracy": 0.0, "samples": 0, "avg_move": 0.0, "expected_move": 0.0}


# ── Stage classification ─────────────────────────────────────────────────────

def _classify_stage(patterns: list[PatternResult]) -> str:
    active = {p.name for p in patterns if p.detected}
    total_active = len(active)
    volume_signals = {p.name for p in patterns if p.detected and p.category == "volume"}

    if total_active == 0:
        return "no_setup"

    if "macd_launch_zone" in active and total_active >= 3 and volume_signals:
        return "launch_zone"

    if "keltner_squeeze" in active and ("higher_lows" in active or "macd_launch_zone" in active):
        return "pre_breakout"

    if volume_signals and total_active >= 2:
        return "accumulation"

    if "relative_strength" in active or total_active >= 2:
        return "early_accumulation"

    return "early_accumulation"


STAGE_LABELS = {
    "no_setup":            "No setup detected",
    "early_accumulation":  "Early accumulation — watching",
    "accumulation":        "Accumulation phase — big buyers detected",
    "pre_breakout":        "Pre-breakout — pressure building, explosion coming",
    "launch_zone":         "Launch zone — all systems go, spike imminent",
}

STAGE_TIMEFRAME = {
    "early_accumulation":  "3-5 days",
    "accumulation":        "2-3 days",
    "pre_breakout":        "1-2 days",
    "launch_zone":         "1 day",
}


# ── Main prediction function ─────────────────────────────────────────────────

def predict(
    symbol: str,
    df: pd.DataFrame,
    sector_etf: str = "SPY",
    spy_df: pd.DataFrame | None = None,
) -> Prediction | None:
    """
    Run all pattern detectors on a symbol and produce a prediction.
    Returns None if no meaningful setup is detected.

    Gate checks (any fail = no prediction):
    1. Must be in an uptrend (SMA20 > SMA50)
    2. Must have at least one volume-based signal
    3. Must meet minimum weighted confidence
    """
    if df is None or len(df) < 55:  # need 50+ bars for trend filter
        return None

    # Gate 1: Trend filter — no predictions in downtrends
    if not _is_uptrending(df):
        return None

    # Run all pattern detectors
    patterns = [
        detect_keltner_squeeze(df),
        detect_obv_divergence(df),
        detect_adl_divergence(df),
        detect_volume_accumulation(df),
        detect_higher_lows(df),
        detect_fair_value_gap(df),
        detect_macd_launch_zone(df),
        detect_relative_strength(df, sector_etf, spy_df=spy_df),
    ]

    active_patterns = [p for p in patterns if p.detected]
    if not active_patterns:
        return None

    # Gate 2: Volume gate — must have at least one volume signal
    volume_signals = [p for p in active_patterns if p.category == "volume"]
    if not volume_signals:
        return None

    # Weighted scoring: patterns with higher predictive value count more
    weighted_score = 0.0
    max_weighted = 0.0
    for p in patterns:
        weight = PATTERN_WEIGHTS.get(p.name, 1.0)
        max_weighted += 10.0 * weight
        if p.detected:
            weighted_score += p.score * weight

    composite = weighted_score / max_weighted * 10.0 if max_weighted > 0 else 0.0

    # Confirmation bonus scaled by number of categories active
    active_categories = len({p.category for p in active_patterns})
    confirmation_bonus = min(2.0, (active_categories - 1) * 0.8)

    # Multi-timeframe modifier: weekly trend alignment
    try:
        mtf_bonus = _weekly_trend_modifier(df)
    except Exception:
        mtf_bonus = 0.0

    confidence_raw = composite + confirmation_bonus + mtf_bonus
    confidence = max(1, min(10, round(confidence_raw)))

    if confidence < MIN_CONFIDENCE:
        return None

    # Stage classification
    stage = _classify_stage(patterns)
    if stage == "no_setup":
        return None

    # Historical accuracy
    hist = _compute_historical_accuracy(symbol, patterns, bar_df=df)
    historical_accuracy = hist.get("accuracy", 0.0)
    historical_samples = hist.get("samples", 0)

    if historical_samples >= HIST_MIN_SAMPLES and historical_accuracy < MIN_HISTORICAL_ACCURACY:
        log.debug("[prediction] %s: skipped — historical accuracy %.0f%% < %.0f%% (%d samples)",
                  symbol, historical_accuracy * 100, MIN_HISTORICAL_ACCURACY * 100, historical_samples)
        return None

    # Price targets — ATR-based for tighter, volatility-adjusted levels
    current_price = float(df["close"].iloc[-1])
    atr_series = calc_atr(df)
    current_atr = float(atr_series.iloc[-1]) if len(atr_series.dropna()) > 0 else current_price * 0.02

    # Expected move from historical data or ATR-based estimate
    expected_move_pct = hist.get("avg_winning_move", 0.0)
    if expected_move_pct <= 0:
        # Estimate: 2x ATR as percentage
        expected_move_pct = max(2.0, min(8.0, (current_atr * 2 / current_price) * 100))

    # Entry zone
    entry_low = round(current_price * 0.995, 2)
    entry_high = round(current_price * 1.005, 2)

    # Target: current + expected move
    target_price = round(current_price * (1 + expected_move_pct / 100), 2)

    # ATR-based stop loss — tighter than swing-low based
    stop_loss = round(current_price - STOP_ATR_MULTIPLIER * current_atr, 2)
    # Sanity: stop shouldn't be more than 5% below entry
    stop_floor = current_price * 0.95
    stop_loss = max(stop_loss, round(stop_floor, 2))

    # Build reasons
    reasons = []
    for p in active_patterns:
        if p.name == "keltner_squeeze":
            reasons.append(f"Keltner squeeze: extreme volatility compression ({p.details.get('squeeze_bars', 0)} bars)")
        elif p.name == "obv_divergence":
            reasons.append(f"OBV divergence: stealth buying detected (div={p.details.get('divergence', 0):.2f})")
        elif p.name == "adl_divergence":
            reasons.append(f"ADL divergence: money flow positive while price flat (div={p.details.get('divergence', 0):.2f})")
        elif p.name == "volume_accumulation":
            reasons.append(f"Volume up {p.details.get('vol_increase_ratio', 0):.0%} over 3 days but price flat")
        elif p.name == "higher_lows":
            mss = " + structure shift confirmed" if p.details.get("mss_confirmed") else ""
            reasons.append(f"Higher lows — coiling ({p.details.get('ascending_pct', 0):.0f}% ascending){mss}")
        elif p.name == "macd_launch_zone":
            reasons.append(f"MACD launch zone: RSI {p.details.get('rsi', 0):.0f}, histogram converging")
        elif p.name == "fair_value_gap":
            reasons.append(f"Fair value gap at ${p.details.get('fvg_mid', 0):.2f} ({p.details.get('bars_ago', 0)} bars ago, {p.details.get('fvg_size_pct', 0):.1f}% gap)")
        elif p.name == "relative_strength":
            reasons.append(f"Outperforming SPY {p.details.get('outperform_days', 0)}/{p.details.get('total_days', 5)} days (+{p.details.get('relative_return_pct', 0):.1f}%)")

    if mtf_bonus > 0:
        reasons.append("Weekly trend aligned — higher timeframe confirmation")
    elif mtf_bonus < 0:
        reasons.append("Warning: against weekly trend")

    if historical_samples >= HIST_MIN_SAMPLES:
        reasons.append(f"Historical accuracy: {historical_accuracy:.0%} over {historical_samples} similar setups")

    return Prediction(
        symbol=symbol,
        predicted_spike=True,
        confidence=confidence,
        stage=stage,
        expected_move_pct=round(expected_move_pct, 1),
        entry_low=entry_low,
        entry_high=entry_high,
        target_price=target_price,
        stop_loss=stop_loss,
        historical_accuracy=round(historical_accuracy, 3),
        historical_samples=historical_samples,
        patterns=patterns,
        reasons=reasons,
        timeframe=STAGE_TIMEFRAME.get(stage, "1-3 days"),
    )


_bad_symbols: set[str] = set()  # symbols that failed data fetch — skip for the day
_bad_symbols_date: date | None = None


def predict_batch(symbols: list[str], bars_cache: dict[str, pd.DataFrame] | None = None) -> list[Prediction]:
    """
    Run predictions on a batch of symbols. Returns only stocks with valid predictions,
    sorted by confidence descending.
    """
    global _bad_symbols, _bad_symbols_date
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Reset bad symbols cache daily
    today = date.today()
    if _bad_symbols_date != today:
        _bad_symbols = set()
        _bad_symbols_date = today

    # Filter out known bad symbols
    valid_symbols = [s for s in symbols if s not in _bad_symbols]
    if len(valid_symbols) < len(symbols):
        log.debug("[prediction] Skipping %d known bad symbols", len(symbols) - len(valid_symbols))

    predictions: list[Prediction] = []

    # Fetch SPY data once for all relative-strength checks
    spy_df = get_spy_history(period="10d", interval="1d")

    def _predict_one(sym: str) -> Prediction | None:
        if bars_cache and sym in bars_cache:
            df = bars_cache[sym]
        else:
            try:
                df = rate_limited_yf(
                    lambda: yf.Ticker(sym).history(period="60d", interval="1d")
                )
                if df is None or df.empty:
                    _bad_symbols.add(sym)
                    return None
                df.columns = [c.lower() for c in df.columns]
                df = df[["open", "high", "low", "close", "volume"]].copy().sort_index()
            except Exception:
                _bad_symbols.add(sym)
                return None
        return predict(sym, df, spy_df=spy_df)

    # Process in batches of 50 with pauses to avoid Yahoo rate limits
    import time as _time
    BATCH_SIZE = 50
    for batch_start in range(0, len(valid_symbols), BATCH_SIZE):
        batch = valid_symbols[batch_start:batch_start + BATCH_SIZE]
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_sym = {executor.submit(_predict_one, sym): sym for sym in batch}
            for future in as_completed(future_to_sym):
                sym = future_to_sym[future]
                try:
                    result = future.result()
                    if result is not None:
                        predictions.append(result)
                except Exception as exc:
                    log.debug("[prediction] %s failed: %s", sym, exc)
        if batch_start + BATCH_SIZE < len(valid_symbols):
            _time.sleep(2)  # 2s pause between batches

    # Sort by confidence descending, then by historical accuracy
    predictions.sort(key=lambda p: (p.confidence, p.historical_accuracy), reverse=True)

    log.info(
        "[prediction] Batch complete: %d symbols scanned, %d predictions generated",
        len(symbols), len(predictions),
    )

    return predictions
