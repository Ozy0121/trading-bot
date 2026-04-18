"""Tests for quant_factors.py — multi-factor quant scoring model."""

import pandas as pd
import numpy as np
import pytest


def _make_ohlcv(n: int = 30, trend: str = "up") -> pd.DataFrame:
    """Generate realistic OHLCV DataFrame with lowercase cols and DatetimeIndex."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    if trend == "up":
        close = 100.0 + np.cumsum(np.abs(np.random.randn(n)) * 0.8)
    elif trend == "flat":
        close = np.full(n, 100.0)
    else:
        close = 100.0 + np.cumsum(np.random.randn(n) * 2)

    high = close + np.abs(np.random.randn(n)) * 1.5
    low = close - np.abs(np.random.randn(n)) * 1.5
    opn = close + np.random.randn(n) * 0.3
    volume = np.random.randint(500_000, 5_000_000, n).astype(float)

    return pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


EXPECTED_KEYS = {
    "symbol",
    "quant_score",
    "momentum_score",
    "quality_score",
    "smc_score",
    "volatility_score",
}


class TestComputeQuantScore:
    """Tests for compute_quant_score."""

    def test_compute_quant_score_keys(self):
        from quant_factors import compute_quant_score

        df = _make_ohlcv(30, trend="up")
        result = compute_quant_score("AAPL", df, momentum_rank=0.75)
        assert set(result.keys()) == EXPECTED_KEYS

    def test_compute_quant_score_ranges(self):
        from quant_factors import compute_quant_score

        df = _make_ohlcv(30, trend="up")
        result = compute_quant_score("AAPL", df, momentum_rank=0.5)
        for key in EXPECTED_KEYS:
            if key == "symbol":
                assert isinstance(result[key], str)
            else:
                assert isinstance(result[key], float), f"{key} is not float"
                assert 0.0 <= result[key] <= 10.0, f"{key}={result[key]} out of range"

    def test_quality_score_flat_obv(self):
        from quant_factors import compute_quant_score

        df = _make_ohlcv(30, trend="flat")
        result = compute_quant_score("FLAT", df, momentum_rank=0.5)
        assert result["quality_score"] == 0.0


class TestRankMomentum:
    """Tests for rank_momentum."""

    def test_rank_momentum_percentiles(self):
        from quant_factors import rank_momentum

        bars = {}
        for i, sym in enumerate(["A", "B", "C", "D", "E"]):
            np.random.seed(i + 100)
            bars[sym] = _make_ohlcv(30, trend="up")

        ranks = rank_momentum(bars)
        assert len(ranks) == 5
        for sym, rank_val in ranks.items():
            assert isinstance(rank_val, float), f"{sym} rank is not float"
            assert 0.0 <= rank_val <= 1.0, f"{sym} rank={rank_val} out of range"
