"""
tests/test_sentiment_cache.py
-----------------------------
Unit tests for the sentiment_cache module.

Tests cover:
- Sentiment score range (0.0-10.0)
- Cache TTL (second call returns cached value)
- Bullish/bearish keyword scoring
- Neutral (no headlines) returns 5.0
- Alpaca fallback to Yahoo RSS
- Earnings penalty calculation (0-2.0 based on proximity)
"""

from __future__ import annotations

import sys
import os
import importlib
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sentiment_cache


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_caches():
    """Clear sentiment and earnings caches before each test."""
    sentiment_cache._cache.clear()
    sentiment_cache._earnings_cache.clear()
    yield
    sentiment_cache._cache.clear()
    sentiment_cache._earnings_cache.clear()


@pytest.fixture
def mock_alpaca_news():
    """Patch _fetch_alpaca_news to return controlled headline lists."""
    with patch("sentiment_cache._fetch_alpaca_news") as mock:
        yield mock


@pytest.fixture
def mock_yahoo_rss():
    """Patch _fetch_yahoo_rss to return controlled headline lists."""
    with patch("sentiment_cache._fetch_yahoo_rss") as mock:
        yield mock


# ── Sentiment scoring tests ───────────────────────────────────────────────────

def test_sentiment_score_range(mock_alpaca_news, mock_yahoo_rss):
    """get_sentiment_score returns a float between 0.0 and 10.0."""
    mock_alpaca_news.return_value = ["stock upgrades to buy", "stock falls slightly"]
    mock_yahoo_rss.return_value = None

    score = sentiment_cache.get_sentiment_score("AAPL")
    assert isinstance(score, float)
    assert 0.0 <= score <= 10.0


def test_sentiment_cache_hit(mock_alpaca_news, mock_yahoo_rss):
    """Second call within TTL returns cached value without re-fetching."""
    mock_alpaca_news.return_value = ["stock surges on upgrade"]
    mock_yahoo_rss.return_value = None

    first_score = sentiment_cache.get_sentiment_score("AAPL")
    second_score = sentiment_cache.get_sentiment_score("AAPL")

    # Should only have been called once (second call uses cache)
    assert mock_alpaca_news.call_count == 1
    assert first_score == second_score


def test_sentiment_all_bullish(mock_alpaca_news, mock_yahoo_rss):
    """All bullish headlines produce a score above 7.0."""
    mock_alpaca_news.return_value = [
        "stock surges on upgrade to strong buy",
        "beats earnings expectations with record revenue",
        "analyst raises price target, bullish outlook",
    ]
    mock_yahoo_rss.return_value = None

    score = sentiment_cache.get_sentiment_score("NVDA")
    assert score > 7.0


def test_sentiment_all_bearish(mock_alpaca_news, mock_yahoo_rss):
    """All bearish headlines produce a score below 3.0."""
    mock_alpaca_news.return_value = [
        "stock plunges on downgrade to underperform",
        "misses earnings estimates, warning issued",
        "analyst cuts price target, bearish",
    ]
    mock_yahoo_rss.return_value = None

    score = sentiment_cache.get_sentiment_score("TSLA")
    assert score < 3.0


def test_sentiment_no_headlines(mock_alpaca_news, mock_yahoo_rss):
    """When both Alpaca and Yahoo return None, score is 5.0 (neutral)."""
    mock_alpaca_news.return_value = None
    mock_yahoo_rss.return_value = None

    score = sentiment_cache.get_sentiment_score("AMD")
    assert score == 5.0


def test_sentiment_alpaca_fallback(mock_alpaca_news, mock_yahoo_rss):
    """When Alpaca fails, Yahoo RSS headlines are scored instead."""
    mock_alpaca_news.return_value = None
    mock_yahoo_rss.return_value = ["stock surges on upgrade to outperform"]

    score = sentiment_cache.get_sentiment_score("META")

    # Yahoo was used as fallback
    mock_yahoo_rss.assert_called_once_with("META")
    # Score should be bullish (> 5.0)
    assert score > 5.0


# ── Earnings penalty tests ────────────────────────────────────────────────────

def test_earnings_penalty_3_days():
    """Earnings 3 days out returns penalty of 0.5."""
    earnings_date = date.today() + timedelta(days=3)

    mock_ticker = MagicMock()
    mock_ticker.calendar = {"Earnings Date": [earnings_date]}

    with patch("sentiment_cache.yf") as mock_yf:
        mock_yf.Ticker.return_value = mock_ticker
        penalty = sentiment_cache.get_earnings_penalty("AAPL")

    assert penalty == 0.5


def test_earnings_penalty_today():
    """Earnings today returns maximum penalty of 2.0."""
    earnings_date = date.today()

    mock_ticker = MagicMock()
    mock_ticker.calendar = {"Earnings Date": [earnings_date]}

    with patch("sentiment_cache.yf") as mock_yf:
        mock_yf.Ticker.return_value = mock_ticker
        penalty = sentiment_cache.get_earnings_penalty("TSLA")

    assert penalty == 2.0


def test_earnings_penalty_far():
    """Earnings more than 3 days out returns penalty of 0.0."""
    earnings_date = date.today() + timedelta(days=10)

    mock_ticker = MagicMock()
    mock_ticker.calendar = {"Earnings Date": [earnings_date]}

    with patch("sentiment_cache.yf") as mock_yf:
        mock_yf.Ticker.return_value = mock_ticker
        penalty = sentiment_cache.get_earnings_penalty("MSFT")

    assert penalty == 0.0


def test_earnings_penalty_no_data():
    """Missing calendar data returns penalty of 0.0."""
    mock_ticker = MagicMock()
    mock_ticker.calendar = {}

    with patch("sentiment_cache.yf") as mock_yf:
        mock_yf.Ticker.return_value = mock_ticker
        penalty = sentiment_cache.get_earnings_penalty("PLTR")

    assert penalty == 0.0
