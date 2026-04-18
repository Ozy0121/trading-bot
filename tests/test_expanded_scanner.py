"""
tests/test_expanded_scanner.py
------------------------------
Unit tests for the four-tier expanded scanner pipeline.
"""

from __future__ import annotations

import json
import os
import time

import numpy as np
import pandas as pd
import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = 30, base_price: float = 50.0,
                trend: str = "up", base_volume: int = 1_000_000) -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame with lowercase columns."""
    dates = pd.date_range(end=pd.Timestamp("2026-04-17"), periods=n, freq="D")
    closes = []
    price = base_price
    for i in range(n):
        if trend == "up":
            price += 0.5
        elif trend == "down":
            price -= 0.5
        else:  # flat
            price += 0.0
        closes.append(price)

    closes = np.array(closes)
    df = pd.DataFrame({
        "open":   closes - 0.2,
        "high":   closes + 0.3,
        "low":    closes - 0.4,
        "close":  closes,
        "volume": [base_volume] * n,
    }, index=dates)
    return df


def _make_bars_dict(symbols: list[str], n: int = 30,
                    trend: str = "up",
                    base_price: float = 50.0,
                    base_volume: int = 1_000_000) -> dict[str, pd.DataFrame]:
    """Return {sym: _make_ohlcv(n) for sym in symbols}."""
    return {sym: _make_ohlcv(n, base_price=base_price, trend=trend,
                             base_volume=base_volume) for sym in symbols}


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestTier1PriceFilter:
    def test_tier1_filters(self):
        """Symbols outside $5-$200 are rejected; ETFs are rejected."""
        from expanded_scanner import _filter_price_mcap

        bars = {}
        bars["AAPL"] = _make_ohlcv(5, base_price=50.0)
        bars["PENNY"] = _make_ohlcv(5, base_price=1.0)      # below $5
        bars["EXPENSIVE"] = _make_ohlcv(5, base_price=300.0)  # above $200
        bars["TQQQ"] = _make_ohlcv(5, base_price=40.0)        # ETF name

        symbols = ["AAPL", "PENNY", "EXPENSIVE", "TQQQ"]
        result = _filter_price_mcap(symbols, bars)

        assert "AAPL" in result
        assert "PENNY" not in result, "Below $5 should be rejected"
        assert "EXPENSIVE" not in result, "Above $200 should be rejected"
        assert "TQQQ" not in result, "Known leveraged ETF should be rejected"


class TestTier2VolumeFilter:
    def test_tier2_volume_filter(self):
        """Symbols with avg volume < 500K are rejected; >= 500K pass."""
        from expanded_scanner import _filter_volume

        bars = {}
        bars["LOWVOL"] = _make_ohlcv(5, base_volume=200_000)
        bars["HIGHVOL"] = _make_ohlcv(5, base_volume=600_000)

        result = _filter_volume(["LOWVOL", "HIGHVOL"], bars)

        assert "HIGHVOL" in result
        assert "LOWVOL" not in result


class TestTier3MomentumFilter:
    def test_tier3_momentum_gate(self):
        """Positive 5-day return passes; flat with normal volume fails."""
        from expanded_scanner import _filter_momentum

        bars_5d_up = {"WINNER": _make_ohlcv(5, trend="up")}
        bars_5d_flat = {"LOSER": _make_ohlcv(5, trend="flat")}
        bars_20d_up = {"WINNER": _make_ohlcv(20, trend="up")}
        bars_20d_flat = {"LOSER": _make_ohlcv(20, trend="flat")}

        result = _filter_momentum(
            ["WINNER", "LOSER"],
            {**bars_5d_up, **bars_5d_flat},
            {**bars_20d_up, **bars_20d_flat},
        )

        assert "WINNER" in result
        assert "LOSER" not in result

    def test_unusual_volume_passes_t3(self):
        """Stock with volume >2x 20-day avg passes T3 regardless of return direction (UNIV-02)."""
        from expanded_scanner import _filter_momentum

        # Flat return but huge volume spike on last day
        bars_5d = _make_ohlcv(5, trend="flat", base_volume=500_000)
        bars_20d = _make_ohlcv(20, trend="flat", base_volume=500_000)
        # Spike volume on last day to 3x avg
        bars_5d.iloc[-1, bars_5d.columns.get_loc("volume")] = 1_500_000

        result = _filter_momentum(
            ["VOLSPIKE"],
            {"VOLSPIKE": bars_5d},
            {"VOLSPIKE": bars_20d},
        )

        assert "VOLSPIKE" in result, "Unusual volume should pass T3"


class TestPipeline:
    def test_pipeline_produces_survivors(self, monkeypatch):
        """Mock pipeline produces <= 50 sorted results with quant_score key."""
        import expanded_scanner

        # Mock dependencies
        test_symbols = [f"SYM{i}" for i in range(10)]
        monkeypatch.setattr(
            "expanded_scanner.get_full_universe",
            lambda include_discovery=True: test_symbols,
        )

        bars = _make_bars_dict(test_symbols, n=30, base_volume=800_000)
        monkeypatch.setattr(
            "expanded_scanner.fetch_bulk_bars",
            lambda syms, period="5d", interval="1d": {
                s: bars[s] for s in syms if s in bars
            },
        )

        # Mock fetch_ticker_info to return non-ETF info
        monkeypatch.setattr(
            "expanded_scanner.fetch_ticker_info",
            lambda sym: {"longName": f"{sym} Corp", "quoteType": "EQUITY"},
        )

        # Mock shared_state.update to prevent side effects
        monkeypatch.setattr("expanded_scanner.shared_state.update", lambda **kw: None)

        # Mock save to avoid file I/O
        monkeypatch.setattr("expanded_scanner.save_overnight_results", lambda r, f: None)

        result = expanded_scanner.run_expanded_pipeline(timeout_seconds=60)

        assert isinstance(result, list)
        assert len(result) <= 50
        if result:
            assert "quant_score" in result[0]

    def test_pipeline_isolation(self):
        """expanded_scanner.py contains no imports from scanner.py (D-04)."""
        import expanded_scanner
        import inspect

        source = inspect.getsource(expanded_scanner)
        assert "from scanner import" not in source
        assert "import scanner" not in source


class TestPersistence:
    def test_save_load_overnight_results(self, tmp_path, monkeypatch):
        """Save results to JSON, load them back, verify round-trip; expired returns empty."""
        import expanded_scanner

        test_file = str(tmp_path / "overnight_results.json")
        monkeypatch.setattr("expanded_scanner.OVERNIGHT_RESULTS_PATH", test_file)

        test_data = [{"symbol": "AAPL", "quant_score": 7.5}]
        test_meta = {"tier1_count": 100}

        expanded_scanner.save_overnight_results(test_data, test_meta)
        loaded = expanded_scanner.load_overnight_results()

        assert loaded == test_data, "Round-trip should preserve data"

        # Now expire it
        with open(test_file, "r") as f:
            payload = json.load(f)
        payload["expires_at"] = time.time() - 100
        with open(test_file, "w") as f:
            json.dump(payload, f)

        loaded_expired = expanded_scanner.load_overnight_results()
        assert loaded_expired == [], "Expired results should return empty list"


class TestETFDetection:
    def test_etf_detection(self):
        """_is_etf_or_preferred detects ETFs and preferred shares."""
        from expanded_scanner import _is_etf_or_preferred

        # ETF by quoteType
        assert _is_etf_or_preferred("SPY", {"quoteType": "ETF"}) is True

        # ETF by name keyword
        assert _is_etf_or_preferred("TQQQ", {"longName": "ProShares UltraPro QQQ ETF"}) is True

        # Regular equity
        assert _is_etf_or_preferred("AAPL", {"longName": "Apple Inc", "quoteType": "EQUITY"}) is False

        # Known leveraged ETF by symbol (no info)
        assert _is_etf_or_preferred("TQQQ") is True

        # Preferred share suffix (symbol heuristic)
        assert _is_etf_or_preferred("SOFIP") is True
