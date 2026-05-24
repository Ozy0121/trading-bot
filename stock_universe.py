"""
stock_universe.py
-----------------
Expanded stock universe for scanning — S&P 500, NASDAQ 100, Russell 2000
(small caps), top volume discovery, leveraged ETFs, and futures-tracking ETFs.

Full universe targets 2,500+ stocks with a scan funnel:
  Universe (2,500+) → Hard gate filters → Scored → Top N shown

Data sources:
  - S&P 500: Wikipedia (daily cache)
  - NASDAQ 100: Wikipedia (daily cache)
  - Russell 2000 proxy: NASDAQ Screener API filtered by market cap (daily cache)
  - Top volume: NASDAQ Screener API sorted by volume (daily cache)
  - Static: Leveraged ETFs, Futures ETFs
"""

from __future__ import annotations

import io
import threading
from datetime import date, datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

from data_provider import fetch_bars, fetch_bulk_bars, fetch_ticker_info

from logger_setup import get_logger

log = get_logger()

# ── Static lists ─────────────────────────────────────────────────────────────

# Leveraged ETFs for bigger moves
LEVERAGED_ETFS = [
    "TQQQ", "SQQQ", "SPXL", "SPXS", "UVXY",
    "SOXL", "SOXS", "LABU", "LABD",
]

# Futures-tracking and sector ETFs
FUTURES_SECTOR_ETFS = [
    "USO", "GLD", "SLV", "UNG", "TLT",
    "XLF", "XLE", "XLK", "ARKK",
    "DBA", "DBB",
]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# Symbols known to have bad data (delisted, ticker changed, etc.)
_BAD_SYMBOLS: set[str] = {"MMC", "ANSS"}

# ── Caches ───────────────────────────────────────────────────────────────────

_sp500_cache: list[str] = []
_sp500_date: date | None = None
_sp500_lock = threading.Lock()

_ndx100_cache: list[str] = []
_ndx100_date: date | None = None
_ndx100_lock = threading.Lock()

_russell2k_cache: list[str] = []
_russell2k_date: date | None = None
_russell2k_lock = threading.Lock()

_top_volume_cache: list[str] = []
_top_volume_date: date | None = None
_top_volume_lock = threading.Lock()

# Full NASDAQ screener cache (shared by Russell 2000 + top volume)
_nasdaq_rows_cache: list[dict] = []
_nasdaq_rows_date: date | None = None
_nasdaq_rows_lock = threading.Lock()

# Discovery cache
_discovery_cache: list[dict] = []
_discovery_date: date | None = None
_discovery_lock = threading.Lock()

# Funnel stats (updated each time get_full_universe is called)
_funnel_stats: dict = {}
_funnel_lock = threading.Lock()


# ── NASDAQ Screener API (bulk stock list with market cap) ────────────────────

def _fetch_nasdaq_screener() -> list[dict]:
    """
    Fetch all US-listed stocks from the NASDAQ screener API.
    Returns list of dicts with keys: symbol, marketCap, volume, price.
    Cached per day.
    """
    global _nasdaq_rows_cache, _nasdaq_rows_date
    today = date.today()

    with _nasdaq_rows_lock:
        if _nasdaq_rows_date == today and _nasdaq_rows_cache:
            return _nasdaq_rows_cache

    try:
        # First get total count
        url = "https://api.nasdaq.com/api/screener/stocks?tableType=earnings&limit=100&offset=0"
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        total = int(data.get("data", {}).get("totalrecords", 0))

        if total <= 0:
            log.warning("[universe] NASDAQ screener returned 0 records")
            return _nasdaq_rows_cache or []

        # Fetch all in one request
        url_all = f"https://api.nasdaq.com/api/screener/stocks?tableType=earnings&limit={total}&offset=0"
        resp_all = requests.get(url_all, headers=_HEADERS, timeout=60)
        resp_all.raise_for_status()
        data_all = resp_all.json()
        rows = data_all.get("data", {}).get("table", {}).get("rows", [])

        # Parse into clean dicts
        parsed: list[dict] = []
        for row in rows:
            sym = row.get("symbol", "").strip()
            if not sym:
                continue
            # Skip warrants, units, preferred, foreign listings
            if any(c in sym for c in ["^", ".", "/", " "]):
                continue
            if len(sym) > 5:
                continue

            mcap_str = row.get("marketCap", "0").replace(",", "")
            try:
                mcap = int(mcap_str) if mcap_str.isdigit() else 0
            except (ValueError, TypeError):
                mcap = 0

            price_str = row.get("lastsale", "$0").replace("$", "").replace(",", "")
            try:
                price = float(price_str)
            except (ValueError, TypeError):
                price = 0.0

            parsed.append({
                "symbol": sym,
                "marketCap": mcap,
                "price": price,
                "name": row.get("name", ""),
            })

        log.info("[universe] NASDAQ screener: %d valid stocks fetched", len(parsed))

        with _nasdaq_rows_lock:
            _nasdaq_rows_cache = parsed
            _nasdaq_rows_date = today

        return parsed

    except Exception as exc:
        log.warning("[universe] NASDAQ screener fetch failed: %s", exc)
        with _nasdaq_rows_lock:
            return _nasdaq_rows_cache or []


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
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text), header=0)
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
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text), header=0)
        df = None
        for t in tables:
            cols = [c.lower() for c in t.columns]
            if "ticker" in cols or "symbol" in cols:
                df = t
                break
        if df is None:
            df = tables[3]

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


# ── Russell 2000 proxy (small caps from NASDAQ screener) ─────────────────────

def get_russell2000(exclude: set[str] | None = None) -> list[str]:
    """
    Approximate Russell 2000 using NASDAQ screener filtered by market cap.
    Russell 2000 = small/mid caps roughly $300M to $10B that aren't in S&P 500.
    Cached per day.
    """
    global _russell2k_cache, _russell2k_date
    today = date.today()

    with _russell2k_lock:
        if _russell2k_date == today and _russell2k_cache:
            return _russell2k_cache

    rows = _fetch_nasdaq_screener()
    exclude = exclude or set()

    # Filter: $300M - $10B market cap, price > $2, not in exclusion set
    candidates = []
    for row in rows:
        sym = row["symbol"]
        mcap = row["marketCap"]
        price = row["price"]

        if sym in exclude or sym in _BAD_SYMBOLS:
            continue
        if not (300_000_000 <= mcap <= 10_000_000_000):
            continue
        if price < 2.0:
            continue

        candidates.append((sym, mcap))

    # Sort by market cap descending, take top 2000
    candidates.sort(key=lambda x: x[1], reverse=True)
    symbols = [c[0] for c in candidates[:2000]]

    log.info("[universe] Russell 2000 proxy: %d stocks ($300M-$10B market cap)", len(symbols))

    with _russell2k_lock:
        _russell2k_cache = symbols
        _russell2k_date = today

    return symbols


# ── Top volume stocks (not in indices) ───────────────────────────────────────

def get_top_volume(count: int = 100, exclude: set[str] | None = None) -> list[str]:
    """
    Get top N stocks by daily volume that aren't already in the major indices.
    Uses NASDAQ screener data. Cached per day.
    """
    global _top_volume_cache, _top_volume_date
    today = date.today()

    with _top_volume_lock:
        if _top_volume_date == today and _top_volume_cache:
            return _top_volume_cache

    exclude = exclude or set()

    # Use Yahoo Finance most_actives screener for real-time volume data
    results: list[tuple[str, int]] = []
    try:
        quotes = _screen_yahoo("most_actives", 200)
        for q in quotes:
            sym = q.get("symbol", "")
            vol = q.get("regularMarketVolume", 0) or 0
            price = q.get("regularMarketPrice", 0) or 0
            if not sym or "." in sym or len(sym) > 5:
                continue
            if sym in exclude or sym in _BAD_SYMBOLS:
                continue
            if price < 2.0:
                continue
            results.append((sym, vol))
    except Exception as exc:
        log.warning("[universe] Yahoo most_actives failed: %s", exc)

    # Supplement with NASDAQ screener data if we didn't get enough
    if len(results) < count:
        rows = _fetch_nasdaq_screener()
        already = {r[0] for r in results}
        for row in rows:
            sym = row["symbol"]
            if sym in exclude or sym in already or sym in _BAD_SYMBOLS:
                continue
            if row["price"] < 2.0:
                continue
            if row["marketCap"] < 100_000_000:  # at least $100M
                continue
            results.append((sym, row["marketCap"]))  # use mcap as proxy for activity

    # Sort by volume/activity descending, take top N
    results.sort(key=lambda x: x[1], reverse=True)
    symbols = [r[0] for r in results[:count]]

    log.info("[universe] Top volume stocks: %d symbols", len(symbols))

    with _top_volume_lock:
        _top_volume_cache = symbols
        _top_volume_date = today

    return symbols


# ── Yahoo Finance screener helper ────────────────────────────────────────────

def _screen_yahoo(screen_id: str, count: int = 50) -> list[dict]:
    """Fetch a Yahoo Finance predefined screener."""
    url = (
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
        f"?count={count}&scrIds={screen_id}&region=US&lang=en-US"
    )
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data["finance"]["result"][0]["quotes"]
    except Exception as exc:
        log.debug("[universe] Yahoo screener '%s' failed: %s", screen_id, exc)
        return []


# ── Discovery scans (52wk highs, bounce plays, unusual volume) ───────────────

def discover_52wk_high_breakouts() -> list[dict]:
    """Stocks near 52-week highs with elevated volume — breakout candidates."""
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
        if price < high_52w * 0.98:
            continue

        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0
        if vol_ratio < 1.5:
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
    """Stocks that dropped 5%+ recently — potential bounce plays."""
    results = []
    quotes = _screen_yahoo("day_losers", 100)

    for q in quotes:
        symbol = q.get("symbol", "")
        price = q.get("regularMarketPrice", 0)
        mkt_cap = q.get("marketCap", 0)
        change_pct = q.get("regularMarketChangePercent", 0)

        if not symbol or "." in symbol:
            continue
        if mkt_cap < 1_000_000_000:
            continue
        if price < 5:
            continue
        if change_pct > -5:
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
    Run discovery scans in parallel. Returns combined list of candidates.
    Cached per day.
    """
    global _discovery_cache, _discovery_date
    today = date.today()

    with _discovery_lock:
        if _discovery_date == today and _discovery_cache:
            return _discovery_cache

    all_results: list[dict] = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
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

    # Deduplicate
    seen = set()
    deduped = []
    for r in all_results:
        sym = r["symbol"]
        if sym not in seen:
            seen.add(sym)
            deduped.append(r)

    log.info("[universe] Discovery: %d unique candidates", len(deduped))

    with _discovery_lock:
        _discovery_cache = deduped
        _discovery_date = today

    return deduped


# ── Full universe builder ────────────────────────────────────────────────────

def get_full_universe(include_discovery: bool = True) -> list[str]:
    """
    Build the complete stock universe for scanning.
    Target: 2,500+ stocks after deduplication.

    Sources:
      - S&P 500 (~503 stocks)
      - NASDAQ 100 (~101 stocks, heavy overlap with S&P)
      - Russell 2000 proxy (~2000 small/mid caps)
      - Top 100 by daily volume (not in indices)
      - Leveraged ETFs (TQQQ, SQQQ, SPXL, etc.)
      - Futures/Sector ETFs (USO, GLD, TLT, XLF, etc.)
      - Discovery scans (breakouts, bounce plays)

    Returns deduplicated list of all symbols.
    """
    global _funnel_stats
    symbols: list[str] = []
    seen: set[str] = set()
    breakdown: dict[str, int] = {}

    def _add(syms: list[str], source: str) -> int:
        added = 0
        for s in syms:
            if s not in seen and s not in _BAD_SYMBOLS:
                seen.add(s)
                symbols.append(s)
                added += 1
        breakdown[source] = added
        return added

    # Core indices
    sp500 = get_sp500()
    _add(sp500, "S&P 500")

    ndx100 = get_nasdaq100()
    _add(ndx100, "NASDAQ 100")

    # Russell 2000 proxy — exclude S&P 500 to avoid overlap
    sp500_set = set(sp500)
    r2k = get_russell2000(exclude=sp500_set)
    _add(r2k, "Russell 2000")

    # Top volume — exclude everything already in universe
    top_vol = get_top_volume(count=100, exclude=seen.copy())
    _add(top_vol, "Top Volume")

    # Specialty ETFs
    _add(LEVERAGED_ETFS, "Leveraged ETFs")
    _add(FUTURES_SECTOR_ETFS, "Futures/Sector ETFs")

    # Discovery candidates
    if include_discovery:
        discovery = run_discovery()
        _add([d["symbol"] for d in discovery], "Discovery")

    # Log the breakdown
    log.info("[universe] ═══ STOCK UNIVERSE BREAKDOWN ═══")
    for source, count in breakdown.items():
        log.info("[universe]   %s: %d stocks", source, count)
    log.info("[universe]   TOTAL: %d unique stocks", len(symbols))

    # Store funnel stats for dashboard
    with _funnel_lock:
        _funnel_stats = {
            "universe_size": len(symbols),
            "breakdown": breakdown,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    return symbols


def get_funnel_stats() -> dict:
    """Get the latest scan funnel stats for the dashboard."""
    with _funnel_lock:
        return dict(_funnel_stats)


def get_scan_summary(
    total_scanned: int,
    passed_filters: int,
    top_ranked: int,
) -> str:
    """Format the scan funnel string for the dashboard."""
    return (
        f"Universe: {total_scanned:,} "
        f"-> Passed filters: {passed_filters:,} "
        f"-> Scored: {passed_filters:,} "
        f"-> Top {top_ranked} shown"
    )


# ── Heatmap data fetcher ─────────────────────────────────────────────────────

def fetch_heatmap_data(symbols: list[str] | None = None) -> list[dict]:
    """
    Fetch market cap, price, daily change for heatmap rendering.
    Uses batch download for efficiency.
    """
    if symbols is None:
        symbols = get_sp500() + get_nasdaq100()
        symbols = list(dict.fromkeys(symbols))  # dedup preserving order

    results = []

    bulk = fetch_bulk_bars(symbols, period="2d", interval="1d")
    if not bulk:
        log.warning("[universe] Heatmap batch download returned no data")
        return results

    def _get_info(sym):
        try:
            sym_df = bulk.get(sym)
            if sym_df is None or sym_df.empty:
                return None
            closes = sym_df["close"].dropna()

            if len(closes) < 2:
                return None

            price = float(closes.iloc[-1])
            prev_close = float(closes.iloc[-2])
            change_pct = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0.0

            info = fetch_ticker_info(sym)
            market_cap = info.get("marketCap", 0) or info.get("market_cap", 0) or 0

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
