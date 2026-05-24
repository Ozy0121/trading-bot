"""
tune_prediction.py — Fast parameter sweep for prediction engine v3.

Fetches data once, then tests multiple parameter combinations to find
the best win rate / expectancy tradeoff. Target: >59% win rate.
"""

import importlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

from data_provider import fetch_bars
from logger_setup import get_logger

log = get_logger()

BACKTEST_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "SOFI", "PLTR", "RIVN", "SNAP", "ROKU", "COIN", "MARA",
    "CRWD", "DDOG", "NET", "SHOP", "ENPH",
    "BAC", "F", "T", "INTC", "PFE",
    "SPY", "QQQ",
]

FORWARD_DAYS = 3
WIN_THRESHOLD = 0.01
MIN_WARMUP = 55


def fetch_all_data() -> dict[str, pd.DataFrame]:
    stock_data = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fetch_bars, s, period="1y", interval="1d"): s for s in BACKTEST_UNIVERSE}
        for f in as_completed(futs):
            sym = futs[f]
            try:
                df = f.result()
                if df is not None and len(df) > MIN_WARMUP + FORWARD_DAYS + 10:
                    stock_data[sym] = df[["open", "high", "low", "close", "volume"]].copy()
            except Exception:
                pass
    print(f"Fetched data for {len(stock_data)}/{len(BACKTEST_UNIVERSE)} stocks")
    return stock_data


def test_params(stock_data, params):
    """Test a parameter set. Returns (signals, wins, losses, avg_day3)."""
    import prediction as pred

    # Patch parameters
    pred.VP_THRESHOLD = params["vp_thresh"]
    pred.CVD_THRESHOLD = params["cvd_thresh"]
    pred.AMT_THRESHOLD = params["amt_thresh"]
    pred.MIN_CONFIDENCE = params["min_conf"]
    pred.MIN_HISTORICAL_ACCURACY = params["min_hist_acc"]
    pred.CONFLUENCE_MULTIPLIER = params["confluence_mult"]
    pred.TREND_SMA_FAST = params.get("trend_fast", 20)
    pred.TREND_SMA_SLOW = params.get("trend_slow", 50)

    # Patch trend filter if provided
    if params.get("trend_mode") == "relaxed":
        original_trend = pred._is_uptrending
        def _relaxed_trend(df):
            closes = df["close"]
            if len(closes) < params.get("trend_slow", 50) + 5:
                return False
            sma_slow = closes.rolling(params.get("trend_slow", 50)).mean()
            current_price = float(closes.iloc[-1])
            sma_s = float(sma_slow.iloc[-1])
            return current_price >= sma_s * 0.92
        pred._is_uptrending = _relaxed_trend
    elif params.get("trend_mode") == "off":
        pred._is_uptrending = lambda df: True
    elif params.get("trend_mode") == "very_relaxed":
        def _very_relaxed(df):
            closes = df["close"]
            if len(closes) < 30:
                return False
            sma30 = closes.rolling(30).mean()
            current_price = float(closes.iloc[-1])
            return current_price >= float(sma30.iloc[-1]) * 0.90
        pred._is_uptrending = _very_relaxed

    # Patch gate count if provided
    original_predict = None
    gate_min = params.get("gate_min", 2)

    signals = 0
    wins = 0
    losses = 0
    day3_returns = []

    for sym, df in stock_data.items():
        closes = df["close"]
        n = len(df)
        for i in range(MIN_WARMUP, n - FORWARD_DAYS):
            window = df.iloc[:i + 1].copy()
            try:
                result = pred.predict(sym, window)
            except Exception:
                continue

            if result is None or not result.predicted_spike:
                continue

            entry_price = float(closes.iloc[i])
            if entry_price <= 0:
                continue

            fwd_price = float(closes.iloc[i + FORWARD_DAYS])
            day3_ret = (fwd_price - entry_price) / entry_price * 100

            signals += 1
            day3_returns.append(day3_ret)
            if day3_ret > WIN_THRESHOLD:
                wins += 1
            else:
                losses += 1

    win_rate = wins / signals * 100 if signals > 0 else 0
    avg_day3 = sum(day3_returns) / len(day3_returns) if day3_returns else 0
    avg_win = sum(r for r in day3_returns if r > WIN_THRESHOLD) / max(1, wins)
    avg_loss = sum(r for r in day3_returns if r <= WIN_THRESHOLD) / max(1, losses)
    expectancy = (win_rate / 100 * avg_win) + ((100 - win_rate) / 100 * avg_loss) if signals else 0

    return {
        "signals": signals,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1),
        "avg_day3": round(avg_day3, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 2),
    }


PARAM_GRID = [
    # Baseline (current)
    {"name": "v3_baseline", "vp_thresh": 5.0, "cvd_thresh": 5.5, "amt_thresh": 5.0,
     "min_conf": 5, "min_hist_acc": 0.50, "confluence_mult": 1.3,
     "trend_mode": "strict", "gate_min": 2},

    # A: Lower thresholds, keep strict trend
    {"name": "lower_thresh_strict", "vp_thresh": 3.5, "cvd_thresh": 4.0, "amt_thresh": 3.5,
     "min_conf": 4, "min_hist_acc": 0.40, "confluence_mult": 1.3,
     "trend_mode": "strict", "gate_min": 2},

    # B: Lower thresholds + relaxed trend
    {"name": "lower_thresh_relaxed", "vp_thresh": 3.5, "cvd_thresh": 4.0, "amt_thresh": 3.5,
     "min_conf": 4, "min_hist_acc": 0.40, "confluence_mult": 1.3,
     "trend_mode": "relaxed", "gate_min": 2},

    # C: Medium thresholds + relaxed trend + higher confluence
    {"name": "med_thresh_high_conf", "vp_thresh": 4.0, "cvd_thresh": 4.5, "amt_thresh": 4.0,
     "min_conf": 4, "min_hist_acc": 0.40, "confluence_mult": 1.4,
     "trend_mode": "relaxed", "gate_min": 2},

    # D: Very low thresholds + no trend filter
    {"name": "low_thresh_no_trend", "vp_thresh": 3.0, "cvd_thresh": 3.5, "amt_thresh": 3.0,
     "min_conf": 3, "min_hist_acc": 0.35, "confluence_mult": 1.3,
     "trend_mode": "off", "gate_min": 2},

    # E: Medium thresholds + very relaxed trend
    {"name": "med_thresh_vrelaxed", "vp_thresh": 4.0, "cvd_thresh": 4.0, "amt_thresh": 4.0,
     "min_conf": 4, "min_hist_acc": 0.40, "confluence_mult": 1.3,
     "trend_mode": "very_relaxed", "gate_min": 2},

    # F: Higher VP weight (VP is the key signal), lower CVD threshold
    {"name": "vp_heavy_relaxed", "vp_thresh": 3.5, "cvd_thresh": 3.5, "amt_thresh": 4.0,
     "min_conf": 4, "min_hist_acc": 0.35, "confluence_mult": 1.35,
     "trend_mode": "relaxed", "gate_min": 2},

    # G: Tight thresholds but no hist accuracy filter
    {"name": "tight_no_hist", "vp_thresh": 5.0, "cvd_thresh": 5.0, "amt_thresh": 5.0,
     "min_conf": 5, "min_hist_acc": 0.0, "confluence_mult": 1.3,
     "trend_mode": "relaxed", "gate_min": 2},

    # H: Best of all — moderate thresholds, relaxed trend, no hist filter, high confluence
    {"name": "balanced_best", "vp_thresh": 4.0, "cvd_thresh": 4.0, "amt_thresh": 3.5,
     "min_conf": 4, "min_hist_acc": 0.0, "confluence_mult": 1.35,
     "trend_mode": "very_relaxed", "gate_min": 2},

    # I: Conservative — high thresholds, relaxed trend, no hist filter
    {"name": "conservative_relaxed", "vp_thresh": 5.5, "cvd_thresh": 5.5, "amt_thresh": 5.0,
     "min_conf": 5, "min_hist_acc": 0.0, "confluence_mult": 1.3,
     "trend_mode": "relaxed", "gate_min": 2},
]


if __name__ == "__main__":
    print("=" * 70)
    print("PREDICTION ENGINE v3 PARAMETER TUNING")
    print(f"Target: >59% win rate with positive expectancy")
    print("=" * 70)

    print("\nPhase 1: Fetching data (one time)...")
    t0 = time.time()
    stock_data = fetch_all_data()
    print(f"Data fetch: {time.time() - t0:.1f}s\n")

    print("Phase 2: Testing parameter combinations...\n")
    results = []
    for params in PARAM_GRID:
        t1 = time.time()
        r = test_params(stock_data, params)
        elapsed = time.time() - t1
        r["name"] = params["name"]
        r["time"] = round(elapsed, 1)
        results.append(r)

        marker = ""
        if r["win_rate"] >= 59:
            marker = " <<< TARGET MET!"
        elif r["win_rate"] >= 50:
            marker = " *"

        print(f"  {params['name']:30s} | {r['signals']:4d} signals | "
              f"WR {r['win_rate']:5.1f}% | exp {r['expectancy']:+6.2f}% | "
              f"avg3d {r['avg_day3']:+5.2f}% | {elapsed:.1f}s{marker}")

    print("\n" + "=" * 70)
    print("RESULTS RANKED BY WIN RATE:")
    print("=" * 70)
    for r in sorted(results, key=lambda x: (x["win_rate"], x["expectancy"]), reverse=True):
        marker = " *** TARGET" if r["win_rate"] >= 59 else ""
        print(f"  {r['name']:30s} | WR {r['win_rate']:5.1f}% | "
              f"exp {r['expectancy']:+6.2f}% | {r['signals']:4d} signals | "
              f"avg_win {r['avg_win']:+5.2f}% avg_loss {r['avg_loss']:+5.2f}%{marker}")

    # Save results
    os.makedirs("data", exist_ok=True)
    with open("data/tune_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to data/tune_results.json")
