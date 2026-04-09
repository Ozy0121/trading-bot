"""
prediction.py
-------------
Pre-spike prediction engine — detects accumulation patterns, Bollinger squeeze,
volume building, MACD launch zones, and coiling (higher lows) BEFORE a stock
spikes. Includes historical pattern matching for probability estimates.

Goal: find the stock before everyone else, buy while it's quiet, sell after the spike.

Pattern library:
  1. Volume accumulation: volume building 3-5 days while price flat
  2. Bollinger squeeze: bands tightening = pressure building
  3. Higher lows (coiling): price compressing at support
  4. MACD launch zone: histogram flattening, RSI 40-55
  5. Relative strength: quietly outperforming sector 3+ days
  6. Decreasing sell volume: sellers exhausted
  7. Composite pre-spike score combining all patterns

Historical backtesting:
  - When this exact pattern appeared before, what happened next?
  - Calculates win rate and expected move over 1-3 day horizon
"""

from __future__ import annotations

import math
import threading
from datetime import date, datetime, timezone
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd
import yfinance as yf

from indicators import rsi as calc_rsi, macd as calc_macd, bollinger_bands
from logger_setup import get_logger
from yf_limiter import rate_limited_yf, get_spy_history

log = get_logger()

# ── Constants ────────────────────────────────────────────────────────────────

# Bollinger squeeze: bandwidth percentile threshold (tightest N% = squeeze)
BB_SQUEEZE_PERCENTILE = 20
BB_SQUEEZE_LOOKBACK = 30  # days to compute bandwidth percentile

# Volume accumulation: volume must be rising while price stays flat
VOL_ACCUM_DAYS = 5        # look back 5 days
VOL_ACCUM_PRICE_RANGE = 0.03   # price range < 3% = "flat"
VOL_ACCUM_MIN_INCREASE = 1.3   # avg volume last 3 days >= 1.3x avg prior 10 days

# Higher lows (coiling)
COIL_MIN_LOWS = 3         # need at least 3 swing lows
COIL_LOOKBACK = 20        # bars to look for swing lows

# MACD launch zone
MACD_HIST_FLAT_THRESHOLD = 0.15  # histogram magnitude < this = "flattening"
MACD_RSI_LOW = 40.0
MACD_RSI_HIGH = 55.0

# Relative strength
REL_STRENGTH_DAYS = 5     # outperforming sector for N days

# Historical pattern matching
HIST_LOOKBACK_DAYS = 365  # 1 year of daily data for backtesting
HIST_MIN_SAMPLES = 10     # need at least 10 pattern matches for confidence
HIST_FORWARD_DAYS = 3     # predict 3-day forward return
HIST_WIN_THRESHOLD = 0.03 # 3%+ gain = a "win"

# Overall prediction
MIN_CONFIDENCE = 5        # out of 10; below this we skip
MIN_HISTORICAL_ACCURACY = 0.60  # 60% minimum hit rate

# Cache for historical analysis (expensive, refresh daily)
_hist_cache: dict[str, tuple[date, dict]] = {}
_hist_lock = threading.Lock()


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class PatternResult:
    """Result from a single pattern detector."""
    name: str
    detected: bool
    score: float          # 0-10 contribution to prediction
    details: dict = field(default_factory=dict)


@dataclass
class Prediction:
    """Complete prediction output for a stock."""
    symbol: str
    predicted_spike: bool
    confidence: int                  # 1-10
    stage: str                       # "accumulation", "pre_breakout", "launch_zone"
    expected_move_pct: float         # expected % gain in 1-3 days
    entry_low: float                 # buy between entry_low and entry_high
    entry_high: float
    target_price: float
    stop_loss: float
    historical_accuracy: float       # % of similar setups that resulted in spike
    historical_samples: int          # how many similar setups found
    patterns: list[PatternResult] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    timeframe: str = "1-3 days"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["patterns"] = [asdict(p) for p in self.patterns]
        return d


# ── Pattern detectors ────────────────────────────────────────────────────────

def detect_bb_squeeze(df: pd.DataFrame) -> PatternResult:
    """
    Bollinger Band squeeze: bands at tightest point in 30 days.
    This means volatility is compressed — a big move is coming.
    """
    if len(df) < BB_SQUEEZE_LOOKBACK + 5:
        return PatternResult("bb_squeeze", False, 0.0)

    closes = df["close"]
    bb_upper, bb_mid, bb_lower = bollinger_bands(closes)

    # Bandwidth = (upper - lower) / middle
    bandwidth = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)
    bandwidth = bandwidth.dropna()

    if len(bandwidth) < BB_SQUEEZE_LOOKBACK:
        return PatternResult("bb_squeeze", False, 0.0)

    recent_bw = bandwidth.iloc[-BB_SQUEEZE_LOOKBACK:]
    current_bw = float(bandwidth.iloc[-1])
    percentile = float((recent_bw < current_bw).sum() / len(recent_bw) * 100)

    detected = percentile <= BB_SQUEEZE_PERCENTILE
    # Score: tighter squeeze = higher score
    # percentile 0 -> 10, percentile 20 -> 5, percentile 50+ -> 0
    score = max(0.0, min(10.0, (BB_SQUEEZE_PERCENTILE - percentile) / BB_SQUEEZE_PERCENTILE * 10))

    return PatternResult(
        "bb_squeeze",
        detected,
        round(score, 1),
        {
            "bandwidth": round(current_bw, 4),
            "percentile": round(percentile, 1),
            "tightest_in_days": BB_SQUEEZE_LOOKBACK,
        },
    )


def detect_volume_accumulation(df: pd.DataFrame) -> PatternResult:
    """
    Volume building over 3-5 days while price stays flat.
    Big players quietly buying before a move.
    """
    if len(df) < VOL_ACCUM_DAYS + 10:
        return PatternResult("volume_accumulation", False, 0.0)

    closes = df["close"].iloc[-(VOL_ACCUM_DAYS + 10):]
    volumes = df["volume"].iloc[-(VOL_ACCUM_DAYS + 10):]

    # Price flatness: range of last N days / avg price < threshold
    recent_closes = closes.iloc[-VOL_ACCUM_DAYS:]
    price_range = (float(recent_closes.max()) - float(recent_closes.min())) / float(recent_closes.mean())
    price_flat = price_range < VOL_ACCUM_PRICE_RANGE

    # Volume building: recent avg vs prior avg
    recent_vol = float(volumes.iloc[-3:].mean())
    prior_vol = float(volumes.iloc[-10:-3].mean()) if len(volumes) >= 10 else float(volumes.mean())
    vol_increase = recent_vol / prior_vol if prior_vol > 0 else 1.0

    # Check for volume trend (each day's volume increasing)
    last_5_vols = volumes.iloc[-VOL_ACCUM_DAYS:]
    vol_trending_up = 0
    for i in range(1, len(last_5_vols)):
        if float(last_5_vols.iloc[i]) > float(last_5_vols.iloc[i - 1]):
            vol_trending_up += 1
    vol_trend_pct = vol_trending_up / max(1, len(last_5_vols) - 1)

    detected = price_flat and vol_increase >= VOL_ACCUM_MIN_INCREASE
    # Score based on how strong the accumulation signal is
    score = 0.0
    if detected:
        score = min(10.0, 5.0 + (vol_increase - 1.0) * 5.0 + vol_trend_pct * 3.0)

    return PatternResult(
        "volume_accumulation",
        detected,
        round(score, 1),
        {
            "price_range_pct": round(price_range * 100, 2),
            "price_flat": price_flat,
            "vol_increase_ratio": round(vol_increase, 2),
            "vol_trend_pct": round(vol_trend_pct * 100, 1),
        },
    )


def detect_higher_lows(df: pd.DataFrame) -> PatternResult:
    """
    Price making higher lows while staying below resistance — coiling for breakout.
    Uses swing low detection on daily lows.
    """
    if len(df) < COIL_LOOKBACK + 2:
        return PatternResult("higher_lows", False, 0.0)

    lows = df["low"].iloc[-COIL_LOOKBACK:]

    # Find swing lows: a bar where low < both neighbors
    swing_lows = []
    for i in range(1, len(lows) - 1):
        if float(lows.iloc[i]) < float(lows.iloc[i - 1]) and float(lows.iloc[i]) < float(lows.iloc[i + 1]):
            swing_lows.append(float(lows.iloc[i]))

    if len(swing_lows) < COIL_MIN_LOWS:
        return PatternResult("higher_lows", False, 0.0)

    # Check if swing lows are ascending
    ascending_count = 0
    for i in range(1, len(swing_lows)):
        if swing_lows[i] > swing_lows[i - 1]:
            ascending_count += 1
    ascending_pct = ascending_count / max(1, len(swing_lows) - 1)

    detected = ascending_pct >= 0.6  # at least 60% of lows are higher

    # Score: more consistent higher lows = higher score
    score = 0.0
    if detected:
        score = min(10.0, ascending_pct * 10.0)
        # Bonus if price is also near a local high (compressed range = about to break)
        highs = df["high"].iloc[-COIL_LOOKBACK:]
        recent_high = float(highs.iloc[-5:].max())
        current_close = float(df["close"].iloc[-1])
        if current_close > recent_high * 0.97:  # within 3% of recent high
            score = min(10.0, score + 2.0)

    return PatternResult(
        "higher_lows",
        detected,
        round(score, 1),
        {
            "swing_lows_found": len(swing_lows),
            "ascending_pct": round(ascending_pct * 100, 1),
            "last_3_lows": [round(l, 4) for l in swing_lows[-3:]],
        },
    )


def detect_macd_launch_zone(df: pd.DataFrame) -> PatternResult:
    """
    MACD histogram flattening near zero and about to cross while RSI 40-55.
    This is the perfect launch zone — not overbought, momentum building.
    """
    closes = df["close"]
    if len(closes) < 30:
        return PatternResult("macd_launch_zone", False, 0.0)

    rsi_series = calc_rsi(closes)
    _, _, hist = calc_macd(closes)

    rsi_val = float(rsi_series.dropna().iloc[-1]) if len(rsi_series.dropna()) > 0 else 50.0
    hist_vals = hist.dropna()
    if len(hist_vals) < 5:
        return PatternResult("macd_launch_zone", False, 0.0)

    current_hist = float(hist_vals.iloc[-1])
    prev_hist = float(hist_vals.iloc[-2])

    # Histogram flattening: magnitude small and getting less negative (or going positive)
    hist_flat = abs(current_hist) < MACD_HIST_FLAT_THRESHOLD
    hist_improving = current_hist > prev_hist  # trending toward positive

    # Check last 3 histogram values for convergence toward zero
    last3 = [abs(float(hist_vals.iloc[i])) for i in range(-3, 0)]
    converging = all(last3[i] >= last3[i + 1] for i in range(len(last3) - 1))

    # RSI in the sweet spot
    rsi_in_zone = MACD_RSI_LOW <= rsi_val <= MACD_RSI_HIGH

    detected = (hist_flat or converging) and hist_improving and rsi_in_zone

    score = 0.0
    if detected:
        # Closer RSI is to 47.5 (center of zone), higher score
        rsi_center_dist = abs(rsi_val - 47.5) / 7.5  # 0 at center, 1 at edges
        score = min(10.0, 7.0 + (1.0 - rsi_center_dist) * 3.0)
        if converging:
            score = min(10.0, score + 1.0)

    return PatternResult(
        "macd_launch_zone",
        detected,
        round(score, 1),
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
    """
    Stock quietly outperforming its sector/SPY for 3+ days.
    Relative strength building = smart money accumulating.

    Pass spy_df to avoid redundant yfinance fetches when called in a batch.
    """
    if len(df) < REL_STRENGTH_DAYS + 2:
        return PatternResult("relative_strength", False, 0.0)

    try:
        if spy_df is not None:
            spy = spy_df
        else:
            # Fallback: fetch via shared cache (avoids per-symbol fetches)
            spy = get_spy_history(period="10d", interval="1d")
        if spy is None or len(spy) < REL_STRENGTH_DAYS:
            return PatternResult("relative_strength", False, 0.0)
    except Exception:
        return PatternResult("relative_strength", False, 0.0)

    # Daily returns for stock and benchmark
    stock_closes = df["close"].iloc[-REL_STRENGTH_DAYS:]
    spy_closes = spy["close"].iloc[-REL_STRENGTH_DAYS:]

    if len(stock_closes) < REL_STRENGTH_DAYS or len(spy_closes) < REL_STRENGTH_DAYS:
        return PatternResult("relative_strength", False, 0.0)

    stock_returns = stock_closes.pct_change().dropna()
    spy_returns = spy_closes.pct_change().dropna()

    min_len = min(len(stock_returns), len(spy_returns))
    if min_len < 3:
        return PatternResult("relative_strength", False, 0.0)

    # Count days where stock outperformed benchmark
    outperform_days = 0
    for i in range(min_len):
        if float(stock_returns.iloc[i]) > float(spy_returns.iloc[i]):
            outperform_days += 1

    outperform_pct = outperform_days / min_len
    detected = outperform_days >= 3

    # Cumulative relative return
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
        {
            "outperform_days": outperform_days,
            "total_days": min_len,
            "stock_return_pct": round(stock_cum * 100, 2),
            "benchmark_return_pct": round(spy_cum * 100, 2),
            "relative_return_pct": round(relative_return * 100, 2),
        },
    )


def detect_decreasing_sell_volume(df: pd.DataFrame) -> PatternResult:
    """
    Decreasing volume on down days = sellers exhausted.
    Buyers about to take over.
    """
    if len(df) < 10:
        return PatternResult("decreasing_sell_volume", False, 0.0)

    closes = df["close"].iloc[-10:]
    volumes = df["volume"].iloc[-10:]

    # Identify "down" bars (close < open or close < previous close)
    down_volumes = []
    for i in range(1, len(closes)):
        if float(closes.iloc[i]) < float(closes.iloc[i - 1]):
            down_volumes.append(float(volumes.iloc[i]))

    if len(down_volumes) < 3:
        return PatternResult("decreasing_sell_volume", False, 0.0,
                             {"down_bars": len(down_volumes), "reason": "not enough down bars"})

    # Check if down volumes are decreasing
    decreasing_count = 0
    for i in range(1, len(down_volumes)):
        if down_volumes[i] < down_volumes[i - 1]:
            decreasing_count += 1

    decreasing_pct = decreasing_count / max(1, len(down_volumes) - 1)
    detected = decreasing_pct >= 0.6

    # Also check: up volume > down volume recently
    up_volumes = []
    for i in range(1, len(closes)):
        if float(closes.iloc[i]) >= float(closes.iloc[i - 1]):
            up_volumes.append(float(volumes.iloc[i]))

    avg_up_vol = sum(up_volumes) / len(up_volumes) if up_volumes else 0
    avg_down_vol = sum(down_volumes) / len(down_volumes) if down_volumes else 1
    vol_ratio = avg_up_vol / avg_down_vol if avg_down_vol > 0 else 1.0

    score = 0.0
    if detected:
        score = min(10.0, 5.0 + decreasing_pct * 3.0 + max(0, vol_ratio - 1.0) * 3.0)

    return PatternResult(
        "decreasing_sell_volume",
        detected,
        round(score, 1),
        {
            "down_bars": len(down_volumes),
            "decreasing_pct": round(decreasing_pct * 100, 1),
            "up_down_vol_ratio": round(vol_ratio, 2),
        },
    )


# ── Historical pattern matching ──────────────────────────────────────────────

def _compute_historical_accuracy(
    symbol: str,
    current_patterns: list[PatternResult],
    bar_df: pd.DataFrame | None = None,
) -> dict:
    """
    Look back at historical data: when similar patterns appeared, what happened next?
    Returns dict with accuracy, sample count, avg move, and expected move.

    Pass bar_df to reuse data already fetched in _predict_one() instead of
    making a redundant yfinance call.
    """
    today = date.today()

    with _hist_lock:
        cached = _hist_cache.get(symbol)
        if cached and cached[0] == today:
            return cached[1]

    try:
        # Reuse provided bar data if it has enough history; otherwise fetch
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
        highs = hist["high"]
        lows = hist["low"]

        # Compute rolling indicators for the full history
        bb_upper, bb_mid, bb_lower = bollinger_bands(closes)
        bandwidth = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)
        rsi_series = calc_rsi(closes)
        _, _, macd_hist = calc_macd(closes)

        # Count active patterns now
        active_pattern_names = {p.name for p in current_patterns if p.detected}
        if not active_pattern_names:
            result = {"accuracy": 0.0, "samples": 0, "avg_move": 0.0, "expected_move": 0.0}
            with _hist_lock:
                _hist_cache[symbol] = (today, result)
            return result

        # Scan history for days where similar conditions existed
        wins = 0
        total = 0
        moves = []

        for i in range(35, len(closes) - HIST_FORWARD_DAYS):
            match_count = 0
            patterns_to_check = len(active_pattern_names)

            # Check BB squeeze at this point
            if "bb_squeeze" in active_pattern_names:
                bw_window = bandwidth.iloc[max(0, i - BB_SQUEEZE_LOOKBACK):i + 1].dropna()
                if len(bw_window) >= 10:
                    current_bw = float(bw_window.iloc[-1])
                    pctile = float((bw_window < current_bw).sum() / len(bw_window) * 100)
                    if pctile <= BB_SQUEEZE_PERCENTILE:
                        match_count += 1

            # Check MACD launch zone at this point
            if "macd_launch_zone" in active_pattern_names:
                rsi_val = float(rsi_series.iloc[i]) if not pd.isna(rsi_series.iloc[i]) else 50
                hist_val = float(macd_hist.iloc[i]) if not pd.isna(macd_hist.iloc[i]) else 0
                if MACD_RSI_LOW <= rsi_val <= MACD_RSI_HIGH and abs(hist_val) < MACD_HIST_FLAT_THRESHOLD:
                    match_count += 1

            # Check volume accumulation at this point
            if "volume_accumulation" in active_pattern_names:
                if i >= 10:
                    recent_v = float(volumes.iloc[i - 2:i + 1].mean())
                    prior_v = float(volumes.iloc[i - 10:i - 2].mean())
                    price_rng = float(closes.iloc[i - 5:i + 1].max() - closes.iloc[i - 5:i + 1].min())
                    price_avg = float(closes.iloc[i - 5:i + 1].mean())
                    if prior_v > 0 and price_avg > 0:
                        if recent_v / prior_v >= VOL_ACCUM_MIN_INCREASE and price_rng / price_avg < VOL_ACCUM_PRICE_RANGE:
                            match_count += 1

            # Need at least half of active patterns to match
            if match_count >= max(1, patterns_to_check // 2):
                # Check forward return
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
        # Expected move = accuracy * avg winning move
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
    """
    Classify the prediction into a stage based on which patterns are active.

    - "early_accumulation": volume building, but no other strong signals yet
    - "accumulation": volume + at least one more pattern
    - "pre_breakout": BB squeeze + higher lows or MACD launch zone
    - "launch_zone": MACD launch zone + multiple confirmations
    """
    active = {p.name for p in patterns if p.detected}
    total_active = len(active)

    if total_active == 0:
        return "no_setup"

    if "macd_launch_zone" in active and total_active >= 3:
        return "launch_zone"

    if "bb_squeeze" in active and ("higher_lows" in active or "macd_launch_zone" in active):
        return "pre_breakout"

    if "volume_accumulation" in active and total_active >= 2:
        return "accumulation"

    if "volume_accumulation" in active or "relative_strength" in active:
        return "early_accumulation"

    if total_active >= 2:
        return "accumulation"

    return "early_accumulation"


STAGE_LABELS = {
    "no_setup":            "No setup detected",
    "early_accumulation":  "Early accumulation — watching",
    "accumulation":        "Accumulation phase — big buyers detected, breakout hasn't happened yet",
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

    Pass spy_df to avoid redundant SPY fetches in detect_relative_strength.
    """
    if df is None or len(df) < 35:
        return None

    # Run all pattern detectors
    patterns = [
        detect_bb_squeeze(df),
        detect_volume_accumulation(df),
        detect_higher_lows(df),
        detect_macd_launch_zone(df),
        detect_relative_strength(df, sector_etf, spy_df=spy_df),
        detect_decreasing_sell_volume(df),
    ]

    active_patterns = [p for p in patterns if p.detected]
    if not active_patterns:
        return None

    # Composite prediction score (weighted by pattern scores)
    total_score = sum(p.score for p in active_patterns)
    max_possible = len(patterns) * 10.0
    composite = total_score / max_possible * 10.0 if max_possible > 0 else 0.0

    # Bonus for multiple confirmations
    confirmation_bonus = min(2.0, (len(active_patterns) - 1) * 0.5)
    confidence_raw = composite + confirmation_bonus
    confidence = max(1, min(10, round(confidence_raw)))

    if confidence < MIN_CONFIDENCE:
        return None

    # Stage classification
    stage = _classify_stage(patterns)
    if stage == "no_setup":
        return None

    # Historical accuracy — reuse the bar data we already have
    hist = _compute_historical_accuracy(symbol, patterns, bar_df=df)
    historical_accuracy = hist.get("accuracy", 0.0)
    historical_samples = hist.get("samples", 0)

    # Skip if historical accuracy is too low (and we have enough samples)
    if historical_samples >= HIST_MIN_SAMPLES and historical_accuracy < MIN_HISTORICAL_ACCURACY:
        log.debug("[prediction] %s: skipped — historical accuracy %.0f%% < %.0f%% (%d samples)",
                  symbol, historical_accuracy * 100, MIN_HISTORICAL_ACCURACY * 100, historical_samples)
        return None

    # Price targets
    current_price = float(df["close"].iloc[-1])
    bb_upper, _, bb_lower = bollinger_bands(df["close"])
    bb_upper_val = float(bb_upper.dropna().iloc[-1]) if len(bb_upper.dropna()) > 0 else current_price * 1.05

    # Expected move from historical data or estimate
    expected_move_pct = hist.get("avg_winning_move", 0.0)
    if expected_move_pct <= 0:
        # Estimate based on BB width
        bw = (bb_upper_val - current_price) / current_price * 100 if current_price > 0 else 3.0
        expected_move_pct = max(2.0, min(8.0, bw))

    # Entry zone: slightly below current price to just above
    entry_low = round(current_price * 0.995, 2)
    entry_high = round(current_price * 1.005, 2)

    # Target: current + expected move
    target_price = round(current_price * (1 + expected_move_pct / 100), 2)

    # Stop loss: below recent swing low or 3% below entry
    recent_low = float(df["low"].iloc[-5:].min())
    stop_loss = round(min(recent_low * 0.99, current_price * 0.97), 2)

    # Build reasons
    reasons = []
    for p in active_patterns:
        if p.name == "bb_squeeze":
            reasons.append(f"Bollinger squeeze at tightest point in {p.details.get('tightest_in_days', 30)} days")
        elif p.name == "volume_accumulation":
            reasons.append(f"Volume up {p.details.get('vol_increase_ratio', 0):.0%} over 3 days but price flat")
        elif p.name == "higher_lows":
            reasons.append(f"Making higher lows — coiling for breakout ({p.details.get('ascending_pct', 0):.0f}% ascending)")
        elif p.name == "macd_launch_zone":
            reasons.append(f"MACD launch zone: RSI {p.details.get('rsi', 0):.0f}, histogram converging to zero")
        elif p.name == "relative_strength":
            reasons.append(f"Outperforming SPY {p.details.get('outperform_days', 0)} of last {p.details.get('total_days', 5)} days (+{p.details.get('relative_return_pct', 0):.1f}%)")
        elif p.name == "decreasing_sell_volume":
            reasons.append(f"Sell volume decreasing — sellers exhausted (up/down vol ratio: {p.details.get('up_down_vol_ratio', 0):.1f}x)")

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
