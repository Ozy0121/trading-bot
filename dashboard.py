"""
dashboard.py
------------
Flask web server.

Routes:
  GET    /                          — dashboard HTML
  GET    /api/state                 — current bot state JSON
  GET    /api/stream                — SSE stream (1s push)
  GET    /api/account               — account info for start screen
  GET    /api/positions             — all open positions (with bracket info)
  GET    /api/bars/<symbol>         — OHLCV + indicators (?interval=5m&range=5D)
  GET    /api/quote/<symbol>        — latest bid/ask quote
  GET    /api/performance           — growth stats, P&L calendar
  GET    /api/orders                — open orders
  GET    /api/orders/history        — closed/filled orders (last 100)
  POST   /api/order                 — place manual order
  DELETE /api/order/<id>/cancel     — cancel an order
  POST   /api/start                 — start bot
  POST   /api/kill                  — kill current symbol position
  POST   /api/sell_all              — sell ALL positions + stop bot
  POST   /api/config/exits          — update stop-loss and take-profit percentages
  POST   /api/stop                  — check bracket protection or stop bot
  GET    /api/expanded-scan         — expanded scanner results + funnel
  POST   /api/expanded-scan/run     — trigger manual expanded scan
"""

import json
import logging
import math
import threading
import time

from flask import Flask, Response, jsonify, render_template, request, abort, stream_with_context

import config
import progress
import state as shared_state
from logger_setup import get_logger
from safety import get_active_stop_loss_symbols, check_shutdown_stop_losses

logging.getLogger("werkzeug").setLevel(logging.ERROR)

app = Flask(__name__)
log = get_logger()

_trading_client = None
_data_client    = None
_kill_fn        = None
_start_fn       = None
_coordinator    = None


def set_coordinator(coordinator):
    global _coordinator
    _coordinator = coordinator


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
    """SSE: pushes full state + progress every second."""
    def generate():
        try:
            while True:
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
            "conviction_threshold":  config.CONVICTION_THRESHOLD,
        })
    except Exception as exc:
        abort(500, str(exc))


@app.route("/api/positions")
def api_positions():
    if _trading_client is None:
        abort(503, "Not connected.")
    try:
        positions = _trading_client.get_all_positions()
        # Get bracket protection status for all symbols
        protected_symbols = get_active_stop_loss_symbols(_trading_client)
        bracket_info = shared_state.snapshot().get("bracket_info", {})

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

            sym = p.symbol.upper()
            sym_bracket = bracket_info.get(sym, {})
            avg_entry = float(p.avg_entry_price)

            # Compute SL/TP from entry price + config percentages
            sl_price = sym_bracket.get("stop_loss_price",
                        round(avg_entry * (1 - config.TRAILING_STOP_PCT), 2) if avg_entry > 0 else None)
            tp_price = sym_bracket.get("take_profit_price",
                        round(avg_entry * (1 + config.TAKE_PROFIT_PCT), 2) if avg_entry > 0 else None)

            # Bracket status
            if sym in protected_symbols:
                bracket_status = "protected"
            elif sym_bracket.get("status") == "placing":
                bracket_status = "placing"
            else:
                bracket_status = "unprotected"

            result.append({
                "symbol":            sym,
                "qty":               qty,
                "avg_entry":         round(avg_entry, 4),
                "current_price":     round(float(p.current_price), 4),
                "pnl":               round(float(p.unrealized_pl), 2),
                "pnl_pct":           round(pnl_pct, 2),
                "market_value":      round(float(p.market_value), 2),
                "stop_loss_price":   sl_price,
                "take_profit_price": tp_price,
                "bracket_status":    bracket_status,
            })
        return jsonify(result)
    except Exception as exc:
        abort(500, str(exc))


@app.route("/api/bars/<symbol>")
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

        # ── Map UI params → fetch_bars ────────────────────────────────────
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

        # ── Fetch ─────────────────────────────────────────────────────────
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

        # ── Serialise bars ─────────────────────────────────────────────────
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

        # ── Indicators ─────────────────────────────────────────────────────
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


@app.route("/api/quote/<symbol>")
def api_quote(symbol):
    """Latest bid/ask for a symbol."""
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


@app.route("/api/orders")
def api_orders():
    """Return open orders."""
    if _trading_client is None:
        abort(503, "Not connected.")
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums   import QueryOrderStatus
        orders = _trading_client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=50))
        return jsonify([{
            "id":          str(o.id),
            "symbol":      o.symbol,
            "side":        str(o.side.value),
            "type":        str(o.order_type.value),
            "qty":         float(o.qty or 0),
            "filled_qty":  float(o.filled_qty or 0),
            "limit_price": float(o.limit_price) if o.limit_price else None,
            "stop_price":  float(o.stop_price)  if o.stop_price  else None,
            "tif":         str(o.time_in_force.value),
            "status":      str(o.status.value),
            "created_at":  str(o.created_at),
        } for o in orders])
    except Exception as exc:
        abort(500, str(exc))


@app.route("/api/orders/history")
def api_orders_history():
    """Return last 100 closed/filled orders."""
    if _trading_client is None:
        abort(503, "Not connected.")
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums   import QueryOrderStatus
        orders = _trading_client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=100))
        return jsonify([{
            "id":           str(o.id),
            "symbol":       o.symbol,
            "side":         str(o.side.value),
            "type":         str(o.order_type.value),
            "qty":          float(o.qty or 0),
            "filled_qty":   float(o.filled_qty or 0),
            "filled_price": float(o.filled_avg_price) if o.filled_avg_price else None,
            "status":       str(o.status.value),
            "created_at":   str(o.created_at),
            "filled_at":    str(o.filled_at) if o.filled_at else None,
        } for o in orders])
    except Exception as exc:
        abort(500, str(exc))


@app.route("/api/order", methods=["POST"])
def api_order():
    """Place a manual order."""
    if _trading_client is None:
        abort(503, "Not connected.")
    body = request.get_json(silent=True) or {}
    if body.get("confirm") != "YES":
        abort(400, "Confirmation required.")
    try:
        from alpaca.trading.requests import (
            MarketOrderRequest, LimitOrderRequest,
            StopOrderRequest, StopLimitOrderRequest,
        )
        from alpaca.trading.enums import OrderSide, TimeInForce

        symbol      = body.get("symbol", "").upper().strip()
        side_str    = body.get("side", "buy").lower()
        order_type  = body.get("order_type", "market").lower()
        qty         = body.get("qty")
        limit_price = body.get("limit_price")
        stop_price  = body.get("stop_price")
        tif_str     = body.get("tif", "day").lower()

        if not symbol: abort(400, "Symbol required.")
        if not qty:    abort(400, "Quantity required.")

        side    = OrderSide.BUY if side_str == "buy" else OrderSide.SELL
        tif_map = {"day": TimeInForce.DAY, "gtc": TimeInForce.GTC,
                   "ioc": TimeInForce.IOC}
        tif     = tif_map.get(tif_str, TimeInForce.DAY)
        qty     = float(qty)

        if order_type == "market":
            req = MarketOrderRequest(symbol=symbol, qty=qty, side=side,
                                     time_in_force=tif)
        elif order_type == "limit":
            req = LimitOrderRequest(symbol=symbol, qty=qty, side=side,
                                    time_in_force=tif,
                                    limit_price=float(limit_price))
        elif order_type == "stop":
            req = StopOrderRequest(symbol=symbol, qty=qty, side=side,
                                   time_in_force=tif,
                                   stop_price=float(stop_price))
        elif order_type == "stop_limit":
            req = StopLimitOrderRequest(symbol=symbol, qty=qty, side=side,
                                        time_in_force=tif,
                                        limit_price=float(limit_price),
                                        stop_price=float(stop_price))
        else:
            abort(400, f"Unknown order type: {order_type}")

        order = _trading_client.submit_order(req)
        log.info("[dashboard] Manual %s %s %s x%.4f", side_str.upper(),
                 order_type, symbol, qty)
        return jsonify({"ok": True, "order_id": str(order.id),
                        "status": str(order.status.value)})
    except Exception as exc:
        log.error("[dashboard] Order error: %s", exc)
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/api/order/<order_id>/cancel", methods=["DELETE"])
def api_cancel_order(order_id):
    """Cancel an open order by ID."""
    if _trading_client is None:
        abort(503, "Not connected.")
    try:
        import uuid as _uuid
        _trading_client.cancel_order_by_id(_uuid.UUID(order_id))
        return jsonify({"ok": True})
    except Exception as exc:
        abort(500, str(exc))


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
            wl = get_watchlist()
            progress.track("scan", total=len(wl), current=0, label=f"Scanning {len(wl)} stocks...")
            results = run_scan(wl, progress_cb=lambda cur, tot: progress.track("scan", current=cur, total=tot))
            shared_state.update(
                watchlist=[{k: v for k, v in r.items() if k != "df"} for r in results],
                use_top_movers=config.USE_TOP_MOVERS,
            )
            passed = len([r for r in results if r.get("fired")])
            progress.complete("scan", message=f"{passed} stocks passed filters")
        except Exception as exc:
            log.warning("[dashboard] Background scan error: %s", exc)
            progress.fail("scan", message=str(exc))
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
    shared_state.update(status="starting",
                       conviction_threshold=config.CONVICTION_THRESHOLD)
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


@app.route("/api/config/exits", methods=["POST"])
def api_config_exits():
    """Update stop-loss and take-profit percentages at runtime (per BRACKET-05, D-17)."""
    data = request.get_json(silent=True) or {}
    stop_loss_pct = data.get("stop_loss_pct")
    take_profit_pct = data.get("take_profit_pct")

    errors = []
    if stop_loss_pct is not None:
        try:
            val = float(stop_loss_pct) / 100.0  # UI sends percentage, config stores decimal
            if not (0.01 <= val <= 0.10):
                errors.append("Stop-loss must be between 1% and 10%.")
            else:
                config.TRAILING_STOP_PCT = val
        except (ValueError, TypeError):
            errors.append("Stop-loss must be a number.")

    if take_profit_pct is not None:
        try:
            val = float(take_profit_pct) / 100.0
            if not (0.02 <= val <= 0.20):
                errors.append("Take-profit must be between 2% and 20%.")
            else:
                config.TAKE_PROFIT_PCT = val
        except (ValueError, TypeError):
            errors.append("Take-profit must be a number.")

    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    log.info("[dashboard] Exit settings updated: SL=%.1f%% TP=%.1f%%",
             config.TRAILING_STOP_PCT * 100, config.TAKE_PROFIT_PCT * 100)
    return jsonify({
        "ok": True,
        "stop_loss_pct": round(config.TRAILING_STOP_PCT * 100, 1),
        "take_profit_pct": round(config.TAKE_PROFIT_PCT * 100, 1),
    })


@app.route("/api/stop", methods=["POST"])
def api_stop():
    """Check bracket protection status or stop bot (per BRACKET-03).

    ?check_only=true — returns protection status without stopping.
    POST without check_only — performs shutdown with protection warning logged.
    """
    check_only = request.args.get("check_only", "false").lower() == "true"
    if _trading_client:
        result = check_shutdown_stop_losses(_trading_client)
        if check_only:
            return jsonify(result)
        if not result["all_protected"]:
            log.warning("[dashboard] Shutdown with unprotected positions: %s",
                        result["unprotected"])

    # Perform shutdown — leave positions and bracket orders in place
    log.critical("[dashboard] Bot stop requested via /api/stop.")
    shared_state.update(status="stopping")

    def _do():
        import bot as _bot
        _bot.request_shutdown()
        shared_state.update(status="stopped")

    threading.Thread(target=_do, daemon=True, name="api-stop").start()
    return jsonify({"ok": True, "message": "Stopping bot. Positions and bracket orders left in place."})


@app.route("/api/agents/status")
def api_agents_status():
    if _coordinator is None:
        return jsonify({"agents": [], "pipeline": {}})
    return Response(_snap_json(_coordinator.get_agents_status()),
                    mimetype="application/json")


# ── Prediction & Overnight Scanner endpoints ─────────────────────────────────

@app.route("/api/predictions")
def api_predictions():
    """Return current pre-spike predictions from the prediction engine."""
    snap = shared_state.snapshot()
    return jsonify({
        "predictions": snap.get("predictions", []),
        "count": snap.get("prediction_count", 0),
        "scan_summary": snap.get("scan_summary", ""),
        "universe_size": snap.get("scan_universe_size", 0),
        "scan_funnel": snap.get("scan_funnel", {}),
    })


@app.route("/api/predictions/run", methods=["POST"])
def api_predictions_run():
    """Trigger a prediction scan in the background."""
    def _do():
        try:
            from stock_universe import get_full_universe, get_scan_summary, get_funnel_stats
            from prediction import predict_batch
            from expanded_scanner import load_overnight_results, run_expanded_pipeline

            progress.track("predictions", total=0, current=0, label="Loading quant-filtered stocks...")
            progress.push_log("predictions", "Starting prediction scan...")

            survivors = load_overnight_results()
            if survivors:
                universe = [s["symbol"] for s in survivors if "symbol" in s]
                progress.push_log("predictions", f"Using {len(universe)} expanded scanner survivors")
            else:
                progress.track("predictions", total=0, current=0, label="Running quant filter on 2,500+ stocks...")
                progress.push_log("predictions", "No cached results — running quant filter on 2,500+ stocks...")
                scored = run_expanded_pipeline()
                universe = [s["symbol"] for s in scored if "symbol" in s]
                progress.push_log("predictions", f"Quant filter produced {len(universe)} survivors")

            if not universe:
                universe = get_full_universe(include_discovery=True)
                progress.push_log("predictions", f"No survivors — falling back to full universe ({len(universe)})", "warning")

            funnel = get_funnel_stats()
            progress.track("predictions", total=len(universe), current=0,
                           label=f"AI analyzing {len(universe):,} stocks...")
            predictions = predict_batch(universe,
                                        progress_cb=lambda cur, tot, label="": progress.track("predictions", current=cur, total=tot, label=label or f"AI analyzing {tot:,} stocks..."))

            pred_dicts = [p.to_dict() for p in predictions[:30]]
            shared_state.update(
                predictions=pred_dicts,
                prediction_count=len(predictions),
                scan_universe_size=len(universe),
                scan_funnel=funnel.get("breakdown", {}),
                scan_summary=get_scan_summary(len(universe), len(predictions), min(30, len(predictions))),
            )
            progress.complete("predictions", message=f"{len(predictions)} predictions generated")
        except Exception as exc:
            log.error("[dashboard] Prediction scan failed: %s", exc, exc_info=True)
            progress.fail("predictions", message=str(exc))

    threading.Thread(target=_do, daemon=True, name="prediction-scan").start()
    return jsonify({"ok": True, "message": "Prediction scan started."})


@app.route("/api/overnight")
def api_overnight():
    """Return the latest overnight predictions and accuracy stats."""
    from prediction_scanner import get_latest_predictions, get_accuracy_summary
    preds = get_latest_predictions()
    accuracy = get_accuracy_summary()
    return jsonify({
        "predictions": preds,
        "accuracy": accuracy,
    })


@app.route("/api/overnight/run", methods=["POST"])
def api_overnight_run():
    """Trigger an overnight scan manually."""
    def _do():
        try:
            from prediction_scanner import run_overnight_scan
            progress.track("overnight", total=0, current=0, label="Running overnight analysis...")
            result = run_overnight_scan(
                progress_cb=lambda cur, tot, lbl=None: progress.track("overnight", current=cur, total=tot,
                                                                       label=lbl or f"Analyzing stock {cur}/{tot}..."))
            shared_state.update(overnight_predictions=result)
            count = len(result) if isinstance(result, list) else 0
            progress.complete("overnight", message=f"{count} picks for tomorrow")
        except Exception as exc:
            log.error("[dashboard] Overnight scan failed: %s", exc, exc_info=True)
            progress.fail("overnight", message=str(exc))

    threading.Thread(target=_do, daemon=True, name="manual-overnight").start()
    return jsonify({"ok": True, "message": "Overnight scan started."})


@app.route("/api/overnight/accuracy")
def api_overnight_accuracy():
    """Check and return prediction accuracy."""
    from prediction_scanner import check_prediction_accuracy
    try:
        result = check_prediction_accuracy()
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)})


@app.route("/api/prediction-log/accuracy")
def api_prediction_log_accuracy():
    """Live prediction accuracy from formal tracking system."""
    from prediction_log import get_accuracy, check_outcomes, get_recent_predictions
    try:
        resolved = check_outcomes()
        accuracy = get_accuracy()
        recent = get_recent_predictions(20)
        accuracy["recently_resolved"] = resolved
        accuracy["recent_predictions"] = recent
        return jsonify(accuracy)
    except Exception as exc:
        log.error("[dashboard] Prediction log accuracy failed: %s", exc)
        return jsonify({"error": str(exc)})


@app.route("/api/expanded-scan")
def api_expanded_scan():
    """Return the latest expanded scanner results and funnel stats."""
    snap = shared_state.snapshot()
    return jsonify({
        "results": snap.get("expanded_scan_results", []),
        "scan_time": snap.get("expanded_scan_time"),
        "status": snap.get("expanded_scan_status", "idle"),
        "funnel": snap.get("expanded_scan_funnel", {}),
    })


@app.route("/api/expanded-scan/run", methods=["POST"])
def api_expanded_scan_run():
    """Trigger an expanded scan manually (D-07)."""
    snap = shared_state.snapshot()
    if snap.get("expanded_scan_status") == "running":
        return jsonify({"ok": False, "message": "Scan already running."})

    def _do():
        try:
            from expanded_scanner import trigger_manual_scan
            progress.track("expanded_scan", total=0, current=0, label="Running expanded scan...")
            trigger_manual_scan()
            progress.complete("expanded_scan", message="Expanded scan complete")
        except Exception as exc:
            log.error("[dashboard] Expanded scan failed: %s", exc, exc_info=True)
            progress.fail("expanded_scan", message=str(exc))

    threading.Thread(target=_do, daemon=True, name="manual-expanded-scan").start()
    return jsonify({"ok": True, "message": "Expanded scan started."})


@app.route("/api/expanded-scan/cancel", methods=["POST"])
def api_expanded_scan_cancel():
    """Cancel a running expanded scan."""
    from expanded_scanner import cancel_scan
    cancel_scan()
    progress.fail("expanded_scan", message="Scan cancelled by user")
    return jsonify({"ok": True, "message": "Cancel requested."})


@app.route("/api/scan-logs", methods=["GET", "DELETE"])
def api_scan_logs():
    """Return or clear the scanner log buffer."""
    if request.method == "DELETE":
        progress.clear_logs()
        return jsonify({"ok": True})
    since = float(request.args.get("since", 0))
    return jsonify(progress.get_logs(since))


@app.route("/api/intelligence")
def api_intelligence():
    """Return intelligence data: treasury rates, insider trades, SEC filings, market movers."""
    from openbb_intel import get_intelligence_report, check_openbb_status
    try:
        watchlist = list(config.WATCHLIST) if hasattr(config, "WATCHLIST") else []
        # Use top prediction symbols if available
        snap = shared_state.snapshot()
        pred_symbols = [p.get("symbol", "") for p in snap.get("predictions", [])[:20]]
        symbols = list(dict.fromkeys(pred_symbols + watchlist))[:30]
        report = get_intelligence_report(symbols)
        report["openbb_check"] = check_openbb_status()
        return jsonify(report)
    except Exception as exc:
        log.error("[dashboard] Intelligence report failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)})


@app.route("/api/heatmap/market")
def api_heatmap_market():
    """Return market heatmap data for S&P 500 + NASDAQ 100."""
    snap = shared_state.snapshot()
    cached = snap.get("heatmap_data", [])
    if cached:
        return jsonify(cached)

    # Trigger background fetch if empty
    def _do():
        try:
            from stock_universe import fetch_heatmap_data
            data = fetch_heatmap_data()
            shared_state.update(heatmap_data=data)
        except Exception as exc:
            log.error("[dashboard] Heatmap fetch failed: %s", exc)

    threading.Thread(target=_do, daemon=True, name="heatmap-fetch").start()
    return jsonify([])


@app.route("/api/heatmap/positions")
def api_heatmap_positions():
    """Return positions heatmap data (size=value, color=P&L)."""
    if _trading_client is None:
        return jsonify([])
    try:
        positions = _trading_client.get_all_positions()
        bracket_info = shared_state.snapshot().get("bracket_info", {})
        result = []
        for p in positions:
            qty = float(p.qty)
            if qty <= 0:
                continue
            sym = p.symbol.upper()
            avg_entry = float(p.avg_entry_price)
            current = float(p.current_price)
            market_val = float(p.market_value)
            pnl = float(p.unrealized_pl)
            try:
                pnl_pct = float(p.unrealized_plpc) * 100
            except Exception:
                pnl_pct = ((current - avg_entry) / avg_entry * 100) if avg_entry > 0 else 0.0

            sym_bracket = bracket_info.get(sym, {})
            sl = sym_bracket.get("stop_loss_price",
                    round(avg_entry * (1 - config.TRAILING_STOP_PCT), 2) if avg_entry > 0 else None)
            tp = sym_bracket.get("take_profit_price",
                    round(avg_entry * (1 + config.TAKE_PROFIT_PCT), 2) if avg_entry > 0 else None)

            result.append({
                "symbol": sym,
                "qty": qty,
                "avg_entry": round(avg_entry, 4),
                "current_price": round(current, 4),
                "market_value": round(market_val, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "stop_loss": sl,
                "take_profit": tp,
            })
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)})


# ── Auto-trade from predictions ─────────────────────────────────────────────

@app.route("/api/predictions/auto-trade", methods=["POST"])
def api_predictions_auto_trade():
    """
    Place GTC limit bracket orders for the top prediction picks.
    Can be called anytime — orders sit waiting for the price to hit.
    """
    if _trading_client is None:
        abort(503, "Not connected.")

    body = request.get_json(silent=True) or {}
    if body.get("confirm") != "YES":
        abort(400, "Confirmation required.")

    max_orders = min(int(body.get("max_orders", 1)), 3)  # hard cap at 3 (PDT limit)

    def _do():
        try:
            from prediction_scanner import get_latest_predictions
            from bot import place_limit_buy
            from safety import check_pdt_allows_buy, calculate_safe_qty, get_dynamic_fraction, get_pdt_info

            preds = get_latest_predictions()
            if not preds:
                log.warning("[auto-trade] No predictions available")
                return

            # Get account equity
            acct = _trading_client.get_account()
            equity = float(acct.equity)
            snap = shared_state.snapshot()
            consecutive_losses = snap.get("consecutive_losses", 0)

            # Check PDT before starting
            pdt = get_pdt_info(_trading_client)
            if pdt["applies"] and pdt["remaining"] <= 0:
                log.warning("[auto-trade] PDT limit reached — cannot place orders")
                return

            # Cap orders to PDT remaining trades
            effective_max = min(max_orders, pdt["remaining"]) if pdt["applies"] else max_orders

            # Get top picks (launch_zone and pre_breakout only)
            ready = preds.get("ready_tomorrow", [])
            if not ready:
                ready = [p for p in preds.get("all_predictions", [])
                         if p.get("confidence", 0) >= 8
                         and p.get("stage") in ("launch_zone", "pre_breakout")]

            placed = 0
            for p in ready[:effective_max]:
                sym = p["symbol"]
                entry_price = p.get("entry_high", 0)
                stop_loss = p.get("stop_loss", 0)
                target = p.get("target_price", 0)

                if not entry_price or not stop_loss or not target:
                    log.warning("[auto-trade] Skipping %s — missing price data", sym)
                    continue

                log.info("[auto-trade] Placing GTC limit order: %s @ $%.2f "
                         "(SL=$%.2f TP=$%.2f conf=%d stage=%s)",
                         sym, entry_price, stop_loss, target,
                         p.get("confidence", 0), p.get("stage", ""))

                ok = place_limit_buy(
                    _trading_client, equity, entry_price, sym,
                    stop_loss=stop_loss, take_profit=target,
                    consecutive_losses=consecutive_losses,
                )
                if ok:
                    placed += 1

            log.info("[auto-trade] Placed %d/%d orders", placed, min(len(ready), effective_max))
        except Exception as exc:
            log.error("[auto-trade] Failed: %s", exc, exc_info=True)

    threading.Thread(target=_do, daemon=True, name="auto-trade").start()
    return jsonify({"ok": True, "message": f"Placing up to {max_orders} prediction order(s)..."})


# ── Strategy Backtester endpoints ───────────────────────────────────────────

@app.route("/api/backtest")
def api_backtest():
    """Return the latest backtest results."""
    from backtester import get_latest_backtest
    result = get_latest_backtest()
    if result is None:
        return jsonify({"error": "no backtest results — run one first"})
    return jsonify(result)


@app.route("/api/backtest/run", methods=["POST"])
def api_backtest_run():
    """Trigger a full strategy backtest in the background."""
    def _do():
        try:
            from backtester import run_backtest
            progress.track("backtest", total=0, current=0, label="Running backtest...")
            run_backtest(progress_cb=lambda cur, tot, lbl=None: progress.track("backtest", current=cur, total=tot,
                                                                                label=lbl or f"Processing day {cur}/{tot}..."))
            progress.complete("backtest", message="Backtest finished")
        except Exception as exc:
            log.error("[dashboard] Backtest failed: %s", exc, exc_info=True)
            progress.fail("backtest", message=str(exc))

    threading.Thread(target=_do, daemon=True, name="strategy-backtest").start()
    return jsonify({"ok": True, "message": "Backtest started — this takes a few minutes."})


@app.route("/api/health")
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


def run(port: int = 5000):
    log.info("[dashboard] http://localhost:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
