"""
tests/test_strategies.py
------------------------
Unit tests for the multi-strategy scan modules and REGISTRY.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from strategies import REGISTRY
from strategies.momentum import scan as momentum_scan
from strategies.mean_reversion import scan as mean_reversion_scan
from strategies.catalyst import scan as catalyst_scan


# ── DataFrame helpers ─────────────────────────────────────────────────────────

def _make_df(closes: list[float], volume_multiplier: float = 1.0) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a list of close prices."""
    n = len(closes)
    closes_arr = np.array(closes, dtype=float)
    base_vol   = 1_000_000.0
    volumes    = np.full(n, base_vol)
    volumes[-1] = base_vol * volume_multiplier
    return pd.DataFrame({
        "open":   closes_arr * 0.99,
        "high":   closes_arr * 1.01,
        "low":    closes_arr * 0.98,
        "close":  closes_arr,
        "volume": volumes,
    })


def make_breakout_df() -> pd.DataFrame:
    """50-bar df: prices trend up, last close > 20-day rolling max, volume 3x avg."""
    # Prices: slow trend then big jump on last bar
    prices = [100.0 + i * 0.2 for i in range(49)]  # gradual uptrend
    prices.append(prices[-1] + 5.0)               # big jump above 20-day max
    return _make_df(prices, volume_multiplier=3.0)


def make_oversold_df() -> pd.DataFrame:
    """50-bar df: repeatedly declining pattern to force RSI<35 AND price below lower BB."""
    # Build prices that decline steadily but end below the lower Bollinger Band.
    # Use a steeper decline for the last few bars so RSI stays low and price
    # breaks below the rolling lower BB (mean - 2*std).
    prices  = [100.0 - i * 0.5 for i in range(45)]   # gradual base decline
    last    = prices[-1]
    prices += [last - i * 4.0 for i in range(1, 6)]   # sharp final plunge
    return _make_df(prices, volume_multiplier=1.0)


def make_flat_df() -> pd.DataFrame:
    """50-bar df: sideways prices — no signals should fire."""
    np.random.seed(42)
    prices = [100.0 + np.random.uniform(-0.5, 0.5) for _ in range(50)]
    return _make_df(prices, volume_multiplier=1.0)


# ── Registry tests ────────────────────────────────────────────────────────────

def test_registry():
    """REGISTRY has exactly 3 keys and all values are callable."""
    assert set(REGISTRY.keys()) == {"momentum", "mean_reversion", "catalyst"}
    for name, fn in REGISTRY.items():
        assert callable(fn), f"REGISTRY['{name}'] is not callable"


# ── Momentum tests ────────────────────────────────────────────────────────────

def test_momentum_fires():
    """Momentum scan fires on breakout + 3x volume."""
    result = momentum_scan("TEST", make_breakout_df())
    assert result["strategy"] == "momentum"
    assert result["fired"] is True
    assert result["technical_score"] > 0
    assert result["volume_ratio"] >= 2.0


def test_momentum_no_fire():
    """Momentum scan does not fire on flat/sideways data."""
    result = momentum_scan("TEST", make_flat_df())
    assert result["fired"] is False


def test_momentum_score_range():
    """Technical score is always in [0, 10] regardless of input."""
    for df in [make_breakout_df(), make_flat_df(), make_oversold_df()]:
        result = momentum_scan("TEST", df)
        assert 0 <= result["technical_score"] <= 10, \
            f"technical_score out of range: {result['technical_score']}"


def test_momentum_insufficient_data():
    """Momentum returns fired=False when fewer than required bars are supplied."""
    tiny_df = _make_df([100.0] * 10)
    result  = momentum_scan("TEST", tiny_df)
    assert result["fired"] is False


# ── Mean reversion tests ──────────────────────────────────────────────────────

def test_mean_reversion_fires():
    """Mean reversion fires when RSI < 35 and price at lower Bollinger Band."""
    result = mean_reversion_scan("TEST", make_oversold_df())
    assert result["strategy"] == "mean_reversion"
    assert result["fired"] is True
    assert result["technical_score"] > 0


def test_mean_reversion_no_fire():
    """Mean reversion does not fire on flat data (RSI ~50)."""
    result = mean_reversion_scan("TEST", make_flat_df())
    assert result["fired"] is False


def test_mean_reversion_insufficient_data():
    """Mean reversion returns fired=False with < 22 bars."""
    tiny_df = _make_df([100.0] * 10)
    result  = mean_reversion_scan("TEST", tiny_df)
    assert result["fired"] is False


# ── Catalyst tests ────────────────────────────────────────────────────────────

def test_catalyst_both():
    """ARK buying + analyst upgrade = technical_score 10.0."""
    cats = {"TEST": {"ark_buying": True, "analyst_upgrade": True, "catalyst_count": 2}}
    result = catalyst_scan("TEST", _make_df([100.0] * 5), catalysts=cats)
    assert result["strategy"] == "catalyst"
    assert result["technical_score"] == 10.0
    assert result["fired"] is True


def test_catalyst_none():
    """No catalysts = technical_score 0.0 and fired=False."""
    cats = {"TEST": {"ark_buying": False, "analyst_upgrade": False, "catalyst_count": 0}}
    result = catalyst_scan("TEST", _make_df([100.0] * 5), catalysts=cats)
    assert result["technical_score"] == 0.0
    assert result["fired"] is False


def test_catalyst_ark_only():
    """ARK buying only = technical_score 5.0."""
    cats = {"TEST": {"ark_buying": True, "analyst_upgrade": False, "catalyst_count": 1}}
    result = catalyst_scan("TEST", _make_df([100.0] * 5), catalysts=cats)
    assert result["technical_score"] == 5.0
    assert result["fired"] is True


def test_catalyst_upgrade_only():
    """Analyst upgrade only = technical_score 5.0."""
    cats = {"TEST": {"ark_buying": False, "analyst_upgrade": True, "catalyst_count": 1}}
    result = catalyst_scan("TEST", _make_df([100.0] * 5), catalysts=cats)
    assert result["technical_score"] == 5.0
    assert result["fired"] is True


def test_catalyst_missing_symbol():
    """Symbol not in catalysts dict = default zeroed result, fired=False."""
    cats = {}
    result = catalyst_scan("MISSING", _make_df([100.0] * 5), catalysts=cats)
    assert result["fired"] is False
    assert result["technical_score"] == 0.0
