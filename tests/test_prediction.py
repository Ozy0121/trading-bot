"""Tests for prediction.py calibrated weights, combo bonus, and volume gate."""

from unittest.mock import patch
import numpy as np
import pandas as pd
import pytest

from prediction import (
    PATTERN_WEIGHTS,
    COMBO_BONUS_CORE,
    COMBO_BONUS_MULTIPLIER,
    PatternResult,
    predict,
)


def _make_uptrending_df(n=80):
    """Generate synthetic OHLCV data with SMA20 > SMA50 (uptrend)."""
    np.random.seed(42)
    base = np.linspace(90, 120, n) + np.random.normal(0, 0.5, n)
    df = pd.DataFrame({
        "open": base - 0.5,
        "high": base + 1.0,
        "low": base - 1.0,
        "close": base,
        "volume": np.random.randint(500_000, 2_000_000, n).astype(float),
    })
    df.index = pd.date_range("2025-01-01", periods=n, freq="B")
    return df


def test_pattern_weights_calibrated():
    expected_keys = {
        "adl_divergence", "volume_accumulation", "higher_lows",
        "keltner_squeeze", "relative_strength", "fair_value_gap", "macd_launch_zone",
    }
    assert set(PATTERN_WEIGHTS.keys()) == expected_keys
    assert "obv_divergence" not in PATTERN_WEIGHTS
    assert PATTERN_WEIGHTS["adl_divergence"] == 3.0
    assert PATTERN_WEIGHTS["volume_accumulation"] == 2.5


def test_combo_bonus_constants():
    assert COMBO_BONUS_CORE == {"adl_divergence", "volume_accumulation"}
    assert COMBO_BONUS_MULTIPLIER == 1.5


def _make_pattern(name, detected, category="volume", score=8.0):
    return PatternResult(name=name, detected=detected, score=score if detected else 0.0, category=category)


def test_volume_gate_requires_core_volume():
    """Predictions with no adl_divergence or volume_accumulation should be rejected."""
    df = _make_uptrending_df()

    def fake_keltner(d): return _make_pattern("keltner_squeeze", True, "volatility")
    def fake_adl(d): return _make_pattern("adl_divergence", False, "volume")
    def fake_vol(d): return _make_pattern("volume_accumulation", False, "volume")
    def fake_higher(d): return _make_pattern("higher_lows", True, "price")
    def fake_fvg(d): return _make_pattern("fair_value_gap", False, "price")
    def fake_macd(d): return _make_pattern("macd_launch_zone", False, "momentum")
    def fake_rs(d, *a, **kw): return _make_pattern("relative_strength", True, "momentum")

    with patch("prediction.detect_keltner_squeeze", fake_keltner), \
         patch("prediction.detect_adl_divergence", fake_adl), \
         patch("prediction.detect_volume_accumulation", fake_vol), \
         patch("prediction.detect_higher_lows", fake_higher), \
         patch("prediction.detect_fair_value_gap", fake_fvg), \
         patch("prediction.detect_macd_launch_zone", fake_macd), \
         patch("prediction.detect_relative_strength", fake_rs), \
         patch("prediction._is_uptrending", return_value=True):
        result = predict("TEST", df)
    assert result is None


def test_volume_gate_accepts_adl_divergence():
    """Predictions with adl_divergence should pass the volume gate."""
    df = _make_uptrending_df()

    def fake_keltner(d): return _make_pattern("keltner_squeeze", False, "volatility")
    def fake_adl(d): return _make_pattern("adl_divergence", True, "volume")
    def fake_vol(d): return _make_pattern("volume_accumulation", False, "volume")
    def fake_higher(d): return _make_pattern("higher_lows", True, "price")
    def fake_fvg(d): return _make_pattern("fair_value_gap", False, "price")
    def fake_macd(d): return _make_pattern("macd_launch_zone", False, "momentum")
    def fake_rs(d, *a, **kw): return _make_pattern("relative_strength", True, "momentum")

    with patch("prediction.detect_keltner_squeeze", fake_keltner), \
         patch("prediction.detect_adl_divergence", fake_adl), \
         patch("prediction.detect_volume_accumulation", fake_vol), \
         patch("prediction.detect_higher_lows", fake_higher), \
         patch("prediction.detect_fair_value_gap", fake_fvg), \
         patch("prediction.detect_macd_launch_zone", fake_macd), \
         patch("prediction.detect_relative_strength", fake_rs), \
         patch("prediction._is_uptrending", return_value=True), \
         patch("prediction._compute_historical_accuracy", return_value={"accuracy": 0.6, "samples": 15}), \
         patch("prediction._weekly_trend_modifier", return_value=1.0), \
         patch("prediction._classify_stage", return_value="early_squeeze"):
        result = predict("TEST", df)
    assert result is not None


def test_obv_divergence_not_called():
    """predict() should not call detect_obv_divergence."""
    df = _make_uptrending_df()

    with patch("prediction.detect_obv_divergence") as mock_obv, \
         patch("prediction._is_uptrending", return_value=False):
        predict("TEST", df)
    mock_obv.assert_not_called()
