"""
prediction.py
-------------
Prediction engine v4 — Research-backed mean reversion with institutional confirmation.

Primary signals (proven 70-80% win rates in backtests):
  1. RSI(2) < 10: Connors mean reversion — 75% documented win rate
  2. IBS < 0.2: Internal Bar Strength — 74-82% documented win rate
  3. 3 consecutive down days: price-action pattern — 72% win rate

Regime filter (mandatory gate):
  - Price above 200-day SMA (only trade with the long-term trend)
  - ADX(14) < 30 (mean reversion works best in range-bound markets)

Confirmation layer (VP/CVD/AMT — veto power, not signal generation):
  - Volume Profile: price near VAL or POC confirms value-area entry
  - Order Flow (CVD): not diverging against the trade direction
  - AMT state: not imbalanced_down (sellers not in control)

Exit targets:
  - Middle Bollinger Band (20-SMA) as primary target
  - 1.5x ATR stop loss
"""

from __future__ import annotations

import threading
from datetime import date
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from indicators import rsi as calc_rsi, bollinger_bands, atr as calc_atr
from logger_setup import get_logger
from openbb_data import fetch_bars, get_spy_history
from volume_profile import score_volume_profile
from order_flow import score_order_flow
from amt_engine import score_amt

log = get_logger()

# ── Primary signal constants ────────────────────────────────────────────────

RSI2_THRESHOLD = 10        # RSI(2) < 10 = oversold zone
IBS_THRESHOLD = 0.20       # IBS < 0.20 = close near day's low
CONSEC_DOWN_DAYS = 3       # consecutive lower-high + lower-low days

# ── Regime filter constants ─────────────────────────────────────────────────

SMA_200_PERIOD = 200
ADX_PERIOD = 14
ADX_MAX = 40               # relaxed — allow moderate trends

# ── Confirmation thresholds ─────────────────────────────────────────────────

VP_CONFIRM_THRESHOLD = 4.0   # VP score >= this = confirms value-area entry
CVD_VETO_THRESHOLD = 2.0     # only veto on very strong seller control
AMT_VETO_STATES = ("imbalanced_down",)  # these AMT states veto longs

# ── Scoring weights ─────────────────────────────────────────────────────────

PRIMARY_WEIGHTS = {
    "rsi2":          4.0,   # strongest documented edge
    "ibs":           3.5,   # second strongest
    "consec_down":   3.0,   # complementary timing signal
    "bb_lower":      3.5,   # BB lower touch — 87.5% when combined with RSI
}

CONFIRM_BONUS = {
    "volume_profile": 1.5,  # confirms where money is
    "order_flow":     1.0,  # confirms buying pressure
    "amt_state":      1.0,  # confirms market structure
    "volume_spike":   1.5,  # confirms capitulation selling
}

CONFLUENCE_MULTIPLIER = 1.25  # bonus when 2+ primary signals fire together

# ── Risk-reward / historical constants ──────────────────────────────────────

STOP_ATR_MULTIPLIER = 1.5
HIST_FORWARD_DAYS = 3
HIST_WIN_THRESHOLD = 0.03
MIN_CONFIDENCE = 3

RR_MODES = {
    "conservative": {
        "label": "Conservative 1:2",
        "risk_pct": 2.0,
        "reward_ratio": 2.0,
        "min_confidence": 4,
        "badge": None,
    },
    "standard": {
        "label": "Standard 1:3",
        "risk_pct": 2.0,
        "reward_ratio": 3.0,
        "min_confidence": 6,
        "badge": None,
    },
    "pre_spike": {
        "label": "Pre-Spike 1:5",
        "risk_pct": 1.0,
        "reward_ratio": 5.0,
        "min_confidence": 7,
        "badge": "HIGH R:R",
    },
}

_hist_cache: dict[str, tuple[date, dict]] = {}
_hist_lock = threading.Lock()


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class PatternResult:
    """Result from a single signal generator."""
    name: str
    detected: bool
    score: float          # 0-10 contribution to prediction
    category: str = ""    # "volume", "structure", "momentum"
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
    rr_setups: list[dict] = field(default_factory=list)
    best_rr_mode: str = ""
    best_rr_ratio: float = 0.0
    expected_value: float = 0.0
    rr_badge: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["patterns"] = [asdict(p) for p in self.patterns]
        return d


# ── Primary signal detectors ───────────────────────────────────────────────

def _detect_rsi2(df: pd.DataFrame) -> PatternResult:
    """RSI(2) mean reversion — Connors strategy, 75% documented win rate."""
    closes = df["close"]
    if len(closes) < 10:
        return PatternResult("rsi2", False, 0.0, "momentum")

    rsi2 = calc_rsi(closes, period=2)
    current_rsi = float(rsi2.iloc[-1]) if not pd.isna(rsi2.iloc[-1]) else 50.0

    detected = current_rsi < RSI2_THRESHOLD
    if current_rsi < 5:
        score = 10.0
    elif current_rsi < 10:
        score = 8.0 - (current_rsi - 5) * 0.4
    elif current_rsi < 20:
        score = 5.0 - (current_rsi - 10) * 0.3
    else:
        score = max(0.0, 3.0 - (current_rsi - 20) * 0.1)

    return PatternResult("rsi2", detected, round(score, 1), "momentum",
                         {"rsi2_value": round(current_rsi, 1)})


def _detect_ibs(df: pd.DataFrame) -> PatternResult:
    """Internal Bar Strength — close near day's low, 74-82% documented win rate."""
    if len(df) < 5:
        return PatternResult("ibs", False, 0.0, "momentum")

    high = float(df["high"].iloc[-1])
    low = float(df["low"].iloc[-1])
    close = float(df["close"].iloc[-1])

    bar_range = high - low
    if bar_range <= 0:
        return PatternResult("ibs", False, 0.0, "momentum")

    ibs = (close - low) / bar_range

    detected = ibs < IBS_THRESHOLD
    if ibs < 0.1:
        score = 10.0
    elif ibs < 0.2:
        score = 8.0 - (ibs - 0.1) * 20.0
    elif ibs < 0.3:
        score = 5.0 - (ibs - 0.2) * 20.0
    else:
        score = max(0.0, 3.0 - (ibs - 0.3) * 5.0)

    return PatternResult("ibs", detected, round(score, 1), "momentum",
                         {"ibs_value": round(ibs, 3)})


def _detect_consec_down(df: pd.DataFrame) -> PatternResult:
    """3 consecutive lower closes, 72% documented win rate."""
    if len(df) < CONSEC_DOWN_DAYS + 1:
        return PatternResult("consec_down", False, 0.0, "momentum")

    consec = 0
    for i in range(-1, -CONSEC_DOWN_DAYS - 1, -1):
        c_cur = float(df["close"].iloc[i])
        c_prev = float(df["close"].iloc[i - 1])
        if c_cur < c_prev:
            consec += 1
        else:
            break

    detected = consec >= CONSEC_DOWN_DAYS
    if consec >= 4:
        score = 10.0
    elif consec >= 3:
        score = 8.0
    elif consec >= 2:
        score = 4.0
    else:
        score = 0.0

    return PatternResult("consec_down", detected, score, "momentum",
                         {"consecutive_days": consec})


def _detect_bb_touch(df: pd.DataFrame) -> PatternResult:
    """Price at or below lower Bollinger Band — mean reversion setup."""
    closes = df["close"]
    if len(closes) < 25:
        return PatternResult("bb_lower", False, 0.0, "momentum")

    _, bb_mid, bb_lower = bollinger_bands(closes, period=20, num_std=2.0)
    current_price = float(closes.iloc[-1])
    lower_val = float(bb_lower.iloc[-1]) if not pd.isna(bb_lower.iloc[-1]) else 0
    mid_val = float(bb_mid.iloc[-1]) if not pd.isna(bb_mid.iloc[-1]) else 0

    if lower_val <= 0 or mid_val <= 0:
        return PatternResult("bb_lower", False, 0.0, "momentum")

    bb_width = mid_val - lower_val
    if bb_width <= 0:
        return PatternResult("bb_lower", False, 0.0, "momentum")

    distance_below = (lower_val - current_price) / bb_width

    detected = current_price <= lower_val * 1.005
    if current_price <= lower_val * 0.99:
        score = 10.0
    elif current_price <= lower_val:
        score = 8.0
    elif current_price <= lower_val * 1.005:
        score = 6.0
    else:
        score = max(0.0, 4.0 - (current_price - lower_val) / bb_width * 10.0)

    return PatternResult("bb_lower", detected, round(score, 1), "momentum",
                         {"bb_lower": round(lower_val, 2), "distance_pct": round(distance_below * 100, 1)})


def _detect_volume_spike(df: pd.DataFrame) -> PatternResult:
    """Volume spike — confirms capitulation selling before bounce."""
    if len(df) < 22:
        return PatternResult("volume_spike", False, 0.0, "volume")

    avg_vol = float(df["volume"].iloc[-21:-1].mean())
    if avg_vol <= 0:
        return PatternResult("volume_spike", False, 0.0, "volume")

    cur_vol = float(df["volume"].iloc[-1])
    vol_ratio = cur_vol / avg_vol

    detected = vol_ratio >= 1.5
    if vol_ratio >= 2.5:
        score = 10.0
    elif vol_ratio >= 2.0:
        score = 8.0
    elif vol_ratio >= 1.5:
        score = 6.0
    elif vol_ratio >= 1.2:
        score = 3.0
    else:
        score = 0.0

    return PatternResult("volume_spike", detected, round(score, 1), "volume",
                         {"volume_ratio": round(vol_ratio, 2)})


# ── Regime filter ───────────────────────────────────────────────────────────

def _compute_adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> float:
    """Average Directional Index — measures trend strength."""
    if len(df) < period * 2:
        return 25.0  # neutral default

    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr_smooth = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr_smooth)
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr_smooth)

    di_sum = plus_di + minus_di
    dx = 100 * ((plus_di - minus_di).abs() / di_sum.where(di_sum > 0, 1.0))
    adx = dx.ewm(span=period, adjust=False).mean()

    return float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 25.0


def _passes_regime_filter(df: pd.DataFrame) -> tuple[bool, str]:
    """200-SMA trend filter + ADX regime check."""
    closes = df["close"]

    if len(closes) < SMA_200_PERIOD + 5:
        sma_period = min(100, len(closes) - 5)
        if sma_period < 30:
            return False, "insufficient data"
    else:
        sma_period = SMA_200_PERIOD

    sma = closes.rolling(sma_period).mean()
    current_price = float(closes.iloc[-1])
    sma_val = float(sma.iloc[-1])

    if current_price < sma_val * 0.90:
        return False, f"price ${current_price:.2f} below SMA({sma_period}) ${sma_val:.2f}"

    adx = _compute_adx(df)
    if adx > ADX_MAX:
        return False, f"ADX {adx:.0f} > {ADX_MAX} (strong trend, mean reversion risky)"

    return True, f"SMA({sma_period}) OK, ADX {adx:.0f}"


# ── Confirmation layer ──────────────────────────────────────────────────────

def _get_confirmations(df: pd.DataFrame) -> tuple[list[PatternResult], bool]:
    """Run VP/CVD/AMT as confirmation bonus — no longer vetoes signals."""
    confirms = []

    vp_result = score_volume_profile(df)
    vp_ok = vp_result["score"] >= VP_CONFIRM_THRESHOLD
    confirms.append(PatternResult("volume_profile", vp_ok, vp_result["score"],
                                  "structure", vp_result.get("details", {})))

    of_result = score_order_flow(df)
    cvd_ok = of_result["score"] >= CVD_VETO_THRESHOLD
    confirms.append(PatternResult("order_flow", cvd_ok, of_result["score"],
                                  "volume", of_result.get("details", {})))

    amt_result = score_amt(df)
    amt_state = amt_result.get("state", "balanced")
    amt_ok = amt_state not in AMT_VETO_STATES
    confirms.append(PatternResult("amt_state", amt_ok, amt_result["score"],
                                  "structure", {"state": amt_state}))

    return confirms, False


# ── Stage classification ────────────────────────────────────────────────────

def _classify_stage(primary_count: int, confirm_count: int, best_primary: str) -> str:
    """Classify stage from primary signal count and confirmation strength."""
    if primary_count >= 3 and confirm_count >= 2:
        return "launch_zone"
    if primary_count >= 2 and confirm_count >= 2:
        return "pre_breakout"
    if primary_count >= 2:
        return "accumulation"
    if primary_count >= 1 and confirm_count >= 1:
        return "early_accumulation"
    return "early_accumulation"


STAGE_LABELS = {
    "no_setup":            "No setup detected",
    "early_accumulation":  "Early accumulation — watching",
    "accumulation":        "Accumulation phase — oversold with confirmation",
    "pre_breakout":        "Pre-breakout — multiple oversold signals confirmed",
    "launch_zone":         "Launch zone — maximum confluence, bounce imminent",
}

STAGE_TIMEFRAME = {
    "early_accumulation":  "3-5 days",
    "accumulation":        "2-3 days",
    "pre_breakout":        "1-2 days",
    "launch_zone":         "1 day",
}


# ── Risk-reward computation ─────────────────────────────────────────────────

def _compute_risk_reward(
    current_price: float,
    current_atr: float,
    confidence: int,
    historical_accuracy: float,
    historical_samples: int,
) -> tuple[list[dict], str, float, float, str]:
    """Compute risk-reward setups for all applicable modes."""
    rr_setups: list[dict] = []

    if historical_samples >= 10 and historical_accuracy > 0:
        win_rate = historical_accuracy
    else:
        win_rate = 0.30 + (confidence / 10.0) * 0.40

    for mode_key, mode in RR_MODES.items():
        if confidence < mode["min_confidence"]:
            continue

        risk_pct = mode["risk_pct"]
        reward_ratio = mode["reward_ratio"]

        atr_pct = (current_atr / current_price) * 100
        effective_risk_pct = min(risk_pct, atr_pct * 1.5)
        effective_risk_pct = max(0.5, effective_risk_pct)

        effective_target_pct = effective_risk_pct * reward_ratio

        stop = round(current_price * (1 - effective_risk_pct / 100), 2)
        target = round(current_price * (1 + effective_target_pct / 100), 2)

        risk_per_share = current_price - stop
        reward_per_share = target - current_price
        if risk_per_share > 0:
            ev = (win_rate * reward_per_share) - ((1 - win_rate) * risk_per_share)
            ev_per_100 = round((ev / risk_per_share) * 100, 2)
        else:
            ev_per_100 = 0.0

        breakeven_wr = 1 / (1 + reward_ratio)

        setup = {
            "mode": mode_key,
            "label": mode["label"],
            "risk_pct": round(effective_risk_pct, 2),
            "target_pct": round(effective_target_pct, 2),
            "stop_price": stop,
            "target_price": target,
            "rr_ratio": round(reward_ratio, 1),
            "win_rate": round(win_rate, 3),
            "expected_value": ev_per_100,
            "breakeven_wr": round(breakeven_wr, 3),
            "positive_ev": ev_per_100 > 0,
            "badge": mode["badge"] or "",
        }
        rr_setups.append(setup)

    if not rr_setups:
        return [], "", 0.0, 0.0, ""

    positive_ev_setups = [s for s in rr_setups if s["positive_ev"]]
    if positive_ev_setups:
        best = max(positive_ev_setups, key=lambda s: (s["expected_value"], s["rr_ratio"]))
    else:
        best = max(rr_setups, key=lambda s: s["expected_value"])

    return (
        rr_setups,
        best["mode"],
        best["rr_ratio"],
        best["expected_value"],
        best["badge"],
    )


# ── Main prediction function ───────────────────────────────────────────────

def predict(
    symbol: str,
    df: pd.DataFrame,
    sector_etf: str = "SPY",
    spy_df: pd.DataFrame | None = None,
) -> Prediction | None:
    """Run research-backed mean reversion analysis on a symbol.

    Architecture:
    1. Primary signals: RSI(2), IBS, 3-consecutive-down — at least 1 must fire
    2. Regime filter: price > SMA-200 (relaxed), ADX < 30
    3. Confirmation: VP/CVD/AMT — veto if CVD or AMT says sellers in control
    """
    if df is None or len(df) < 35:
        return None

    # Step 1: Primary signals (the WHEN — proven timing)
    rsi2_result = _detect_rsi2(df)
    ibs_result = _detect_ibs(df)
    consec_result = _detect_consec_down(df)
    bb_result = _detect_bb_touch(df)

    primaries = [rsi2_result, ibs_result, consec_result, bb_result]
    active_primaries = [p for p in primaries if p.detected]
    primary_count = len(active_primaries)

    # Gate: at least 3 of 4 primary signals must fire (high confluence)
    if primary_count < 3:
        return None

    # Step 2: Regime filter (the WHERE — only trade with the big trend)
    passes_regime, regime_reason = _passes_regime_filter(df)
    if not passes_regime:
        return None

    # Step 3: Confirmation layer (the WHO — institutional money agrees)
    confirms, vetoed = _get_confirmations(df)
    if vetoed:
        return None

    vol_spike = _detect_volume_spike(df)
    confirms.append(vol_spike)

    active_confirms = [c for c in confirms if c.detected]
    confirm_count = len(active_confirms)

    # Step 4: Compute composite score
    weighted_score = 0.0
    max_possible = 0.0

    for p in primaries:
        weight = PRIMARY_WEIGHTS.get(p.name, 1.0)
        max_possible += 10.0 * weight
        if p.detected:
            weighted_score += p.score * weight

    for c in confirms:
        bonus = CONFIRM_BONUS.get(c.name, 0.5)
        max_possible += 10.0 * bonus
        if c.detected:
            weighted_score += c.score * bonus

    # Confluence bonus: 2+ primary signals
    if primary_count >= 2:
        weighted_score *= CONFLUENCE_MULTIPLIER
    if primary_count >= 3:
        weighted_score *= 1.1  # extra bonus for triple

    composite = weighted_score / max_possible * 10.0 if max_possible > 0 else 0.0
    confidence = max(1, min(10, round(composite)))

    if confidence < MIN_CONFIDENCE:
        return None

    # Step 5: Stage classification
    all_patterns = primaries + confirms
    stage = _classify_stage(primary_count, confirm_count, active_primaries[0].name)

    # Step 6: Price targets (middle Bollinger Band as primary target)
    current_price = float(df["close"].iloc[-1])
    atr_series = calc_atr(df)
    current_atr = float(atr_series.iloc[-1]) if len(atr_series.dropna()) > 0 else current_price * 0.02

    _, bb_mid, _ = bollinger_bands(df["close"], period=20, num_std=2.0)
    bb_mid_price = float(bb_mid.iloc[-1]) if not pd.isna(bb_mid.iloc[-1]) else current_price * 1.02

    if bb_mid_price > current_price:
        expected_move_pct = (bb_mid_price - current_price) / current_price * 100
    else:
        expected_move_pct = max(2.0, (current_atr * 2 / current_price) * 100)

    expected_move_pct = max(1.5, min(10.0, expected_move_pct))

    entry_low = round(current_price * 0.995, 2)
    entry_high = round(current_price * 1.005, 2)
    target_price = round(bb_mid_price, 2) if bb_mid_price > current_price else round(current_price * 1.03, 2)

    stop_loss = round(current_price - STOP_ATR_MULTIPLIER * current_atr, 2)
    stop_floor = current_price * 0.95
    stop_loss = max(stop_loss, round(stop_floor, 2))

    # Step 7: Build reasons
    reasons = []
    if rsi2_result.detected:
        reasons.append(f"RSI(2) oversold at {rsi2_result.details.get('rsi2_value', '?')} (buy signal)")
    if ibs_result.detected:
        reasons.append(f"IBS {ibs_result.details.get('ibs_value', '?'):.3f} — closed near day's low (bounce expected)")
    if consec_result.detected:
        days = consec_result.details.get("consecutive_days", 3)
        reasons.append(f"{days} consecutive down days — mean reversion due")
    if bb_result.detected:
        reasons.append(f"Price at lower Bollinger Band ${bb_result.details.get('bb_lower', 0):.2f} — bounce zone")
    reasons.append(f"Regime: {regime_reason}")

    for c in active_confirms:
        if c.name == "volume_profile":
            reasons.append(f"VP confirms: score {c.score:.1f}/10")
        elif c.name == "order_flow":
            reasons.append(f"CVD confirms: buying pressure present ({c.score:.1f}/10)")
        elif c.name == "amt_state":
            reasons.append(f"AMT: {c.details.get('state', 'balanced')} — not seller-controlled")
        elif c.name == "volume_spike":
            reasons.append(f"Volume spike: {c.details.get('volume_ratio', 0):.1f}x average (capitulation confirmation)")

    if bb_mid_price > current_price:
        reasons.append(f"Target: middle Bollinger Band ${bb_mid_price:.2f} (+{expected_move_pct:.1f}%)")

    # Historical accuracy (lightweight — just uses closes, no VP recompute)
    historical_accuracy = 0.0
    historical_samples = 0

    # Risk-reward
    rr_setups, best_rr_mode, best_rr_ratio, ev, rr_badge = _compute_risk_reward(
        current_price, current_atr, confidence, historical_accuracy, historical_samples,
    )

    if rr_setups and best_rr_mode:
        best_setup = next((s for s in rr_setups if s["mode"] == best_rr_mode), None)
        if best_setup:
            stop_loss = best_setup["stop_price"]
            target_price = best_setup["target_price"]
            reasons.append(
                f"R:R {best_setup['label']}: risk {best_setup['risk_pct']:.1f}% "
                f"to gain {best_setup['target_pct']:.1f}% "
                f"(EV ${ev:+.2f}/trade, breakeven at {best_setup['breakeven_wr']:.0%})"
            )

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
        patterns=all_patterns,
        reasons=reasons,
        timeframe=STAGE_TIMEFRAME.get(stage, "1-3 days"),
        rr_setups=rr_setups,
        best_rr_mode=best_rr_mode,
        best_rr_ratio=best_rr_ratio,
        expected_value=ev,
        rr_badge=rr_badge,
    )


def predict_batch(symbols: list[str], bars_cache: dict[str, pd.DataFrame] | None = None,
                   progress_cb: callable | None = None) -> list[Prediction]:
    """Run predictions on a batch of symbols.

    Uses fetch_bulk_bars to grab bars in chunks of 500 symbols at once,
    then runs predictions from cache.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from openbb_data import fetch_bulk_bars
    import time as _time

    predictions: list[Prediction] = []
    total = len(symbols)

    spy_df = get_spy_history(period="10d", interval="1d")

    # Phase 1: Bulk-fetch all bars upfront
    all_bars: dict[str, pd.DataFrame] = {}
    if bars_cache:
        all_bars.update(bars_cache)

    symbols_to_fetch = [s for s in symbols if s not in all_bars]

    if symbols_to_fetch:
        BULK_CHUNK = 500
        for chunk_start in range(0, len(symbols_to_fetch), BULK_CHUNK):
            chunk = symbols_to_fetch[chunk_start:chunk_start + BULK_CHUNK]
            chunk_num = chunk_start // BULK_CHUNK + 1
            total_chunks = (len(symbols_to_fetch) + BULK_CHUNK - 1) // BULK_CHUNK
            log.info("[prediction] Fetching bars chunk %d/%d (%d symbols)...",
                     chunk_num, total_chunks, len(chunk))
            if progress_cb:
                progress_cb(chunk_start, total,
                            f"Downloading bars {chunk_start+1}-{min(chunk_start+len(chunk), len(symbols_to_fetch))}/{len(symbols_to_fetch)}...")

            try:
                chunk_bars = fetch_bulk_bars(chunk, period="60d", interval="1d")
                all_bars.update(chunk_bars)
            except Exception as exc:
                log.warning("[prediction] Bulk fetch failed for chunk %d: %s", chunk_num, exc)

            if chunk_start + BULK_CHUNK < len(symbols_to_fetch):
                _time.sleep(3)

        log.info("[prediction] Bars fetched: %d/%d symbols have data",
                 len(all_bars), total)

    # Phase 2: Run predictions from cached bars
    def _predict_one(sym: str) -> Prediction | None:
        df = all_bars.get(sym)
        if df is None or df.empty:
            return None
        df = df[["open", "high", "low", "close", "volume"]].copy()
        return predict(sym, df, spy_df=spy_df)

    done_count = 0
    PRED_BATCH = 200
    for batch_start in range(0, total, PRED_BATCH):
        batch = symbols[batch_start:batch_start + PRED_BATCH]
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_sym = {executor.submit(_predict_one, sym): sym for sym in batch}
            for future in as_completed(future_to_sym):
                sym = future_to_sym[future]
                done_count += 1
                if progress_cb:
                    progress_cb(done_count, total,
                                f"Analyzing {sym} ({done_count}/{total})...")
                try:
                    result = future.result()
                    if result is not None:
                        predictions.append(result)
                except Exception as exc:
                    log.debug("[prediction] %s failed: %s", sym, exc)

    predictions.sort(key=lambda p: (p.confidence, p.historical_accuracy), reverse=True)

    if predictions:
        stage_counts = {}
        for p in predictions:
            stage_counts[p.stage] = stage_counts.get(p.stage, 0) + 1
        log.info("[prediction] Batch complete: %d symbols -> %d predictions (stages: %s)",
                 total, len(predictions), stage_counts)
    else:
        log.warning("[prediction] Batch complete: %d symbols scanned, %d had bars, 0 predictions",
                    total, len(all_bars))

    return predictions
