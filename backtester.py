"""
backtester.py
-------------
Strategy backtester — runs each strategy against historical data to measure
whether it actually works. Tests momentum, mean reversion, accumulation, and
the prediction engine against 6-12 months of daily bars.

For each signal a strategy would have fired, checks:
  - Did the stock go up 1, 2, 3 days later?
  - What was the max gain / max drawdown in the 3-day window?
  - Would a 3% stop loss have been hit before the target?

Produces a per-strategy report card:
  - Win rate, avg win, avg loss, expectancy
  - Best/worst performers
  - Signal frequency (how often it fires)
  - Comparison across strategies

Catalyst strategy is excluded from backtesting because it depends on
external API data (ARK buys, analyst upgrades) that isn't available historically.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from openbb_data import fetch_bars
from indicators import rsi as calc_rsi
from strategies.momentum import scan as momentum_scan
from strategies.mean_reversion import scan as mean_reversion_scan
from strategies.accumulation import scan as accumulation_scan
from logger_setup import get_logger

log = get_logger()

# ── Config ──────────────────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BACKTEST_FILE = os.path.join(DATA_DIR, "backtest_results.json")

LOOKBACK_PERIOD = "1y"     # how far back to test
FORWARD_DAYS = 3           # check returns over 1-3 days after signal
SMART_EXIT_WINDOW = 5      # prediction_v2 uses wider window for smart exit
STOP_LOSS_PCT = 0.05       # 5% stop loss — mean reversion needs room to breathe
TARGET_PCT = 0.06          # 6% take profit
WIN_THRESHOLD = 0.01       # 1%+ gain = "win"

# Stocks to backtest against (mix of styles)
BACKTEST_UNIVERSE = [
    # Large cap tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    # Growth / volatile
    "SOFI", "PLTR", "RIVN", "SNAP", "ROKU", "COIN", "MARA",
    # Mid-cap momentum
    "CRWD", "DDOG", "NET", "SHOP", "SQ", "ENPH",
    # Value / mean reversion
    "BAC", "F", "T", "INTC", "PFE", "WBA",
    # ETFs for baseline
    "SPY", "QQQ",
]

# How many bars we need before we can start testing
MIN_WARMUP_BARS = 35

_backtest_lock = threading.Lock()
_last_result: dict | None = None


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class SignalResult:
    """One signal fired by a strategy on a specific day."""
    symbol: str
    signal_date: str
    entry_price: float
    day1_return: float       # % return after 1 day
    day2_return: float       # % return after 2 days
    day3_return: float       # % return after 3 days
    max_gain_pct: float      # max intra-period gain
    max_drawdown_pct: float  # max intra-period drawdown
    hit_target: bool
    hit_stop: bool
    is_win: bool             # day3_return > WIN_THRESHOLD
    smart_exit_day: int = 0        # which day the smart exit triggered (0 = N/A)
    smart_exit_return: float = 0.0 # return at smart exit point


@dataclass
class StrategyReport:
    """Backtest report for one strategy."""
    strategy: str
    total_signals: int
    wins: int
    losses: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    expectancy: float        # avg win * win_rate - avg loss * loss_rate
    avg_day1: float
    avg_day3: float
    hit_target_pct: float
    hit_stop_pct: float
    best_signal: dict | None
    worst_signal: dict | None
    signals_per_stock: float  # avg signals per stock tested
    verdict: str             # "RELIABLE", "MARGINAL", "UNRELIABLE"
    issues: list[str] = field(default_factory=list)


# ── Core backtest logic ─────────────────────────────────────────────────────

def _find_smart_exit(df: pd.DataFrame, entry_idx: int, entry_price: float,
                     window: int = SMART_EXIT_WINDOW) -> tuple[int, float]:
    """Find best exit within window: first profitable up-close, RSI(2)>65, or best close."""
    closes = df["close"]
    n = len(df)
    max_fwd = min(window, n - entry_idx - 1)
    best_day = max_fwd
    best_ret = (float(closes.iloc[entry_idx + max_fwd]) - entry_price) / entry_price * 100

    for d in range(1, max_fwd + 1):
        idx = entry_idx + d
        cur_close = float(closes.iloc[idx])
        prev_close = float(closes.iloc[idx - 1])
        ret = (cur_close - entry_price) / entry_price * 100

        if ret > best_ret:
            best_day = d
            best_ret = ret

        if cur_close > prev_close and ret > WIN_THRESHOLD:
            return d, ret

        if idx >= entry_idx + 2:
            rsi2 = calc_rsi(closes.iloc[:idx + 1], period=2)
            rsi_val = float(rsi2.iloc[-1]) if not pd.isna(rsi2.iloc[-1]) else 0
            if rsi_val > 65:
                return d, ret

    return best_day, best_ret


def _backtest_strategy_on_stock(
    strategy_name: str,
    strategy_fn: callable,
    symbol: str,
    df: pd.DataFrame,
) -> list[SignalResult]:
    """
    Walk through historical data day by day. On each day, give the strategy
    only the data up to that point. If it fires, record forward returns.
    """
    results = []
    closes = df["close"]
    highs = df["high"]
    lows = df["low"]
    n = len(df)
    use_smart_exit = strategy_name == "prediction_v2"
    fwd_days = SMART_EXIT_WINDOW if use_smart_exit else FORWARD_DAYS

    for i in range(MIN_WARMUP_BARS, n - fwd_days):
        window = df.iloc[:i + 1].copy()

        try:
            result = strategy_fn(symbol, window)
        except Exception:
            continue

        if not result.get("fired"):
            continue

        entry_price = float(closes.iloc[i])
        if entry_price <= 0:
            continue

        # Forward returns (always compute day 1-3 for reporting)
        actual_fwd = min(FORWARD_DAYS, n - i - 1)
        fwd_closes = [float(closes.iloc[i + d]) for d in range(1, actual_fwd + 1)]
        fwd_highs = [float(highs.iloc[i + d]) for d in range(1, min(fwd_days, n - i - 1) + 1)]
        fwd_lows = [float(lows.iloc[i + d]) for d in range(1, min(fwd_days, n - i - 1) + 1)]

        day_returns = [(c - entry_price) / entry_price * 100 for c in fwd_closes]
        while len(day_returns) < 3:
            day_returns.append(day_returns[-1] if day_returns else 0.0)

        max_gain = (max(fwd_highs) - entry_price) / entry_price * 100 if fwd_highs else 0
        max_dd = (min(fwd_lows) - entry_price) / entry_price * 100 if fwd_lows else 0

        hit_target = max(fwd_highs) >= entry_price * (1 + TARGET_PCT) if fwd_highs else False
        hit_stop = min(fwd_lows) <= entry_price * (1 - STOP_LOSS_PCT) if fwd_lows else False

        signal_date = str(df.index[i].date()) if hasattr(df.index[i], 'date') else str(df.index[i])

        smart_day = 0
        smart_ret = 0.0
        if use_smart_exit:
            smart_day, smart_ret = _find_smart_exit(df, i, entry_price)
            is_win = smart_ret > WIN_THRESHOLD
        else:
            is_win = day_returns[2] > WIN_THRESHOLD

        results.append(SignalResult(
            symbol=symbol,
            signal_date=signal_date,
            entry_price=round(entry_price, 2),
            day1_return=round(day_returns[0], 2),
            day2_return=round(day_returns[1], 2),
            day3_return=round(day_returns[2], 2),
            max_gain_pct=round(max_gain, 2),
            max_drawdown_pct=round(max_dd, 2),
            hit_target=hit_target,
            hit_stop=hit_stop,
            is_win=is_win,
            smart_exit_day=smart_day,
            smart_exit_return=round(smart_ret, 2),
        ))

    return results


def _fetch_stock_data(symbol: str) -> pd.DataFrame | None:
    """Fetch 1 year of daily data for backtesting."""
    try:
        df = fetch_bars(symbol, period=LOOKBACK_PERIOD, interval="1d")
        if df is None or df.empty or len(df) < MIN_WARMUP_BARS + FORWARD_DAYS + 10:
            return None
        # fetch_bars already returns lowercase columns and sorted index
        df = df[["open", "high", "low", "close", "volume"]].copy()
        return df
    except Exception as exc:
        log.debug("[backtest] Failed to fetch %s: %s", symbol, exc)
        return None


def _build_report(strategy_name: str, all_signals: list[SignalResult],
                  stocks_tested: int) -> StrategyReport:
    """Compute strategy stats from all signals."""
    total = len(all_signals)
    if total == 0:
        return StrategyReport(
            strategy=strategy_name, total_signals=0, wins=0, losses=0,
            win_rate=0, avg_win_pct=0, avg_loss_pct=0, expectancy=0,
            avg_day1=0, avg_day3=0, hit_target_pct=0, hit_stop_pct=0,
            best_signal=None, worst_signal=None,
            signals_per_stock=0, verdict="NO DATA", issues=["No signals fired"],
        )

    wins = [s for s in all_signals if s.is_win]
    losses = [s for s in all_signals if not s.is_win]
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = win_count / total * 100

    has_smart = any(s.smart_exit_day > 0 for s in all_signals)
    def _ret(s):
        return s.smart_exit_return if has_smart and s.smart_exit_day > 0 else s.day3_return

    avg_win = sum(_ret(s) for s in wins) / len(wins) if wins else 0
    avg_loss = sum(_ret(s) for s in losses) / len(losses) if losses else 0

    # Expectancy: expected value per trade
    expectancy = (win_rate / 100 * avg_win) + ((100 - win_rate) / 100 * avg_loss)

    avg_day1 = sum(s.day1_return for s in all_signals) / total
    avg_day3 = sum(s.day3_return for s in all_signals) / total
    hit_target = sum(1 for s in all_signals if s.hit_target) / total * 100
    hit_stop = sum(1 for s in all_signals if s.hit_stop) / total * 100

    # Best/worst by day3 return
    best = max(all_signals, key=lambda s: s.day3_return)
    worst = min(all_signals, key=lambda s: s.day3_return)

    # Verdict
    issues = []
    if win_rate < 45:
        issues.append(f"Low win rate: {win_rate:.0f}% (need >45%)")
    if expectancy < 0:
        issues.append(f"Negative expectancy: {expectancy:.2f}% per trade")
    if hit_stop > 40:
        issues.append(f"Stop loss hit too often: {hit_stop:.0f}% of trades")
    if avg_day3 < 0:
        issues.append(f"Average 3-day return is negative: {avg_day3:.2f}%")
    if total < 20:
        issues.append(f"Low sample size: only {total} signals")

    if expectancy >= 0.5 and win_rate >= 50:
        verdict = "RELIABLE"
    elif expectancy >= 0 and win_rate >= 40:
        verdict = "MARGINAL"
    else:
        verdict = "UNRELIABLE"

    return StrategyReport(
        strategy=strategy_name,
        total_signals=total,
        wins=win_count,
        losses=loss_count,
        win_rate=round(win_rate, 1),
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        expectancy=round(expectancy, 2),
        avg_day1=round(avg_day1, 2),
        avg_day3=round(avg_day3, 2),
        hit_target_pct=round(hit_target, 1),
        hit_stop_pct=round(hit_stop, 1),
        best_signal=asdict(best),
        worst_signal=asdict(worst),
        signals_per_stock=round(total / max(1, stocks_tested), 1),
        verdict=verdict,
        issues=issues,
    )


# ── Main entry point ───────────────────────────────────────────────────────

def _prediction_signal(symbol: str, window: pd.DataFrame) -> dict:
    """Adapter: wraps prediction.predict() into the backtester's strategy interface."""
    from prediction import predict
    result = predict(symbol, window)
    if result is not None and result.predicted_spike:
        return {
            "fired": True,
            "confidence": result.confidence,
            "stage": result.stage,
            "patterns": [p.name for p in result.patterns if p.detected],
        }
    return {"fired": False}


STRATEGIES = {
    "momentum": momentum_scan,
    "mean_reversion": mean_reversion_scan,
    "accumulation": accumulation_scan,
    "prediction_v2": _prediction_signal,
}


def run_backtest(symbols: list[str] | None = None,
                 progress_cb: callable | None = None) -> dict:
    """
    Run full backtest of all strategies against the backtest universe.
    Returns comprehensive report dict.
    """
    global _last_result

    symbols = symbols or BACKTEST_UNIVERSE
    log.info("[backtest] Starting backtest: %d strategies x %d stocks...",
             len(STRATEGIES), len(symbols))

    start_time = datetime.now(timezone.utc)

    # Fetch all stock data in parallel
    stock_data: dict[str, pd.DataFrame] = {}
    fetch_done = 0
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_sym = {executor.submit(_fetch_stock_data, sym): sym for sym in symbols}
        for future in as_completed(future_to_sym):
            sym = future_to_sym[future]
            fetch_done += 1
            if progress_cb:
                progress_cb(fetch_done, len(symbols), f"Fetching data: {fetch_done}/{len(symbols)}...")
            try:
                df = future.result()
                if df is not None:
                    stock_data[sym] = df
            except Exception:
                pass

    log.info("[backtest] Fetched data for %d/%d stocks", len(stock_data), len(symbols))

    # Run each strategy against all stocks
    strategy_reports: dict[str, StrategyReport] = {}
    total_tests = len(STRATEGIES) * len(stock_data)
    test_done = 0

    for strat_name, strat_fn in STRATEGIES.items():
        log.info("[backtest] Testing strategy: %s", strat_name)
        all_signals: list[SignalResult] = []

        for sym, df in stock_data.items():
            signals = _backtest_strategy_on_stock(strat_name, strat_fn, sym, df)
            all_signals.extend(signals)
            test_done += 1
            if progress_cb:
                progress_cb(test_done, total_tests, f"Backtesting {strat_name}: {sym}...")

        report = _build_report(strat_name, all_signals, len(stock_data))
        strategy_reports[strat_name] = report

        # Log results
        if report.verdict == "RELIABLE":
            log.info(
                "[backtest] RELIABLE: %s — %d signals, %.0f%% win rate, "
                "+%.2f%% expectancy, avg 3-day: %+.2f%%",
                strat_name, report.total_signals, report.win_rate,
                report.expectancy, report.avg_day3,
            )
        elif report.verdict == "MARGINAL":
            log.warning(
                "[backtest] MARGINAL: %s — %d signals, %.0f%% win rate, "
                "%+.2f%% expectancy | Issues: %s",
                strat_name, report.total_signals, report.win_rate,
                report.expectancy, "; ".join(report.issues),
            )
        else:
            log.warning(
                "[backtest] UNRELIABLE: %s — %d signals, %.0f%% win rate, "
                "%+.2f%% expectancy | Issues: %s",
                strat_name, report.total_signals, report.win_rate,
                report.expectancy, "; ".join(report.issues),
            )

    # Build overall result
    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()

    # Rank strategies
    ranked = sorted(
        strategy_reports.values(),
        key=lambda r: r.expectancy,
        reverse=True,
    )

    result = {
        "backtest_date": date.today().isoformat(),
        "backtest_time": end_time.isoformat(),
        "duration_seconds": round(duration, 1),
        "stocks_tested": len(stock_data),
        "period": LOOKBACK_PERIOD,
        "strategies": {name: asdict(r) for name, r in strategy_reports.items()},
        "ranking": [{"strategy": r.strategy, "expectancy": r.expectancy,
                      "win_rate": r.win_rate, "verdict": r.verdict}
                     for r in ranked],
        "recommendation": _build_recommendation(ranked),
    }

    # Save to disk
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(BACKTEST_FILE, "w") as f:
            json.dump(result, f, indent=2, default=str)
        log.info("[backtest] Results saved to %s", BACKTEST_FILE)
    except Exception as exc:
        log.error("[backtest] Failed to save results: %s", exc)

    with _backtest_lock:
        _last_result = result

    log.info(
        "[backtest] Complete in %.0fs: %s",
        duration,
        " > ".join(f"{r.strategy}({r.verdict})" for r in ranked),
    )

    return result


def _build_recommendation(ranked: list[StrategyReport]) -> str:
    """Build a plain-English recommendation based on backtest results."""
    reliable = [r for r in ranked if r.verdict == "RELIABLE"]
    marginal = [r for r in ranked if r.verdict == "MARGINAL"]
    unreliable = [r for r in ranked if r.verdict == "UNRELIABLE"]

    parts = []
    if reliable:
        names = ", ".join(r.strategy for r in reliable)
        parts.append(f"Trust: {names} — these strategies have positive expectancy and >50% win rates.")
    if marginal:
        names = ", ".join(r.strategy for r in marginal)
        parts.append(f"Use with caution: {names} — breakeven or slightly positive, need more confirmation before trading.")
    if unreliable:
        names = ", ".join(r.strategy for r in unreliable)
        parts.append(f"Avoid or fix: {names} — negative expectancy, losing money over time.")

    if not reliable and not marginal:
        parts.append("WARNING: No strategies are currently reliable. Consider adjusting parameters or adding new strategies.")

    return " ".join(parts)


def get_latest_backtest() -> dict | None:
    """Load the most recent backtest results."""
    global _last_result

    with _backtest_lock:
        if _last_result is not None:
            return _last_result

    try:
        with open(BACKTEST_FILE, "r") as f:
            result = json.load(f)
        with _backtest_lock:
            _last_result = result
        return result
    except (FileNotFoundError, json.JSONDecodeError):
        return None
