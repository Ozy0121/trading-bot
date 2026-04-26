"""
pattern_backtester.py
---------------------
Walk-forward backtester for the 8 pattern detectors in prediction.py.

Tests each pattern against historical data to produce:
  - Per-pattern hit rates, edge, and win/loss ratios
  - Pattern combination analysis (2- and 3-pattern combos)
  - Baseline comparisons (dart-throwing, simple momentum)

Usage:
    py pattern_backtester.py                       # full backtest (~200 stocks, 250 days)
    py pattern_backtester.py --universe 50         # smaller universe
    py pattern_backtester.py --test-days 60        # shorter test window
    py pattern_backtester.py --patterns keltner_squeeze,obv_divergence
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from itertools import combinations

import numpy as np
import pandas as pd

from logger_setup import get_logger

log = get_logger()

# ── Constants ───────────────────────────────────────────────────────────────

FORWARD_DAYS = 5
MIN_LOOKBACK = 60
DEFAULT_UNIVERSE_SIZE = 200
DEFAULT_TEST_DAYS = 250
MIN_COMBO_OCCURRENCES = 20
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "data", "pattern_backtest_results.json")

# ── Pattern detector registry ───────────────────────────────────────────────

from prediction import (
    detect_keltner_squeeze,
    detect_obv_divergence,
    detect_adl_divergence,
    detect_volume_accumulation,
    detect_higher_lows,
    detect_fair_value_gap,
    detect_macd_launch_zone,
    detect_relative_strength,
    _is_uptrending,
)

PATTERN_DETECTORS: dict[str, callable] = {
    "keltner_squeeze": detect_keltner_squeeze,
    "obv_divergence": detect_obv_divergence,
    "adl_divergence": detect_adl_divergence,
    "volume_accumulation": detect_volume_accumulation,
    "higher_lows": detect_higher_lows,
    "fair_value_gap": detect_fair_value_gap,
    "macd_launch_zone": detect_macd_launch_zone,
    "relative_strength": detect_relative_strength,
}


# ── Data loading ────────────────────────────────────────────────────────────


def _load_universe_data(
    universe_size: int = DEFAULT_UNIVERSE_SIZE,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Download 2 years of daily bars for the stock universe + SPY."""
    from stock_universe import get_sp500
    from openbb_data import fetch_bulk_bars

    symbols = get_sp500()[:universe_size]
    print(f"[backtester] Fetching 2-year daily bars for {len(symbols)} stocks + SPY...")

    all_symbols = list(set(symbols + ["SPY"]))

    def _progress(cur, tot, lbl=None):
        if lbl:
            print(f"\r[backtester] {lbl}", end="", flush=True)

    bars = fetch_bulk_bars(all_symbols, period="2y", interval="1d", progress_cb=_progress)
    print()

    spy_df = bars.pop("SPY", pd.DataFrame())
    if spy_df.empty:
        log.warning("[backtester] SPY data not available — relative strength will be skipped")

    valid = {sym: df for sym, df in bars.items() if len(df) >= MIN_LOOKBACK + FORWARD_DAYS + 10}
    print(f"[backtester] Got data for {len(valid)}/{len(symbols)} stocks ({len(valid)} have enough bars)")

    return valid, spy_df


# ── Walk-forward engine ─────────────────────────────────────────────────────


def _run_walk_forward(
    bars_by_symbol: dict[str, pd.DataFrame],
    spy_df: pd.DataFrame,
    test_days: int = DEFAULT_TEST_DAYS,
    pattern_names: list[str] | None = None,
) -> list[dict]:
    """Run pattern detectors on historical data with no lookahead bias.

    For each stock, for each test date in the last `test_days` trading days:
    - Slice data up to (and including) the test date
    - Run pattern detectors on the slice
    - Record 5-day forward return

    Returns list of observation dicts.
    """
    detectors = {
        name: fn for name, fn in PATTERN_DETECTORS.items()
        if pattern_names is None or name in pattern_names
    }

    observations: list[dict] = []
    total_stocks = len(bars_by_symbol)
    processed = 0
    total_obs = 0

    for sym, df in bars_by_symbol.items():
        processed += 1
        n_bars = len(df)
        start_idx = max(MIN_LOOKBACK, n_bars - test_days - FORWARD_DAYS)
        end_idx = n_bars - FORWARD_DAYS

        if start_idx >= end_idx:
            continue

        for t in range(start_idx, end_idx):
            window = df.iloc[:t + 1]
            forward_close = float(df["close"].iloc[t + FORWARD_DAYS])
            current_close = float(df["close"].iloc[t])

            if current_close <= 0:
                continue

            forward_return = (forward_close - current_close) / current_close

            fired = []
            scores = {}
            for name, detector in detectors.items():
                try:
                    if name == "relative_strength" and not spy_df.empty:
                        spy_window = spy_df.iloc[:min(t + 1, len(spy_df))]
                        result = detector(window, spy_df=spy_window)
                    else:
                        result = detector(window)

                    if result.detected:
                        fired.append(name)
                        scores[name] = result.score
                except Exception:
                    pass

            observations.append({
                "symbol": sym,
                "date_idx": t,
                "patterns_fired": fired,
                "pattern_scores": scores,
                "forward_return": round(forward_return, 6),
                "current_close": round(current_close, 2),
            })
            total_obs += 1

        if processed % 10 == 0 or processed == total_stocks:
            print(f"\r[backtester] {processed}/{total_stocks} stocks, {total_obs:,} observations", end="", flush=True)

    print()
    return observations


# ── Per-pattern statistics ──────────────────────────────────────────────────


def _compute_pattern_stats(
    observations: list[dict],
    pattern_names: list[str] | None = None,
) -> dict[str, dict]:
    """Compute hit rate, edge, and win/loss ratio for each pattern."""
    names = pattern_names or list(PATTERN_DETECTORS.keys())

    all_returns = [obs["forward_return"] for obs in observations]
    baseline_hit_rate = sum(1 for r in all_returns if r > 0) / len(all_returns) if all_returns else 0.5
    baseline_avg_return = sum(all_returns) / len(all_returns) if all_returns else 0.0

    stats: dict[str, dict] = {}

    for name in names:
        fired_returns = [
            obs["forward_return"]
            for obs in observations
            if name in obs["patterns_fired"]
        ]

        if not fired_returns:
            stats[name] = {
                "times_fired": 0,
                "hit_rate": 0.0,
                "avg_return": 0.0,
                "avg_winning_return": 0.0,
                "avg_losing_return": 0.0,
                "win_loss_ratio": 0.0,
                "edge_vs_baseline": 0.0,
                "return_edge": 0.0,
            }
            continue

        wins = [r for r in fired_returns if r > 0]
        losses = [r for r in fired_returns if r <= 0]

        hit_rate = len(wins) / len(fired_returns)
        avg_return = sum(fired_returns) / len(fired_returns)
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        win_loss_ratio = avg_win / abs(avg_loss) if avg_loss != 0 else float("inf") if avg_win > 0 else 0.0

        stats[name] = {
            "times_fired": len(fired_returns),
            "hit_rate": round(hit_rate, 4),
            "avg_return": round(avg_return * 100, 3),
            "avg_winning_return": round(avg_win * 100, 3),
            "avg_losing_return": round(avg_loss * 100, 3),
            "win_loss_ratio": round(win_loss_ratio, 3),
            "edge_vs_baseline": round((hit_rate - baseline_hit_rate) * 100, 2),
            "return_edge": round((avg_return - baseline_avg_return) * 100, 3),
        }

    stats["_baseline"] = {
        "total_observations": len(observations),
        "baseline_hit_rate": round(baseline_hit_rate, 4),
        "baseline_avg_return_pct": round(baseline_avg_return * 100, 3),
    }

    return stats


# ── Pattern combination analysis ────────────────────────────────────────────


def _compute_combo_stats(
    observations: list[dict],
    pattern_names: list[str] | None = None,
    min_occurrences: int = MIN_COMBO_OCCURRENCES,
) -> dict:
    """Compute hit rates for 2-pattern and 3-pattern combinations."""
    names = pattern_names or list(PATTERN_DETECTORS.keys())

    all_returns = [obs["forward_return"] for obs in observations]
    baseline_hit_rate = sum(1 for r in all_returns if r > 0) / len(all_returns) if all_returns else 0.5

    def _combo_hit_rate(combo: tuple[str, ...]) -> dict | None:
        combo_set = set(combo)
        fired_returns = [
            obs["forward_return"]
            for obs in observations
            if combo_set.issubset(obs["patterns_fired"])
        ]
        if len(fired_returns) < min_occurrences:
            return None

        hit_rate = sum(1 for r in fired_returns if r > 0) / len(fired_returns)
        avg_return = sum(fired_returns) / len(fired_returns)

        return {
            "patterns": list(combo),
            "occurrences": len(fired_returns),
            "hit_rate": round(hit_rate, 4),
            "avg_return_pct": round(avg_return * 100, 3),
            "edge_vs_baseline": round((hit_rate - baseline_hit_rate) * 100, 2),
        }

    two_combos = []
    for combo in combinations(names, 2):
        result = _combo_hit_rate(combo)
        if result:
            two_combos.append(result)

    three_combos = []
    for combo in combinations(names, 3):
        result = _combo_hit_rate(combo)
        if result:
            three_combos.append(result)

    two_combos.sort(key=lambda x: x["edge_vs_baseline"], reverse=True)
    three_combos.sort(key=lambda x: x["edge_vs_baseline"], reverse=True)

    return {
        "two_pattern_combos": two_combos,
        "three_pattern_combos": three_combos,
    }


# ── Baseline strategies ─────────────────────────────────────────────────────


def _compute_baseline_stats(
    bars_by_symbol: dict[str, pd.DataFrame],
    test_days: int = DEFAULT_TEST_DAYS,
) -> dict:
    """Compute dart-throwing and momentum baseline strategies.

    Dart-throwing: average 5-day forward return across all stocks.
    Momentum: top 20% by 20-day return with SMA20 > SMA50, measure 5-day forward.
    """
    dart_returns: list[float] = []
    momentum_returns: list[float] = []

    for sym, df in bars_by_symbol.items():
        n_bars = len(df)
        start_idx = max(MIN_LOOKBACK, n_bars - test_days - FORWARD_DAYS)
        end_idx = n_bars - FORWARD_DAYS

        if start_idx >= end_idx:
            continue

        closes = df["close"]

        for t in range(start_idx, end_idx):
            current = float(closes.iloc[t])
            forward = float(closes.iloc[t + FORWARD_DAYS])
            if current <= 0:
                continue
            ret = (forward - current) / current
            dart_returns.append(ret)

    # Momentum baseline: computed per-date across all stocks
    # For each test date, rank stocks by 20-day return, take top 20% with SMA20 > SMA50
    sample_df = next(iter(bars_by_symbol.values()))
    n_bars = len(sample_df)
    start_idx = max(MIN_LOOKBACK, n_bars - test_days - FORWARD_DAYS)
    end_idx = n_bars - FORWARD_DAYS

    for t in range(start_idx, end_idx):
        candidates = []
        for sym, df in bars_by_symbol.items():
            if len(df) <= t + FORWARD_DAYS or t < 50:
                continue
            closes = df["close"]
            current = float(closes.iloc[t])
            if current <= 0 or t < 20:
                continue

            ret_20d = (current - float(closes.iloc[t - 20])) / float(closes.iloc[t - 20]) if float(closes.iloc[t - 20]) > 0 else 0
            sma20 = float(closes.iloc[t - 19:t + 1].mean())
            sma50 = float(closes.iloc[max(0, t - 49):t + 1].mean()) if t >= 49 else float(closes.iloc[:t + 1].mean())

            if sma20 > sma50:
                forward = float(closes.iloc[t + FORWARD_DAYS])
                fwd_ret = (forward - current) / current
                candidates.append((ret_20d, fwd_ret))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            top_n = max(1, len(candidates) // 5)
            for _, fwd_ret in candidates[:top_n]:
                momentum_returns.append(fwd_ret)

    dart_hit_rate = sum(1 for r in dart_returns if r > 0) / len(dart_returns) if dart_returns else 0
    dart_avg_return = sum(dart_returns) / len(dart_returns) if dart_returns else 0

    mom_hit_rate = sum(1 for r in momentum_returns if r > 0) / len(momentum_returns) if momentum_returns else 0
    mom_avg_return = sum(momentum_returns) / len(momentum_returns) if momentum_returns else 0

    return {
        "dart_throwing": {
            "total_observations": len(dart_returns),
            "hit_rate": round(dart_hit_rate, 4),
            "avg_return_pct": round(dart_avg_return * 100, 3),
        },
        "momentum_top20_sma_filter": {
            "total_observations": len(momentum_returns),
            "hit_rate": round(mom_hit_rate, 4),
            "avg_return_pct": round(mom_avg_return * 100, 3),
        },
    }


# ── Output formatting ───────────────────────────────────────────────────────


def _print_summary(
    pattern_stats: dict[str, dict],
    combo_stats: dict,
    baseline_stats: dict,
) -> None:
    """Print a formatted summary table to the terminal."""
    baseline_info = pattern_stats.pop("_baseline", {})

    print("\n" + "=" * 90)
    print("  PATTERN BACKTESTER RESULTS")
    print("=" * 90)

    print(f"\n  Total observations: {baseline_info.get('total_observations', 0):,}")
    print(f"  Baseline hit rate (any stock goes up in 5 days): {baseline_info.get('baseline_hit_rate', 0):.1%}")
    print(f"  Baseline avg 5-day return: {baseline_info.get('baseline_avg_return_pct', 0):+.2f}%")

    # Per-pattern table
    print("\n" + "-" * 90)
    print(f"  {'Pattern':<25} {'Fired':>7} {'Hit Rate':>10} {'Edge':>8} {'Avg Ret':>9} {'Avg Win':>9} {'Avg Loss':>10} {'W/L':>6}")
    print("-" * 90)

    sorted_patterns = sorted(
        [(name, s) for name, s in pattern_stats.items()],
        key=lambda x: x[1].get("edge_vs_baseline", 0),
        reverse=True,
    )

    for name, s in sorted_patterns:
        if s["times_fired"] == 0:
            print(f"  {name:<25} {'0':>7} {'--':>10} {'--':>8} {'--':>9} {'--':>9} {'--':>10} {'--':>6}")
            continue

        edge_str = f"{s['edge_vs_baseline']:+.1f}pp"
        print(
            f"  {name:<25} {s['times_fired']:>7,} {s['hit_rate']:>9.1%} {edge_str:>8} "
            f"{s['avg_return']:>+8.2f}% {s['avg_winning_return']:>+8.2f}% "
            f"{s['avg_losing_return']:>+9.2f}% {s['win_loss_ratio']:>6.2f}"
        )

    # Baseline comparison
    print("\n" + "-" * 90)
    print("  BASELINES")
    print("-" * 90)
    dart = baseline_stats.get("dart_throwing", {})
    mom = baseline_stats.get("momentum_top20_sma_filter", {})
    print(f"  {'Dart throwing':<25} {dart.get('total_observations', 0):>7,} {dart.get('hit_rate', 0):>9.1%} {'--':>8} {dart.get('avg_return_pct', 0):>+8.2f}%")
    print(f"  {'Momentum top 20% + SMA':<25} {mom.get('total_observations', 0):>7,} {mom.get('hit_rate', 0):>9.1%} {'--':>8} {mom.get('avg_return_pct', 0):>+8.2f}%")

    # Combo analysis
    two_combos = combo_stats.get("two_pattern_combos", [])
    three_combos = combo_stats.get("three_pattern_combos", [])

    if two_combos:
        print("\n" + "-" * 90)
        print("  BEST 2-PATTERN COMBOS (by edge)")
        print("-" * 90)
        print(f"  {'Patterns':<45} {'Count':>7} {'Hit Rate':>10} {'Edge':>8} {'Avg Ret':>9}")
        for c in two_combos[:10]:
            label = " + ".join(c["patterns"])
            edge_str = f"{c['edge_vs_baseline']:+.1f}pp"
            print(f"  {label:<45} {c['occurrences']:>7,} {c['hit_rate']:>9.1%} {edge_str:>8} {c['avg_return_pct']:>+8.2f}%")

    if three_combos:
        print("\n" + "-" * 90)
        print("  BEST 3-PATTERN COMBOS (by edge)")
        print("-" * 90)
        print(f"  {'Patterns':<55} {'Count':>7} {'Hit Rate':>10} {'Edge':>8}")
        for c in three_combos[:10]:
            label = " + ".join(c["patterns"])
            edge_str = f"{c['edge_vs_baseline']:+.1f}pp"
            print(f"  {label:<55} {c['occurrences']:>7,} {c['hit_rate']:>9.1%} {edge_str:>8}")

    # Verdict
    print("\n" + "=" * 90)
    above_baseline = [name for name, s in sorted_patterns if s["times_fired"] > 0 and s["edge_vs_baseline"] > 2.0]
    below_baseline = [name for name, s in sorted_patterns if s["times_fired"] > 0 and s["edge_vs_baseline"] < -2.0]
    if above_baseline:
        print(f"  KEEP (>2pp edge): {', '.join(above_baseline)}")
    if below_baseline:
        print(f"  DROP (<-2pp edge): {', '.join(below_baseline)}")
    noise = [name for name, s in sorted_patterns if s["times_fired"] > 0 and -2.0 <= s["edge_vs_baseline"] <= 2.0]
    if noise:
        print(f"  NOISE (±2pp):      {', '.join(noise)}")
    print("=" * 90 + "\n")

    pattern_stats["_baseline"] = baseline_info


# ── Main orchestrator ───────────────────────────────────────────────────────


def run_pattern_backtest(
    universe_size: int = DEFAULT_UNIVERSE_SIZE,
    test_days: int = DEFAULT_TEST_DAYS,
    pattern_names: list[str] | None = None,
) -> dict:
    """Run the full pattern backtester and return results dict."""
    start_time = time.time()

    # Load data
    bars_by_symbol, spy_df = _load_universe_data(universe_size)

    if not bars_by_symbol:
        print("[backtester] ERROR: No stock data loaded. Check internet connection.")
        return {}

    # Walk-forward
    print(f"[backtester] Running walk-forward test ({test_days} days, {len(bars_by_symbol)} stocks)...")
    observations = _run_walk_forward(bars_by_symbol, spy_df, test_days, pattern_names)

    if not observations:
        print("[backtester] ERROR: No observations generated.")
        return {}

    print(f"[backtester] Generated {len(observations):,} observations")

    # Compute stats
    print("[backtester] Computing per-pattern statistics...")
    pattern_stats = _compute_pattern_stats(observations, pattern_names)

    print("[backtester] Computing pattern combination analysis...")
    combo_stats = _compute_combo_stats(observations, pattern_names)

    print("[backtester] Computing baseline strategies...")
    baseline_stats = _compute_baseline_stats(bars_by_symbol, test_days)

    duration = time.time() - start_time

    # Build results
    results = {
        "metadata": {
            "run_date": datetime.now(timezone.utc).isoformat(),
            "universe_size": len(bars_by_symbol),
            "test_days": test_days,
            "forward_days": FORWARD_DAYS,
            "total_observations": len(observations),
            "duration_seconds": round(duration, 1),
            "patterns_tested": pattern_names or list(PATTERN_DETECTORS.keys()),
        },
        "per_pattern_stats": pattern_stats,
        "combo_stats": combo_stats,
        "baseline_stats": baseline_stats,
    }

    # Save JSON
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    try:
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"[backtester] Results saved to {RESULTS_FILE}")
    except Exception as exc:
        print(f"[backtester] WARNING: Failed to save results: {exc}")

    # Print summary
    _print_summary(pattern_stats, combo_stats, baseline_stats)

    print(f"[backtester] Completed in {duration:.1f}s")

    return results


# ── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Walk-forward pattern backtester")
    parser.add_argument("--universe", type=int, default=DEFAULT_UNIVERSE_SIZE,
                        help=f"Number of stocks to test (default: {DEFAULT_UNIVERSE_SIZE})")
    parser.add_argument("--test-days", type=int, default=DEFAULT_TEST_DAYS,
                        help=f"Number of trading days to test (default: {DEFAULT_TEST_DAYS})")
    parser.add_argument("--patterns", type=str, default=None,
                        help="Comma-separated pattern names to test (default: all)")
    args = parser.parse_args()

    pattern_names = None
    if args.patterns:
        pattern_names = [p.strip() for p in args.patterns.split(",")]
        invalid = [p for p in pattern_names if p not in PATTERN_DETECTORS]
        if invalid:
            print(f"ERROR: Unknown patterns: {invalid}")
            print(f"Valid patterns: {list(PATTERN_DETECTORS.keys())}")
            sys.exit(1)

    run_pattern_backtest(
        universe_size=args.universe,
        test_days=args.test_days,
        pattern_names=pattern_names,
    )


if __name__ == "__main__":
    main()
