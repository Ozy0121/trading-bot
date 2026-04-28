"""
openbb_data.py
--------------
Unified data abstraction layer for all market data fetching.

Provider priority: Polygon.io (paid) → yfinance (free) → FMP (free fallback).

Usage:
    from openbb_data import fetch_bars, fetch_quote, fetch_ticker_info, fetch_bulk_bars

    df = fetch_bars("AAPL", period="60d", interval="1d")
    price = fetch_quote("AAPL")
    info = fetch_ticker_info("AAPL")
    bulk = fetch_bulk_bars(["AAPL", "MSFT"], period="5d")
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta

import pandas as pd
import requests
import yfinance as yf

from logger_setup import get_logger
from yf_limiter import rate_limited_yf, get_spy_history, get_sector_cached  # noqa: F401 (re-exported)

log = get_logger()

# ── Config ───────────────────────────────────────────────────────────────────

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
POLYGON_BASE_URL = "https://api.polygon.io"
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
FMP_BASE_URL = "https://financialmodelingprep.com"
REQUEST_TIMEOUT = 15

# ── Polygon grouped daily cache ──────────────────────────────────────────────
# Prevents re-fetching the same data hundreds of times per scan cycle.
# Refresh: 5 min during market hours (9:30-16:00 ET), 30 min otherwise.

_grouped_cache: dict[str, dict[str, dict]] = {}  # date_str -> {sym: bar_dict}
_grouped_cache_ts: float = 0.0
_grouped_cache_lock = threading.Lock()
_MARKET_HOURS_TTL = 300    # 5 minutes
_AFTER_HOURS_TTL = 1800    # 30 minutes

# ── API call tracking ────────────────────────────────────────────────────────

_api_stats_lock = threading.Lock()
_api_stats = {
    "polygon_calls": 0,
    "polygon_cache_hits": 0,
    "yfinance_calls": 0,
    "fmp_calls": 0,
    "last_polygon_refresh": None,
    "last_yfinance_call": None,
    "last_fmp_call": None,
}


def get_api_stats() -> dict:
    with _api_stats_lock:
        return dict(_api_stats)


def _track_api_call(provider: str):
    with _api_stats_lock:
        _api_stats[f"{provider}_calls"] += 1
        _api_stats[f"last_{provider}_call"] = datetime.now().isoformat()


def _track_cache_hit():
    with _api_stats_lock:
        _api_stats["polygon_cache_hits"] += 1


def _is_market_hours() -> bool:
    try:
        import zoneinfo
        now_et = datetime.now(zoneinfo.ZoneInfo("America/New_York"))
        if now_et.weekday() >= 5:
            return False
        hour = now_et.hour
        minute = now_et.minute
        return (hour > 9 or (hour == 9 and minute >= 30)) and hour < 16
    except Exception:
        return False


def _grouped_cache_ttl() -> int:
    return _MARKET_HOURS_TTL if _is_market_hours() else _AFTER_HOURS_TTL

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


# ── Polygon.io interval mapping ──────────────────────────────────────────────

_INTERVAL_MAP_POLYGON: dict[str, tuple[int, str]] = {
    "1m":  (1, "minute"),
    "5m":  (5, "minute"),
    "15m": (15, "minute"),
    "30m": (30, "minute"),
    "60m": (1, "hour"),
    "1h":  (1, "hour"),
    "1d":  (1, "day"),
}


def _polygon_get(endpoint: str, params: dict | None = None) -> dict | None:
    if not POLYGON_API_KEY:
        return None
    params = {**(params or {}), "apiKey": POLYGON_API_KEY}
    url = f"{POLYGON_BASE_URL}{endpoint}"
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 429:
            log.warning("[openbb_data] Polygon rate limited on %s", endpoint)
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as exc:
        log.debug("[openbb_data] Polygon HTTP error (%s): %s", endpoint, exc)
        return None
    except Exception as exc:
        log.debug("[openbb_data] Polygon request failed (%s): %s", endpoint, exc)
        return None


def _polygon_bars(symbol: str, period: str = "60d", interval: str = "1d") -> pd.DataFrame | None:
    """Fetch bars for a single symbol from Polygon.io."""
    multiplier, timespan = _INTERVAL_MAP_POLYGON.get(interval, (1, "day"))
    days = _period_to_days(period)
    date_to = datetime.now().strftime("%Y-%m-%d")
    date_from = (datetime.now() - timedelta(days=days + 5)).strftime("%Y-%m-%d")

    data = _polygon_get(
        f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{date_from}/{date_to}",
        {"adjusted": "true", "sort": "asc", "limit": 50000},
    )
    if not data or data.get("resultsCount", 0) == 0:
        return None

    results = data.get("results", [])
    if not results:
        return None

    df = pd.DataFrame(results)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "t": "timestamp"})
    df.index = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df = df.sort_index()
    return df


def _polygon_grouped_daily(date_str: str) -> dict[str, dict] | None:
    """Fetch grouped daily bars for ALL US stocks on a single date.

    Results are cached per date_str; repeated calls for the same date
    within the TTL window return instantly from cache.
    """
    with _grouped_cache_lock:
        if date_str in _grouped_cache:
            _track_cache_hit()
            return _grouped_cache[date_str]

    _track_api_call("polygon")
    data = _polygon_get(
        f"/v2/aggs/grouped/locale/us/market/stocks/{date_str}",
        {"adjusted": "true"},
    )
    if not data or data.get("resultsCount", 0) == 0:
        return None

    result = {}
    for bar in data.get("results", []):
        sym = bar.get("T", "")
        if sym:
            result[sym] = {
                "open": bar["o"], "high": bar["h"], "low": bar["l"],
                "close": bar["c"], "volume": bar["v"],
                "timestamp": bar["t"],
            }

    with _grouped_cache_lock:
        _grouped_cache[date_str] = result

    return result


def _polygon_bulk_bars(symbols: list[str], period: str = "5d", progress_cb=None) -> dict[str, pd.DataFrame]:
    """
    Fetch bars for many symbols via Polygon.

    Strategy: grouped daily (1 call/day) for short periods with many symbols,
    per-ticker aggregates for longer periods or fewer symbols.
    """
    days = _period_to_days(period)

    # For periods > 10 days or small symbol lists, use per-ticker endpoint
    if days > 10 or len(symbols) < 50:
        return _polygon_bulk_per_ticker(symbols, period, progress_cb)

    # Grouped daily: 1 API call per trading day, returns ALL tickers
    return _polygon_bulk_grouped(symbols, period, progress_cb)


def _polygon_bulk_grouped(symbols: list[str], period: str = "5d", progress_cb=None) -> dict[str, pd.DataFrame]:
    """Grouped daily: best for short periods with large symbol lists.

    Uses a TTL-based cache so repeated calls (e.g. inside a scan loop)
    return instantly without hitting the API again.
    """
    global _grouped_cache_ts

    now = time.time()
    ttl = _grouped_cache_ttl()

    with _grouped_cache_lock:
        cache_age = now - _grouped_cache_ts
        cache_valid = _grouped_cache_ts > 0 and cache_age < ttl

    days = _period_to_days(period)
    per_sym: dict[str, list[dict]] = {s: [] for s in symbols}

    trading_days_needed = days + 2
    dates = []
    for i in range(trading_days_needed + 5):
        d = datetime.now() - timedelta(days=i)
        if d.weekday() < 5:
            dates.append(d.strftime("%Y-%m-%d"))
        if len(dates) >= trading_days_needed:
            break

    if cache_valid:
        for date_str in reversed(dates):
            with _grouped_cache_lock:
                grouped = _grouped_cache.get(date_str)
            if not grouped:
                continue
            for sym in symbols:
                if sym in grouped:
                    per_sym[sym].append(grouped[sym])
    else:
        if progress_cb:
            progress_cb(0, len(symbols), f"Fetching {len(dates)} days from Polygon...")

        for date_idx, date_str in enumerate(reversed(dates)):
            grouped = _polygon_grouped_daily(date_str)
            if not grouped:
                continue
            for sym in symbols:
                if sym in grouped:
                    per_sym[sym].append(grouped[sym])
            if progress_cb and date_idx % 2 == 0:
                progress_cb(0, len(symbols), f"Polygon: fetched {date_idx + 1}/{len(dates)} days...")

        with _grouped_cache_lock:
            _grouped_cache_ts = time.time()
            with _api_stats_lock:
                _api_stats["last_polygon_refresh"] = datetime.now().isoformat()

    result: dict[str, pd.DataFrame] = {}
    for sym, bars in per_sym.items():
        if not bars:
            continue
        df = pd.DataFrame(bars)
        df.index = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df = df.sort_index()
        if len(df) >= 1:
            result[sym] = df

    if progress_cb:
        progress_cb(len(symbols), len(symbols), f"Polygon: got bars for {len(result):,}/{len(symbols):,} symbols")

    missing = [s for s in symbols if s not in result]
    next_refresh_min = max(1, (ttl - int(now - _grouped_cache_ts)) // 60)

    if cache_valid:
        log.debug("[openbb_data] Polygon data served from cache (%d/%d symbols)", len(result), len(symbols))
    else:
        log.info("[openbb_data] Polygon grouped daily: %d/%d symbols across %d days",
                 len(result), len(symbols), len(dates))

    if missing and len(missing) <= 20:
        log.info("[openbb_data] Missing symbols (%d): %s", len(missing), ", ".join(missing[:20]))
    elif missing:
        log.info("[openbb_data] Missing %d symbols (first 10): %s", len(missing), ", ".join(missing[:10]))

    log.info("[openbb_data] Polygon data cached — next refresh in %d minutes", next_refresh_min)
    return result


def _polygon_bulk_per_ticker(symbols: list[str], period: str = "30d", progress_cb=None) -> dict[str, pd.DataFrame]:
    """Per-ticker aggregates: best for longer periods or smaller symbol lists."""
    result: dict[str, pd.DataFrame] = {}

    if progress_cb:
        progress_cb(0, len(symbols), f"Polygon: fetching {period} bars for {len(symbols):,} symbols...")

    for i, sym in enumerate(symbols):
        df = _polygon_bars(sym, period=period, interval="1d")
        if df is not None:
            result[sym] = df
        if progress_cb and i % 50 == 0 and i > 0:
            progress_cb(i, len(symbols), f"Polygon: {i:,}/{len(symbols):,} symbols...")

    if progress_cb:
        progress_cb(len(symbols), len(symbols), f"Polygon: got {period} bars for {len(result):,}/{len(symbols):,} symbols")

    log.info("[openbb_data] Polygon per-ticker: %d/%d symbols (%s)", len(result), len(symbols), period)
    return result


# ── FMP helper ────────────────────────────────────────────────────────────────

def _fmp_get(endpoint: str, params: dict) -> dict | list | None:
    """
    Make a GET request to the FMP REST API.
    Returns parsed JSON or None on error.
    Requires FMP_API_KEY to be set; returns None immediately if key is absent.
    """
    if not FMP_API_KEY:
        return None

    _track_api_call("fmp")
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

    Priority: Polygon.io → yfinance → FMP.
    Returns a DataFrame with lowercase columns [open, high, low, close, volume]
    and a DatetimeIndex, sorted ascending. Returns None if all providers fail.
    """
    # ── Primary: Polygon.io ─────────────────────────────────────────────────
    if POLYGON_API_KEY:
        try:
            df = _polygon_bars(symbol, period=period, interval=interval)
            if df is not None and not df.empty:
                log.debug("[openbb_data] %s bars via Polygon (period=%s)", symbol, period)
                return df
        except Exception as exc:
            log.debug("[openbb_data] %s Polygon failed (%s), trying yfinance", symbol, exc)

    # ── Fallback 1: yfinance ────────────────────────────────────────────────
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

    # ── Fallback 2: FMP ─────────────────────────────────────────────────────
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

    log.warning("[openbb_data] %s: all providers failed for bars", symbol)
    return None


def fetch_quote(symbol: str) -> float | None:
    """
    Get the latest price for a symbol.

    Priority: Polygon.io → yfinance → FMP.
    Returns None on failure.
    """
    # ── Primary: Polygon.io ─────────────────────────────────────────────────
    if POLYGON_API_KEY:
        try:
            data = _polygon_get(f"/v2/last/trade/{symbol}")
            if data and "results" in data:
                price = float(data["results"].get("p", 0))
                if price > 0:
                    log.debug("[openbb_data] %s quote via Polygon: %.4f", symbol, price)
                    return price
        except Exception as exc:
            log.debug("[openbb_data] %s Polygon quote failed (%s), trying yfinance", symbol, exc)

    # ── Fallback 1: yfinance ────────────────────────────────────────────────
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

    # ── Fallback 2: FMP ─────────────────────────────────────────────────────
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

    Priority: Polygon.io → yfinance → FMP.
    Returns empty dict on failure.
    """
    # ── Primary: Polygon.io ─────────────────────────────────────────────────
    if POLYGON_API_KEY:
        try:
            data = _polygon_get(f"/v3/reference/tickers/{symbol}")
            if data and "results" in data:
                r = data["results"]
                info = {
                    "sector":    r.get("sic_description", ""),
                    "industry":  r.get("sic_description", ""),
                    "marketCap": r.get("market_cap", 0),
                    "longName":  r.get("name", ""),
                    "exchange":  r.get("primary_exchange", ""),
                    "locale":    r.get("locale", ""),
                }
                if info.get("longName"):
                    log.debug("[openbb_data] %s info via Polygon", symbol)
                    return info
        except Exception as exc:
            log.debug("[openbb_data] %s Polygon info failed (%s), trying yfinance", symbol, exc)

    # ── Fallback 1: yfinance ────────────────────────────────────────────────
    try:
        info = rate_limited_yf(lambda: yf.Ticker(symbol).info)
        if isinstance(info, dict) and info:
            log.debug("[openbb_data] %s info via yfinance", symbol)
            return info
    except Exception as exc:
        log.debug("[openbb_data] %s yfinance info failed (%s), trying FMP", symbol, exc)

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
            log.debug("[openbb_data] %s info via FMP fallback", symbol)
            return normalized
    except Exception as exc:
        log.warning("[openbb_data] %s FMP info fallback failed: %s", symbol, exc)

    return {}


def fetch_bulk_bars(
    symbols: list[str],
    period: str = "5d",
    interval: str = "1d",
    progress_cb: callable | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV bars for multiple symbols at once.

    Priority: Polygon grouped daily (all symbols in ~5 API calls) → yfinance → individual fallback.
    Returns dict mapping symbol -> DataFrame (lowercase columns, DatetimeIndex).
    Missing symbols are omitted from the result.
    """
    result: dict[str, pd.DataFrame] = {}

    if not symbols:
        return result

    # ── Primary: Polygon grouped daily ──────────────────────────────────────
    if POLYGON_API_KEY and interval in ("1d", "daily"):
        try:
            result = _polygon_bulk_bars(symbols, period=period, progress_cb=progress_cb)
            if result:
                return result
        except Exception as exc:
            log.info("[openbb_data] Polygon bulk_bars failed (%s), falling back to yfinance", exc)

    # ── Fallback 1: yfinance bulk download (batched) ────────────────────────
    batch_size = 100
    if len(symbols) > batch_size:
        batches = [symbols[i:i+batch_size] for i in range(0, len(symbols), batch_size)]
        for batch_idx, batch in enumerate(batches):
            if progress_cb:
                done = batch_idx * batch_size
                progress_cb(done, len(symbols), f"Fetching bars: {done:,}/{len(symbols):,} symbols...")
            batch_result = _yf_bulk_batch(batch, period=period, interval=interval)
            result.update(batch_result)
            if batch_idx < len(batches) - 1:
                time.sleep(2.0)
        if progress_cb:
            progress_cb(len(symbols), len(symbols), f"Fetched bars for {len(result):,}/{len(symbols):,} symbols")
        return result

    result = _yf_bulk_batch(symbols, period=period, interval=interval)
    if result:
        return result

    # ── Fallback 2: individual fetch_bars calls ─────────────────────────────
    log.info("[openbb_data] bulk_bars: fetching %d symbols individually via fallback", len(symbols))
    consecutive_failures = 0
    for i, sym in enumerate(symbols):
        if i > 0 and i % 10 == 0:
            time.sleep(1.0)
        try:
            df = fetch_bars(sym, period=period, interval=interval)
            if df is not None:
                result[sym] = df
                consecutive_failures = 0
            else:
                consecutive_failures += 1
        except Exception:
            consecutive_failures += 1
        if consecutive_failures >= 20:
            log.warning("[openbb_data] bulk_bars fallback: %d consecutive failures, skipping remaining %d symbols",
                        consecutive_failures, len(symbols) - i - 1)
            break

    return result


def _yf_bulk_batch(symbols: list[str], period: str = "5d", interval: str = "1d") -> dict[str, pd.DataFrame]:
    """Fetch a single batch of symbols via yf.download."""
    result: dict[str, pd.DataFrame] = {}
    _track_api_call("yfinance")
    try:
        raw = rate_limited_yf(
            lambda: yf.download(
                symbols,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        )

        if raw is not None and not raw.empty:
            if len(symbols) == 1:
                sym = symbols[0]
                df = _normalize_df(raw)
                if df is not None:
                    result[sym] = df
            else:
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
    except Exception as exc:
        log.info("[openbb_data] bulk_bars yfinance failed (%s)", exc)

    return result
