"""
tests/test_scanner.py
---------------------
Integration tests for the multi-strategy scanner orchestrator.

All external calls (yfinance, sentiment_cache, config) are mocked to avoid
real API calls and ensure deterministic results.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

import scanner as scanner_mod
import config
from scanner import (
    _volume_ratio_to_score,
    _fetch_sector_scores,
    _score_symbol_multi,
    get_watchlist,
    best_buy,
    SECTOR_ETFS,
)


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


def make_sample_df() -> pd.DataFrame:
    """50-row OHLCV DataFrame with realistic data."""
    prices = [100.0 + i * 0.3 for i in range(50)]
    return _make_df(prices, volume_multiplier=2.5)


def make_flat_df() -> pd.DataFrame:
    """50-row sideways prices — no strong directional signals."""
    np.random.seed(42)
    noise  = np.random.normal(0, 0.1, 50)
    prices = [100.0 + n for n in noise]
    return _make_df(prices, volume_multiplier=1.0)


# ── Helpers for building fake result dicts ────────────────────────────────────

def _make_result(symbol: str, composite: float, fired: bool = True) -> dict:
    """Build a minimal result dict for testing best_buy() logic."""
    return {
        "symbol":       symbol,
        "price":        50.0,
        "signal":       "BUY" if fired else "HOLD",
        "raw_signal":   "BUY" if fired else "HOLD",
        "score":        composite,
        "rsi":          45.0,
        "volume_ratio": 2.5,
        "bb_upper":     55.0,
        "bb_lower":     45.0,
        "macd_hist":    0.01,
        "strategy":     "momentum",
        "conviction": {
            "technical":        composite * 0.8,
            "volume":           composite * 0.9,
            "sentiment":        5.0,
            "sector":           5.0,
            "composite":        composite,
            "strategies_fired": ["momentum"] if fired else [],
            "earnings_penalty": 0.0,
        },
        "df": make_sample_df(),
    }


# ── Volume score tests ────────────────────────────────────────────────────────

def test_volume_score_below_threshold():
    """Vol ratio 1.0 -> score < 5.0."""
    score = _volume_ratio_to_score(1.0)
    assert score < 5.0, f"Expected < 5.0, got {score}"


def test_volume_score_at_threshold():
    """Vol ratio 2.0 -> score == 5.0."""
    score = _volume_ratio_to_score(2.0)
    assert score == 5.0, f"Expected 5.0, got {score}"


def test_volume_score_above_threshold():
    """Vol ratio 5.0 -> score == 10.0."""
    score = _volume_ratio_to_score(5.0)
    assert score == 10.0, f"Expected 10.0, got {score}"


def test_volume_score_zero():
    """Vol ratio 0.0 -> score == 0.0 (clamped)."""
    score = _volume_ratio_to_score(0.0)
    assert score == 0.0, f"Expected 0.0, got {score}"


def test_volume_score_between():
    """Vol ratio 3.5 -> score between 5.0 and 10.0."""
    score = _volume_ratio_to_score(3.5)
    assert 5.0 < score < 10.0, f"Expected between 5.0 and 10.0, got {score}"


# ── Conviction threshold tests ────────────────────────────────────────────────

def test_conviction_threshold():
    """best_buy() returns empty list when all composites < threshold."""
    results = [
        _make_result("AAPL", 4.9),
        _make_result("TSLA", 4.0),
        _make_result("NVDA", 3.0),
    ]
    result = best_buy(results)
    assert result == []


def test_conviction_above_threshold():
    """best_buy() returns list with candidate when composite >= threshold."""
    results = [
        _make_result("AAPL", 7.5),
        _make_result("TSLA", 4.5),
    ]
    result = best_buy(results)
    assert len(result) >= 1
    assert result[0]["symbol"] == "AAPL"


def test_conviction_returns_first_above_threshold():
    """best_buy() returns top candidate above threshold first."""
    results = [
        _make_result("NVDA", 8.5),  # above threshold -- should be returned first
        _make_result("AMD",  7.2),  # also above threshold
        _make_result("TSLA", 4.0),  # below threshold
    ]
    result = best_buy(results)
    assert len(result) >= 1
    assert result[0]["symbol"] == "NVDA"


def test_best_buy_returns_top_3():
    """best_buy() returns exactly 3 candidates when >= 3 are above threshold."""
    results = [
        _make_result("A", 8.0),
        _make_result("B", 7.5),
        _make_result("C", 7.0),
        _make_result("D", 6.5),
        _make_result("E", 5.0),
    ]
    with patch.object(scanner_mod.config, "CONVICTION_THRESHOLD", 5.8):
        result = best_buy(results)
    assert len(result) == 3, f"Expected 3 candidates, got {len(result)}"
    assert result[0]["conviction"]["composite"] == 8.0
    assert result[2]["conviction"]["composite"] == 7.0


def test_best_buy_returns_fewer_than_3():
    """best_buy() returns fewer than 3 candidates when only 2 are above threshold."""
    results = [
        _make_result("A", 8.0),
        _make_result("B", 7.5),
    ]
    with patch.object(scanner_mod.config, "CONVICTION_THRESHOLD", 5.8):
        result = best_buy(results)
    assert len(result) == 2


def test_best_buy_empty_results():
    """best_buy() returns empty list when given empty input."""
    result = best_buy([])
    assert result == []


def test_top_movers_skip_momentum():
    """_score_symbol_multi() skips momentum strategy for symbols in _top_mover_symbols."""
    df = make_sample_df()
    momentum_called = []

    def mock_momentum(sym, df_):
        momentum_called.append(sym)
        return {"strategy": "momentum", "fired": True, "technical_score": 7.0, "volume_ratio": 2.5, "details": {}}

    def mock_meanrev(sym, df_):
        return {"strategy": "meanrev", "fired": False, "technical_score": 3.0, "volume_ratio": 1.5, "details": {}}

    scanner_mod._top_mover_symbols = {"TSLA"}
    try:
        with (
            patch.object(scanner_mod, "fetch_bars_yf", return_value=df),
            patch("scanner.get_sentiment_score", return_value=5.0),
            patch("scanner.get_earnings_penalty", return_value=0.0),
            patch("scanner._get_stock_sector_score", return_value=5.0),
            patch.dict("scanner.REGISTRY", {
                "momentum": mock_momentum,
                "meanrev":  mock_meanrev,
            }),
        ):
            result = scanner_mod._score_symbol_multi("TSLA", {})
    finally:
        scanner_mod._top_mover_symbols = set()

    assert result is not None
    assert "TSLA" not in momentum_called, "Momentum should be skipped for top mover TSLA"


def test_non_mover_runs_momentum():
    """_score_symbol_multi() runs momentum strategy for non-top-mover symbols."""
    df = make_sample_df()
    momentum_called = []

    def mock_momentum(sym, df_):
        momentum_called.append(sym)
        return {"strategy": "momentum", "fired": True, "technical_score": 7.0, "volume_ratio": 2.5, "details": {}}

    scanner_mod._top_mover_symbols = {"TSLA"}
    try:
        with (
            patch.object(scanner_mod, "fetch_bars_yf", return_value=df),
            patch("scanner.get_sentiment_score", return_value=5.0),
            patch("scanner.get_earnings_penalty", return_value=0.0),
            patch("scanner._get_stock_sector_score", return_value=5.0),
            patch.dict("scanner.REGISTRY", {
                "momentum": mock_momentum,
            }),
        ):
            result = scanner_mod._score_symbol_multi("AAPL", {})
    finally:
        scanner_mod._top_mover_symbols = set()

    assert result is not None
    assert "AAPL" in momentum_called, "Momentum should run for non-top-mover AAPL"


def test_expanded_watchlist_size():
    """config.SWING_WATCHLIST contains at least 50 stocks."""
    assert len(config.SWING_WATCHLIST) >= 50, (
        f"Expected >= 50 stocks, got {len(config.SWING_WATCHLIST)}"
    )


def test_watchlist_sector_coverage():
    """SWING_WATCHLIST includes at least one stock from each major GICS sector."""
    watchlist = set(config.SWING_WATCHLIST)
    sector_representatives = {
        "Technology":           "NVDA",
        "Consumer Disc":        "TSLA",
        "Communication Svcs":   "DIS",
        "Financials":           "JPM",
        "Healthcare":           "UNH",
        "Energy":               "XOM",
        "Industrials":          "CAT",
        "Consumer Staples":     "COST",
        "Materials":            "FCX",
        "Real Estate":          "AMT",
        "Utilities":            "NEE",
    }
    for sector, stock in sector_representatives.items():
        assert stock in watchlist, (
            f"Missing {sector} representative {stock} from SWING_WATCHLIST"
        )


# ── Skip logging tests ────────────────────────────────────────────────────────

def test_skip_logging(caplog):
    """Skipped candidates are logged at INFO level with full breakdown."""
    import logging
    results = [
        _make_result("LOW1", 3.0),
        _make_result("LOW2", 2.5),
    ]

    with caplog.at_level(logging.INFO, logger="trading_bot"):
        result = best_buy(results)

    assert result == []
    # Check that "Skipped" appears in log output
    all_messages = " ".join(caplog.messages)
    assert "Skipped" in all_messages, f"Expected 'Skipped' in logs, got: {caplog.messages}"


# ── Conviction breakdown tests ────────────────────────────────────────────────

def test_conviction_breakdown():
    """
    _score_symbol_multi() result dict has conviction key with all 5 sub-keys
    as floats in 0-10 range.
    """
    df = make_sample_df()

    # Mock all external dependencies
    mock_strategy_result = {
        "strategy": "momentum",
        "fired":    True,
        "technical_score": 7.0,
        "volume_ratio":    2.5,
        "details":  {},
    }

    with (
        patch.object(scanner_mod, "fetch_bars_yf", return_value=df),
        patch("scanner.get_sentiment_score", return_value=6.0),
        patch("scanner.get_earnings_penalty", return_value=0.0),
        patch("scanner._get_stock_sector_score", return_value=5.0),
        patch.dict("scanner.REGISTRY", {
            "momentum": lambda sym, df_: mock_strategy_result,
        }),
    ):
        result = scanner_mod._score_symbol_multi("AAPL", {})

    assert result is not None, "Expected a result dict"
    assert "conviction" in result, "Missing 'conviction' key"

    conv = result["conviction"]
    required_keys = {"technical", "volume", "sentiment", "sector", "composite"}
    for key in required_keys:
        assert key in conv, f"Missing conviction sub-key: {key}"
        val = conv[key]
        assert isinstance(val, (int, float)), f"conviction[{key}] should be numeric"
        assert 0.0 <= val <= 10.0, f"conviction[{key}]={val} out of 0-10 range"

    assert "strategies_fired" in conv
    assert "earnings_penalty" in conv


# ── Scan sorted tests ─────────────────────────────────────────────────────────

def test_scan_sorted():
    """scan() returns results sorted by composite descending."""
    df = make_sample_df()

    scores_by_sym = {"AAPL": 4.0, "NVDA": 8.0, "TSLA": 6.0}
    call_count = {}

    def mock_score(sym, etf_scores, catalysts=None):
        call_count[sym] = call_count.get(sym, 0) + 1
        composite = scores_by_sym[sym]
        return {
            "symbol":  sym,
            "price":   100.0,
            "signal":  "HOLD",
            "raw_signal": "HOLD",
            "score":   composite,
            "rsi":     50.0,
            "volume_ratio": 1.5,
            "bb_upper": None,
            "bb_lower": None,
            "macd_hist": 0.0,
            "strategy": "momentum",
            "conviction": {
                "technical": composite, "volume": composite,
                "sentiment": composite, "sector": composite,
                "composite": composite, "strategies_fired": [],
                "earnings_penalty": 0.0,
            },
            "df": df,
        }

    with (
        patch.object(scanner_mod, "_score_symbol_multi", side_effect=mock_score),
        patch.object(scanner_mod, "_fetch_sector_scores", return_value={}),
        patch("scanner.shared_state") as mock_state,
    ):
        mock_state.update = MagicMock()
        results = scanner_mod.scan(["AAPL", "NVDA", "TSLA"])

    assert len(results) == 3
    composites = [r["conviction"]["composite"] for r in results]
    assert composites == sorted(composites, reverse=True), f"Not sorted: {composites}"
    assert results[0]["symbol"] == "NVDA"


# ── Parallel scan tests ───────────────────────────────────────────────────────

def test_parallel_scan():
    """scan() processes all symbols via ThreadPoolExecutor."""
    symbols = ["A", "B", "C", "D", "E"]
    df      = make_sample_df()

    processed = []

    def mock_score(sym, etf_scores, catalysts=None):
        processed.append(sym)
        composite = 5.0
        return {
            "symbol":  sym,
            "price":   100.0,
            "signal":  "HOLD",
            "raw_signal": "HOLD",
            "score":   composite,
            "rsi":     50.0,
            "volume_ratio": 1.5,
            "bb_upper": None,
            "bb_lower": None,
            "macd_hist": 0.0,
            "strategy": "momentum",
            "conviction": {
                "technical": 5.0, "volume": 5.0,
                "sentiment": 5.0, "sector": 5.0,
                "composite": composite, "strategies_fired": [],
                "earnings_penalty": 0.0,
            },
            "df": df,
        }

    with (
        patch.object(scanner_mod, "_score_symbol_multi", side_effect=mock_score),
        patch.object(scanner_mod, "_fetch_sector_scores", return_value={}),
        patch("scanner.shared_state") as mock_state,
    ):
        mock_state.update = MagicMock()
        results = scanner_mod.scan(symbols)

    assert len(results) == 5, f"Expected 5 results, got {len(results)}"
    assert set(processed) == set(symbols), f"Not all symbols processed: {processed}"


# ── Earnings penalty tests ────────────────────────────────────────────────────

def test_earnings_penalty():
    """composite is reduced by earnings penalty vs a run with 0 penalty."""
    df = make_sample_df()

    mock_strategy_result = {
        "strategy": "momentum",
        "fired":    True,
        "technical_score": 7.0,
        "volume_ratio":    2.5,
        "details":  {},
    }

    common_patches = dict(
        fetch_bars_yf=df,
        sentiment_score=6.0,
        sector_score=5.0,
    )

    # Without penalty
    with (
        patch.object(scanner_mod, "fetch_bars_yf", return_value=df),
        patch("scanner.get_sentiment_score", return_value=6.0),
        patch("scanner.get_earnings_penalty", return_value=0.0),
        patch("scanner._get_stock_sector_score", return_value=5.0),
        patch.dict("scanner.REGISTRY", {
            "momentum": lambda sym, df_: mock_strategy_result,
        }),
    ):
        result_no_penalty = scanner_mod._score_symbol_multi("AAPL", {})

    # With penalty of 1.5
    with (
        patch.object(scanner_mod, "fetch_bars_yf", return_value=df),
        patch("scanner.get_sentiment_score", return_value=6.0),
        patch("scanner.get_earnings_penalty", return_value=1.5),
        patch("scanner._get_stock_sector_score", return_value=5.0),
        patch.dict("scanner.REGISTRY", {
            "momentum": lambda sym, df_: mock_strategy_result,
        }),
    ):
        result_with_penalty = scanner_mod._score_symbol_multi("AAPL", {})

    assert result_no_penalty is not None
    assert result_with_penalty is not None

    no_pen   = result_no_penalty["conviction"]["composite"]
    with_pen = result_with_penalty["conviction"]["composite"]
    assert with_pen < no_pen, (
        f"Penalty should reduce composite: no_penalty={no_pen}, with_penalty={with_pen}"
    )
    assert result_with_penalty["conviction"]["earnings_penalty"] == 1.5


# ── Watchlist config tests ────────────────────────────────────────────────────

def test_watchlist_config():
    """get_watchlist() returns SWING_WATCHLIST symbols when USE_TOP_MOVERS is False."""
    fake_watchlist = ["AAPL", "NVDA", "TSLA"]

    with (
        patch.object(scanner_mod.config, "USE_TOP_MOVERS", False),
        patch.object(scanner_mod.config, "SWING_WATCHLIST", fake_watchlist),
    ):
        result = get_watchlist()

    assert result == fake_watchlist, f"Expected {fake_watchlist}, got {result}"


def test_watchlist_merges_movers():
    """get_watchlist() merges top movers with SWING_WATCHLIST when USE_TOP_MOVERS is True."""
    fake_movers    = ["MEME", "MOON"]
    fake_watchlist = ["AAPL", "MEME"]  # MEME overlaps with movers

    with (
        patch.object(scanner_mod.config, "USE_TOP_MOVERS", True),
        patch.object(scanner_mod.config, "SWING_WATCHLIST", fake_watchlist),
        patch.object(scanner_mod, "fetch_top_movers", return_value=fake_movers),
    ):
        result = get_watchlist()

    # Should be deduplicated
    assert result.count("MEME") == 1, "MEME should appear only once"
    assert "MOON" in result
    assert "AAPL" in result


# ── Sector scoring tests ──────────────────────────────────────────────────────

def test_sector_scoring():
    """
    _fetch_sector_scores() returns dict with all 11 ETF keys and scores
    between 0 and 10.
    """
    # Build a mock multi-ticker yf.download return value
    # Returns a multi-level column DataFrame: (ETF, OHLCV)
    dates = pd.date_range("2025-01-01", periods=5, freq="B")
    arrays = [
        [etf for etf in SECTOR_ETFS for _ in ["Close"]],
        ["Close"] * len(SECTOR_ETFS),
    ]
    idx = pd.MultiIndex.from_arrays(arrays)

    # Give each ETF a unique close so rankings are distinct
    data = {
        (etf, "Close"): [100.0 + i * (j + 1) for i in range(5)]
        for j, etf in enumerate(SECTOR_ETFS)
    }
    mock_df = pd.DataFrame(data, index=dates)
    mock_df.columns = pd.MultiIndex.from_tuples(mock_df.columns)

    with patch("scanner.yf.download", return_value=mock_df):
        scores = _fetch_sector_scores()

    assert isinstance(scores, dict), f"Expected dict, got {type(scores)}"
    assert set(scores.keys()) == set(SECTOR_ETFS), (
        f"Missing ETFs: {set(SECTOR_ETFS) - set(scores.keys())}"
    )
    for etf, score in scores.items():
        assert 0.0 <= score <= 10.0, f"{etf} score {score} out of 0-10 range"


def test_sector_scoring_fallback():
    """_fetch_sector_scores() returns 5.0 for all ETFs when yf.download fails."""
    with patch("scanner.yf.download", side_effect=Exception("network error")):
        scores = _fetch_sector_scores()

    assert isinstance(scores, dict)
    assert set(scores.keys()) == set(SECTOR_ETFS)
    for etf, score in scores.items():
        assert score == 5.0, f"{etf} should fallback to 5.0, got {score}"


# ── Recalibration tests (02-04) ───────────────────────────────────────────────

def test_volume_fairness_mean_reversion():
    """
    D-18: When only mean_reversion fires (vol ratio 1.0), volume sub-score
    should be neutral 5.0, not the penalized formula result (~2.0).
    """
    df = make_sample_df()

    # mean_reversion always returns volume_ratio 1.0 (below 2x threshold)
    mock_meanrev_result = {
        "strategy": "mean_reversion",
        "fired":    True,
        "technical_score": 7.0,
        "volume_ratio":    1.0,
        "details":  {},
    }

    # Use ONLY mean_reversion in registry so no other strategies fire
    with (
        patch.object(scanner_mod, "fetch_bars_yf", return_value=df),
        patch("scanner.get_sentiment_score", return_value=5.0),
        patch("scanner.get_earnings_penalty", return_value=0.0),
        patch("scanner._get_stock_sector_score", return_value=5.0),
        patch.object(scanner_mod, "_market_regime_multiplier", return_value=1.0),
        patch.dict("scanner.REGISTRY", {
            "mean_reversion": lambda sym, df_: dict(mock_meanrev_result),
        }, clear=True),
    ):
        result = scanner_mod._score_symbol_multi("TSLA", {})

    assert result is not None
    # Volume sub-score must be neutral 5.0, not the formula result for ratio 1.0 (~2.0)
    vol_score = result["conviction"]["volume"]
    assert vol_score == 5.0, (
        f"Expected neutral volume score 5.0 for mean_reversion, got {vol_score}"
    )


def test_volume_fairness_momentum():
    """
    D-18: When momentum fires with high volume ratio, volume sub-score should
    use the actual formula (> 5.0 for ratio > 2x), not the neutral default.
    """
    df = make_sample_df()

    mock_momentum = {
        "strategy": "momentum",
        "fired":    True,
        "technical_score": 7.0,
        "volume_ratio":    3.0,   # above 2x -> score > 5.0
        "details":  {},
    }

    with (
        patch.object(scanner_mod, "fetch_bars_yf", return_value=df),
        patch("scanner.get_sentiment_score", return_value=5.0),
        patch("scanner.get_earnings_penalty", return_value=0.0),
        patch("scanner._get_stock_sector_score", return_value=5.0),
        patch.object(scanner_mod, "_market_regime_multiplier", return_value=1.0),
        patch.dict("scanner.REGISTRY", {
            "momentum": lambda sym, df_: dict(mock_momentum),
        }, clear=True),
    ):
        result = scanner_mod._score_symbol_multi("AAPL", {})

    assert result is not None
    vol_score = result["conviction"]["volume"]
    # _volume_ratio_to_score(3.0) = 5.0 + (1.0/3.0)*5.0 = 6.67
    assert vol_score > 5.0, (
        f"Expected volume score > 5.0 for momentum with ratio 3.0, got {vol_score}"
    )


def test_market_regime_bearish():
    """
    D-19: When _market_regime_multiplier returns 0.7, composite should be
    ~70% of the neutral-regime composite. conviction['regime_multiplier'] == 0.7.
    """
    df = make_sample_df()

    mock_strategy = {
        "strategy": "momentum",
        "fired":    True,
        "technical_score": 8.0,
        "volume_ratio":    2.5,
        "details":  {},
    }

    with (
        patch.object(scanner_mod, "fetch_bars_yf", return_value=df),
        patch("scanner.get_sentiment_score", return_value=6.0),
        patch("scanner.get_earnings_penalty", return_value=0.0),
        patch("scanner._get_stock_sector_score", return_value=5.0),
        patch.object(scanner_mod, "_market_regime_multiplier", return_value=1.0),
        patch.dict("scanner.REGISTRY", {
            "momentum": lambda sym, df_: dict(mock_strategy),
        }, clear=True),
    ):
        result_neutral = scanner_mod._score_symbol_multi("AAPL", {})

    with (
        patch.object(scanner_mod, "fetch_bars_yf", return_value=df),
        patch("scanner.get_sentiment_score", return_value=6.0),
        patch("scanner.get_earnings_penalty", return_value=0.0),
        patch("scanner._get_stock_sector_score", return_value=5.0),
        patch.object(scanner_mod, "_market_regime_multiplier", return_value=0.7),
        patch.dict("scanner.REGISTRY", {
            "momentum": lambda sym, df_: dict(mock_strategy),
        }, clear=True),
    ):
        result_bearish = scanner_mod._score_symbol_multi("AAPL", {})

    assert result_neutral is not None
    assert result_bearish is not None

    # Bearish composite should be ~70% of neutral
    neutral_comp = result_neutral["conviction"]["composite"]
    bearish_comp = result_bearish["conviction"]["composite"]
    assert bearish_comp < neutral_comp, (
        f"Bearish composite {bearish_comp} should be < neutral {neutral_comp}"
    )
    assert result_bearish["conviction"]["regime_multiplier"] == 0.7


def test_market_regime_neutral():
    """
    D-19: When _market_regime_multiplier returns 1.0, composite is unchanged
    and conviction['regime_multiplier'] == 1.0.
    """
    df = make_sample_df()

    mock_strategy = {
        "strategy": "momentum",
        "fired":    True,
        "technical_score": 7.0,
        "volume_ratio":    2.5,
        "details":  {},
    }

    with (
        patch.object(scanner_mod, "fetch_bars_yf", return_value=df),
        patch("scanner.get_sentiment_score", return_value=6.0),
        patch("scanner.get_earnings_penalty", return_value=0.0),
        patch("scanner._get_stock_sector_score", return_value=5.0),
        patch.object(scanner_mod, "_market_regime_multiplier", return_value=1.0),
        patch.dict("scanner.REGISTRY", {
            "momentum": lambda sym, df_: dict(mock_strategy),
        }, clear=True),
    ):
        result = scanner_mod._score_symbol_multi("AAPL", {})

    assert result is not None
    assert result["conviction"]["regime_multiplier"] == 1.0


def test_sector_cache_thread_safe():
    """D-21: _sector_cache_lock exists as a threading.Lock on the scanner module."""
    import threading as _threading
    assert hasattr(scanner_mod, "_sector_cache_lock"), (
        "scanner module is missing _sector_cache_lock"
    )
    assert isinstance(scanner_mod._sector_cache_lock, type(_threading.Lock())), (
        f"_sector_cache_lock should be a threading.Lock, got {type(scanner_mod._sector_cache_lock)}"
    )


def test_conviction_threshold_58():
    """
    D-01 updated: best_buy() returns empty list for composites at 5.5 and 5.7
    (both below 5.8 threshold).
    """
    results = [
        _make_result("AAPL", 5.7),
        _make_result("TSLA", 5.5),
    ]
    with patch.object(scanner_mod.config, "CONVICTION_THRESHOLD", 5.8):
        result = best_buy(results)
    assert result == [], f"Expected empty list for composites below 5.8, got {result}"


def test_conviction_at_threshold_58():
    """D-01 updated: best_buy() returns candidate when composite == 5.8."""
    results = [
        _make_result("AAPL", 5.8),
        _make_result("TSLA", 5.5),
    ]
    with patch.object(scanner_mod.config, "CONVICTION_THRESHOLD", 5.8):
        result = best_buy(results)
    assert len(result) >= 1
    assert result[0]["symbol"] == "AAPL"
