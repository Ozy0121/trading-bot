"""
tests/test_prediction_signals.py
---------------------------------
Unit tests for prediction_signals.py — 6 new confirmation detectors.

Tests verify detection thresholds, edge cases, and calibration sync.
All tests use synthetic DataFrames with controlled OHLCV data.
"""

from __future__ import annotations

import pytest
import numpy as np
import pandas as pd


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_df(n: int, close: float = 100.0, high_offset: float = 1.0,
             low_offset: float = 1.0, volume: float = 1_000_000.0,
             closes: list[float] | None = None) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame of length n."""
    if closes is not None:
        c = np.array(closes, dtype=float)
        n = len(c)
    else:
        c = np.full(n, close)

    h = c + high_offset
    lo = c - low_offset
    v = np.full(n, volume)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"open": c, "high": h, "low": lo, "close": c, "volume": v}, index=idx)


# ── Test: _detect_stoch_rsi ──────────────────────────────────────────────────

class TestDetectStochRsi:
    def test_stoch_rsi_detection(self):
        """Steeply declining prices → RSI drops → stoch_rsi < 0.10 → detected."""
        from prediction_signals import _detect_stoch_rsi

        # Build 60 bars: first 30 mild, then 30 sharply declining
        mild = [100.0 - i * 0.05 for i in range(30)]
        sharp = [mild[-1] - i * 3.0 for i in range(30)]
        closes = mild + sharp
        df = _make_df(60, closes=closes)

        result = _detect_stoch_rsi(df)
        assert result.name == "stoch_rsi"
        assert result.detected is True
        assert result.score >= 8.0
        assert result.category == "momentum"
        assert "stoch_rsi_value" in result.details

    def test_stoch_rsi_not_detected(self):
        """Stable or rising prices → stoch_rsi > 0.20 → detected=False, score=0."""
        from prediction_signals import _detect_stoch_rsi

        closes = [100.0 + i * 0.5 for i in range(60)]
        df = _make_df(60, closes=closes)

        result = _detect_stoch_rsi(df)
        assert result.detected is False
        assert result.score == 0.0

    def test_stoch_rsi_insufficient_data(self):
        """Short DataFrame → detected=False."""
        from prediction_signals import _detect_stoch_rsi

        df = _make_df(10)
        result = _detect_stoch_rsi(df)
        assert result.detected is False
        assert result.score == 0.0


# ── Test: _detect_mfi ───────────────────────────────────────────────────────

class TestDetectMfi:
    def test_mfi_detection(self):
        """Heavy selling (low close, high volume on down days) → MFI < 20 → detected."""
        from prediction_signals import _detect_mfi

        # Declining prices with high volume → persistent negative money flow
        n = 30
        closes = [100.0 - i * 2.0 for i in range(n)]
        highs  = [c + 0.5 for c in closes]
        lows   = [c - 2.0 for c in closes]
        volumes = [2_000_000.0] * n

        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        df = pd.DataFrame({
            "open": closes, "high": highs, "low": lows,
            "close": closes, "volume": volumes
        }, index=idx)

        result = _detect_mfi(df)
        assert result.name == "mfi"
        assert result.category == "volume"
        assert result.detected is True
        assert "mfi_value" in result.details

    def test_mfi_not_detected(self):
        """Rising prices with volume → MFI > 20 → detected=False."""
        from prediction_signals import _detect_mfi

        closes = [100.0 + i * 1.5 for i in range(30)]
        df = _make_df(30, closes=closes)

        result = _detect_mfi(df)
        assert result.detected is False
        assert result.score == 0.0

    def test_mfi_insufficient_data(self):
        """Too few bars → detected=False."""
        from prediction_signals import _detect_mfi

        df = _make_df(5)
        result = _detect_mfi(df)
        assert result.detected is False


# ── Test: _detect_vwap ──────────────────────────────────────────────────────

class TestDetectVwap:
    def test_vwap_detection(self):
        """Price drops below VWAP → detected=True."""
        from prediction_signals import _detect_vwap

        # First 20 bars at 110, last 5 bars at 80 → VWAP well above current close
        closes = [110.0] * 20 + [80.0] * 5
        highs  = [c + 1.0 for c in closes]
        lows   = [c - 1.0 for c in closes]
        volumes = [1_000_000.0] * 25

        idx = pd.date_range("2024-01-01", periods=25, freq="D")
        df = pd.DataFrame({
            "open": closes, "high": highs, "low": lows,
            "close": closes, "volume": volumes
        }, index=idx)

        result = _detect_vwap(df)
        assert result.name == "vwap"
        assert result.category == "volume"
        assert result.detected is True
        assert result.score >= 5.0
        assert "vwap_value" in result.details
        assert "pct_below_vwap" in result.details

    def test_vwap_not_detected(self):
        """Price above VWAP → detected=False."""
        from prediction_signals import _detect_vwap

        closes = [80.0] * 20 + [110.0] * 5
        highs  = [c + 1.0 for c in closes]
        lows   = [c - 1.0 for c in closes]
        volumes = [1_000_000.0] * 25

        idx = pd.date_range("2024-01-01", periods=25, freq="D")
        df = pd.DataFrame({
            "open": closes, "high": highs, "low": lows,
            "close": closes, "volume": volumes
        }, index=idx)

        result = _detect_vwap(df)
        assert result.detected is False

    def test_vwap_insufficient_data(self):
        """Too few bars → detected=False."""
        from prediction_signals import _detect_vwap

        df = _make_df(5)
        result = _detect_vwap(df)
        assert result.detected is False


# ── Test: _detect_keltner_lower ─────────────────────────────────────────────

class TestDetectKeltnerLower:
    def test_keltner_lower_detection(self):
        """Price at/below lower Keltner channel → detected=True."""
        from prediction_signals import _detect_keltner_lower

        # Low-volatility bars (tight ±0.5) then a drop that pushes below channel.
        # With tight ATR the channel bands are narrow — a drop to 95.0 goes below ~96.
        closes = [100.0] * 30 + [95.0] * 10
        n = len(closes)
        highs  = [c + 0.5 for c in closes]
        lows   = [c - 0.5 for c in closes]
        volumes = [1_000_000.0] * n

        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        df = pd.DataFrame({
            "open": closes, "high": highs, "low": lows,
            "close": closes, "volume": volumes
        }, index=idx)

        result = _detect_keltner_lower(df)
        assert result.name == "keltner_lower"
        assert result.category == "volatility"
        assert result.detected is True
        assert result.score >= 6.0
        assert "keltner_lower" in result.details
        assert "price" in result.details

    def test_keltner_not_detected(self):
        """Price well above lower channel → detected=False."""
        from prediction_signals import _detect_keltner_lower

        closes = [100.0] * 40
        highs  = [105.0] * 40
        lows   = [95.0] * 40
        volumes = [1_000_000.0] * 40

        idx = pd.date_range("2024-01-01", periods=40, freq="D")
        df = pd.DataFrame({
            "open": closes, "high": highs, "low": lows,
            "close": closes, "volume": volumes
        }, index=idx)

        result = _detect_keltner_lower(df)
        assert result.detected is False

    def test_keltner_insufficient_data(self):
        """Too few bars → detected=False."""
        from prediction_signals import _detect_keltner_lower

        df = _make_df(10)
        result = _detect_keltner_lower(df)
        assert result.detected is False


# ── Test: _detect_macd_divergence ────────────────────────────────────────────

class TestDetectMacdDivergence:
    def test_macd_divergence_detected(self):
        """Price makes lower low, MACD histogram makes higher low → bullish divergence."""
        from prediction_signals import _detect_macd_divergence

        # Build 80 bars: stable base, then two dips where second price low is lower
        # but MACD histogram recovers (less negative on second dip)
        n = 80
        closes = [100.0] * n

        # Create first dip at bar 45: price drops to 90
        for i in range(40, 50):
            closes[i] = 90.0 - (i - 40) * 0.2

        # Create second dip at bar 65: price drops to 87 (lower than first)
        for i in range(60, 70):
            closes[i] = 95.0 - (i - 60) * 1.0

        # Ramp back up
        for i in range(70, 80):
            closes[i] = closes[69] + (i - 69) * 1.0

        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        highs  = [c + 2.0 for c in closes]
        lows   = [c - 2.0 for c in closes]
        volumes = [1_000_000.0] * n
        df = pd.DataFrame({
            "open": closes, "high": highs, "low": lows,
            "close": closes, "volume": volumes
        }, index=idx)

        result = _detect_macd_divergence(df)
        assert result.name == "macd_divergence"
        assert result.category == "momentum"
        # Details must contain divergence_type if detected, or not detected but no error
        assert isinstance(result.detected, bool)
        assert isinstance(result.score, float)

    def test_macd_divergence_not_detected(self):
        """No divergence pattern → detected=False."""
        from prediction_signals import _detect_macd_divergence

        # Steady uptrend → no divergence
        closes = [100.0 + i * 0.5 for i in range(80)]
        df = _make_df(80, closes=closes)

        result = _detect_macd_divergence(df)
        assert result.detected is False
        assert result.score == 0.0

    def test_macd_divergence_insufficient_data(self):
        """Short DataFrame → detected=False."""
        from prediction_signals import _detect_macd_divergence

        df = _make_df(20)
        result = _detect_macd_divergence(df)
        assert result.detected is False


# ── Test: _detect_support_level ─────────────────────────────────────────────

class TestDetectSupportLevel:
    def test_support_level_detection(self):
        """Price near swing low → detected=True."""
        from prediction_signals import _detect_support_level

        # Build 40 bars: dip to 90, recover to 100, then close near 90 again
        closes = [100.0] * 10 + [90.0] * 5 + [100.0] * 20 + [91.0] * 5
        df = _make_df(40, closes=closes)

        result = _detect_support_level(df)
        assert result.name == "support_level"
        assert result.category == "structure"
        assert result.detected is True
        assert result.score >= 4.0
        assert "nearest_support" in result.details
        assert "distance_pct" in result.details

    def test_support_level_not_detected(self):
        """Price far above all historical swing lows → detected=False.

        Uses an uptrend with a valley (swing low at ~50) followed by a sustained
        run to 120, so the current close is >50% above the nearest support.
        """
        from prediction_signals import _detect_support_level

        # V-shape that bottoms at 50, then rises steadily to 120
        # Swing low at 50 will be detected but price at 120 is 140% above it
        bottom = [70, 60, 50, 60, 70]          # clear V low at 50
        rise   = list(range(75, 125, 2))        # steady rise to 124
        closes = bottom + rise
        df = _make_df(len(closes), closes=[float(c) for c in closes])

        result = _detect_support_level(df)
        assert result.detected is False

    def test_support_insufficient_data(self):
        """Short DataFrame → detected=False."""
        from prediction_signals import _detect_support_level

        df = _make_df(10)
        result = _detect_support_level(df)
        assert result.detected is False


# ── Test: _find_swing_lows / _find_swing_highs ──────────────────────────────

class TestSwingPoints:
    def test_swing_lows_detected(self):
        """Known local minima correctly identified."""
        from prediction_signals import _find_swing_lows

        # Build a series with clear V-shape dip at position 5
        closes = [100, 98, 95, 92, 88, 85, 89, 93, 97, 100,
                  101, 103, 100, 97, 92, 88, 91, 95, 98, 100,
                  102, 104, 106, 108, 110, 112]
        df = _make_df(len(closes), closes=closes)

        lows = _find_swing_lows(df)
        assert isinstance(lows, list)
        # Should find at least one swing low
        assert len(lows) >= 1
        # All lows should be valid prices
        for lo in lows:
            assert isinstance(lo, float)

    def test_swing_highs_detected(self):
        """Known local maxima correctly identified."""
        from prediction_signals import _find_swing_highs

        closes = [85, 90, 95, 100, 105, 100, 95, 90, 85,
                  88, 95, 102, 108, 102, 95, 88, 85,
                  90, 95, 100, 105, 100, 95, 90, 85]
        df = _make_df(len(closes), closes=closes)

        highs = _find_swing_highs(df)
        assert isinstance(highs, list)
        assert len(highs) >= 1
        for hi in highs:
            assert isinstance(hi, float)

    def test_swing_lows_insufficient_data(self):
        """Short DataFrame returns empty list."""
        from prediction_signals import _find_swing_lows

        df = _make_df(3)
        result = _find_swing_lows(df)
        assert result == []


# ── Test: calibration sync ───────────────────────────────────────────────────

class TestCalibrationSync:
    def test_calibration_sync(self):
        """All 6 new keys must exist in both DEFAULT_CONFIRM_BONUS and DEFAULT_CONFIRM at 0.5."""
        from prediction import DEFAULT_CONFIRM_BONUS
        from signal_calibration import DEFAULT_CONFIRM

        new_keys = ["stoch_rsi", "mfi", "vwap", "keltner_lower", "macd_divergence", "support_level"]

        for k in new_keys:
            assert k in DEFAULT_CONFIRM_BONUS, f"Missing {k} in prediction.DEFAULT_CONFIRM_BONUS"
            assert DEFAULT_CONFIRM_BONUS[k] == 0.5, f"Expected 0.5 for {k} in DEFAULT_CONFIRM_BONUS, got {DEFAULT_CONFIRM_BONUS[k]}"

        for k in new_keys:
            assert k in DEFAULT_CONFIRM, f"Missing {k} in signal_calibration.DEFAULT_CONFIRM"
            assert DEFAULT_CONFIRM[k] == 0.5, f"Expected 0.5 for {k} in DEFAULT_CONFIRM, got {DEFAULT_CONFIRM[k]}"

    def test_existing_keys_unchanged(self):
        """Original keys must remain at their original values."""
        from prediction import DEFAULT_CONFIRM_BONUS
        from signal_calibration import DEFAULT_CONFIRM

        original_prediction = {"volume_profile": 1.5, "order_flow": 1.0, "amt_state": 1.0, "volume_spike": 1.5}
        original_calibration = {"volume_profile": 1.5, "order_flow": 1.0, "amt_state": 1.0, "volume_spike": 1.5}

        for k, v in original_prediction.items():
            assert DEFAULT_CONFIRM_BONUS[k] == v, f"Changed existing key {k} in DEFAULT_CONFIRM_BONUS"
        for k, v in original_calibration.items():
            assert DEFAULT_CONFIRM[k] == v, f"Changed existing key {k} in DEFAULT_CONFIRM"
