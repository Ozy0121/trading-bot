"""Tests for the Quant Analyst agent."""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from agents.event_bus import EventBus
from agents.quant_analyst import QuantAnalyst
from agents.base import QuantOutput


def _make_bars(n: int = 100, base_price: float = 100.0) -> pd.DataFrame:
    """Create a realistic OHLCV DataFrame for testing."""
    dates = pd.date_range(end=datetime.now(), periods=n, freq="5min")
    np.random.seed(42)
    closes = base_price + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open":   closes - np.random.rand(n) * 0.3,
        "high":   closes + np.random.rand(n) * 0.5,
        "low":    closes - np.random.rand(n) * 0.5,
        "close":  closes,
        "volume": np.random.randint(100000, 500000, n),
    }, index=dates)


def test_quant_analyst_returns_quant_outputs():
    """run() returns a list of QuantOutput dataclasses."""
    bus = EventBus()
    agent = QuantAnalyst(bus)

    bars_by_symbol = {"NVDA": _make_bars(), "AMD": _make_bars(base_price=80.0)}
    spy_bars = _make_bars(base_price=450.0)

    with patch.object(agent, '_fetch_bars', return_value=bars_by_symbol), \
         patch.object(agent, '_fetch_spy_bars', return_value=spy_bars):
        result = agent.run({"symbols": ["NVDA", "AMD"]})

    assert "outputs" in result
    outputs = result["outputs"]
    assert len(outputs) == 2
    assert all(isinstance(o, QuantOutput) for o in outputs)


def test_quant_analyst_scores_sorted_descending():
    """Results are sorted by composite_score descending."""
    bus = EventBus()
    agent = QuantAnalyst(bus)

    bars = {"NVDA": _make_bars(), "AMD": _make_bars(base_price=80.0)}
    spy = _make_bars(base_price=450.0)

    with patch.object(agent, '_fetch_bars', return_value=bars), \
         patch.object(agent, '_fetch_spy_bars', return_value=spy):
        result = agent.run({"symbols": ["NVDA", "AMD"]})

    scores = [o.composite_score for o in result["outputs"]]
    assert scores == sorted(scores, reverse=True)


def test_quant_analyst_handles_empty_bars():
    """Agent handles symbols with no bar data gracefully."""
    bus = EventBus()
    agent = QuantAnalyst(bus)

    with patch.object(agent, '_fetch_bars', return_value={}), \
         patch.object(agent, '_fetch_spy_bars', return_value=_make_bars()):
        result = agent.run({"symbols": ["FAKE"]})

    assert result["outputs"] == []


def test_quant_analyst_computes_new_indicators():
    """Verify new indicators (ATR, Stochastic RSI, etc.) are populated."""
    bus = EventBus()
    agent = QuantAnalyst(bus)

    bars = {"NVDA": _make_bars(n=200)}
    spy = _make_bars(n=200, base_price=450.0)

    with patch.object(agent, '_fetch_bars', return_value=bars), \
         patch.object(agent, '_fetch_spy_bars', return_value=spy):
        result = agent.run({"symbols": ["NVDA"]})

    out = result["outputs"][0]
    assert out.atr > 0
    assert 0 <= out.stochastic_rsi <= 1
    assert out.volatility_20d > 0
    assert out.beta != 0  # should be computed vs SPY
