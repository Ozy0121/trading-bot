"""
stock_universe.py
-----------------
Expanded stock universe for scanning — S&P 500, NASDAQ 100, small/mid cap
discovery, leveraged ETFs, futures-tracking ETFs, and dynamic filters.

Provides tiered scanning:
  Tier 1: Core watchlist + top movers (fast, every cycle)
  Tier 2: S&P 500 + NASDAQ 100 (full scan, hourly)
  Tier 3: Small/mid cap discovery (daily, market close)

Discovery filters:
  - Small caps ($300M-$2B) with high momentum
  - Mid caps ($2B-$10B) with unusual volume
  - Stocks hitting 52-week highs on volume (breakout candidates)
  - Stocks that crashed 10%+ recently with strong fundamentals (bounce plays)
  - High short interest (short squeeze potential)
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf
import pandas as pd
import requests

from logger_setup import get_logger

log = get_logger()

# ── Static lists ─────────────────────────────────────────────────────────────

# Futures-tracking ETFs
FUTURES_ETFS = ["USO", "GLD", "SLV", "UNG", "TLT", "DBA", "DBB"]

# Leveraged ETFs for bigger moves
LEVERAGED_ETFS = ["TQQQ", "SQQQ", "SPXL", "SPXS", "UVXY", "SOXL", "SOXS", "LABU", "LABD"]

# S&P 500 — full list (updated periodically, fetched dynamically with fallback)
_sp500_cache: list[str] = []
_sp500_date: date | None = None
_sp500_lock = threading.Lock()

# NASDAQ 100
_ndx100_cache: list[str] = []
_ndx100_date: date | None = None
_ndx100_lock = threading.Lock()

# Discovery cache
_discovery_cache: list[dict] = []
_discovery_date: date | None = None
_discovery_lock = threading.Lock()


# ── S&P 500 fetcher ─────────────────────────────────────────────────────────

def get_sp500() -> list[str]:
    """Fetch S&P 500 symbols from Wikipedia. Cached per day."""
    global _sp500_cache, _sp500_date
    today = date.today()

    with _sp500_lock:
        if _sp500_date == today and _sp500_cache:
            return _sp500_cache

    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(resp.text, header=0)
        df = tables[0]
        symbols = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        symbols = [s.strip() for s in symbols if s.strip()]
        log.info("[universe] Fetched %d S&P 500 symbols", len(symbols))

        with _sp500_lock:
            _sp500_cache = symbols
            _sp500_date = today
        return symbols

    except Exception as exc:
        log.warning("[universe] S&P 500 fetch failed: %s — using fallback", exc)
        with _sp500_lock:
            if _sp500_cache:
                return _sp500_cache
        return _SP500_FALLBACK


def get_nasdaq100() -> list[str]:
    """Fetch NASDAQ 100 symbols from Wikipedia. Cached per day."""
    global _ndx100_cache, _ndx100_date
    today = date.today()

    with _ndx100_lock:
        if _ndx100_date == today and _ndx100_cache:
            return _ndx100_cache

    try:
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(resp.text, header=0)
        # The table with tickers — look for a "Ticker" or "Symbol" column
        df = None
        for t in tables:
            cols = [c.lower() for c in t.columns]
            if "ticker" in cols or "symbol" in cols:
                df = t
                break
        if df is None:
            df = tables[3]  # common position for the components table

        col = "Ticker" if "Ticker" in df.columns else "Symbol"
        symbols = df[col].str.replace(".", "-", regex=False).tolist()
        symbols = [s.strip() for s in symbols if s.strip()]
        log.info("[universe] Fetched %d NASDAQ 100 symbols", len(symbols))

        with _ndx100_lock:
            _ndx100_cache = symbols
            _ndx100_date = today
        return symbols

    except Exception as exc:
        log.warning("[universe] NASDAQ 100 fetch failed: %s — using fallback", exc)
        with _ndx100_lock:
            if _ndx100_cache:
                return _ndx100_cache
        return _NDX100_FALLBACK


# ── Discovery scans (small/mid caps, 52wk highs, bounce plays) ──────────────

def _screen_yahoo(screen_id: str, count: int = 50) -> list[dict]:
    """Fetch a Yahoo Finance predefined screener."""
    url = (
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
        f"?count={count}&scrIds={screen_id}&region=US&lang=en-US"
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data["finance"]["result"][0]["quotes"]
    except Exception as exc:
        log.debug("[universe] Yahoo screener '%s' failed: %s", screen_id, exc)
        return []


def discover_small_caps() -> list[dict]:
    """
    Find small caps ($300M-$2B) with high momentum.
    Uses Yahoo's small_cap_gainers screener + yfinance info filtering.
    """
    results = []
    quotes = _screen_yahoo("small_cap_gainers", 100)

    for q in quotes:
        symbol = q.get("symbol", "")
        mkt_cap = q.get("marketCap", 0)
        price = q.get("regularMarketPrice", 0)
        volume = q.get("regularMarketVolume", 0)
        change_pct = q.get("regularMarketChangePercent", 0)

        if not symbol or "." in symbol:
            continue
        if not (300_000_000 <= mkt_cap <= 2_000_000_000):
            continue
        if price < 3 or volume < 500_000:
            continue

        results.append({
            "symbol": symbol,
            "market_cap": mkt_cap,
            "price": price,
            "volume": volume,
            "change_pct": round(change_pct, 2),
            "source": "small_cap_momentum",
        })

    log.info("[universe] Small cap discovery: %d candidates", len(results))
    return results


def discover_mid_cap_volume() -> list[dict]:
    """
    Find mid caps ($2B-$10B) with unusual volume spikes.
    """
    results = []
    quotes = _screen_yahoo("most_actives", 100)

    for q in quotes:
        symbol = q.get("symbol", "")
        mkt_cap = q.get("marketCap", 0)
        price = q.get("regularMarketPrice", 0)
        volume = q.get("regularMarketVolume", 0)
        avg_volume = q.get("averageDailyVolume3Month", 1)

        if not symbol or "." in symbol:
            continue
        if not (2_000_000_000 <= mkt_cap <= 10_000_000_000):
            continue
        if price < 5:
            continue

        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0
        if vol_ratio < 2.0:  # need at least 2x normal volume
            continue

        results.append({
            "symbol": symbol,
            "market_cap": mkt_cap,
            "price": price,
            "volume": volume,
            "vol_ratio": round(vol_ratio, 1),
            "source": "mid_cap_unusual_volume",
        })

    log.info("[universe] Mid cap unusual volume: %d candidates", len(results))
    return results


def discover_52wk_high_breakouts() -> list[dict]:
    """
    Stocks hitting new 52-week highs with big volume — breakout candidates.
    """
    results = []
    quotes = _screen_yahoo("day_gainers", 100)

    for q in quotes:
        symbol = q.get("symbol", "")
        price = q.get("regularMarketPrice", 0)
        volume = q.get("regularMarketVolume", 0)
        avg_volume = q.get("averageDailyVolume3Month", 1)
        high_52w = q.get("fiftyTwoWeekHigh", 0)

        if not symbol or "." in symbol:
            continue
        if price < 5 or high_52w <= 0:
            continue

        # Within 2% of 52-week high
        if price < high_52w * 0.98:
            continue

        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0
        if vol_ratio < 1.5:  # need elevated volume
            continue

        results.append({
            "symbol": symbol,
            "price": price,
            "high_52w": round(high_52w, 2),
            "pct_from_high": round((price / high_52w - 1) * 100, 2),
            "vol_ratio": round(vol_ratio, 1),
            "source": "52wk_high_breakout",
        })

    log.info("[universe] 52-week high breakouts: %d candidates", len(results))
    return results


def discover_bounce_plays() -> list[dict]:
    """
    Stocks that crashed 10%+ recently — potential bounce plays.
    Uses day_losers screener and checks for strong fundamentals.
    """
    results = []
    quotes = _screen_yahoo("day_losers", 100)

    for q in quotes:
        symbol = q.get("symbol", "")
        price = q.get("regularMarketPrice", 0)
        mkt_cap = q.get("marketCap", 0)
        change_pct = q.get("regularMarketChangePercent", 0)

        if not symbol or "." in symbol:
            continue
        if mkt_cap < 1_000_000_000:  # at least $1B — strong fundamentals
            continue
        if price < 5:
            continue
        if change_pct > -5:  # need significant drop
            continue

        results.append({
            "symbol": symbol,
            "price": price,
            "market_cap": mkt_cap,
            "drop_pct": round(change_pct, 2),
            "source": "bounce_play",
        })

    log.info("[universe] Bounce play candidates: %d", len(results))
    return results


def run_discovery() -> list[dict]:
    """
    Run all discovery scans in parallel. Returns combined list of candidates.
    Cached per day.
    """
    global _discovery_cache, _discovery_date
    today = date.today()

    with _discovery_lock:
        if _discovery_date == today and _discovery_cache:
            return _discovery_cache

    all_results: list[dict] = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(discover_small_caps): "small_caps",
            executor.submit(discover_mid_cap_volume): "mid_cap_volume",
            executor.submit(discover_52wk_high_breakouts): "52wk_highs",
            executor.submit(discover_bounce_plays): "bounce_plays",
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                results = future.result()
                all_results.extend(results)
            except Exception as exc:
                log.warning("[universe] Discovery scan '%s' failed: %s", name, exc)

    # Deduplicate by symbol
    seen = set()
    deduped = []
    for r in all_results:
        sym = r["symbol"]
        if sym not in seen:
            seen.add(sym)
            deduped.append(r)

    log.info("[universe] Discovery complete: %d unique candidates across all scans", len(deduped))

    with _discovery_lock:
        _discovery_cache = deduped
        _discovery_date = today

    return deduped


def get_full_universe(include_discovery: bool = True) -> list[str]:
    """
    Get the complete expanded stock universe for scanning.
    Returns deduplicated list of all symbols.
    """
    symbols: list[str] = []
    seen: set[str] = set()

    def _add(syms):
        for s in syms:
            if s not in seen and s not in _BAD_SYMBOLS:
                seen.add(s)
                symbols.append(s)

    # Core indices
    _add(get_sp500())
    _add(get_nasdaq100())

    # Specialty ETFs
    _add(FUTURES_ETFS)
    _add(LEVERAGED_ETFS)

    # Discovery candidates
    if include_discovery:
        discovery = run_discovery()
        _add([d["symbol"] for d in discovery])

    log.info("[universe] Full universe: %d symbols", len(symbols))
    return symbols


def get_scan_summary(
    total_scanned: int,
    passed_filters: int,
    top_ranked: int,
) -> str:
    """Format the scan summary string for the dashboard."""
    return f"Scanned {total_scanned:,} stocks → {passed_filters} passed filters → Top {top_ranked} ranked"


# ── Heatmap data fetcher ─────────────────────────────────────────────────────

def fetch_heatmap_data(symbols: list[str] | None = None) -> list[dict]:
    """
    Fetch market cap, price, daily change, and sector for heatmap rendering.
    Uses yfinance batch download for efficiency.
    """
    if symbols is None:
        symbols = get_sp500() + get_nasdaq100()
        symbols = list(dict.fromkeys(symbols))  # dedup preserving order

    results = []

    # Batch download today's data
    try:
        data = yf.download(
            symbols,
            period="2d",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        log.warning("[universe] Heatmap batch download failed: %s", exc)
        return results

    # Fetch info for market cap and sector (cached by yfinance)
    def _get_info(sym):
        try:
            if len(symbols) == 1:
                closes = data["Close"].dropna()
            else:
                if sym not in data.columns.get_level_values(0):
                    return None
                closes = data[sym]["Close"].dropna()

            if len(closes) < 2:
                return None

            price = float(closes.iloc[-1])
            prev_close = float(closes.iloc[-2])
            change_pct = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0.0

            info = yf.Ticker(sym).fast_info
            market_cap = getattr(info, "market_cap", None) or 0

            return {
                "symbol": sym,
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
                "market_cap": market_cap,
                "volume": int(closes.index[-1].day_of_year) if hasattr(closes.index[-1], 'day_of_year') else 0,
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_get_info, sym): sym for sym in symbols[:600]}
        for future in as_completed(futures):
            try:
                result = future.result()
                if result and result["market_cap"] > 0:
                    results.append(result)
            except Exception:
                pass

    log.info("[universe] Heatmap data: %d stocks with valid data", len(results))
    return results


# ── Fallback lists (if Wikipedia is unreachable) ────────────────────────────

_SP500_FALLBACK = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA", "BRK-B", "UNH",
    "JNJ", "XOM", "JPM", "V", "PG", "AVGO", "MA", "HD", "CVX", "MRK", "ABBV",
    "LLY", "PEP", "COST", "KO", "ADBE", "WMT", "CRM", "MCD", "BAC", "CSCO",
    "ACN", "NFLX", "AMD", "LIN", "TMO", "PFE", "ABT", "DHR", "ORCL", "CMCSA",
    "DIS", "PM", "TXN", "VZ", "INTC", "NKE", "WFC", "AMGN", "UPS", "RTX",
    "COP", "BA", "CAT", "GS", "MS", "IBM", "GE", "DE", "SBUX", "INTU",
    "BLK", "LOW", "ISRG", "GILD", "AXP", "MDLZ", "BKNG", "SPGI", "SYK",
    "ADI", "REGN", "TJX", "LRCX", "VRTX", "MMC", "ZTS", "PLD", "CB",
    "PANW", "NOW", "SHW", "SNPS", "CDNS", "CME", "KLAC", "MO", "CL",
    "SO", "DUK", "ICE", "BMY", "EOG", "SLB", "ANET", "MCK", "APD",
]

# Symbols known to have bad data on yfinance (delisted, ticker changed, etc.)
_BAD_SYMBOLS = {"MMC", "ANSS"}

_NDX100_FALLBACK = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA", "AVGO", "COST",
    "NFLX", "AMD", "ADBE", "PEP", "CSCO", "INTC", "CMCSA", "TMUS", "AMGN",
    "TXN", "INTU", "ISRG", "BKNG", "GILD", "LRCX", "VRTX", "REGN", "MDLZ",
    "KLAC", "SNPS", "CDNS", "PANW", "MRVL", "ORLY", "MNST", "FTNT", "CTAS",
    "ADP", "CHTR", "MELI", "DXCM", "PYPL", "MAR", "ABNB", "PCAR", "TTD",
    "CPRT", "MCHP", "KDP", "NXPI", "LULU", "AEP", "CEG", "ROST", "IDXX",
    "EXC", "CTSH", "FAST", "VRSK", "EA", "ODFL", "GEHC", "XEL", "BKR",
    "DDOG", "FANG", "TEAM", "KHC", "ANSS", "ZS", "DLTR", "CDW", "CSGP",
    "MRNA", "ILMN", "BIIB", "ENPH", "SIRI", "WBD", "JD", "LCID", "RIVN",
    "PLTR", "CRWD", "SOFI", "HOOD", "COIN", "DKNG", "RBLX", "SNAP", "PINS",
]
