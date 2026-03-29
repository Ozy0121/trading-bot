"""
scanner.py
----------
Multi-strategy scanner orchestrator — scans a watchlist of stocks, scores
each one using parallel bar fetching and a conviction-based composite score,
and returns a ranked candidate list.

Conviction scoring breaks the composite into four weighted sub-scores:
  - Technical (40%): max score from all strategies that evaluated the symbol
  - Volume    (20%): volume ratio mapped to 0-10 scale (2x avg = score 5.0)
  - Sentiment (20%): news sentiment from sentiment_cache (0-10)
  - Sector    (20%): sector ETF 5-day momentum, linearly ranked (0-10)

Only candidates with composite >= CONVICTION_THRESHOLD (7.0) are returned by
best_buy(). Every scan cycle logs all candidates with full score breakdowns.

USE_TOP_MOVERS=true  — fetches Yahoo Finance's top gainers each morning.
USE_TOP_MOVERS=false — uses the fixed SWING_WATCHLIST from config.
"""

from __future__ import annotations

import requests
import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

import config
from indicators import rsi as calc_rsi, macd as calc_macd, bollinger_bands
from logger_setup import get_logger, log_trade_event
from strategies import REGISTRY
from sentiment_cache import get_sentiment_score, get_earnings_penalty
import state as shared_state

log = get_logger()

_YF_INTERVAL = {
    "1Min":  "1m",
    "5Min":  "5m",
    "15Min": "15m",
    "1Hour": "60m",
    "1Day":  "1d",
}

# Top-movers cache (refreshed once per trading day)
_movers_cache: list[str] = []
_movers_date:  date | None = None

# Sector cache: symbol -> (cache_date, sector_string)
_sector_cache: dict[str, tuple[date, str]] = {}

# Sector ETFs for 5-day momentum ranking (SCAN-02, D-11, D-12)
SECTOR_ETFS = ["XLK", "XLE", "XLF", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB"]

SECTOR_ETF_MAP = {
    "Technology":             "XLK",
    "Energy":                 "XLE",
    "Financial Services":     "XLF",
    "Financials":             "XLF",
    "Healthcare":             "XLV",
    "Industrials":            "XLI",
    "Communication Services": "XLC",
    "Consumer Cyclical":      "XLY",
    "Consumer Defensive":     "XLP",
    "Utilities":              "XLU",
    "Real Estate":            "XLRE",
    "Basic Materials":        "XLB",
}


# ── Sector ETF scoring ────────────────────────────────────────────────────────

def _fetch_sector_scores() -> dict[str, float]:
    """
    Compute 5-day % change for each sector ETF and convert to a 0-10 score via
    linear ranking: rank 0 (best performer) -> 10.0, rank N-1 -> 0.0.

    Returns dict mapping ETF symbol to score. Falls back to {etf: 5.0} on error.
    """
    try:
        df = yf.download(
            SECTOR_ETFS,
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
        )

        changes: dict[str, float] = {}
        for etf in SECTOR_ETFS:
            try:
                if etf in df.columns.get_level_values(0):
                    closes = df[etf]["Close"].dropna()
                else:
                    # Single-ticker fallback (when only one ETF is passed)
                    closes = df["Close"].dropna()
                if len(closes) >= 2:
                    pct = (float(closes.iloc[-1]) - float(closes.iloc[0])) / float(closes.iloc[0])
                    changes[etf] = pct
                else:
                    changes[etf] = 0.0
            except Exception:
                changes[etf] = 0.0

        # Rank linearly: highest change -> score 10.0, lowest -> 0.0
        sorted_etfs = sorted(changes.keys(), key=lambda e: changes[e], reverse=True)
        n = len(sorted_etfs)
        scores: dict[str, float] = {}
        for rank, etf in enumerate(sorted_etfs):
            if n == 1:
                scores[etf] = 5.0
            else:
                scores[etf] = round(10.0 - (rank / (n - 1)) * 10.0, 2)

        return scores

    except Exception as exc:
        log.warning("[scanner] Sector ETF fetch failed: %s — defaulting to 5.0", exc)
        return {etf: 5.0 for etf in SECTOR_ETFS}


def _get_stock_sector_score(symbol: str, etf_scores: dict[str, float]) -> float:
    """
    Look up the stock's sector via yfinance (cached per trading day), map it
    to the relevant sector ETF, and return that ETF's score. Defaults to 5.0
    if the sector is unknown or the lookup fails.
    """
    today = date.today()

    # Check sector cache
    cached = _sector_cache.get(symbol)
    if cached is not None:
        cache_date, sector = cached
        if cache_date == today:
            etf = SECTOR_ETF_MAP.get(sector, "")
            return etf_scores.get(etf, 5.0)

    # Fetch sector from yfinance
    try:
        sector = yf.Ticker(symbol).info.get("sector", "") or ""
    except Exception:
        sector = ""

    _sector_cache[symbol] = (today, sector)
    etf = SECTOR_ETF_MAP.get(sector, "")
    return etf_scores.get(etf, 5.0)


# ── Volume scoring ────────────────────────────────────────────────────────────

def _volume_ratio_to_score(vol_ratio: float) -> float:
    """
    Map volume ratio to a 0-10 score (PRED-02).

    Below 2x:  score = min(5.0, (vol_ratio / 2.0) * 4)   — linear up to 4.0
    At/above 2x: score = 5 + min(5.0, (vol_ratio - 2.0) / 3.0 * 5.0)

    2x -> exactly 5.0. 5x -> 10.0. 1x -> 2.0. 0x -> 0.0.
    """
    if vol_ratio < 2.0:
        result = min(5.0, (vol_ratio / 2.0) * 4.0)
    else:
        result = 5.0 + min(5.0, (vol_ratio - 2.0) / 3.0 * 5.0)

    return round(max(0.0, min(10.0, result)), 2)


# ── Top movers fetcher ────────────────────────────────────────────────────────

def fetch_top_movers() -> list[str]:
    """
    Pull today's top gainers from Yahoo Finance (no API key).
    Filters: listed on NYSE/NASDAQ, price $5-$500, volume > 1M.
    Returns up to TOP_MOVERS_COUNT symbols.
    """
    global _movers_cache, _movers_date

    today = date.today()
    if _movers_date == today and _movers_cache:
        log.info("[scanner] Using cached top movers: %s", ", ".join(_movers_cache))
        return _movers_cache

    log.info("[scanner] Fetching top gainers from Yahoo Finance...")

    url = (
        "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
        "?count=50&scrIds=day_gainers&region=US&lang=en-US"
    )
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp   = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data   = resp.json()
        quotes = data["finance"]["result"][0]["quotes"]
    except Exception as exc:
        log.warning("[scanner] Top movers fetch failed: %s. Falling back to watchlist.", exc)
        return config.SWING_WATCHLIST

    symbols = []
    for q in quotes:
        symbol   = q.get("symbol", "")
        price    = q.get("regularMarketPrice", 0)
        volume   = q.get("regularMarketVolume", 0)
        exchange = q.get("exchange", "")
        mkt_cap  = q.get("marketCap", 0)

        if not symbol or "." in symbol:
            continue
        if exchange not in ("NYQ", "NMS", "NGM", "NCM", "PCX", "NYS", "NAS"):
            continue
        if not (config.MIN_PRICE <= price <= config.MAX_PRICE):
            continue
        if volume < config.MIN_VOLUME:
            continue
        if mkt_cap and mkt_cap < 50_000_000:
            continue

        symbols.append(symbol)
        if len(symbols) >= config.TOP_MOVERS_COUNT:
            break

    if symbols:
        # Always include large-cap anchors so we don't miss them
        anchors = ["NVDA", "AMD", "TSLA", "META", "MSFT", "PLTR"]
        for a in anchors:
            if a not in symbols:
                symbols.append(a)
        log.info("[scanner] Watchlist (%d): %s", len(symbols), ", ".join(symbols))
        _movers_cache = symbols
        _movers_date  = today
        return symbols
    else:
        log.warning("[scanner] No movers passed filters. Using fixed watchlist.")
        return config.SWING_WATCHLIST


def get_watchlist() -> list[str]:
    """Return the scan watchlist: top movers (merged with SWING_WATCHLIST) or fixed list."""
    if config.USE_TOP_MOVERS:
        movers = fetch_top_movers()
        # Merge top movers with SWING_WATCHLIST (dedup, movers first)
        seen = set(movers)
        combined = list(movers)
        for sym in config.SWING_WATCHLIST:
            if sym not in seen:
                combined.append(sym)
                seen.add(sym)
        return combined
    return config.SWING_WATCHLIST


# ── Bar data ──────────────────────────────────────────────────────────────────

def fetch_bars_yf(symbol: str) -> pd.DataFrame | None:
    interval = _YF_INTERVAL.get(config.BAR_TIMEFRAME, "5m")
    period   = "5d" if interval in ("1m", "2m", "5m", "15m", "30m") else "60d"

    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
        if df.empty:
            return None

        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].copy().sort_index()

        # Drop last forming bar
        if len(df) > 1:
            df = df.iloc[:-1]

        return df
    except Exception as exc:
        log.warning("[scanner] yfinance failed for %s: %s", symbol, exc)
        return None


# ── Per-symbol multi-strategy scoring ────────────────────────────────────────

def _score_symbol_multi(
    symbol: str,
    etf_scores: dict[str, float],
    catalysts: dict | None = None,
) -> dict | None:
    """
    Fetch bars, run all strategies from REGISTRY, and return a scored dict with
    conviction breakdown. Returns None if insufficient data.

    Backward-compatible keys are preserved for bot.py compatibility:
    symbol, price, signal, raw_signal, score, rsi, volume_ratio,
    bb_upper, bb_lower, macd_hist, df, strategy, conviction (new: breakdown dict).
    """
    df = fetch_bars_yf(symbol)
    if df is None or len(df) < max(config.LONG_WINDOW + 2, 22):
        return None

    closes = df["close"]
    price  = float(closes.iloc[-1])

    # ── Volume ratio (vs 20-bar avg) ───────────────────────────────────────
    vol_series   = df["volume"]
    avg_vol      = float(vol_series.tail(20).mean()) if len(vol_series) >= 20 else float(vol_series.mean())
    curr_vol     = float(vol_series.iloc[-1])
    volume_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0

    # ── Technical indicators (for backward compat keys) ────────────────────
    rsi_s   = calc_rsi(closes)
    rsi_val = float(rsi_s.dropna().iloc[-1]) if len(rsi_s.dropna()) > 0 else 50.0

    _, _, hist = calc_macd(closes)
    macd_hist  = float(hist.dropna().iloc[-1]) if len(hist.dropna()) > 0 else 0.0

    bb_u_s, _, bb_l_s = bollinger_bands(closes)
    bb_upper = float(bb_u_s.dropna().iloc[-1]) if len(bb_u_s.dropna()) > 0 else None
    bb_lower = float(bb_l_s.dropna().iloc[-1]) if len(bb_l_s.dropna()) > 0 else None

    # ── Run all strategies ──────────────────────────────────────────────────
    strategy_results: list[dict] = []
    for strat_name, strat_fn in REGISTRY.items():
        try:
            if strat_name == "catalyst":
                result = strat_fn(symbol, df, catalysts=catalysts)
            else:
                result = strat_fn(symbol, df)
            result["_name"] = strat_name
            strategy_results.append(result)
        except Exception as exc:
            log.warning("[scanner] Strategy %s failed for %s: %s", strat_name, symbol, exc)

    # ── Technical sub-score: max fired score; partial credit if none fired ─
    fired_results = [r for r in strategy_results if r.get("fired")]
    strategies_fired = [r["_name"] for r in fired_results]

    if fired_results:
        technical_score = max(r.get("technical_score", 0.0) for r in fired_results)
        best_result     = max(fired_results, key=lambda r: r.get("technical_score", 0.0))
        best_strategy   = best_result["_name"]
        raw_signal      = "BUY"
    else:
        # Partial credit: max technical_score * 0.5 across all strategies
        all_scores = [r.get("technical_score", 0.0) for r in strategy_results]
        technical_score = max(all_scores) * 0.5 if all_scores else 0.0
        best_strategy   = strategy_results[0]["_name"] if strategy_results else "none"
        raw_signal      = "HOLD"

    # ── Volume sub-score ───────────────────────────────────────────────────
    all_vol_ratios = [r.get("volume_ratio", volume_ratio) for r in strategy_results]
    best_vol_ratio = max(all_vol_ratios) if all_vol_ratios else volume_ratio
    volume_score   = _volume_ratio_to_score(best_vol_ratio)

    # ── Sentiment sub-score ────────────────────────────────────────────────
    sentiment_score = get_sentiment_score(symbol)

    # ── Sector sub-score ───────────────────────────────────────────────────
    sector_score = _get_stock_sector_score(symbol, etf_scores)

    # ── Composite conviction score (D-03) ──────────────────────────────────
    composite = (
        config.CONVICTION_WEIGHT_TECHNICAL * technical_score
        + config.CONVICTION_WEIGHT_VOLUME    * volume_score
        + config.CONVICTION_WEIGHT_SENTIMENT * sentiment_score
        + config.CONVICTION_WEIGHT_SECTOR    * sector_score
    )

    # ── Earnings penalty (D-10) ────────────────────────────────────────────
    earnings_penalty = get_earnings_penalty(symbol)
    composite = max(0.0, composite - earnings_penalty)
    composite = round(composite, 2)

    # ── Conviction breakdown dict (D-05) ───────────────────────────────────
    conviction = {
        "technical":       round(technical_score, 2),
        "volume":          round(volume_score, 2),
        "sentiment":       round(sentiment_score, 2),
        "sector":          round(sector_score, 2),
        "composite":       composite,
        "strategies_fired": strategies_fired,
        "earnings_penalty": round(earnings_penalty, 2),
    }

    # Effective signal: BUY only if a strategy fired AND composite >= threshold
    signal = (
        "BUY"
        if raw_signal == "BUY" and composite >= config.CONVICTION_THRESHOLD
        else "HOLD"
    )

    return {
        "symbol":       symbol,
        "price":        round(price, 4),
        "signal":       signal,
        "raw_signal":   raw_signal,
        "score":        composite,
        "rsi":          round(rsi_val, 1),
        "volume_ratio": round(volume_ratio, 2),
        "bb_upper":     round(bb_upper, 4) if bb_upper is not None else None,
        "bb_lower":     round(bb_lower, 4) if bb_lower is not None else None,
        "macd_hist":    round(macd_hist, 4),
        "conviction":   conviction,
        "strategy":     best_strategy,
        "df":           df,
    }


# ── Scan result logging ───────────────────────────────────────────────────────

def _log_scan_results(results: list[dict]) -> None:
    """Log all scan results with full score breakdowns. (PRED-05, D-16)"""
    threshold = config.CONVICTION_THRESHOLD
    above = [r for r in results if r["conviction"]["composite"] >= threshold]

    log.info(
        "[scanner] Scan complete: %d candidates, %d above %.1f threshold",
        len(results), len(above), threshold,
    )

    top5 = results[:5]
    for r in top5:
        conv = r["conviction"]
        fired_str = "+".join(conv["strategies_fired"]) or "none"
        marker    = "**ABOVE THRESHOLD**" if conv["composite"] >= threshold else "below"
        log.info(
            "[scanner] %s: composite=%.1f/10 [tech=%.1f vol=%.1f sent=%.1f sec=%.1f] "
            "strategies=%s %s",
            r["symbol"], conv["composite"],
            conv["technical"], conv["volume"], conv["sentiment"], conv["sector"],
            fired_str, marker,
        )

    for r in results[5:]:
        conv = r["conviction"]
        log.debug(
            "[scanner] %s: composite=%.1f/10 [tech=%.1f vol=%.1f sent=%.1f sec=%.1f]",
            r["symbol"], conv["composite"],
            conv["technical"], conv["volume"], conv["sentiment"], conv["sector"],
        )

    # Structured trade event for candidates passing threshold
    for r in above:
        log_trade_event(
            log, "SCAN_CANDIDATE",
            symbol=r["symbol"],
            composite=r["conviction"]["composite"],
            strategies="+".join(r["conviction"]["strategies_fired"]),
        )


# ── Public interface ──────────────────────────────────────────────────────────

def scan(watchlist: list[str], catalysts: dict | None = None) -> list[dict]:
    """
    Multi-strategy scan of all symbols. Returns results sorted by composite
    conviction score descending. (STRAT-06, SCAN-01, SCAN-05)
    """
    log.info("[scanner] Multi-strategy scan: %d symbols", len(watchlist))

    # Pre-fetch sector ETF scores once for the whole scan
    etf_scores = _fetch_sector_scores()

    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_sym = {
            executor.submit(_score_symbol_multi, sym, etf_scores, catalysts): sym
            for sym in watchlist
        }
        for future in as_completed(future_to_sym):
            sym = future_to_sym[future]
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except Exception as exc:
                log.warning("[scanner] Failed to score %s: %s", sym, exc)

    # Sort by composite conviction descending
    results.sort(key=lambda r: r["conviction"]["composite"], reverse=True)

    _log_scan_results(results)

    # Update shared state (strip df to avoid serialization issues — Pitfall 7)
    state_results = [{k: v for k, v in r.items() if k != "df"} for r in results]
    shared_state.update(
        scan_results=state_results,
        last_scan_time=datetime.now(timezone.utc).isoformat(),
        scan_conviction_scores={r["symbol"]: r["conviction"]["composite"] for r in results},
    )

    return results


def best_buy(results: list[dict]) -> dict | None:
    """
    Return the highest-conviction BUY candidate that clears CONVICTION_THRESHOLD.
    Logs skipped candidates at INFO level with full score breakdown. (PRED-04, PRED-05)
    """
    threshold = config.CONVICTION_THRESHOLD

    for r in results:
        conv = r.get("conviction", {})
        composite = conv.get("composite", 0.0)

        if composite >= threshold:
            log.info(
                "[scanner] Best candidate: %s (conviction: %.1f/10 — "
                "tech:%.1f vol:%.1f sent:%.1f sec:%.1f)",
                r["symbol"], composite,
                conv.get("technical", 0), conv.get("volume", 0),
                conv.get("sentiment", 0), conv.get("sector", 0),
            )
            return r

        # Log skipped candidate with full breakdown
        log.info(
            "[scanner] Skipped %s (%.1f/10): technical=%.1f, volume=%.1f, "
            "sentiment=%.1f, sector=%.1f — composite below %.1f threshold",
            r["symbol"], composite,
            conv.get("technical", 0), conv.get("volume", 0),
            conv.get("sentiment", 0), conv.get("sector", 0),
            threshold,
        )

    return None
