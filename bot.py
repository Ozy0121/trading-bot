"""
bot.py
------
Core trading loop with swing-trading strategy.

Strategy summary:
  - Hold overnight (swing trades, not day trades)
  - High-conviction entries only: SMA + RSI + Volume spike + MACD must all align
  - Catalyst confirmation: ARK buys + analyst upgrades boost score
  - Trailing stop (3%) protects profits as price moves up
  - 6% take-profit target
  - Dynamic position sizing: 5% of equity, halved on 3-loss streak
  - PDT protection: tracks day trades, never exceeds 3/5-day window
  - Graceful shutdown: liquidates all positions on Ctrl-C
"""

import signal
import sys
import time
from datetime import datetime, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, OrderStatus
from alpaca.data.historical import StockHistoricalDataClient

import config
import state as shared_state
from logger_setup import get_logger, log_trade_event
from scanner import scan, best_buy, fetch_bars_yf, get_watchlist
from indicators import compute_all as compute_indicators
from catalysts import get_catalysts
from safety import (
    assert_market_open,
    calculate_safe_qty,
    check_pdt_allows_buy,
    check_pdt_allows_sell,
    check_shutdown_stop_losses,
    clear_peak_price,
    clear_position_date,
    daily_loss_exceeded,
    get_active_stop_loss_symbols,
    get_dynamic_fraction,
    get_pdt_info,
    get_peak_price,
    kill_switch,
    liquidate_all,
    load_state_from_file,
    place_oco_exit,
    poll_order_fill,
    record_buy_date,
    record_peak_price,
    record_session_start_equity,
    trailing_stop_triggered,
    update_peak_price,
)

log = get_logger()

_shutdown_requested = False
_trading_client_global: TradingClient | None = None


def request_shutdown() -> None:
    global _shutdown_requested
    _shutdown_requested = True
    shared_state.update(status="stopping")


def _handle_signal(signum, frame):
    global _shutdown_requested
    log.warning("[bot] Signal %s — liquidating all positions before exit...", signum)
    _shutdown_requested = True
    shared_state.update(status="stopping")
    if _trading_client_global:
        # ── BRACKET-03: Warn about unprotected positions before shutdown ──────
        try:
            result = check_shutdown_stop_losses(_trading_client_global)
            if not result["all_protected"]:
                for sym in result["unprotected"]:
                    log.warning("[bot] WARNING: %s has NO server-side stop-loss!", sym)
                log_trade_event(log, "SHUTDOWN_UNPROTECTED",
                                symbols=",".join(result["unprotected"]))
        except Exception:
            pass
        try:
            liquidate_all(_trading_client_global)
        except Exception as exc:
            log.error("[bot] Shutdown liquidation error: %s", exc)
    shared_state.update(status="stopped")
    sys.exit(0)


signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── Position helpers ─────────────────────────────────────────────────────────

def get_current_position(trading_client: TradingClient):
    try:
        pos = trading_client.get_open_position(config.SYMBOL)
        return float(pos.qty), float(pos.avg_entry_price), float(pos.unrealized_pl)
    except Exception:
        return 0.0, 0.0, 0.0


def get_held_position(trading_client: TradingClient, symbol: str):
    """Return (qty, avg_cost, unrealized_pnl) for a specific symbol."""
    try:
        pos = trading_client.get_open_position(symbol)
        return float(pos.qty), float(pos.avg_entry_price), float(pos.unrealized_pl)
    except Exception:
        return 0.0, 0.0, 0.0


def get_all_positions_data(trading_client: TradingClient) -> list:
    try:
        positions = trading_client.get_all_positions()
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
        return result
    except Exception as exc:
        log.warning("[bot] Could not fetch positions: %s", exc)
        return []


# ── Order execution ──────────────────────────────────────────────────────────

def place_buy(trading_client: TradingClient, equity: float, price: float,
              symbol: str, consecutive_losses: int = 0) -> bool:
    """Submit a bracket buy order with stop-loss and take-profit. Returns True if order placed."""
    fraction = get_dynamic_fraction(consecutive_losses)
    qty = calculate_safe_qty(price, equity, fraction=fraction)
    if qty < 1:
        log.warning("[bot] BUY: qty=0 after safety check (price=%.2f equity=%.2f). Skipping.",
                    price, equity)
        return False

    stop_price = round(price * (1 - config.TRAILING_STOP_PCT), 2)
    profit_price = round(price * (1 + config.TAKE_PROFIT_PCT), 2)

    log.info("[bot] BUY: %d shares of %s @ ~$%.2f (fraction=%.1f%%) SL=$%.2f TP=$%.2f",
             qty, symbol, price, fraction * 100, stop_price, profit_price)
    log_trade_event(log, "BUY_ORDER_ATTEMPT", symbol=symbol, qty=qty,
                    approx_price=f"{price:.2f}")

    order = trading_client.submit_order(
        MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            stop_loss=StopLossRequest(stop_price=stop_price),
            take_profit=TakeProfitRequest(limit_price=profit_price),
        )
    )
    log_trade_event(log, "BUY_ORDER_SUBMITTED", symbol=symbol, qty=qty,
                    order_id=order.id, status=order.status)

    # ── Poll for fill confirmation (SAFE-03) ──────────────────────────────────
    filled_order = poll_order_fill(trading_client, str(order.id))
    if filled_order.status == OrderStatus.REJECTED:
        log.warning("[bot] BUY REJECTED for %s: order %s", symbol, order.id)
        log_trade_event(log, "ORDER_REJECTED", symbol=symbol, order_id=str(order.id))
        return False
    if filled_order.status == OrderStatus.PARTIALLY_FILLED:
        actual_qty = int(float(filled_order.filled_qty))
        log.info("[bot] PARTIAL FILL: %d/%d shares of %s", actual_qty, qty, symbol)
        log_trade_event(log, "PARTIAL_FILL_ACCEPTED", symbol=symbol,
                        filled=actual_qty, requested=qty)
        # Accept partial — bracket legs are auto-placed by Alpaca for filled qty
    elif filled_order.status == OrderStatus.FILLED:
        actual_qty = int(float(filled_order.filled_qty))
        log.info("[bot] FILL CONFIRMED: %d shares of %s @ $%s",
                 actual_qty, symbol, filled_order.filled_avg_price)
        log_trade_event(log, "FILL_CONFIRMED", symbol=symbol, qty=actual_qty,
                        fill_price=str(filled_order.filled_avg_price))
    else:
        log.warning("[bot] BUY order %s in state %s after fill poll",
                    order.id, filled_order.status)

    log_trade_event(log, "BRACKET_ORDER_PLACED", symbol=symbol,
                    stop_price=f"{stop_price:.2f}", profit_price=f"{profit_price:.2f}")

    # Store bracket info in shared state for dashboard (BRACKET-04 prep)
    shared_state.update(
        bracket_info={symbol: {
            "stop_loss_price": stop_price,
            "take_profit_price": profit_price,
            "status": "protected",
        }}
    )

    record_buy_date(symbol)
    record_peak_price(symbol, price)   # initialise trailing stop

    shared_state.push_trade(
        time=datetime.now(timezone.utc).strftime("%H:%M:%S"),
        event="BUY",
        detail=f"{symbol} {qty}sh @ ~${price:.2f} | frac={fraction*100:.0f}% | SL=${stop_price:.2f} TP=${profit_price:.2f}",
    )
    return True


def place_sell(trading_client: TradingClient, qty: float, price: float,
               reason: str = "SIGNAL", symbol: str = None,
               avg_cost: float = 0.0) -> None:
    """Submit a market sell and record the trade outcome."""
    symbol = symbol or shared_state.snapshot().get("symbol") or config.SYMBOL
    log.info("[bot] SELL: %.0f shares of %s @ ~$%.2f (reason=%s)",
             qty, symbol, price, reason)
    log_trade_event(log, "SELL_ORDER_ATTEMPT", symbol=symbol, qty=qty,
                    approx_price=f"{price:.2f}", reason=reason)

    order = trading_client.submit_order(
        MarketOrderRequest(symbol=symbol, qty=qty,
                           side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
    )
    log_trade_event(log, "SELL_ORDER_SUBMITTED", symbol=symbol, qty=qty,
                    order_id=order.id, status=order.status)

    clear_position_date(symbol)
    clear_peak_price(symbol)

    # Record trade outcome for growth tracking
    if avg_cost > 0:
        pnl    = (price - avg_cost) * qty
        is_win = pnl > 0
        shared_state.record_trade(symbol=symbol, pnl=pnl,
                                   entry=avg_cost, exit_price=price,
                                   is_win=is_win)
        log.info("[bot] Trade closed: %s pnl=$%.2f (%s)",
                 symbol, pnl, "WIN" if is_win else "LOSS")

    shared_state.push_trade(
        time=datetime.now(timezone.utc).strftime("%H:%M:%S"),
        event="SELL",
        detail=f"{symbol} {qty:.0f}sh @ ~${price:.2f} [{reason}]",
    )


# ── Main trading loop ────────────────────────────────────────────────────────

def run_bot(trading_client: TradingClient, data_client: StockHistoricalDataClient,
            session_start_equity: float) -> None:
    global _trading_client_global
    _trading_client_global = trading_client

    log.info("[bot] Starting. Poll interval: %ds | Goal: $%.0f",
             config.POLL_INTERVAL, config.ACCOUNT_GOAL)
    shared_state.update(status="running", symbol=config.SYMBOL,
                        account_goal=config.ACCOUNT_GOAL)

    # ── BRACKET-02: Check existing positions for missing stop-losses ──────────
    load_state_from_file()
    log.info("[bot] Checking existing positions for bracket protection...")
    try:
        protected = get_active_stop_loss_symbols(trading_client)
        positions = trading_client.get_all_positions()
        for pos in positions:
            sym = pos.symbol.upper()
            qty = float(pos.qty)
            if qty > 0 and sym not in protected:
                current_price = float(pos.current_price)
                log.warning("[bot] Missing stop-loss for %s -- recreating bracket order", sym)
                place_oco_exit(trading_client, sym, int(qty), current_price)
    except Exception as exc:
        log.error("[bot] Startup bracket check failed: %s", exc, exc_info=True)

    while not _shutdown_requested:
        cycle_start = datetime.now(timezone.utc)
        log.info("[bot] ── Cycle: %s ──", cycle_start.strftime("%Y-%m-%dT%H:%M:%SZ"))

        try:
            # ── 1. Market hours ──────────────────────────────────────────────
            if not assert_market_open(trading_client):
                shared_state.push_trade(
                    time=cycle_start.strftime("%H:%M:%S"),
                    event="MARKET_CLOSED", detail="Waiting for open",
                )
                _interruptible_sleep(config.POLL_INTERVAL)
                continue

            # ── 2. Account info ──────────────────────────────────────────────
            account = trading_client.get_account()
            equity  = float(account.equity)
            cash    = float(account.cash)
            bp      = float(account.buying_power)

            # ── 3. Daily loss check ──────────────────────────────────────────
            if daily_loss_exceeded(equity):
                log.critical("[bot] Daily loss limit hit. Kill switch.")
                shared_state.update(status="loss_limit_hit")
                shared_state.push_trade(
                    time=cycle_start.strftime("%H:%M:%S"),
                    event="DAILY_LOSS_LIMIT",
                    detail=f"Loss exceeded ${config.DAILY_LOSS_LIMIT:.2f}.",
                )
                kill_switch(trading_client)
                break

            # ── 4. PDT status ────────────────────────────────────────────────
            pdt = get_pdt_info(trading_client)
            shared_state.update(
                pdt_applies=pdt["applies"],
                pdt_used=pdt["used"],
                pdt_remaining=pdt["remaining"],
            )

            # ── 5. Get consecutive losses for position sizing ─────────────────
            snap = shared_state.snapshot()
            consecutive_losses = snap.get("consecutive_losses", 0)

            # ── 6. Fetch catalysts (ARK + analyst upgrades) ───────────────────
            watchlist = get_watchlist()
            catalysts = get_catalysts(watchlist)

            # ── 7. Scan watchlist ────────────────────────────────────────────
            scan_results = scan(watchlist, catalysts=catalysts)

            shared_state.update(watchlist=[
                {k: v for k, v in r.items() if k != "df"}
                for r in scan_results
            ])

            # ── 8. Find current open positions ───────────────────────────────
            all_positions = get_all_positions_data(trading_client)
            shared_state.update(positions=all_positions)

            # Determine what we're currently holding
            held_symbol = snap.get("symbol") or config.SYMBOL
            # If we have an open position, use that symbol
            if all_positions:
                held_symbol = all_positions[0]["symbol"]
                shared_state.update(symbol=held_symbol)

            held_qty, avg_cost, pos_pnl = get_held_position(trading_client, held_symbol)

            # Get scan result for held symbol
            held_result = next(
                (r for r in scan_results if r["symbol"] == held_symbol), None
            )

            price = held_result["price"] if held_result else 0.0
            sig   = held_result["signal"] if held_result else "HOLD"
            s_sma = held_result.get("short_sma", 0.0) if held_result else 0.0
            l_sma = held_result.get("long_sma",  0.0) if held_result else 0.0

            # ── 9. Update trailing stop peak ─────────────────────────────────
            if held_qty > 0 and price > 0:
                update_peak_price(held_symbol, price)

            peak = get_peak_price(held_symbol)
            trail_level = round(peak * (1 - config.TRAILING_STOP_PCT), 4) if peak else None

            log.info(
                "[bot] %s qty=%.0f equity=$%.2f | PDT %d/3 | losses=%d | peak=%s trail=%s",
                held_symbol, held_qty, equity,
                pdt["used"], consecutive_losses,
                f"${peak:.2f}" if peak else "—",
                f"${trail_level:.2f}" if trail_level else "—",
            )

            # ── 10. Shared state update ──────────────────────────────────────
            daily_pnl = equity - session_start_equity

            ind = {}
            if held_result and held_result.get("df") is not None:
                ind = compute_indicators(held_result["df"])

            cat = catalysts.get(held_symbol, {})

            shared_state.update(
                equity=equity, cash=cash, buying_power=bp,
                symbol=held_symbol,
                shares_held=held_qty, avg_cost=avg_cost, position_pnl=pos_pnl,
                signal=sig, price=price, short_sma=s_sma, long_sma=l_sma,
                daily_pnl=round(daily_pnl, 2),
                session_start_equity=session_start_equity,
                peak_price=peak, trailing_stop_price=trail_level,
                rsi=held_result.get("rsi")       if held_result else None,
                macd_hist=held_result.get("macd_hist") if held_result else None,
                bb_upper=held_result.get("bb_upper")   if held_result else None,
                bb_lower=held_result.get("bb_lower")   if held_result else None,
                volume_ratio=held_result.get("volume_ratio", 1.0) if held_result else 1.0,
                catalyst_ark=cat.get("ark_buying", False),
                catalyst_upgrade=cat.get("analyst_upgrade", False),
                _rsi_series=ind.get("_rsi_series", []),
                _macd_series=ind.get("_macd_series", []),
                _macd_sig_series=ind.get("_macd_sig_series", []),
                _macd_hist_series=ind.get("_macd_hist_series", []),
                _bb_upper_series=ind.get("_bb_upper_series", []),
                _bb_lower_series=ind.get("_bb_lower_series", []),
            )

            if price and s_sma and l_sma:
                last_bar = held_result["df"].iloc[-1] if held_result else None
                shared_state.push_history(
                    time=cycle_start.isoformat(), price=price,
                    short_sma=s_sma, long_sma=l_sma,
                    bb_upper=held_result.get("bb_upper") if held_result else None,
                    bb_lower=held_result.get("bb_lower") if held_result else None,
                    open_=float(last_bar["open"])   if last_bar is not None else None,
                    high=float(last_bar["high"])    if last_bar is not None else None,
                    low=float(last_bar["low"])      if last_bar is not None else None,
                    volume=float(last_bar["volume"]) if last_bar is not None else None,
                )

            # ── 11. Trailing stop (replaces fixed stop-loss) ─────────────────
            if held_qty > 0 and price > 0:
                if trailing_stop_triggered(held_symbol, price):
                    if check_pdt_allows_sell(trading_client, held_symbol):
                        place_sell(trading_client, held_qty, price,
                                   reason="TRAILING_STOP", symbol=held_symbol,
                                   avg_cost=avg_cost)
                    else:
                        log.warning("[bot] PDT: trailing stop blocked on %s.", held_symbol)
                        shared_state.push_trade(
                            time=cycle_start.strftime("%H:%M:%S"),
                            event="PDT_HOLD",
                            detail=f"Trailing stop triggered on {held_symbol} but PDT blocked.",
                        )
                    _interruptible_sleep(config.POLL_INTERVAL)
                    continue

            # ── 12. Take-profit ──────────────────────────────────────────────
            if held_qty > 0 and avg_cost > 0 and price:
                pnl_pct = (price - avg_cost) / avg_cost

                if config.TAKE_PROFIT_PCT > 0 and pnl_pct >= config.TAKE_PROFIT_PCT:
                    log.info("[bot] TAKE PROFIT: +%.2f%% on %s", pnl_pct * 100, held_symbol)
                    if check_pdt_allows_sell(trading_client, held_symbol):
                        place_sell(trading_client, held_qty, price,
                                   reason="TAKE_PROFIT", symbol=held_symbol,
                                   avg_cost=avg_cost)
                    else:
                        log.warning("[bot] PDT: take-profit blocked on %s.", held_symbol)
                    _interruptible_sleep(config.POLL_INTERVAL)
                    continue

            # ── 13. SMA sell signal ──────────────────────────────────────────
            if held_qty > 0 and sig == "SELL":
                if check_pdt_allows_sell(trading_client, held_symbol):
                    place_sell(trading_client, held_qty, price,
                               reason="SIGNAL", symbol=held_symbol,
                               avg_cost=avg_cost)
                else:
                    log.info("[bot] PDT: holding %s — sell blocked.", held_symbol)
                    shared_state.push_trade(
                        time=cycle_start.strftime("%H:%M:%S"),
                        event="PDT_HOLD",
                        detail=f"SELL signal on {held_symbol} blocked by PDT.",
                    )
                _interruptible_sleep(config.POLL_INTERVAL)
                continue

            # ── 14. Entry ───────────────────────────────────────────────────
            if held_qty == 0:
                if not check_pdt_allows_buy(trading_client):
                    log.info("[bot] PDT: 3/3 day trades used. No new positions today.")
                    shared_state.push_trade(
                        time=cycle_start.strftime("%H:%M:%S"),
                        event="PDT_HOLD",
                        detail="3/3 day trades used — no new positions today.",
                    )
                else:
                    candidate = best_buy(scan_results)
                    if candidate:
                        buy_sym   = candidate["symbol"]
                        buy_price = candidate["price"]
                        conv      = candidate.get("conviction", {})
                        cat_info  = catalysts.get(buy_sym, {})
                        cat_str   = []
                        if cat_info.get("ark_buying"):      cat_str.append("ARK")
                        if cat_info.get("analyst_upgrade"): cat_str.append("Upgrade")
                        if cat_str:
                            log.info("[bot] Catalysts for %s: %s", buy_sym, "+".join(cat_str))

                        log.info("[bot] HIGH CONVICTION BUY: %s @ $%.2f "
                                 "(score=%.1f rsi=%.1f vol=%.1fx macd=%.4f)",
                                 buy_sym, buy_price,
                                 candidate["score"],
                                 candidate["rsi"],
                                 candidate["volume_ratio"],
                                 candidate["macd_hist"])

                        log.info("[bot] Best candidate: %s (conviction: %.1f/10 — "
                                 "tech:%.1f vol:%.1f sent:%.1f sec:%.1f)",
                                 buy_sym, conv.get("composite", 0),
                                 conv.get("technical", 0), conv.get("volume", 0),
                                 conv.get("sentiment", 0), conv.get("sector", 0))

                        log.info("[bot] Executing trade from strategy: %s",
                                 ", ".join(conv.get("strategies_fired", ["unknown"])))

                        shared_state.update(symbol=buy_sym)
                        place_buy(trading_client, equity, buy_price,
                                  symbol=buy_sym,
                                  consecutive_losses=consecutive_losses)
                    else:
                        log.info("[bot] No high-conviction BUY found. Patience. Holding cash.")
            else:
                log.info("[bot] Holding %s — signal=%s. Monitoring trailing stop @ $%s.",
                         held_symbol, sig,
                         f"{trail_level:.2f}" if trail_level else "—")

        except Exception as exc:
            log.error("[bot] Unhandled exception: %s", exc, exc_info=True)

        log.info("[bot] Sleeping %ds...", config.POLL_INTERVAL)
        _interruptible_sleep(config.POLL_INTERVAL)

    shared_state.update(status="stopped")
    log.info("[bot] Main loop exited.")


def _interruptible_sleep(seconds: int) -> None:
    for _ in range(seconds):
        if _shutdown_requested:
            break
        time.sleep(1)


# ── Entry point from server.py ───────────────────────────────────────────────

def run_bot_from_server(trading_client, data_client):
    global _shutdown_requested, _trading_client_global
    _shutdown_requested = False
    _trading_client_global = trading_client

    log.info("[bot] Starting from dashboard...")
    account      = trading_client.get_account()
    start_equity = float(account.equity)
    record_session_start_equity(start_equity)

    # Set account_start_equity only once (for lifetime progress tracking)
    snap = shared_state.snapshot()
    if snap.get("account_start_equity", 0.0) == 0.0:
        shared_state.update(account_start_equity=start_equity)

    shared_state.update(
        status="running",
        session_start_equity=start_equity,
        account_goal=config.ACCOUNT_GOAL,
    )
    run_bot(trading_client, data_client, start_equity)


if __name__ == "__main__":
    print("Use 'py server.py paper' or 'py server.py live' to start.")
    sys.exit(0)
