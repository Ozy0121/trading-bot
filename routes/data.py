"""
routes/data.py
--------------
Flask Blueprint for core data routes: index page, state snapshot, SSE stream,
health check, quote, bars, agent status.
"""

import json
import math
import time

from flask import Blueprint, Response, jsonify, render_template, request, stream_with_context

import config
import progress
import state as shared_state
from logger_setup import get_logger

log = get_logger()
data_bp = Blueprint("data", __name__)


def _snap_json(obj):
    return json.dumps(obj, default=str)


# ── Core routes ──────────────────────────────────────────────────────────────

@data_bp.route("/")
def index():
    return render_template("index.html")


@data_bp.route("/api/state")
def api_state():
    return jsonify(shared_state.snapshot())


@data_bp.route("/api/stream")
def api_stream():
    """SSE: pushes full state + progress every second."""
    def generate():
        try:
            while True:
                from dashboard import _coordinator   # re-read each tick
                snap = shared_state.snapshot()
                snap["_progress"] = progress.snapshot()
                snap["_scan_logs"] = progress.get_logs()
                if _coordinator:
                    snap["_agents"] = _coordinator.get_agents_status()
                yield f"data: {_snap_json(snap)}\n\n"
                time.sleep(1)
        except GeneratorExit:
            pass
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


@data_bp.route("/api/health")
def api_health():
    """System health: API call counts, cache hit rates, last refresh times."""
    from openbb_data import get_api_stats
    stats = get_api_stats()
    total_polygon = stats.get("polygon_calls", 0) + stats.get("polygon_cache_hits", 0)
    cache_rate = (stats["polygon_cache_hits"] / total_polygon * 100) if total_polygon > 0 else 0.0
    return jsonify({
        "polygon_api_calls": stats.get("polygon_calls", 0),
        "polygon_cache_hits": stats.get("polygon_cache_hits", 0),
        "polygon_cache_rate_pct": round(cache_rate, 1),
        "yfinance_calls": stats.get("yfinance_calls", 0),
        "fmp_calls": stats.get("fmp_calls", 0),
        "last_polygon_refresh": stats.get("last_polygon_refresh"),
        "last_yfinance_call": stats.get("last_yfinance_call"),
        "last_fmp_call": stats.get("last_fmp_call"),
    })


# ── Market data routes ───────────────────────────────────────────────────────

@data_bp.route("/api/quote/<symbol>")
def api_quote(symbol):
    """Latest bid/ask for a symbol."""
    from dashboard import _data_client
    symbol = symbol.upper().strip()
    if _data_client is None:
        return jsonify({"symbol": symbol, "bid": None, "ask": None,
                        "spread": None, "mid": None, "error": "no data client"})
    try:
        from alpaca.data.requests import StockLatestQuoteRequest
        req    = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quotes = _data_client.get_stock_latest_quote(req)
        q      = quotes[symbol]
        bid    = float(q.bid_price)
        ask    = float(q.ask_price)
        return jsonify({
            "symbol": symbol,
            "bid":    round(bid, 4),
            "ask":    round(ask, 4),
            "spread": round(ask - bid, 4),
            "mid":    round((bid + ask) / 2, 4),
        })
    except Exception as exc:
        return jsonify({"symbol": symbol, "bid": None, "ask": None,
                        "spread": None, "mid": None, "error": str(exc)})


@data_bp.route("/api/bars/<symbol>")
def api_bars(symbol):
    """OHLCV bars + indicators. ?interval=5m&range=5D"""
    symbol         = symbol.upper().strip()
    interval_param = request.args.get("interval", "5m")
    range_param    = request.args.get("range",    "5D")

    try:
        import pandas as pd
        from openbb_data import fetch_bars
        from indicators import bollinger_bands
        from indicators import rsi as calc_rsi, macd as calc_macd

        # -- Map UI params to fetch_bars -----------------------------------
        INTERVAL_MAP = {
            "1m": "1m",  "5m": "5m",  "15m": "15m", "30m": "30m",
            "1H": "60m", "4H": "60m",          # 4H needs resample
            "1D": "1d",  "1W": "1wk", "1M": "1mo",
        }
        RANGE_MAP = {
            "1D": "1d",  "5D": "5d",  "1M": "1mo", "3M": "3mo",
            "6M": "6mo", "YTD": "ytd","1Y": "1y",  "All": "max",
        }
        yf_interval  = INTERVAL_MAP.get(interval_param, "5m")
        yf_period    = RANGE_MAP.get(range_param, "5d")
        resample_4h  = (interval_param == "4H")

        # Enforce intraday data limits
        INTRADAY_MAX = {"1m": 7, "5m": 60, "15m": 60, "30m": 60, "60m": 730}
        PERIOD_DAYS  = {
            "1d": 1, "5d": 5, "1mo": 30, "3mo": 90,
            "6mo": 180, "ytd": 180, "1y": 365, "max": 3650,
        }
        if yf_interval in INTRADAY_MAX:
            max_d    = INTRADAY_MAX[yf_interval]
            req_d    = PERIOD_DAYS.get(yf_period, 30)
            if req_d > max_d:
                yf_period = f"{max_d}d" if max_d != 730 else "730d"

        # -- Fetch ---------------------------------------------------------
        df = fetch_bars(symbol, period=yf_period, interval=yf_interval)
        if df is None or df.empty:
            return jsonify({"error": "no data", "symbol": symbol,
                            "bars": [], "indicators": {}})

        # fetch_bars already returns lowercase columns and sorted index
        df = df[["open", "high", "low", "close", "volume"]].copy()

        if resample_4h:
            df = df.resample("4h").agg(
                {"open": "first", "high": "max", "low": "min",
                 "close": "last", "volume": "sum"}
            ).dropna()

        # Drop last forming bar on intraday
        if len(df) > 1 and yf_interval not in ("1d", "1wk", "1mo"):
            df = df.iloc[:-1]

        # -- Serialise bars ------------------------------------------------
        bars = []
        for ts, row in df.iterrows():
            try:
                pt = pd.Timestamp(ts)
                unix_ts = int(pt.timestamp()) if pt.tzinfo is not None \
                          else int(pt.tz_localize("UTC").timestamp())
                bars.append({
                    "time":   unix_ts,
                    "open":   round(float(row["open"]),   4),
                    "high":   round(float(row["high"]),   4),
                    "low":    round(float(row["low"]),    4),
                    "close":  round(float(row["close"]),  4),
                    "volume": int(row["volume"]) if "volume" in row else 0,
                })
            except Exception:
                continue

        if not bars:
            return jsonify({"error": "serialization failed", "symbol": symbol,
                            "bars": [], "indicators": {}})

        # -- Indicators ----------------------------------------------------
        closes = df["close"]
        times  = [b["time"] for b in bars]

        def series_to_timed(s: pd.Series) -> list:
            out = []
            for i, (_, v) in enumerate(s.items()):
                if i >= len(times):
                    break
                try:
                    if math.isnan(float(v)):
                        continue
                    out.append({"time": times[i], "value": round(float(v), 4)})
                except Exception:
                    pass
            return out

        short_sma = closes.rolling(config.SHORT_WINDOW).mean()
        long_sma  = closes.rolling(config.LONG_WINDOW).mean()
        bb_u, _, bb_l          = bollinger_bands(closes)
        rsi_s                  = calc_rsi(closes)
        macd_line, macd_sig, macd_hist = calc_macd(closes)

        indicators = {
            "short_sma":        series_to_timed(short_sma),
            "long_sma":         series_to_timed(long_sma),
            "bb_upper":         series_to_timed(bb_u),
            "bb_lower":         series_to_timed(bb_l),
            "rsi_series":       series_to_timed(rsi_s),
            "macd_series":      series_to_timed(macd_line),
            "macd_sig_series":  series_to_timed(macd_sig),
            "macd_hist_series": series_to_timed(macd_hist),
        }

        return jsonify({"symbol": symbol, "bars": bars, "indicators": indicators})

    except Exception as exc:
        log.error("[dashboard] /api/bars/%s error: %s", symbol, exc, exc_info=True)
        return jsonify({"error": str(exc), "symbol": symbol, "bars": [],
                        "indicators": {}})


# ── Agent status route ───────────────────────────────────────────────────────

@data_bp.route("/api/agents/status")
def api_agents_status():
    from dashboard import _coordinator
    if _coordinator is None:
        return jsonify({"agents": [], "pipeline": {}})
    return Response(_snap_json(_coordinator.get_agents_status()),
                    mimetype="application/json")
