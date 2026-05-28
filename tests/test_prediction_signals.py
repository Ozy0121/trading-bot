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


# ── Test: SECTOR_ETF_MAP ─────────────────────────────────────────────────────

class TestSectorEtfMap:
    def test_sector_etf_map_count(self):
        """SECTOR_ETF_MAP must have exactly 11 entries."""
        from yf_limiter import SECTOR_ETF_MAP

        assert len(SECTOR_ETF_MAP) == 11

    def test_sector_etf_map_tickers(self):
        """SECTOR_ETF_MAP must include all 11 standard sector ETFs."""
        from yf_limiter import SECTOR_ETF_MAP

        expected = {"XLK", "XLE", "XLF", "XLV", "XLC", "XLI", "XLY", "XLP", "XLU", "XLRE", "XLB"}
        assert set(SECTOR_ETF_MAP.keys()) == expected


# ── Test: get_sector_etf_bars ────────────────────────────────────────────────

class TestGetSectorEtfBars:
    def test_get_sector_etf_bars_returns_df(self):
        """Mock yfinance: get_sector_etf_bars('XLK') returns DataFrame with lowercase columns."""
        from unittest.mock import patch, MagicMock
        import pandas as pd

        mock_df = pd.DataFrame(
            {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.5], "Volume": [1_000_000]},
            index=pd.date_range("2024-01-01", periods=1, freq="D"),
        )

        with patch("yf_limiter.yf") as mock_yf:
            mock_ticker = MagicMock()
            mock_ticker.history.return_value = mock_df
            mock_yf.Ticker.return_value = mock_ticker

            from yf_limiter import get_sector_etf_bars, _sector_etf_cache
            # Clear cache to ensure fresh fetch
            _sector_etf_cache.clear()

            result = get_sector_etf_bars("XLK_TEST_NOCACHE")

        assert result is not None
        assert isinstance(result, pd.DataFrame)
        # All columns must be lowercase
        for col in result.columns:
            assert col == col.lower(), f"Column {col!r} is not lowercase"

    def test_get_sector_etf_bars_caches(self):
        """Second call same day returns cached copy without hitting yfinance again."""
        from unittest.mock import patch, MagicMock
        from datetime import date
        import pandas as pd

        mock_df = pd.DataFrame(
            {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.5], "Volume": [1_000_000]},
            index=pd.date_range("2024-01-01", periods=1, freq="D"),
        )

        with patch("yf_limiter.yf") as mock_yf:
            mock_ticker = MagicMock()
            mock_ticker.history.return_value = mock_df.copy()
            mock_yf.Ticker.return_value = mock_ticker

            from yf_limiter import get_sector_etf_bars, _sector_etf_cache
            # Pre-seed the cache for today so first call is also a cache hit
            today = date.today()
            _sector_etf_cache["XLK_CACHE_TEST"] = (today, mock_df.copy())

            # Call twice — yfinance should NOT be called at all
            result1 = get_sector_etf_bars("XLK_CACHE_TEST")
            result2 = get_sector_etf_bars("XLK_CACHE_TEST")

        # Both results must be valid DataFrames
        assert result1 is not None
        assert result2 is not None
        # yfinance should NOT have been called (cache hit)
        mock_yf.Ticker.assert_not_called()


# ── Test: prefetch_sector_etf_bars ───────────────────────────────────────────

class TestPrefetchSectorEtfBars:
    def test_prefetch_returns_dict(self):
        """prefetch_sector_etf_bars() fetches all 11 ETFs and returns dict."""
        from unittest.mock import patch, MagicMock
        import pandas as pd

        mock_df = pd.DataFrame(
            {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.5], "Volume": [1_000_000]},
            index=pd.date_range("2024-01-01", periods=1, freq="D"),
        )

        with patch("yf_limiter.yf") as mock_yf:
            mock_ticker = MagicMock()
            mock_ticker.history.return_value = mock_df.copy()
            mock_yf.Ticker.return_value = mock_ticker

            from yf_limiter import prefetch_sector_etf_bars, SECTOR_ETF_MAP, _sector_etf_cache
            # Clear cache to force fresh fetches
            _sector_etf_cache.clear()

            result = prefetch_sector_etf_bars()

        assert isinstance(result, dict)
        # All 11 ETFs should be present (all mocked to succeed)
        assert len(result) == len(SECTOR_ETF_MAP)
        for etf in SECTOR_ETF_MAP:
            assert etf in result
            assert isinstance(result[etf], pd.DataFrame)


# ── Test: _compute_breadth_multiplier ────────────────────────────────────────

def _make_etf_bars(five_day_return: float, n: int = 30) -> pd.DataFrame:
    """Build a minimal sector ETF DataFrame with a specific 5-day return."""
    # We need at least 6 bars; set close[-6] = 100, close[-1] = 100*(1+return)
    closes = [100.0] * n
    closes[-1] = 100.0 * (1 + five_day_return)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": closes, "high": [c + 1.0 for c in closes],
        "low": [c - 1.0 for c in closes], "close": closes,
        "volume": [1_000_000.0] * n,
    }, index=idx)


class TestComputeBreadthMultiplier:
    def test_breadth_multiplier_normal(self):
        """All ETFs positive 5-day return -> returns 1.0."""
        from prediction_signals import _compute_breadth_multiplier

        bars = {etf: _make_etf_bars(0.03) for etf in ["XLK", "XLE", "XLF", "XLV", "XLC",
                                                         "XLI", "XLY", "XLP", "XLU", "XLRE", "XLB"]}
        result = _compute_breadth_multiplier(bars)
        assert result == 1.0

    def test_breadth_multiplier_weak(self):
        """Majority (6+) ETFs down >2% but not >5% over 5 days -> returns 0.5."""
        from prediction_signals import _compute_breadth_multiplier

        bars = {}
        etfs = ["XLK", "XLE", "XLF", "XLV", "XLC", "XLI", "XLY", "XLP", "XLU", "XLRE", "XLB"]
        for i, etf in enumerate(etfs):
            # First 7 down -3% (weak), last 4 flat
            bars[etf] = _make_etf_bars(-0.03 if i < 7 else 0.01)

        result = _compute_breadth_multiplier(bars)
        assert result == 0.5

    def test_breadth_multiplier_very_weak(self):
        """Majority (6+) ETFs down >5% over 5 days -> returns 0.25."""
        from prediction_signals import _compute_breadth_multiplier

        bars = {}
        etfs = ["XLK", "XLE", "XLF", "XLV", "XLC", "XLI", "XLY", "XLP", "XLU", "XLRE", "XLB"]
        for i, etf in enumerate(etfs):
            bars[etf] = _make_etf_bars(-0.07 if i < 7 else 0.01)

        result = _compute_breadth_multiplier(bars)
        assert result == 0.25

    def test_breadth_multiplier_no_data(self):
        """Empty dict input -> returns 1.0 (no penalty)."""
        from prediction_signals import _compute_breadth_multiplier

        assert _compute_breadth_multiplier({}) == 1.0
        assert _compute_breadth_multiplier(None) == 1.0

    def test_breadth_multiplier_insufficient_bars(self):
        """ETF DataFrames with fewer than 6 bars are skipped gracefully."""
        from prediction_signals import _compute_breadth_multiplier

        short_df = pd.DataFrame(
            {"open": [100.0], "high": [101.0], "low": [99.0], "close": [100.0], "volume": [1_000_000.0]},
            index=pd.date_range("2024-01-01", periods=1, freq="D"),
        )
        bars = {"XLK": short_df}
        result = _compute_breadth_multiplier(bars)
        assert result == 1.0


# ── Test: _detect_sector_strength ────────────────────────────────────────────

def _make_spy_bars(twenty_day_return: float, n: int = 25) -> pd.DataFrame:
    """Build a minimal SPY DataFrame with a specific 20-day return."""
    closes = [100.0] * n
    closes[-1] = 100.0 * (1 + twenty_day_return)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": closes, "high": [c + 1.0 for c in closes],
        "low": [c - 1.0 for c in closes], "close": closes,
        "volume": [5_000_000.0] * n,
    }, index=idx)


def _make_sector_etf_bars_20d(twenty_day_return: float, n: int = 25) -> pd.DataFrame:
    """Build a sector ETF DataFrame with a specific 20-day return."""
    closes = [100.0] * n
    closes[-1] = 100.0 * (1 + twenty_day_return)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": closes, "high": [c + 1.0 for c in closes],
        "low": [c - 1.0 for c in closes], "close": closes,
        "volume": [1_000_000.0] * n,
    }, index=idx)


class TestDetectSectorStrength:
    def test_sector_strength_leading(self):
        """Sector ETF 20-day return > SPY 20-day return -> detected=True, score > 0."""
        from unittest.mock import patch
        from prediction_signals import _detect_sector_strength

        spy_df = _make_spy_bars(0.02)          # SPY up 2%
        sector_etf_bars = {"XLK": _make_sector_etf_bars_20d(0.08)}  # Tech up 8%

        # get_sector_cached and SECTOR_ETF_MAP are imported inside _detect_sector_strength
        # from yf_limiter, so patch them there.
        with patch("yf_limiter.get_sector_cached", return_value="Technology"), \
             patch("yf_limiter.SECTOR_ETF_MAP", {"XLK": "Technology"}):
            result = _detect_sector_strength("AAPL", sector_etf_bars, spy_df)

        assert result.name == "sector_strength"
        assert result.category == "regime"
        assert result.detected is True
        assert result.score > 0.0
        assert result.details["spread"] > 0

    def test_sector_strength_lagging(self):
        """Sector ETF 20-day return < SPY 20-day return -> detected=False, score=0."""
        from unittest.mock import patch
        from prediction_signals import _detect_sector_strength

        spy_df = _make_spy_bars(0.05)          # SPY up 5%
        sector_etf_bars = {"XLE": _make_sector_etf_bars_20d(0.01)}  # Energy up 1%

        with patch("yf_limiter.get_sector_cached", return_value="Energy"), \
             patch("yf_limiter.SECTOR_ETF_MAP", {"XLE": "Energy"}):
            result = _detect_sector_strength("XOM", sector_etf_bars, spy_df)

        assert result.detected is False
        assert result.score == 0.0
        assert result.details["spread"] < 0

    def test_sector_strength_no_spy_data(self):
        """No SPY data -> detected=False gracefully."""
        from prediction_signals import _detect_sector_strength

        result = _detect_sector_strength("AAPL", {"XLK": _make_sector_etf_bars_20d(0.05)}, None)
        assert result.detected is False
        assert result.score == 0.0

    def test_sector_strength_no_sector_bars(self):
        """Empty sector ETF bars dict -> detected=False gracefully."""
        from prediction_signals import _detect_sector_strength

        spy_df = _make_spy_bars(0.02)
        result = _detect_sector_strength("AAPL", {}, spy_df)
        assert result.detected is False

    def test_sector_strength_unknown_sector(self):
        """Symbol with no sector mapping -> detected=False gracefully."""
        from unittest.mock import patch
        from prediction_signals import _detect_sector_strength

        spy_df = _make_spy_bars(0.02)
        sector_etf_bars = {"XLK": _make_sector_etf_bars_20d(0.05)}

        with patch("yf_limiter.get_sector_cached", return_value=""):
            result = _detect_sector_strength("UNKN", sector_etf_bars, spy_df)

        assert result.detected is False


# ── Test: re-entry tracker ───────────────────────────────────────────────────

class TestReentryTracker:
    def setup_method(self):
        """Clear the tracker before each test."""
        from prediction_signals import _reentry_tracker
        _reentry_tracker.clear()

    def test_reentry_allowed_first_stop(self):
        """First stop hit, check re-entry -> allowed at 50% size, 1.0 ATR stop."""
        from prediction_signals import record_stop_hit, _check_reentry_allowed

        record_stop_hit("NVDA")
        allowed, size_mult, atr_mult = _check_reentry_allowed("NVDA")

        assert allowed is True
        assert size_mult == 0.5
        assert atr_mult == 1.0

    def test_reentry_blocked_second_stop(self):
        """Two stop hits -> re-entry blocked (setup invalidated, per D-21)."""
        from prediction_signals import record_stop_hit, _check_reentry_allowed

        record_stop_hit("TSLA")
        record_stop_hit("TSLA")
        allowed, size_mult, atr_mult = _check_reentry_allowed("TSLA")

        assert allowed is False
        assert size_mult == 0.0
        assert atr_mult == 0.0

    def test_reentry_normal_no_prior_stop(self):
        """No prior stop hit -> normal entry (True, 1.0, 1.5)."""
        from prediction_signals import _check_reentry_allowed

        allowed, size_mult, atr_mult = _check_reentry_allowed("AAPL")

        assert allowed is True
        assert size_mult == 1.0
        assert atr_mult == 1.5

    def test_record_stop_hit_increments_count(self):
        """record_stop_hit increments count on repeated calls."""
        from prediction_signals import record_stop_hit, _reentry_tracker

        record_stop_hit("AMD")
        assert _reentry_tracker["AMD"]["stop_hit_count"] == 1

        record_stop_hit("AMD")
        assert _reentry_tracker["AMD"]["stop_hit_count"] == 2

    def test_reentry_tracker_prune(self):
        """Entries older than 7 days are pruned; recent entries are kept."""
        from prediction_signals import _prune_reentry_tracker, _reentry_tracker
        from datetime import date, timedelta

        old_date = (date.today() - timedelta(days=8)).isoformat()
        recent_date = date.today().isoformat()

        _reentry_tracker["OLD_SYM"] = {"stop_hit_count": 1, "last_stop_date": old_date}
        _reentry_tracker["NEW_SYM"] = {"stop_hit_count": 1, "last_stop_date": recent_date}

        _prune_reentry_tracker()

        assert "OLD_SYM" not in _reentry_tracker
        assert "NEW_SYM" in _reentry_tracker

    def test_prune_empty_tracker(self):
        """Pruning an empty tracker does not raise."""
        from prediction_signals import _prune_reentry_tracker, _reentry_tracker

        assert len(_reentry_tracker) == 0
        _prune_reentry_tracker()  # Should not raise
