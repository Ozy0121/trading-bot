"""
scanner.py
----------
Scans a watchlist of stocks, scores each one, and returns ranked results.

USE_TOP_MOVERS=true  — fetches Yahoo Finance's top gainers each morning.
USE_TOP_MOVERS=false — uses the fixed WATCHLIST from .env.

Scoring requires ALL FOUR of:
  1. SMA crossover BUY signal
  2. RSI < MAX_RSI_BUY (not overbought)
  3. Volume ratio >= MIN_VOLUME_RATIO (at least 2x average volume)
  4. MACD histogram > 0 (momentum confirming direction)

Catalyst bonuses (ARK buying, analyst upgrade) add to the score but
cannot override a missing condition — they only break ties.
"""

from __future__ import annotations

import requests
import yfinance as yf
import pandas as pd
from datetime import date

import config
from indicators import rsi as calc_rsi, macd as calc_macd, bollinger_bands
from logger_setup import get_logger

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


# ── Top movers fetcher ────────────────────────────────────────────────────────

def fetch_top_movers() -> list[str]:
    """
    Pull today's top gainers from Yahoo Finance (no API key).
    Filters: listed on NYSE/NASDAQ, price $5–$500, volume > 1M.
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
        return config.WATCHLIST

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
        return config.WATCHLIST


def get_watchlist() -> list[str]:
    if config.USE_TOP_MOVERS:
        return fetch_top_movers()
    return config.WATCHLIST


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


# ── Per-symbol scoring ────────────────────────────────────────────────────────

def _score_symbol(symbol: str, catalysts: dict | None = None) -> dict | None:
    """
    Fetch bars, compute all signals and indicators, and return a scored dict.
    Returns None if there's insufficient data.

    High-conviction filter: ALL FOUR must be true for a BUY score > 0:
      1. SMA crossover signals BUY
      2. RSI < MAX_RSI_BUY
      3. Volume ratio >= MIN_VOLUME_RATIO
      4. MACD histogram > 0
    """
    df = fetch_bars_yf(symbol)
    if df is None or len(df) < max(config.LONG_WINDOW + 2, 22):
        return None

    closes = df["close"]
    price  = float(closes.iloc[-1])

    # ── SMA crossover ──────────────────────────────────────────────────────
    short_sma = closes.rolling(config.SHORT_WINDOW).mean()
    long_sma  = closes.rolling(config.LONG_WINDOW).mean()
    prev_short, curr_short = float(short_sma.iloc[-2]), float(short_sma.iloc[-1])
    prev_long,  curr_long  = float(long_sma.iloc[-2]),  float(long_sma.iloc[-1])

    if prev_short <= prev_long and curr_short > curr_long:
        raw_signal = "BUY"
    elif prev_short >= prev_long and curr_short < curr_long:
        raw_signal = "SELL"
    else:
        raw_signal = "HOLD"

    # ── RSI ────────────────────────────────────────────────────────────────
    rsi_s   = calc_rsi(closes)
    rsi_val = float(rsi_s.dropna().iloc[-1]) if len(rsi_s.dropna()) > 0 else 50.0

    # ── MACD ───────────────────────────────────────────────────────────────
    _, _, hist = calc_macd(closes)
    macd_hist  = float(hist.dropna().iloc[-1]) if len(hist.dropna()) > 0 else 0.0

    # ── Bollinger Bands ────────────────────────────────────────────────────
    bb_u_s, _, bb_l_s = bollinger_bands(closes)
    bb_upper = float(bb_u_s.dropna().iloc[-1]) if len(bb_u_s.dropna()) > 0 else None
    bb_lower = float(bb_l_s.dropna().iloc[-1]) if len(bb_l_s.dropna()) > 0 else None

    # ── Volume ratio (vs 20-bar average) ───────────────────────────────────
    vol_series  = df["volume"]
    avg_vol     = float(vol_series.tail(20).mean()) if len(vol_series) >= 20 else float(vol_series.mean())
    curr_vol    = float(vol_series.iloc[-1])
    volume_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0

    # ── Day change % ───────────────────────────────────────────────────────
    open_price = float(df["open"].iloc[0])
    change_pct = ((price - open_price) / open_price * 100) if open_price > 0 else 0.0

    # ── High-conviction filter for BUY ─────────────────────────────────────
    # All four conditions must be true:
    conviction_conditions = {
        "sma_buy":      raw_signal == "BUY",
        "rsi_ok":       rsi_val < config.MAX_RSI_BUY,
        "volume_spike": volume_ratio >= config.MIN_VOLUME_RATIO,
        "macd_pos":     macd_hist > 0,
    }
    all_conditions_met = all(conviction_conditions.values())

    # Effective signal: only BUY if high-conviction, otherwise HOLD
    signal = raw_signal if raw_signal != "BUY" else ("BUY" if all_conditions_met else "HOLD")

    failed = [k for k, v in conviction_conditions.items() if not v] if raw_signal == "BUY" and not all_conditions_met else []
    if failed:
        log.debug("[scanner] %s raw=BUY but failed: %s", symbol, failed)

    # ── Scoring ────────────────────────────────────────────────────────────
    score = 0.0
    if signal == "BUY":
        score += 100
        score += max(0, config.MAX_RSI_BUY - rsi_val)   # lower RSI = more room
        score += macd_hist * 20                           # stronger momentum
        score += min(volume_ratio - 2.0, 5.0) * 10       # volume intensity (capped)

        # Catalyst bonuses (ARK + upgrade)
        cat = (catalysts or {}).get(symbol, {})
        if cat.get("ark_buying"):
            score += 40
            log.info("[scanner] %s: ARK buying (+40 score)", symbol)
        if cat.get("analyst_upgrade"):
            score += 30
            log.info("[scanner] %s: Analyst upgrade (+30 score)", symbol)

    return {
        "symbol":       symbol,
        "signal":       signal,
        "raw_signal":   raw_signal,
        "price":        round(price, 4),
        "change_pct":   round(change_pct, 2),
        "short_sma":    round(curr_short, 4),
        "long_sma":     round(curr_long,  4),
        "rsi":          round(rsi_val, 1),
        "macd_hist":    round(macd_hist, 4),
        "bb_upper":     round(bb_upper, 4) if bb_upper else None,
        "bb_lower":     round(bb_lower, 4) if bb_lower else None,
        "volume_ratio": round(volume_ratio, 2),
        "avg_volume":   int(avg_vol),
        "curr_volume":  int(curr_vol),
        "score":        round(score, 2),
        "conviction":   conviction_conditions,
        "df":           df,
    }


# ── Public interface ──────────────────────────────────────────────────────────

def scan(watchlist: list[str], catalysts: dict | None = None) -> list[dict]:
    """Scan all symbols. Returns results sorted by score (best BUY first)."""
    log.info("[scanner] Scanning %d symbols: %s", len(watchlist), ", ".join(watchlist))
    results = []

    for symbol in watchlist:
        result = _score_symbol(symbol, catalysts=catalysts)
        if result:
            results.append(result)
            log.debug("[scanner] %s | %s (raw:%s) | price=%.2f rsi=%.1f vol_ratio=%.1f score=%.1f",
                      symbol, result["signal"], result["raw_signal"],
                      result["price"], result["rsi"], result["volume_ratio"], result["score"])

    results.sort(key=lambda r: r["score"], reverse=True)
    log.info("[scanner] Signals: %s",
             " | ".join(f"{r['symbol']}:{r['signal']}(vol:{r['volume_ratio']:.1f}x)"
                        for r in results))
    return results


def best_buy(results: list[dict]) -> dict | None:
    """Return top-scoring BUY candidate (already filtered for conviction)."""
    candidates = [r for r in results if r["signal"] == "BUY"]
    return candidates[0] if candidates else None
