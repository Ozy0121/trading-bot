"""
yf_limiter.py
-------------
Global rate limiter for all yfinance API calls across the trading bot.

Problem: scanner.py, prediction.py, backtester.py, prediction_scanner.py, and
stock_universe.py all create ThreadPoolExecutors independently and hit yfinance
concurrently, causing "Too Many Requests" (429) errors.

Solution: A single token-bucket rate limiter that ALL yfinance calls must go
through. Also provides a shared SPY data cache and a persistent sector cache
to eliminate redundant fetches.

Usage:
    from yf_limiter import rate_limited_yf, get_spy_history, get_sector_cached

    # Wrap any yfinance call:
    df = rate_limited_yf(lambda: yf.Ticker("AAPL").history(period="60d"))

    # Fetch SPY once per session:
    spy_df = get_spy_history(period="10d")

    # Get sector with persistent disk cache:
    sector = get_sector_cached("AAPL")
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import date
from typing import TypeVar, Callable

import yfinance as yf
import pandas as pd

from logger_setup import get_logger

log = get_logger()

T = TypeVar("T")

# ── Token bucket rate limiter ───────────────────────────────────────────────

_RATE_LIMIT = 5.0          # max requests per second (global)
_BUCKET_SIZE = 8            # burst capacity
_tokens = float(_BUCKET_SIZE)
_last_refill = time.monotonic()
_limiter_lock = threading.Lock()


def _wait_for_token() -> None:
    """Block until a token is available. Token bucket algorithm."""
    global _tokens, _last_refill

    while True:
        with _limiter_lock:
            now = time.monotonic()
            elapsed = now - _last_refill
            _tokens = min(_BUCKET_SIZE, _tokens + elapsed * _RATE_LIMIT)
            _last_refill = now

            if _tokens >= 1.0:
                _tokens -= 1.0
                return

        # No token available — wait a bit and retry
        time.sleep(0.1)


def rate_limited_yf(fn: Callable[[], T]) -> T:
    """
    Execute a yfinance call after acquiring a rate-limit token.
    Wraps any callable that hits the yfinance API.

    Example:
        df = rate_limited_yf(lambda: yf.Ticker("AAPL").history(period="60d"))
    """
    _wait_for_token()
    return fn()


# ── SPY history cache ───────────────────────────────────────────────────────

_spy_cache: dict[str, tuple[date, pd.DataFrame]] = {}
_spy_lock = threading.Lock()


def get_spy_history(period: str = "10d", interval: str = "1d") -> pd.DataFrame | None:
    """
    Fetch SPY history once per day per (period, interval) combo.
    All callers share the same cached result.
    """
    cache_key = f"{period}_{interval}"
    today = date.today()

    with _spy_lock:
        cached = _spy_cache.get(cache_key)
        if cached and cached[0] == today:
            return cached[1].copy()

    try:
        df = rate_limited_yf(
            lambda: yf.Ticker("SPY").history(period=period, interval=interval)
        )
        if df is None or df.empty:
            return None
        df.columns = [c.lower() for c in df.columns]

        with _spy_lock:
            _spy_cache[cache_key] = (today, df)
        return df.copy()

    except Exception as exc:
        log.warning("[yf_limiter] SPY fetch failed (period=%s): %s", period, exc)
        return None


# ── Sector ETF bar cache ────────────────────────────────────────────────────

SECTOR_ETF_MAP: dict[str, str] = {
    "XLK": "Technology",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "XLC": "Communication Services",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLB": "Materials",
}

_sector_etf_cache: dict[str, tuple[date, pd.DataFrame]] = {}
_sector_etf_lock = threading.Lock()


def get_sector_etf_bars(etf: str, period: str = "30d") -> pd.DataFrame | None:
    """
    Fetch sector ETF daily bars, cached once per day per ETF ticker.
    Follows the same pattern as get_spy_history.

    Args:
        etf: ETF ticker symbol (e.g. "XLK").
        period: yfinance period string (default "30d").

    Returns:
        DataFrame with lowercase columns, or None on failure.
    """
    today = date.today()

    with _sector_etf_lock:
        cached = _sector_etf_cache.get(etf)
        if cached and cached[0] == today:
            return cached[1].copy()

    try:
        df = rate_limited_yf(
            lambda: yf.Ticker(etf).history(period=period, interval="1d")
        )
        if df is None or df.empty:
            return None
        df.columns = [c.lower() for c in df.columns]

        with _sector_etf_lock:
            _sector_etf_cache[etf] = (today, df)
        return df.copy()

    except Exception as exc:
        log.warning("[yf_limiter] Sector ETF fetch failed (etf=%s): %s", etf, exc)
        return None


def prefetch_sector_etf_bars(period: str = "30d") -> dict[str, pd.DataFrame]:
    """
    Prefetch daily bars for all 11 sector ETFs in SECTOR_ETF_MAP.

    Call this once before a batch prediction run to populate the cache and
    avoid redundant per-symbol fetches during ThreadPoolExecutor execution.
    (Per RESEARCH.md Pitfall 5: pre-cache shared data before thread pool.)

    Args:
        period: yfinance period string (default "30d").

    Returns:
        Dict of {etf_ticker: DataFrame} for all successfully fetched ETFs.
        Failed ETFs are skipped and logged.
    """
    results: dict[str, pd.DataFrame] = {}
    for etf in SECTOR_ETF_MAP:
        df = get_sector_etf_bars(etf, period=period)
        if df is not None:
            results[etf] = df
        else:
            log.warning("[yf_limiter] prefetch: skipped %s (fetch failed)", etf)
    return results


# ── Persistent sector cache ─────────────────────────────────────────────────

_SECTOR_CACHE_FILE = os.path.join(os.path.dirname(__file__), "data", "sector_cache.json")
_sector_mem_cache: dict[str, str] = {}
_sector_disk_loaded = False
_sector_lock = threading.Lock()


def _load_sector_cache() -> None:
    """Load sector cache from disk into memory. Called once."""
    global _sector_mem_cache, _sector_disk_loaded

    if _sector_disk_loaded:
        return

    try:
        os.makedirs(os.path.dirname(_SECTOR_CACHE_FILE), exist_ok=True)
        with open(_SECTOR_CACHE_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _sector_mem_cache = data
            log.debug("[yf_limiter] Loaded %d sectors from disk cache", len(data))
    except (FileNotFoundError, json.JSONDecodeError):
        _sector_mem_cache = {}

    _sector_disk_loaded = True


def _save_sector_cache() -> None:
    """Persist sector cache to disk."""
    try:
        os.makedirs(os.path.dirname(_SECTOR_CACHE_FILE), exist_ok=True)
        with open(_SECTOR_CACHE_FILE, "w") as f:
            json.dump(_sector_mem_cache, f, indent=2)
    except Exception as exc:
        log.debug("[yf_limiter] Failed to save sector cache: %s", exc)


def get_sector_cached(symbol: str) -> str:
    """
    Get a stock's sector with persistent disk caching.
    Sectors rarely change, so we cache permanently (not per-day).
    Returns empty string if lookup fails.
    """
    with _sector_lock:
        _load_sector_cache()
        if symbol in _sector_mem_cache:
            return _sector_mem_cache[symbol]

    # Fetch from yfinance (outside lock to avoid blocking)
    try:
        info = rate_limited_yf(lambda: yf.Ticker(symbol).info)
        sector = info.get("sector", "") or ""
    except Exception:
        sector = ""

    with _sector_lock:
        _sector_mem_cache[symbol] = sector
        # Save every 50 new entries to avoid excessive disk writes
        if len(_sector_mem_cache) % 50 == 0:
            _save_sector_cache()

    return sector


def flush_sector_cache() -> None:
    """Force-save the sector cache to disk. Call at shutdown or end of scan."""
    with _sector_lock:
        _save_sector_cache()
