"""
sentiment_cache.py
------------------
Per-symbol news sentiment scoring with 30-minute TTL caching.

Provides two public functions:
  - get_sentiment_score(symbol) -> float 0.0-10.0
      Fetches headlines via Alpaca news API (primary) or Yahoo RSS (fallback),
      scores them with keyword counting, and caches the result for 30 minutes.

  - get_earnings_penalty(symbol) -> float 0.0-2.0
      Returns a conviction penalty based on proximity to next earnings date.
      Penalty increases as earnings approach (2.0 = today, 0.0 = >3 days out).
      Cached once per calendar day.

Used by the scanner orchestrator (Plan 03) to compute composite conviction scores.
"""

from __future__ import annotations

import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import requests

import os

import config
from logger_setup import get_logger

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore[assignment]

try:
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest
    _ALPACA_AVAILABLE = True
except ImportError:
    NewsClient = None  # type: ignore[assignment,misc]
    NewsRequest = None  # type: ignore[assignment]
    _ALPACA_AVAILABLE = False

log = get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

SENTIMENT_TTL = 1800   # 30 minutes in seconds

REQUEST_TIMEOUT = 8    # seconds per HTTP request

# ── Keyword lists (D-06, D-07 updated) ───────────────────────────────────────

# Weighted keyword tiers: stronger signals get higher weight
_BULLISH_KEYWORDS_STRONG = [
    "strong buy", "price target raised", "upgraded", "outperform",
    "surges", "soars", "record high", "blowout", "crushes estimates",
    "massive beat", "buy rating",
]  # weight: 2.0

_BULLISH_KEYWORDS_MODERATE = [
    "upgrade", "upgrades", "overweight", "bullish", "rally",
    "beat", "beats", "jumps", "initiates", "positive", "growth",
    "raises guidance", "above expectations", "accelerating",
]  # weight: 1.0

_BEARISH_KEYWORDS_STRONG = [
    "sell rating", "price target cut", "downgraded", "underperform",
    "plunges", "crashes", "massive miss", "bankruptcy", "fraud",
    "sec investigation", "warning",
]  # weight: 2.0

_BEARISH_KEYWORDS_MODERATE = [
    "downgrade", "downgrades", "underweight", "bearish",
    "falls", "drops", "misses", "miss", "concern", "decline",
    "cuts guidance", "below expectations", "slowing",
]  # weight: 1.0

# ── Sentiment cache (D-06) ────────────────────────────────────────────────────

_cache: dict[str, tuple[float, float]] = {}   # symbol -> (timestamp, score)
_cache_lock = threading.Lock()

# ── Earnings cache (D-09) ─────────────────────────────────────────────────────

_earnings_cache: dict[str, tuple[date, date | None]] = {}   # symbol -> (fetch_date, earnings_date)
_earnings_lock = threading.Lock()


# ── Public API ────────────────────────────────────────────────────────────────

def get_sentiment_score(symbol: str) -> float:
    """
    Return a sentiment score for the given symbol in the range 0.0-10.0.

    5.0 = neutral (no headlines or equal bullish/bearish).
    >5.0 = net bullish. <5.0 = net bearish.

    Result is cached for SENTIMENT_TTL seconds (30 minutes).
    Thread-safe: uses a lock to prevent duplicate API calls from parallel workers.
    """
    now = time.time()

    with _cache_lock:
        entry = _cache.get(symbol)
        if entry is not None:
            ts, score = entry
            if now - ts < SENTIMENT_TTL:
                log.debug("[sentiment_cache] Cache hit for %s (score=%.2f)", symbol, score)
                return score

        # Cache miss or expired — fetch outside the lock to avoid blocking
        # Re-acquire lock after fetch to write result
        pass

    # Fetch without holding the lock (allows parallel fetches for different symbols)
    score = _fetch_sentiment(symbol)

    with _cache_lock:
        _cache[symbol] = (time.time(), score)

    return score


def get_earnings_penalty(symbol: str) -> float:
    """
    Return a conviction penalty (0.0-2.0) based on how close earnings are.

    Penalty schedule:
      >3 days out  → 0.0 (no penalty)
       3 days out  → 0.5
       2 days out  → 1.0
       1 day out   → 1.5
       0 days out  → 2.0 (earnings today)

    Earnings date is fetched via yfinance and cached once per calendar day.
    Returns 0.0 if yfinance is unavailable or earnings data is missing.
    """
    today = date.today()

    with _earnings_lock:
        entry = _earnings_cache.get(symbol)
        if entry is not None:
            fetch_date, earnings_date = entry
            if fetch_date == today:
                return _compute_penalty(earnings_date, today)

    # Fetch earnings date
    earnings_date = _fetch_earnings_date(symbol)

    with _earnings_lock:
        _earnings_cache[symbol] = (today, earnings_date)

    return _compute_penalty(earnings_date, today)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch_sentiment(symbol: str) -> float:
    """
    Fetch headlines via Polygon (primary) → Alpaca → Yahoo RSS (fallback).
    Score them and return a 0.0-10.0 float. Returns 5.0 if both fail.
    Applies D-07 trending topic amplification for stocks with >= 8 articles.
    """
    headlines = _fetch_polygon_news(symbol)

    if headlines is None:
        headlines = _fetch_alpaca_news(symbol)

    if headlines is None:
        log.info("[sentiment_cache] Polygon/Alpaca news unavailable for %s, trying Yahoo RSS", symbol)
        headlines = _fetch_yahoo_rss(symbol)

    if not headlines:
        log.info("[sentiment_cache] No headlines for %s -- returning neutral 5.0", symbol)
        return 5.0

    log.info("[sentiment_cache] Scoring %d headlines for %s", len(headlines), symbol)
    base_score = _score_headlines(headlines)

    # D-07: Trending topic detection -- high article count amplifies signal
    article_count = len(headlines)
    if article_count >= 8:
        # Stock is trending: push score further from neutral (5.0)
        deviation = base_score - 5.0
        amplified = 5.0 + deviation * 1.3  # 30% amplification
        amplified = round(max(0.0, min(10.0, amplified)), 2)
        log.info(
            "[sentiment_cache] %s trending (%d articles) -- amplified %.2f -> %.2f",
            symbol, article_count, base_score, amplified,
        )
        base_score = amplified

    return base_score


def _fetch_polygon_news(symbol: str) -> list[str] | None:
    """Fetch recent news headlines from Polygon.io."""
    if not POLYGON_API_KEY:
        return None
    try:
        resp = requests.get(
            f"https://api.polygon.io/v2/reference/news",
            params={"ticker": symbol, "limit": 10, "order": "desc",
                    "sort": "published_utc", "apiKey": POLYGON_API_KEY},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        headlines = [r["title"] for r in results if r.get("title")]
        log.debug("[sentiment_cache] Polygon returned %d headlines for %s", len(headlines), symbol)
        return headlines if headlines else None
    except Exception as exc:
        log.debug("[sentiment_cache] Polygon news failed for %s: %s", symbol, exc)
        return None


def _fetch_alpaca_news(symbol: str) -> list[str] | None:
    """
    Fetch recent news headlines from Alpaca News API.
    Returns list of headline strings, or None on failure.
    """
    if not _ALPACA_AVAILABLE or NewsClient is None:
        return None

    try:
        client = NewsClient(api_key=config.API_KEY, secret_key=config.SECRET_KEY)
        start = datetime.now(timezone.utc) - timedelta(days=3)
        req = NewsRequest(symbols=symbol, limit=10, start=start)
        news_set = client.get_news(req)
        news_items = news_set.data.get("news", []) if isinstance(news_set.data, dict) else news_set.data
        headlines = [item.headline for item in news_items if hasattr(item, 'headline') and item.headline]
        log.debug("[sentiment_cache] Alpaca returned %d headlines for %s", len(headlines), symbol)
        return headlines if headlines else None
    except Exception as exc:
        log.warning("[sentiment_cache] Alpaca news fetch failed for %s: %s", symbol, exc)
        return None


def _fetch_yahoo_rss(symbol: str) -> list[str] | None:
    """
    Fetch news headlines from Yahoo Finance RSS feed.
    Returns list of headline strings, or None on failure.
    """
    url = (
        f"https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={symbol}&region=US&lang=en-US"
    )
    try:
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = root.findall(".//item")
        headlines = [(item.findtext("title") or "").strip() for item in items[:10]]
        headlines = [h for h in headlines if h]
        log.debug("[sentiment_cache] Yahoo RSS returned %d headlines for %s", len(headlines), symbol)
        return headlines if headlines else None
    except Exception as exc:
        log.warning("[sentiment_cache] Yahoo RSS fetch failed for %s: %s", symbol, exc)
        return None


def _score_headlines(headlines: list[str]) -> float:
    """
    Score headlines using weighted keyword matching (D-06 updated).

    Strong keywords count 2x. Produces wider spread: bullish -> >7, bearish -> <3.
    Formula:
      bull/bear weights normalized by max possible (total * 2.0)
      tanh(raw * 2.5) applies sigmoid-like stretching to push toward extremes
      score = (stretched + 1) / 2 * 10   → range [0, 10]
    """
    import math

    bull_weight = 0.0
    bear_weight = 0.0

    for headline in headlines:
        lower = headline.lower()
        # Strong keywords (weight 2.0)
        if any(kw in lower for kw in _BULLISH_KEYWORDS_STRONG):
            bull_weight += 2.0
        elif any(kw in lower for kw in _BULLISH_KEYWORDS_MODERATE):
            bull_weight += 1.0
        if any(kw in lower for kw in _BEARISH_KEYWORDS_STRONG):
            bear_weight += 2.0
        elif any(kw in lower for kw in _BEARISH_KEYWORDS_MODERATE):
            bear_weight += 1.0

    total = len(headlines)
    if total == 0:
        return 5.0

    # Normalize by headline count, but allow exceeding [-1,+1] for strong signals
    max_possible = total * 2.0  # if every headline matched a strong keyword
    raw = (bull_weight - bear_weight) / max_possible  # [-1, +1]

    # tanh(raw * 4.0) maps: raw=0.5 -> ~0.96, raw=1.0 -> ~1.00 — wider spread than 2.5
    stretched = math.tanh(raw * 4.0)
    score = (stretched + 1) / 2 * 10  # [0, 10]
    return round(max(0.0, min(10.0, score)), 2)


def _fetch_earnings_date(symbol: str) -> date | None:
    """
    Fetch the next earnings date for the symbol using yfinance.
    Returns date or None if unavailable.
    """
    if yf is None:
        log.debug("[sentiment_cache] yfinance not available, skipping earnings for %s", symbol)
        return None

    try:
        ticker = yf.Ticker(symbol)
        calendar = ticker.calendar
        if not calendar:
            return None

        earnings_list = calendar.get("Earnings Date")
        if not earnings_list:
            return None

        # May be a list of dates — take the first upcoming one
        for entry in earnings_list:
            if isinstance(entry, datetime):
                return entry.date()
            if isinstance(entry, date):
                return entry

        return None
    except Exception as exc:
        log.warning("[sentiment_cache] Earnings fetch failed for %s: %s", symbol, exc)
        return None


def _compute_penalty(earnings_date: date | None, today: date) -> float:
    """
    Compute penalty based on days until earnings.

    Schedule: 0 days=2.0, 1=1.5, 2=1.0, 3=0.5, >3=0.0
    Formula: penalty = (3 - days_until) * 0.5 + 0.5  for days_until <= 3
    """
    if earnings_date is None:
        return 0.0

    days_until = (earnings_date - today).days

    if days_until < 0:
        # Earnings already passed
        return 0.0
    if days_until > 3:
        return 0.0

    return (3 - days_until) * 0.5 + 0.5
