"""
routes/trading.py
-----------------
Flask Blueprint for trading-related routes: orders, positions, account,
bot start/stop/kill, exit config, performance, backtest, auto-trade.
"""

import math
import threading

from flask import Blueprint, jsonify, request, abort

import config
import progress
import state as shared_state
from logger_setup import get_logger

log = get_logger()
trading_bp = Blueprint("trading", __name__)


# ── Order routes ─────────────────────────────────────────────────────────────

@trading_bp.route("/api/order", methods=["POST"])
def api_order():
    """Place a manual order."""
    from dashboard import _trading_client
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


@trading_bp.route("/api/order/<order_id>/cancel", methods=["DELETE"])
def api_cancel_order(order_id):
    """Cancel an open order by ID."""
    from dashboard import _trading_client
    if _trading_client is None:
        abort(503, "Not connected.")
    try:
        import uuid as _uuid
        _trading_client.cancel_order_by_id(_uuid.UUID(order_id))
        return jsonify({"ok": True})
    except Exception as exc:
        abort(500, str(exc))


# ── Bot control routes ───────────────────────────────────────────────────────

@trading_bp.route("/api/start", methods=["POST"])
def api_start():
    from dashboard import _trading_client, _data_client, _start_fn
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


@trading_bp.route("/api/stop", methods=["POST"])
def api_stop():
    """Check bracket protection status or stop bot (per BRACKET-03).

    ?check_only=true -- returns protection status without stopping.
    POST without check_only -- performs shutdown with protection warning logged.
    """
    from dashboard import _trading_client
    from safety import check_shutdown_stop_losses
    check_only = request.args.get("check_only", "false").lower() == "true"
    if _trading_client:
        result = check_shutdown_stop_losses(_trading_client)
        if check_only:
            return jsonify(result)
        if not result["all_protected"]:
            log.warning("[dashboard] Shutdown with unprotected positions: %s",
                        result["unprotected"])

    # Perform shutdown -- leave positions and bracket orders in place
    log.critical("[dashboard] Bot stop requested via /api/stop.")
    shared_state.update(status="stopping")

    def _do():
        import bot as _bot
        _bot.request_shutdown()
        shared_state.update(status="stopped")

    threading.Thread(target=_do, daemon=True, name="api-stop").start()
    return jsonify({"ok": True, "message": "Stopping bot. Positions and bracket orders left in place."})


@trading_bp.route("/api/kill", methods=["POST"])
def api_kill():
    from dashboard import _trading_client, _kill_fn
    body = request.get_json(silent=True) or {}
    if body.get("confirm") != "YES":
        abort(400, "Confirmation required.")
    if _kill_fn is None or _trading_client is None:
        abort(503, "Not ready.")
    log.critical("[dashboard] Kill switch via web UI.")
    shared_state.update(status="stopped")
    threading.Thread(target=_kill_fn, args=(_trading_client,), daemon=True).start()
    return jsonify({"ok": True, "message": "Kill switch activated."})


@trading_bp.route("/api/sell_all", methods=["POST"])
def api_sell_all():
    from dashboard import _trading_client
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


@trading_bp.route("/api/config/exits", methods=["POST"])
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


# ── Account & position routes ────────────────────────────────────────────────

@trading_bp.route("/api/positions")
def api_positions():
    from dashboard import _trading_client
    if _trading_client is None:
        abort(503, "Not connected.")
    try:
        from safety import get_active_stop_loss_symbols
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


@trading_bp.route("/api/orders")
def api_orders():
    """Return open orders."""
    from dashboard import _trading_client
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


@trading_bp.route("/api/orders/history")
def api_orders_history():
    """Return last 100 closed/filled orders."""
    from dashboard import _trading_client
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


@trading_bp.route("/api/account")
def api_account():
    from dashboard import _trading_client
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


@trading_bp.route("/api/performance")
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
            projection_str = "Goal reached!"
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


# ── Auto-trade from predictions ──────────────────────────────────────────────

@trading_bp.route("/api/predictions/auto-trade", methods=["POST"])
def api_predictions_auto_trade():
    """
    Place GTC limit bracket orders for the top prediction picks.
    Can be called anytime -- orders sit waiting for the price to hit.
    """
    from dashboard import _trading_client
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


# ── Strategy Backtester endpoints ────────────────────────────────────────────

@trading_bp.route("/api/backtest")
def api_backtest():
    """Return the latest backtest results."""
    from backtester import get_latest_backtest
    result = get_latest_backtest()
    if result is None:
        return jsonify({"error": "no backtest results — run one first"})
    return jsonify(result)


@trading_bp.route("/api/backtest/run", methods=["POST"])
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
