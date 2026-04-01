"""Tests for the News Analyst agent."""

from unittest.mock import patch, MagicMock
from agents.event_bus import EventBus
from agents.news_analyst import NewsAnalyst
from agents.base import NewsOutput


def test_news_analyst_returns_news_outputs():
    """run() returns a list of NewsOutput dataclasses."""
    bus = EventBus()
    agent = NewsAnalyst(bus)
    with patch.object(agent, '_fetch_news', return_value={"NVDA": [{"headline": "NVDA beats earnings", "sentiment": "bullish"}]}), \
         patch.object(agent, '_fetch_catalysts', return_value={"NVDA": {"upgrade": True, "downgrade": False}}), \
         patch.object(agent, '_check_earnings', return_value={"NVDA": None}), \
         patch.object(agent, '_detect_unusual_volume', return_value={"NVDA": False}), \
         patch.object(agent, '_get_sector_momentum', return_value={"NVDA": True}), \
         patch.object(agent, '_get_macro_catalysts', return_value=[]):
        result = agent.run({"symbols": ["NVDA"]})
    assert "outputs" in result
    assert len(result["outputs"]) == 1
    assert isinstance(result["outputs"][0], NewsOutput)
    assert result["outputs"][0].symbol == "NVDA"


def test_news_analyst_empty_symbols():
    """Agent handles empty symbol list gracefully."""
    bus = EventBus()
    agent = NewsAnalyst(bus)
    result = agent.run({"symbols": []})
    assert result["outputs"] == []


def test_news_analyst_earnings_flag():
    """Earnings flag and days_away are set correctly."""
    bus = EventBus()
    agent = NewsAnalyst(bus)
    with patch.object(agent, '_fetch_news', return_value={"NVDA": []}), \
         patch.object(agent, '_fetch_catalysts', return_value={"NVDA": {"upgrade": False, "downgrade": False}}), \
         patch.object(agent, '_check_earnings', return_value={"NVDA": 3}), \
         patch.object(agent, '_detect_unusual_volume', return_value={"NVDA": False}), \
         patch.object(agent, '_get_sector_momentum', return_value={"NVDA": False}), \
         patch.object(agent, '_get_macro_catalysts', return_value=[]):
        result = agent.run({"symbols": ["NVDA"]})
    out = result["outputs"][0]
    assert out.has_earnings_soon is True
    assert out.earnings_days_away == 3
    assert any("earning" in f.lower() for f in out.risk_flags)


def test_news_analyst_sentiment_scoring():
    """Sentiment scoring reflects headline sentiment mix."""
    bus = EventBus()
    agent = NewsAnalyst(bus)
    bullish_news = {"NVDA": [
        {"headline": "NVDA surges on record revenue", "sentiment": "bullish"},
        {"headline": "NVDA upgraded by Goldman Sachs", "sentiment": "bullish"},
        {"headline": "AI demand drives NVDA growth", "sentiment": "bullish"},
    ]}
    with patch.object(agent, '_fetch_news', return_value=bullish_news), \
         patch.object(agent, '_fetch_catalysts', return_value={"NVDA": {"upgrade": True, "downgrade": False}}), \
         patch.object(agent, '_check_earnings', return_value={"NVDA": None}), \
         patch.object(agent, '_detect_unusual_volume', return_value={"NVDA": False}), \
         patch.object(agent, '_get_sector_momentum', return_value={"NVDA": True}), \
         patch.object(agent, '_get_macro_catalysts', return_value=[]):
        result = agent.run({"symbols": ["NVDA"]})
    out = result["outputs"][0]
    assert out.sentiment_label == "bullish"
    assert out.sentiment_score > 50
