"""
dashboard.py
------------
Flask web server.

Routes:
  GET  /                    — dashboard HTML
  GET  /api/state           — current bot state JSON
  GET  /api/stream          — SSE stream (1s push)
  GET  /api/account         — account info for start screen
  GET  /api/positions       — all open positions
  GET  /api/bars/<symbol>   — OHLCV + indicators for any symbol
  GET  /api/performance     — growth stats, P&L calendar
  POST /api/start           — start bot
  POST /api/kill            — kill current symbol position
  POST /api/sell_all        — sell ALL positions + stop bot
"""

import json
import logging
import math
import threading
import time

from flask import Flask, Response, jsonify, render_template, request, abort, stream_with_context

import config
import state as shared_state
from logger_setup import get_logger

logging.getLogger("werkzeug").setLevel(logging.ERROR)

app = Flask(__name__)
log = get_logger()

_trading_client = None
_data_client    = None
_kill_fn        = None
_start_fn       = None


def set_dependencies(trading_client, data_client, kill_fn, start_fn):
    global _trading_client, _data_client, _kill_fn, _start_fn
    _trading_client = trading_client
    _data_client    = data_client
    _kill_fn        = kill_fn
    _start_fn       = start_fn


def _snap_json(obj):
    return json.dumps(obj, default=str)


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    return jsonify(shared_state.snapshot())


@app.route("/api/stream")
def api_stream():
    """SSE: pushes full state every second."""
    def generate():
        try:
            while True:
                yield f"data: {_snap_json(shared_state.snapshot())}\n\n"
                time.sleep(1)
        except GeneratorExit:
            pass
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


@app.route("/api/account")
def api_account():
    if _trading_client is None:
        abort(503, "Not connected.")
    try:
        acct     = _trading_client.get_account()
        equity   = float(acct.equity)
        dt_count = int(getattr(acct, 'daytrade_count', 0) or 0)
        return jsonify({
            "equity":                equity,
            "cash":                  float(acct.cash),
            "buying_power":          float(acct.buying_power),
            "symbol":                config.SYMBOL,
            "short_window":          config.SHORT_WINDOW,
            "long_window":           config.LONG_WINDOW,
            "bar_timeframe":         config.BAR_TIMEFRAME,
            "max_position_value":    config.MAX_POSITION_VALUE,
            "max_position_fraction": config.MAX_POSITION_FRACTION * 100,
            "daily_loss_limit":      config.DAILY_LOSS_LIMIT,
            "paper_trading":         config.PAPER_TRADING,
            "take_profit_pct":       config.TAKE_PROFIT_PCT * 100,
            "trailing_stop_pct":     config.TRAILING_STOP_PCT * 100,
            "stop_loss_pct":         0.0,
            "account_goal":          config.ACCOUNT_GOAL,
            "pdt_applies":           equity < 25_000,
            "pdt_used":              dt_count,
            "pdt_remaining":         max(0, 3 - dt_count),
        })
    except Exception as exc:
        abort(500, str(exc))


@app.route("/api/positions")
def api_positions():
    if _trading_client is None:
        abort(503, "Not connected.")
    try:
        positions = _trading_client.get_all_positions()
        result = []
        for p in positions:
            qty = float(p.qty)
            if qty <= 0:
                continue
            try:
                pnl_pct = float(p.unrealized_plpc) * 100
            except Exception:
                avg  = float(p.avg_entry_price)
                curr = float(p.current_price)
                pnl_pct = ((curr - avg) / avg * 100) if avg > 0 else 0.0
            result.append({
                "symbol":        p.symbol,
                "qty":           qty,
                "avg_entry":     round(float(p.avg_entry_price), 4),
                "current_price": round(float(p.current_price),   4),
                "pnl":           round(float(p.unrealized_pl),   2),
                "pnl_pct":       round(pnl_pct, 2),
                "market_value":  round(float(p.market_value),    2),
            })
        return jsonify(result)
    except Exception as exc:
        abort(500, str(exc))


@app.route("/api/bars/<symbol>")
def api_bars(symbol):
    """OHLCV bars + indicator series for any symbol. Used by chart click."""
    symbol = symbol.upper().strip()
    try:
        import pandas as pd
        from scanner import fetch_bars_yf
        from indicators import bollinger_bands
        from indicators import rsi as calc_rsi, macd as calc_macd

        df = fetch_bars_yf(symbol)
        if df is None or df.empty:
            return jsonify({"error": "no data", "symbol": symbol, "bars": [],
                            "indicators": {}})

        # Serialize OHLCV bars with proper Unix timestamps
        bars = []
        for ts, row in df.iterrows():
            try:
                pt = pd.Timestamp(ts)
                # Ensure UTC-based Unix timestamp
                if pt.tzinfo is not None:
                    unix_ts = int(pt.timestamp())
                else:
                    unix_ts = int(pt.tz_localize("UTC").timestamp())
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

        # Build indicator series aligned to the same timestamps
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
        bb_u, _, bb_l = bollinger_bands(closes)
        rsi_s = calc_rsi(closes)
        macd_line, macd_sig, macd_hist = calc_macd(closes)

        indicators = {
            "short_sma":       series_to_timed(short_sma),
            "long_sma":        series_to_timed(long_sma),
            "bb_upper":        series_to_timed(bb_u),
            "bb_lower":        series_to_timed(bb_l),
            "rsi_series":      series_to_timed(rsi_s),
            "macd_series":     series_to_timed(macd_line),
            "macd_sig_series": series_to_timed(macd_sig),
            "macd_hist_series":series_to_timed(macd_hist),
        }

        return jsonify({"symbol": symbol, "bars": bars, "indicators": indicators})

    except Exception as exc:
        log.error("[dashboard] /api/bars/%s error: %s", symbol, exc, exc_info=True)
        return jsonify({"error": str(exc), "symbol": symbol, "bars": [],
                        "indicators": {}})


@app.route("/api/performance")
def api_performance():
    """Return growth tracking stats for the Performance tab."""
    snap   = shared_state.snapshot()
    equity = snap.get("equity", 0.0) or 0.0
    goal   = snap.get("account_goal", 1000.0)
    start  = snap.get("account_start_equity", 0.0) or equity or 500.0

    total    = snap.get("total_trades", 0)
    wins     = snap.get("winning_trades", 0)
    total_pnl= snap.get("total_pnl", 0.0)
    c_losses = snap.get("consecutive_losses", 0)

    win_rate  = (wins / total * 100) if total > 0 else 0.0
    avg_pnl   = (total_pnl / total) if total > 0 else 0.0

    # Progress toward goal
    progress_pct = 0.0
    if goal > start and equity >= start:
        progress_pct = min(100.0, (equity - start) / (goal - start) * 100)

    # Projection
    projection_str = "Need at least 3 trades for projection"
    if total >= 3 and avg_pnl > 0:
        weekly_gain = (win_rate / 100) * avg_pnl * 3  # 3 trades/week max
        remaining   = goal - equity
        if weekly_gain > 0 and remaining > 0:
            weeks = remaining / weekly_gain
            if weeks < 1:
                projection_str = "Less than 1 week"
            elif weeks < 4:
                projection_str = f"~{math.ceil(weeks)} weeks"
            elif weeks < 52:
                projection_str = f"~{math.ceil(weeks / 4)} months"
            else:
                projection_str = f"~{weeks/52:.1f} years"
        elif remaining <= 0:
            projection_str = "Goal reached! 🎯"
        else:
            projection_str = "Negative avg gain — adjust strategy"

    return jsonify({
        "equity":          equity,
        "goal":            goal,
        "start_equity":    start,
        "progress_pct":    round(progress_pct, 1),
        "total_trades":    total,
        "winning_trades":  wins,
        "win_rate":        round(win_rate, 1),
        "total_pnl":       round(total_pnl, 2),
        "avg_pnl":         round(avg_pnl, 2),
        "consecutive_losses": c_losses,
        "projection":      projection_str,
        "pnl_calendar":    snap.get("pnl_calendar", {}),
        "trade_history":   snap.get("trade_history", []),
        "size_reduced":    c_losses >= config.LOSING_STREAK_THRESHOLD,
    })


@app.route("/api/scan")
def api_scan():
    """Trigger a one-off watchlist scan in the background. Results arrive via SSE."""
    def _do():
        try:
            from scanner import get_watchlist, scan as run_scan
            wl      = get_watchlist()
            results = run_scan(wl)
            shared_state.update(
                watchlist=[{k: v for k, v in r.items() if k != "df"} for r in results],
                use_top_movers=config.USE_TOP_MOVERS,
            )
        except Exception as exc:
            log.warning("[dashboard] Background scan error: %s", exc)
    threading.Thread(target=_do, daemon=True, name="dashboard-scan").start()
    return jsonify({"ok": True, "message": "Scan started."})


@app.route("/api/start", methods=["POST"])
def api_start():
    body = request.get_json(silent=True) or {}
    if body.get("confirm") != "YES":
        abort(400, "Confirmation required.")
    if shared_state.snapshot()["status"] == "running":
        return jsonify({"ok": False, "message": "Already running."})
    if _start_fn is None:
        abort(503, "Server not ready.")
    log.info("[dashboard] Bot start requested.")
    shared_state.update(status="starting")
    threading.Thread(target=_start_fn, args=(_trading_client, _data_client),
                     daemon=True, name="bot-loop").start()
    return jsonify({"ok": True, "message": "Bot started."})


@app.route("/api/kill", methods=["POST"])
def api_kill():
    body = request.get_json(silent=True) or {}
    if body.get("confirm") != "YES":
        abort(400, "Confirmation required.")
    if _kill_fn is None or _trading_client is None:
        abort(503, "Not ready.")
    log.critical("[dashboard] Kill switch via web UI.")
    shared_state.update(status="stopped")
    threading.Thread(target=_kill_fn, args=(_trading_client,), daemon=True).start()
    return jsonify({"ok": True, "message": "Kill switch activated."})


@app.route("/api/sell_all", methods=["POST"])
def api_sell_all():
    body = request.get_json(silent=True) or {}
    if body.get("confirm") != "YES":
        abort(400, "Confirmation required.")
    if _trading_client is None:
        abort(503, "Not connected.")
    log.critical("[dashboard] Sell All & Stop via web UI.")
    shared_state.update(status="stopping")

    def _do():
        from safety import liquidate_all
        import bot as _bot
        _bot.request_shutdown()
        liquidate_all(_trading_client)
        shared_state.update(status="stopped")

    threading.Thread(target=_do, daemon=True, name="sell-all").start()
    return jsonify({"ok": True, "message": "Selling all positions and stopping."})


def run(port: int = 5000):
    log.info("[dashboard] http://localhost:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
