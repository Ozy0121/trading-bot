"""
sentiment.py
------------
Pulls two free data sources in a background thread:

1. StockTwits API  — finance social network
   GET https://api.stocktwits.com/api/2/streams/symbol/{SYMBOL}.json
   No API key required. Returns the latest 30 messages with bullish/bearish labels.
   Rate limit: ~200 requests/hour.

2. Yahoo Finance RSS feed — latest news headlines for the symbol
   GET https://feeds.finance.yahoo.com/rss/2.0/headline?s={SYMBOL}
   No API key required.

Both update the shared state every SENTIMENT_INTERVAL seconds (default 5 min).
"""

import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

import config
import state as shared_state
from logger_setup import get_logger

log = get_logger()

SENTIMENT_INTERVAL = 300   # seconds between sentiment refreshes
REQUEST_TIMEOUT    = 10    # seconds before giving up on a request


def fetch_fear_greed() -> None:
    """
    Fetch the CNN Fear & Greed Index from the Alternative.me API.
    Score 0-100: 0=Extreme Fear, 100=Extreme Greed.
    Maps to bull/bear percentages shown on the dashboard.
    Free, no API key required.
    """
    url = "https://api.alternative.me/fng/?limit=1&format=json"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data  = resp.json()
        entry = data["data"][0]
        score = int(entry["value"])           # 0 (fear) → 100 (greed)
        label = entry["value_classification"] # e.g. "Fear", "Greed", "Neutral"

        # Map the 0-100 score directly to bull/bear %
        bull_pct = score
        bear_pct = 100 - score

        shared_state.update(
            sentiment_bull=bull_pct,
            sentiment_bear=bear_pct,
            sentiment_total=score,        # repurpose total field to show raw score
            sentiment_label=label,
        )
        log.info(
            "[sentiment] Fear & Greed Index: %d/100 (%s) → Bull %d%% Bear %d%%",
            score, label, bull_pct, bear_pct,
        )

    except Exception as exc:
        log.warning("[sentiment] Fear & Greed fetch failed: %s", exc)


def fetch_news() -> None:
    """
    Fetch the latest Yahoo Finance RSS headlines for the symbol.
    Stores up to 15 headlines in shared state.
    """
    url = (
        f"https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={config.SYMBOL}&region=US&lang=en-US"
    )
    try:
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()

        root  = ET.fromstring(resp.content)
        items = root.findall(".//item")

        news = []
        for item in items[:15]:
            title    = (item.findtext("title")    or "").strip()
            pub_date = (item.findtext("pubDate")  or "").strip()
            link     = (item.findtext("link")     or "").strip()
            if title:
                news.append({"title": title, "date": pub_date, "link": link})

        shared_state.update(news=news)
        log.info("[sentiment] Fetched %d news headlines for %s", len(news), config.SYMBOL)

    except Exception as exc:
        log.warning("[sentiment] Yahoo Finance news fetch failed: %s", exc)


def _run_loop() -> None:
    """Background loop: fetch sentiment and news, then sleep."""
    while True:
        fetch_fear_greed()
        fetch_news()
        time.sleep(SENTIMENT_INTERVAL)


def start() -> None:
    """Start the sentiment/news polling loop in a daemon thread."""
    # Run once immediately so data is available before the first poll cycle
    fetch_fear_greed()
    fetch_news()

    t = threading.Thread(target=_run_loop, name="sentiment", daemon=True)
    t.start()
    log.info(
        "[sentiment] Sentiment loop started — refreshes every %ds",
        SENTIMENT_INTERVAL,
    )
