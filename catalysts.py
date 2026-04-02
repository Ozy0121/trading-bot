"""
catalysts.py
-----------
High-signal catalysts used to confirm trade entries.
Used as CONFIRMATION alongside technical signals, not as standalone buy reasons.

Sources:
  1. ARK Invest daily trades  — Cathie Wood publishes every ETF trade daily.
                                When ARK buys a stock it often precedes big moves.
  2. Analyst upgrade scanner  — Scans Yahoo Finance news headlines for upgrade
                                keywords from major banks.

Volume ratio (3rd catalyst) is computed in scanner.py from bar data.

All fetches are cached aggressively to avoid hammering free APIs.
"""

from __future__ import annotations

import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime

import requests

from logger_setup import get_logger

log = get_logger()

REQUEST_TIMEOUT = 8

# ── Cache ────────────────────────────────────────────────────────────────────
_ark_cache: dict[str, bool] = {}   # symbol -> True if ARK bought recently
_ark_cache_date: date | None = None
_ark_lock = threading.Lock()

_upgrade_cache: dict[str, bool] = {}   # symbol -> True if upgrade found
_upgrade_cache_ts: float = 0           # unix time of last fetch
UPGRADE_CACHE_TTL = 3600               # refresh upgrades every hour

# ── Upgrade keywords to scan for in news headlines ───────────────────────────
_UPGRADE_KEYWORDS = [
    "upgrade", "upgrades", "upgraded",
    "outperform", "overweight",
    "price target raised", "raises price target", "raises pt",
    "initiates", "initiated", "strong buy",
    "buy rating", "bullish",
]

_ARK_ETFS = ["ARKK", "ARKQ", "ARKW", "ARKG", "ARKF"]


# ── ARK Invest tracker ────────────────────────────────────────────────────────

def fetch_ark_buys() -> dict[str, bool]:
    """
    Fetch recent ARK Invest buy trades from arkfunds.io (free, no key).
    Returns {symbol: True} for every stock ARK bought in the last 5 days.
    Cached per trading day.
    """
    global _ark_cache, _ark_cache_date

    today = date.today()
    if _ark_cache_date == today and _ark_cache:
        return _ark_cache

    with _ark_lock:
        # Re-check after acquiring lock (another thread may have filled it)
        if _ark_cache_date == today and _ark_cache:
            return _ark_cache

        log.info("[catalysts] Fetching ARK Invest daily trades...")

        ark_buys: dict[str, bool] = {}

        for etf in _ARK_ETFS:
            url = f"https://arkfunds.io/api/v2/etf/trades?symbol={etf}"
            try:
                resp = requests.get(url, timeout=REQUEST_TIMEOUT,
                                    headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                data = resp.json()
                trades = data.get("trades", [])
                for trade in trades:
                    direction = str(trade.get("direction", "")).lower()
                    ticker    = str(trade.get("ticker", "")).upper()
                    if direction == "buy" and ticker:
                        ark_buys[ticker] = True
                        log.debug("[catalysts] ARK %s buying: %s", etf, ticker)
            except Exception as exc:
                log.warning("[catalysts] ARK fetch failed for %s: %s", etf, exc)

        if ark_buys:
            log.info("[catalysts] ARK buying %d stocks: %s",
                     len(ark_buys), ", ".join(sorted(ark_buys.keys())))
        else:
            log.warning("[catalysts] No ARK trades found — API may be down.")

        _ark_cache = ark_buys
        _ark_cache_date = today
        return _ark_cache


# ── Analyst upgrade scanner ───────────────────────────────────────────────────

def scan_analyst_upgrades(symbols: list[str]) -> dict[str, bool]:
    """
    Scan Yahoo Finance RSS news for each symbol.
    Returns {symbol: True} if a recent upgrade headline is found.
    Cached for 1 hour.
    """
    global _upgrade_cache, _upgrade_cache_ts

    now = time.time()
    if now - _upgrade_cache_ts < UPGRADE_CACHE_TTL and _upgrade_cache:
        return _upgrade_cache

    log.info("[catalysts] Scanning analyst upgrades for %d symbols...", len(symbols))
    results: dict[str, bool] = {}

    for symbol in symbols[:15]:   # cap to avoid too many requests
        url = (f"https://feeds.finance.yahoo.com/rss/2.0/headline"
               f"?s={symbol}&region=US&lang=en-US")
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT,
                                headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            root  = ET.fromstring(resp.content)
            items = root.findall(".//item")
            for item in items[:10]:
                title = (item.findtext("title") or "").lower()
                if any(kw in title for kw in _UPGRADE_KEYWORDS):
                    log.info("[catalysts] Analyst upgrade signal: %s — '%s'",
                             symbol, item.findtext("title", ""))
                    results[symbol] = True
                    break
        except Exception:
            pass   # don't log per-symbol failures, too noisy

    _upgrade_cache    = results
    _upgrade_cache_ts = now

    if results:
        log.info("[catalysts] Upgrades found: %s", ", ".join(results.keys()))
    return _upgrade_cache


# ── Combined catalyst lookup ──────────────────────────────────────────────────

def get_catalysts(symbols: list[str]) -> dict[str, dict]:
    """
    Returns a dict of catalyst flags for each symbol:
      {
        "NVDA": {"ark_buying": True,  "analyst_upgrade": False},
        "TSLA": {"ark_buying": False, "analyst_upgrade": True},
        ...
      }

    Volume ratio is NOT included here — it's computed in scanner.py
    from the actual bar data which is already fetched there.
    """
    ark_buys = fetch_ark_buys()
    upgrades = scan_analyst_upgrades(symbols)

    result = {}
    for sym in symbols:
        ark = ark_buys.get(sym, False)
        upg = upgrades.get(sym, False)
        result[sym] = {
            "ark_buying":       ark,
            "analyst_upgrade":  upg,
            "catalyst_count":   sum([ark, upg]),
        }
        if ark or upg:
            log.info("[catalysts] %s — ARK:%s Upgrade:%s", sym, ark, upg)

    return result
