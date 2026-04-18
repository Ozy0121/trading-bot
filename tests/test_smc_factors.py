"""Tests for smc_factors.py — SMC layer detection scoring."""

import pandas as pd
import numpy as np
import pytest


def _make_ohlcv(n: int = 50, trend: str = "up") -> pd.DataFrame:
    """Generate a realistic OHLCV DataFrame with lowercase columns and DatetimeIndex."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    if trend == "up":
        close = 100.0 + np.cumsum(np.abs(np.random.randn(n)) * 0.5)
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


class TestComputeSmcScore:
    """Tests for compute_smc_score."""

    def test_compute_smc_score_returns_float(self):
        from smc_factors import compute_smc_score

        df = _make_ohlcv(50, trend="up")
        result = compute_smc_score(df)
        assert isinstance(result, float)
        assert 0.0 <= result <= 10.0

    def test_compute_smc_score_short_df(self):
        from smc_factors import compute_smc_score

        df = _make_ohlcv(10)
        result = compute_smc_score(df)
        assert result == 0.0

    def test_compute_smc_score_empty_df(self):
        from smc_factors import compute_smc_score

        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        result = compute_smc_score(df)
        assert result == 0.0

    def test_compute_smc_score_no_swings(self):
        from smc_factors import compute_smc_score

        df = _make_ohlcv(50, trend="flat")
        result = compute_smc_score(df)
        assert result == 0.0
