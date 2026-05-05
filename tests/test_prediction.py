"""Tests for prediction.py v4 — mean reversion with smart signals."""

import numpy as np
import pandas as pd
import pytest

from prediction import (
    PRIMARY_WEIGHTS,
    CONFIRM_BONUS,
    CONFLUENCE_MULTIPLIER,
    PatternResult,
    _detect_rsi2,
    _detect_ibs,
    _detect_consec_down,
    _detect_bb_touch,
    _detect_volume_spike,
)


def _make_df(n=80, trend="up"):
    """Generate synthetic OHLCV data."""
    np.random.seed(42)
    if trend == "up":
        base = np.linspace(90, 120, n) + np.random.normal(0, 0.5, n)
    else:
        base = np.linspace(120, 90, n) + np.random.normal(0, 0.5, n)
    df = pd.DataFrame({
        "open": base - 0.5,
        "high": base + 1.0,
        "low": base - 1.0,
        "close": base,
        "volume": np.random.randint(500_000, 2_000_000, n).astype(float),
    })
    df.index = pd.date_range("2025-01-01", periods=n, freq="B")
    return df


def test_primary_weights_configured():
    assert "rsi2" in PRIMARY_WEIGHTS
    assert "ibs" in PRIMARY_WEIGHTS
    assert "consec_down" in PRIMARY_WEIGHTS
    assert "bb_lower" in PRIMARY_WEIGHTS


def test_confirm_bonus_has_volume_spike():
    assert "volume_spike" in CONFIRM_BONUS
    assert CONFIRM_BONUS["volume_spike"] == 1.5


def test_confluence_multiplier():
    assert CONFLUENCE_MULTIPLIER == 1.25


def test_detect_rsi2_oversold():
    df = _make_df(50, "down")
    result = _detect_rsi2(df)
    assert isinstance(result, PatternResult)
    assert result.name == "rsi2"
    assert "rsi2_value" in result.details


def test_detect_ibs():
    df = _make_df(50)
    df.iloc[-1, df.columns.get_loc("close")] = float(df["low"].iloc[-1]) + 0.01
    result = _detect_ibs(df)
    assert result.name == "ibs"
    assert result.detected is True
    assert result.details["ibs_value"] < 0.2


def test_detect_consec_down_uses_closes():
    """Consecutive down detection should use lower closes, not lower-high+lower-low."""
    df = _make_df(50)
    for i in range(-3, 0):
        df.iloc[i, df.columns.get_loc("close")] = float(df["close"].iloc[i - 1]) - 1.0
        df.iloc[i, df.columns.get_loc("high")] = float(df["high"].iloc[i - 1]) + 5.0
    result = _detect_consec_down(df)
    assert result.detected is True
    assert result.details["consecutive_days"] >= 3


def test_detect_consec_down_not_triggered():
    df = _make_df(50, "up")
    result = _detect_consec_down(df)
    assert result.name == "consec_down"


def test_detect_volume_spike_detected():
    df = _make_df(50)
    avg_vol = float(df["volume"].iloc[-21:-1].mean())
    df.iloc[-1, df.columns.get_loc("volume")] = avg_vol * 2.0
    result = _detect_volume_spike(df)
    assert result.detected is True
    assert result.details["volume_ratio"] >= 1.5
    assert result.score >= 6.0


def test_detect_volume_spike_not_detected():
    df = _make_df(50)
    avg_vol = float(df["volume"].iloc[-21:-1].mean())
    df.iloc[-1, df.columns.get_loc("volume")] = avg_vol * 0.5
    result = _detect_volume_spike(df)
    assert result.detected is False


def test_detect_volume_spike_insufficient_data():
    df = _make_df(10)
    result = _detect_volume_spike(df)
    assert result.detected is False
    assert result.score == 0.0


def test_bb_touch():
    df = _make_df(50)
    result = _detect_bb_touch(df)
    assert result.name == "bb_lower"
    assert isinstance(result.detected, bool)
