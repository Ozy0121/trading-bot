"""
openbb_data.py
--------------
Unified data abstraction layer for all market data fetching.

Uses yfinance as the default free provider with FMP (Financial Modeling Prep)
as an automatic fallback on rate-limit or any other errors.

IMPORTANT: OpenBB Platform 4.7.1 is installed but broken on Python 3.14
(ImportError on obb.equity). This module works WITHOUT OpenBB using direct
yfinance + FMP calls, structured so OpenBB can be plugged in as a provider
backend later when Python 3.14 support lands.

Usage:
    from openbb_data import fetch_bars, fetch_quote, fetch_ticker_info, fetch_bulk_bars

    df = fetch_bars("AAPL", period="60d", interval="1d")
    price = fetch_quote("AAPL")
    info = fetch_ticker_info("AAPL")
    bulk = fetch_bulk_bars(["AAPL", "MSFT"], period="5d")
"""

from __future__ import annotations

import os

import pandas as pd
import requests
import yfinance as yf

from logger_setup import get_logger
from yf_limiter import rate_limited_yf, get_spy_history, get_sector_cached  # noqa: F401 (re-exported)

log = get_logger()

# ── Config ───────────────────────────────────────────────────────────────────

FMP_API_KEY = os.getenv("FMP_API_KEY", "")
FMP_BASE_URL = "https://financialmodelingprep.com"
REQUEST_TIMEOUT = 10

# ── Period / interval mappings ────────────────────────────────────────────────

# Maps common period strings to number of days for FMP timeseries parameter
_PERIOD_TO_DAYS: dict[str, int] = {
    "1d":   1,
    "5d":   5,
    "1mo":  30,
    "3mo":  90,
    "6mo":  180,
    "1y":   365,
    "2y":   730,
    "5y":   1825,
    "10y":  3650,
    "max":  3650,
    "ytd":  180,
}

# Maps yfinance interval strings to FMP chart intervals
_INTERVAL_MAP_FMP: dict[str, str] = {
    "1m":  "1min",
    "5m":  "5min",
    "15m": "15min",
    "30m": "30min",
    "60m": "1hour",
    "1h":  "1hour",
    "1d":  "daily",
}


def _period_to_days(period: str) -> int:
    """Convert a period string to number of days for FMP API."""
    if period in _PERIOD_TO_DAYS:
        return _PERIOD_TO_DAYS[period]
    # Handle strings like "60d", "90d"
    if period.endswith("d"):
        try:
            return int(period.rstrip("d"))
        except ValueError:
            pass
    return 60  # sensible fallback


# ── FMP helper ────────────────────────────────────────────────────────────────

def _fmp_get(endpoint: str, params: dict) -> dict | list | None:
    """
    Make a GET request to the FMP REST API.
    Returns parsed JSON or None on error.
    Requires FMP_API_KEY to be set; returns None immediately if key is absent.
    """
    if not FMP_API_KEY:
        return None

    params = {**params, "apikey": FMP_API_KEY}
    url = f"{FMP_BASE_URL}{endpoint}"

    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.debug("[openbb_data] FMP request failed (%s): %s", endpoint, exc)
        return None


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame | None:
    """
    Normalize a DataFrame to lowercase columns, DatetimeIndex, and
    standard [open, high, low, close, volume] column order.
    Returns None if the DataFrame is empty or missing required columns.
    """
    if df is None or df.empty:
        return None

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(set(df.columns)):
        return None

    df = df[["open", "high", "low", "close", "volume"]].copy()

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    df = df.sort_index()
    return df


def _fmp_bars_to_df(data: list) -> pd.DataFrame | None:
    """
    Convert FMP historical price list to a normalized DataFrame.
    FMP returns records in reverse chronological order (newest first).
    """
    if not data:
        return None

    try:
        df = pd.DataFrame(data)
        # FMP daily: columns are date, open, high, low, close, volume
        # FMP intraday: columns are date, open, high, low, close, volume
        if "date" not in df.columns:
            return None

        df.index = pd.to_datetime(df["date"])
        df = df.drop(columns=["date"], errors="ignore")

        # Rename adjClose to adj_close if present; we don't use it but avoid confusion
        df = df.rename(columns={"adjClose": "adj_close", "vwap": "vwap",
                                  "changePercent": "change_pct", "change": "change",
                                  "label": "label", "unadjustedVolume": "unadjusted_volume"})

        # Keep only OHLCV
        rename_map = {}
        for col in df.columns:
            rename_map[col] = col.lower()
        df = df.rename(columns=rename_map)

        return _normalize_df(df)
    except Exception as exc:
        log.debug("[openbb_data] FMP bar conversion failed: %s", exc)
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_bars(symbol: str, period: str = "60d", interval: str = "1d") -> pd.DataFrame | None:
    """
    Fetch OHLCV bars for a symbol.

    Primary: yfinance via rate_limited_yf (token bucket rate limiter).
    Fallback: FMP REST API if yfinance raises any exception.

    Returns a DataFrame with lowercase columns [open, high, low, close, volume]
    and a DatetimeIndex, sorted ascending. Returns None if both providers fail.
    """
    # ── Primary: yfinance ────────────────────────────────────────────────────
    try:
        df = rate_limited_yf(
            lambda: yf.Ticker(symbol).history(period=period, interval=interval)
        )
        if df is not None and not df.empty:
            normalized = _normalize_df(df)
            if normalized is not None:
                log.debug("[openbb_data] %s bars via yfinance (period=%s)", symbol, period)
                return normalized
    except Exception as exc:
        log.info("[openbb_data] %s yfinance failed (%s), trying FMP fallback", symbol, exc)

    # ── Fallback: FMP ────────────────────────────────────────────────────────
    if not FMP_API_KEY:
        log.debug("[openbb_data] %s: no FMP_API_KEY, skipping fallback", symbol)
        return None

    fmp_interval = _INTERVAL_MAP_FMP.get(interval, "daily")

    try:
        if fmp_interval == "daily":
            days = _period_to_days(period)
            data = _fmp_get(
                f"/api/v3/historical-price-full/{symbol}",
                {"timeseries": days},
            )
            if isinstance(data, dict) and "historical" in data:
                df = _fmp_bars_to_df(data["historical"])
                if df is not None:
                    log.info("[openbb_data] %s bars via FMP fallback (daily, %dd)", symbol, days)
                    return df
        else:
            data = _fmp_get(
                f"/api/v3/historical-chart/{fmp_interval}/{symbol}",
                {},
            )
            if isinstance(data, list):
                df = _fmp_bars_to_df(data)
                if df is not None:
                    log.info("[openbb_data] %s bars via FMP fallback (%s)", symbol, fmp_interval)
                    return df
    except Exception as exc:
        log.warning("[openbb_data] %s FMP fallback failed: %s", symbol, exc)

    log.warning("[openbb_data] %s: both providers failed for bars", symbol)
    return None


def fetch_quote(symbol: str) -> float | None:
    """
    Get the latest price for a symbol.

    Primary: yfinance 1-day 1-minute history, take last close.
    Fallback: FMP /api/v3/quote-short/{symbol}.

    Returns None on failure.
    """
    # ── Primary: yfinance ────────────────────────────────────────────────────
    try:
        df = rate_limited_yf(
            lambda: yf.Ticker(symbol).history(period="1d", interval="1m")
        )
        if df is not None and not df.empty:
            df.columns = [c.lower() for c in df.columns]
            price = float(df["close"].iloc[-1])
            log.debug("[openbb_data] %s quote via yfinance: %.4f", symbol, price)
            return price
    except Exception as exc:
        log.info("[openbb_data] %s yfinance quote failed (%s), trying FMP", symbol, exc)

    # ── Fallback: FMP ────────────────────────────────────────────────────────
    if not FMP_API_KEY:
        return None

    try:
        data = _fmp_get(f"/api/v3/quote-short/{symbol}", {})
        if isinstance(data, list) and data:
            price = float(data[0].get("price", 0))
            if price > 0:
                log.info("[openbb_data] %s quote via FMP fallback: %.4f", symbol, price)
                return price
    except Exception as exc:
        log.warning("[openbb_data] %s FMP quote fallback failed: %s", symbol, exc)

    return None


def fetch_ticker_info(symbol: str) -> dict:
    """
    Get ticker metadata (sector, marketCap, etc.).

    Primary: yfinance Ticker.info via rate_limited_yf.
    Fallback: FMP /api/v3/profile/{symbol}.

    Returns empty dict on failure.
    """
    # ── Primary: yfinance ────────────────────────────────────────────────────
    try:
        info = rate_limited_yf(lambda: yf.Ticker(symbol).info)
        if isinstance(info, dict) and info:
            log.debug("[openbb_data] %s info via yfinance", symbol)
            return info
    except Exception as exc:
        log.info("[openbb_data] %s yfinance info failed (%s), trying FMP", symbol, exc)

    # ── Fallback: FMP ────────────────────────────────────────────────────────
    if not FMP_API_KEY:
        return {}

    try:
        data = _fmp_get(f"/api/v3/profile/{symbol}", {})
        if isinstance(data, list) and data:
            profile = data[0]
            # Normalize FMP profile to approximate yfinance info keys
            normalized = {
                "sector":        profile.get("sector", ""),
                "industry":      profile.get("industry", ""),
                "marketCap":     profile.get("mktCap", 0),
                "longName":      profile.get("companyName", ""),
                "exchange":      profile.get("exchangeShortName", ""),
                "website":       profile.get("website", ""),
                "description":   profile.get("description", ""),
                "country":       profile.get("country", ""),
            }
            log.info("[openbb_data] %s info via FMP fallback", symbol)
            return normalized
    except Exception as exc:
        log.warning("[openbb_data] %s FMP info fallback failed: %s", symbol, exc)

    return {}


def fetch_bulk_bars(
    symbols: list[str],
    period: str = "5d",
    interval: str = "1d",
) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV bars for multiple symbols at once.

    Primary: yfinance bulk download (yf.download) via rate_limited_yf.
    Fallback: loop through symbols individually using fetch_bars.

    Returns dict mapping symbol -> DataFrame (lowercase columns, DatetimeIndex).
    Missing symbols are omitted from the result.
    """
    result: dict[str, pd.DataFrame] = {}

    if not symbols:
        return result

    # ── Primary: yfinance bulk download ─────────────────────────────────────
    try:
        raw = rate_limited_yf(
            lambda: yf.download(
                symbols,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        )

        if raw is not None and not raw.empty:
            if len(symbols) == 1:
                # Single symbol: yf.download returns flat columns
                sym = symbols[0]
                df = _normalize_df(raw)
                if df is not None:
                    result[sym] = df
            else:
                # Multi symbol: yf.download returns multi-level columns
                for sym in symbols:
                    try:
                        if sym in raw.columns.get_level_values(0):
                            sym_df = raw[sym].copy()
                            sym_df = _normalize_df(sym_df)
                            if sym_df is not None:
                                result[sym] = sym_df
                    except Exception:
                        pass

            if result:
                log.debug("[openbb_data] bulk_bars via yfinance: %d/%d symbols",
                          len(result), len(symbols))
                return result
    except Exception as exc:
        log.info("[openbb_data] bulk_bars yfinance failed (%s), falling back individually", exc)

    # ── Fallback: individual fetch_bars calls ────────────────────────────────
    log.info("[openbb_data] bulk_bars: fetching %d symbols individually via fallback", len(symbols))
    for sym in symbols:
        df = fetch_bars(sym, period=period, interval=interval)
        if df is not None:
            result[sym] = df

    return result
