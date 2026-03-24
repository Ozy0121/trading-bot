"""
strategy.py
-----------
Simple Moving Average (SMA) Crossover strategy.

Logic:
  - Fetch the last N bars for the configured symbol.
  - Compute a SHORT-period SMA and a LONG-period SMA over closing prices.
  - Signal = BUY  when short SMA crosses ABOVE long SMA (momentum turning up).
  - Signal = SELL when short SMA crosses BELOW long SMA (momentum turning down).
  - Signal = HOLD if no crossover occurred.

Why SMA crossover?
  It's one of the most studied technical indicators, easy to reason about,
  and its signals are unambiguous — making it a good baseline strategy.
"""

from __future__ import annotations

import pandas as pd
from datetime import datetime, timezone, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

import config
from logger_setup import get_logger
from indicators import compute_all as compute_indicators

log = get_logger()

# Map the human-readable BAR_TIMEFRAME string from .env to Alpaca's TimeFrame
_TIMEFRAME_MAP: dict[str, TimeFrame] = {
    "1Min":  TimeFrame(1,  TimeFrameUnit.Minute),
    "5Min":  TimeFrame(5,  TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "1Hour": TimeFrame(1,  TimeFrameUnit.Hour),
    "1Day":  TimeFrame(1,  TimeFrameUnit.Day),
}


def _get_timeframe() -> TimeFrame:
    tf = _TIMEFRAME_MAP.get(config.BAR_TIMEFRAME)
    if tf is None:
        raise ValueError(
            f"[strategy] Unknown BAR_TIMEFRAME '{config.BAR_TIMEFRAME}'. "
            f"Valid options: {list(_TIMEFRAME_MAP.keys())}"
        )
    return tf


def fetch_bars(data_client: StockHistoricalDataClient) -> pd.DataFrame:
    """
    Fetch recent OHLCV bars from Alpaca for the configured symbol.
    Returns a DataFrame indexed by timestamp with at least a 'close' column.
    Fetches enough bars to compute both moving averages plus a buffer.
    """
    needed = config.LONG_WINDOW + config.LOOKBACK_BARS

    # Alpaca expects UTC start/end times
    end   = datetime.now(timezone.utc)
    # Fetch generously (extra days handle weekends/holidays with no data)
    start = end - timedelta(days=needed * 5)

    request = StockBarsRequest(
        symbol_or_symbols=config.SYMBOL,
        timeframe=_get_timeframe(),
        start=start,
        end=end,
        limit=needed,
        feed="iex",   # IEX feed is included in free Alpaca plans (SIP requires paid plan)
    )

    bars = data_client.get_stock_bars(request)

    # alpaca-py returns a BarSet; convert to a plain DataFrame
    df = bars.df

    if df.empty:
        log.warning("[strategy] No bars returned for %s. Market may be closed.", config.SYMBOL)
        return df

    # If multi-symbol, drop the symbol level from the MultiIndex
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(config.SYMBOL, level="symbol")

    df = df.sort_index()  # ensure chronological order
    log.debug("[strategy] Fetched %d bars for %s", len(df), config.SYMBOL)
    return df


def compute_signals(df: pd.DataFrame) -> dict:
    """
    Given a bar DataFrame, compute SMAs and return signal info.

    Returns a dict:
        {
          "signal":    "BUY" | "SELL" | "HOLD",
          "short_sma": float,
          "long_sma":  float,
          "price":     float,   # latest close price
        }
    """
    if len(df) < config.LONG_WINDOW:
        log.warning(
            "[strategy] Not enough bars (%d) to compute %d-period SMA. Holding.",
            len(df), config.LONG_WINDOW,
        )
        return {"signal": "HOLD", "short_sma": None, "long_sma": None, "price": None}

    closes = df["close"]

    # Rolling simple moving averages over the last N closing prices
    short_sma = closes.rolling(config.SHORT_WINDOW).mean()
    long_sma  = closes.rolling(config.LONG_WINDOW).mean()

    # Current and previous bar values (to detect a crossover)
    prev_short, curr_short = short_sma.iloc[-2], short_sma.iloc[-1]
    prev_long,  curr_long  = long_sma.iloc[-2],  long_sma.iloc[-1]
    price = closes.iloc[-1]

    log.debug(
        "[strategy] short_sma=%.4f long_sma=%.4f price=%.4f",
        curr_short, curr_long, price,
    )

    # Crossover detection
    # BUY:  short was BELOW (or equal) long, now short is ABOVE long
    # SELL: short was ABOVE (or equal) long, now short is BELOW long
    if prev_short <= prev_long and curr_short > curr_long:
        signal = "BUY"
    elif prev_short >= prev_long and curr_short < curr_long:
        signal = "SELL"
    else:
        signal = "HOLD"

    log.info(
        "[strategy] Signal=%s | %s | short_sma=%.4f long_sma=%.4f price=%.4f",
        signal, config.SYMBOL, curr_short, curr_long, price,
    )

    # Compute all technical indicators and attach to the result
    ind = compute_indicators(df)

    return {
        "signal":    signal,
        "short_sma": curr_short,
        "long_sma":  curr_long,
        "price":     price,
        **ind,   # rsi, macd, bb_upper/lower, and chart series
    }
