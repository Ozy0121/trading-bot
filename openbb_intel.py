"""
openbb_intel.py
---------------
Intelligence data layer for the dashboard — economic data, insider trading,
SEC filings, and market movers.

Uses free APIs directly (FMP stable, SEC EDGAR, Yahoo Finance) because
OpenBB SDK 4.7.1 is broken on Python 3.14 (OBBject import errors on
every endpoint). When OpenBB fixes Python 3.14 support, replace the
direct API calls with obb.* equivalents.

Endpoints provided:
  - Economic calendar & treasury rates (FMP stable)
  - Insider trading / Form 4 filings (SEC EDGAR)
  - SEC filings (8-K, 10-K, 10-Q) (SEC EDGAR)
  - Market movers: gainers, losers, most active (Yahoo Finance)
  - Company fundamentals (FMP stable/profile)
"""

from __future__ import annotations

import os
import threading
from datetime import date, datetime, timezone

import requests

from logger_setup import get_logger

log = get_logger()

# ── Config ───────────────────────────────────────────────────────────────────

FMP_API_KEY = os.getenv("FMP_API_KEY", "")
FMP_BASE = "https://financialmodelingprep.com"
SEC_EDGAR_BASE = "https://data.sec.gov"
YAHOO_SCREENER = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
_SEC_HEADERS = {
    "User-Agent": "TradingBot/2.0 (contact: tradingbot@localhost)",
    "Accept": "application/json",
}

REQUEST_TIMEOUT = 12

# ── Caches (daily refresh) ───────────────────────────────────────────────────

_cache: dict[str, tuple[date, object]] = {}
_cache_lock = threading.Lock()


def _get_cached(key: str):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and entry[0] == date.today():
            return entry[1]
    return None


def _set_cached(key: str, data: object):
    with _cache_lock:
        _cache[key] = (date.today(), data)


# ── Treasury Rates (FMP stable — free tier) ──────────────────────────────────

def get_treasury_rates(limit: int = 30) -> list[dict]:
    """Get US Treasury yield curve rates."""
    cached = _get_cached("treasury_rates")
    if cached is not None:
        return cached

    try:
        url = f"{FMP_BASE}/stable/treasury-rates?limit={limit}&apikey={FMP_API_KEY}"
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            log.info("[intel] Treasury rates: %d entries", len(data))
            _set_cached("treasury_rates", data)
            return data
    except Exception as exc:
        log.warning("[intel] Treasury rates failed: %s", exc)

    return []


# ── SEC EDGAR — Insider Trading (Form 4) ─────────────────────────────────────

# Map of common stock symbols to SEC CIK numbers
_CIK_CACHE: dict[str, str] = {}
_CIK_LOCK = threading.Lock()


def _get_cik(symbol: str) -> str | None:
    """Look up SEC CIK for a ticker symbol."""
    with _CIK_LOCK:
        if symbol in _CIK_CACHE:
            return _CIK_CACHE[symbol]

    try:
        url = "https://www.sec.gov/files/company_tickers.json"
        resp = requests.get(url, headers=_SEC_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        # Build full cache
        with _CIK_LOCK:
            for entry in data.values():
                ticker = entry.get("ticker", "").upper()
                cik = str(entry.get("cik_str", "")).zfill(10)
                _CIK_CACHE[ticker] = cik

            return _CIK_CACHE.get(symbol.upper())

    except Exception as exc:
        log.debug("[intel] CIK lookup failed: %s", exc)
        return None


def get_insider_trades(symbols: list[str], limit_per_symbol: int = 5) -> list[dict]:
    """
    Fetch recent insider trading (Form 4) filings from SEC EDGAR.
    Returns list of insider trade dicts.
    """
    cached = _get_cached("insider_trades")
    if cached is not None:
        return cached

    results: list[dict] = []

    for symbol in symbols[:20]:  # limit to avoid hammering SEC
        cik = _get_cik(symbol)
        if not cik:
            continue

        try:
            url = f"{SEC_EDGAR_BASE}/submissions/CIK{cik}.json"
            resp = requests.get(url, headers=_SEC_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            descriptions = recent.get("primaryDocDescription", [])
            accessions = recent.get("accessionNumber", [])

            company_name = data.get("name", symbol)

            for i, form in enumerate(forms):
                if form in ("4", "4/A") and i < len(dates):
                    results.append({
                        "symbol": symbol,
                        "company": company_name,
                        "form": form,
                        "date": dates[i] if i < len(dates) else "",
                        "description": descriptions[i] if i < len(descriptions) else "Insider trade",
                        "accession": accessions[i] if i < len(accessions) else "",
                        "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=10",
                    })
                    if len([r for r in results if r["symbol"] == symbol]) >= limit_per_symbol:
                        break

        except Exception as exc:
            log.debug("[intel] EDGAR filings for %s failed: %s", symbol, exc)

    log.info("[intel] Insider trades: %d Form 4 filings across %d symbols", len(results), len(symbols))
    _set_cached("insider_trades", results)
    return results


# ── SEC EDGAR — Recent Filings (8-K, 10-K, 10-Q) ────────────────────────────

def get_sec_filings(symbols: list[str], forms: list[str] | None = None,
                     limit_per_symbol: int = 3) -> list[dict]:
    """
    Fetch recent SEC filings for given symbols.
    Default forms: 8-K, 10-K, 10-Q.
    """
    cached = _get_cached("sec_filings")
    if cached is not None:
        return cached

    if forms is None:
        forms = ["8-K", "10-K", "10-Q", "S-1"]

    target_forms = set(forms)
    results: list[dict] = []

    for symbol in symbols[:20]:
        cik = _get_cik(symbol)
        if not cik:
            continue

        try:
            url = f"{SEC_EDGAR_BASE}/submissions/CIK{cik}.json"
            resp = requests.get(url, headers=_SEC_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            recent = data.get("filings", {}).get("recent", {})
            form_list = recent.get("form", [])
            date_list = recent.get("filingDate", [])
            desc_list = recent.get("primaryDocDescription", [])
            doc_list = recent.get("primaryDocument", [])
            acc_list = recent.get("accessionNumber", [])

            company_name = data.get("name", symbol)
            count = 0

            for i, form in enumerate(form_list):
                if form in target_forms:
                    acc_clean = acc_list[i].replace("-", "") if i < len(acc_list) else ""
                    doc_name = doc_list[i] if i < len(doc_list) else ""
                    filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc_clean}/{doc_name}" if acc_clean and doc_name else ""

                    results.append({
                        "symbol": symbol,
                        "company": company_name,
                        "form": form,
                        "date": date_list[i] if i < len(date_list) else "",
                        "description": desc_list[i] if i < len(desc_list) else form,
                        "url": filing_url,
                    })
                    count += 1
                    if count >= limit_per_symbol:
                        break

        except Exception as exc:
            log.debug("[intel] EDGAR filings for %s failed: %s", symbol, exc)

    log.info("[intel] SEC filings: %d filings across %d symbols", len(results), len(symbols))
    _set_cached("sec_filings", results)
    return results


# ── Market Movers (Yahoo Finance — free) ─────────────────────────────────────

def _yahoo_screener(screen_id: str, count: int = 20) -> list[dict]:
    """Fetch Yahoo Finance predefined screener results."""
    url = f"{YAHOO_SCREENER}?count={count}&scrIds={screen_id}&region=US&lang=en-US"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        quotes = data["finance"]["result"][0]["quotes"]
        return [
            {
                "symbol": q.get("symbol", ""),
                "name": q.get("shortName", ""),
                "price": round(q.get("regularMarketPrice", 0), 2),
                "change_pct": round(q.get("regularMarketChangePercent", 0), 2),
                "volume": q.get("regularMarketVolume", 0),
                "market_cap": q.get("marketCap", 0),
            }
            for q in quotes
            if q.get("symbol") and "." not in q.get("symbol", ".")
        ]
    except Exception as exc:
        log.debug("[intel] Yahoo screener '%s' failed: %s", screen_id, exc)
        return []


def get_market_movers() -> dict:
    """Get today's market movers: gainers, losers, most active."""
    cached = _get_cached("market_movers")
    if cached is not None:
        return cached

    movers = {
        "gainers": _yahoo_screener("day_gainers", 15),
        "losers": _yahoo_screener("day_losers", 15),
        "most_active": _yahoo_screener("most_actives", 15),
    }

    total = sum(len(v) for v in movers.values())
    log.info("[intel] Market movers: %d total (G:%d L:%d A:%d)",
             total, len(movers["gainers"]), len(movers["losers"]), len(movers["most_active"]))

    _set_cached("market_movers", movers)
    return movers


# ── Company Profile (FMP stable — free tier) ─────────────────────────────────

def get_company_profile(symbol: str) -> dict:
    """Get company fundamentals from FMP."""
    cache_key = f"profile_{symbol}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        url = f"{FMP_BASE}/stable/profile?symbol={symbol}&apikey={FMP_API_KEY}"
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            profile = data[0]
            _set_cached(cache_key, profile)
            return profile
    except Exception as exc:
        log.debug("[intel] Company profile for %s failed: %s", symbol, exc)

    return {}


# ── Aggregate Intelligence Report ────────────────────────────────────────────

def get_intelligence_report(watchlist: list[str]) -> dict:
    """
    Build a complete intelligence report for the dashboard.
    Fetches all available data sources in parallel.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    report: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "treasury_rates": [],
        "insider_trades": [],
        "sec_filings": [],
        "market_movers": {},
        "openbb_status": "broken_python314",
        "data_sources": [],
    }

    tasks = {
        "treasury_rates": lambda: get_treasury_rates(limit=10),
        "insider_trades": lambda: get_insider_trades(watchlist),
        "sec_filings": lambda: get_sec_filings(watchlist),
        "market_movers": lambda: get_market_movers(),
    }

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fn): key for key, fn in tasks.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                result = future.result()
                report[key] = result
                report["data_sources"].append(key)
            except Exception as exc:
                log.warning("[intel] %s failed: %s", key, exc)

    return report


# ── OpenBB status check ─────────────────────────────────────────────────────

def check_openbb_status() -> dict:
    """
    Check if OpenBB SDK is functional on this Python version.
    Returns status dict for the dashboard.
    """
    status = {
        "installed": False,
        "version": "",
        "functional": False,
        "error": "",
        "python_version": "",
    }

    import sys
    status["python_version"] = sys.version.split()[0]

    try:
        import openbb
        status["installed"] = True
        status["version"] = getattr(openbb, "__version__", "unknown")
    except ImportError:
        status["error"] = "OpenBB not installed"
        return status

    try:
        from openbb import obb
        # Try a simple endpoint
        obb.equity  # triggers the import
        status["functional"] = True
    except ImportError as exc:
        status["error"] = f"Python {status['python_version']} incompatible: {exc}"
    except Exception as exc:
        status["error"] = str(exc)

    return status
