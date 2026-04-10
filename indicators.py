"""
indicators.py
-------------
Technical indicators from OHLCV data.
RSI, MACD, Bollinger Bands, Keltner Channels, ATR, OBV, ADL.
Pure pandas/numpy — no extra dependencies.
"""

import pandas as pd
import numpy as np


def rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta    = closes.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(closes: pd.Series,
         fast: int = 12, slow: int = 26, signal: int = 9
         ) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast    = closes.ewm(span=fast,   adjust=False).mean()
    ema_slow    = closes.ewm(span=slow,   adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(closes: pd.Series,
                    period: int = 20, num_std: float = 2.0
                    ) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = closes.rolling(period).mean()
    std    = closes.rolling(period).std()
    return middle + num_std * std, middle, middle - num_std * std


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — volatility measure for position sizing and stops."""
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def keltner_channels(df: pd.DataFrame, period: int = 20, mult: float = 1.5
                     ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Keltner Channels — EMA ± ATR multiplier."""
    mid = df["close"].ewm(span=period, adjust=False).mean()
    atr_val = atr(df, period)
    return mid + mult * atr_val, mid, mid - mult * atr_val


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume — cumulative volume weighted by price direction."""
    close, volume = df["close"], df["volume"]
    direction = np.sign(close.diff()).fillna(0)
    return (volume * direction).cumsum()


def adl(df: pd.DataFrame) -> pd.Series:
    """Accumulation/Distribution Line — money flow based on close position in range."""
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
    hl_range = high - low
    mfm = ((close - low) - (high - close)) / hl_range.replace(0, np.nan)
    mfm = mfm.fillna(0)
    return (mfm * volume).cumsum()


def compute_all(df: pd.DataFrame) -> dict:
    """
    Compute all indicators on a bar DataFrame.
    Returns latest scalar values + full [{time, value}] series for charting.
    """
    closes = df["close"]

    def last(series: pd.Series):
        val = series.dropna()
        return float(val.iloc[-1]) if len(val) > 0 else None

    # ── Compute ──────────────────────────────────────────────────────────────
    rsi_series              = rsi(closes)
    macd_line, sig_line, hist = macd(closes)
    bb_upper, _, bb_lower   = bollinger_bands(closes)

    # ── Latest scalar values ─────────────────────────────────────────────────
    rsi_val      = last(rsi_series)
    macd_val     = last(macd_line)
    macd_sig_val = last(sig_line)
    macd_hist_val= last(hist)
    bb_upper_val = last(bb_upper)
    bb_lower_val = last(bb_lower)

    # ── Convert Series → [{time, value}] for Chart.js ────────────────────────
    # Uses the DataFrame index (DatetimeIndex from yfinance) as timestamps.
    def to_timed(series: pd.Series, n: int = 200) -> list:
        """Return last n non-NaN values as [{time: ISO-str, value: float}]."""
        tail = series.tail(n)
        result = []
        for ts, v in tail.items():
            if pd.isna(v):
                continue
            try:
                result.append({
                    "time":  str(ts),
                    "value": round(float(v), 4),
                })
            except Exception:
                pass
        return result

    return {
        # Scalar values for stat cards
        "rsi":         round(rsi_val,       2) if rsi_val       is not None else None,
        "macd":        round(macd_val,      4) if macd_val      is not None else None,
        "macd_signal": round(macd_sig_val,  4) if macd_sig_val  is not None else None,
        "macd_hist":   round(macd_hist_val, 4) if macd_hist_val is not None else None,
        "bb_upper":    round(bb_upper_val,  4) if bb_upper_val  is not None else None,
        "bb_lower":    round(bb_lower_val,  4) if bb_lower_val  is not None else None,

        # Timestamped series for Chart.js [{time, value}, ...]
        "_rsi_series":       to_timed(rsi_series),
        "_macd_series":      to_timed(macd_line),
        "_macd_sig_series":  to_timed(sig_line),
        "_macd_hist_series": to_timed(hist),
        "_bb_upper_series":  to_timed(bb_upper),
        "_bb_lower_series":  to_timed(bb_lower),
    }
