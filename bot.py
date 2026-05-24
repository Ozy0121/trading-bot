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
  - Graceful shutdown: stops polling loop on Ctrl-C (positions and bracket orders left in place)
"""

import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, StopLossRequest, TakeProfitRequest
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
_coordinator = None


def set_coordinator(coordinator) -> None:
    global _coordinator
    _coordinator = coordinator


def request_shutdown() -> None:
    global _shutdown_requested
    _shutdown_requested = True
    shared_state.update(status="stopping")


def _handle_signal(signum, frame):
    global _shutdown_requested
    log.warning("[bot] Signal %s — stopping bot (positions and bracket orders left in place)...", signum)
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

    # Add slippage buffer so bracket legs clear Alpaca's base_price validation.
    # Market orders can fill above the last quote; TP must be >= fill + 0.01.
    slippage_buffer = 0.02  # 2% cushion for market-order slippage
    stop_price = round(price * (1 - config.TRAILING_STOP_PCT - slippage_buffer), 2)
    profit_price = round(price * (1 + config.TAKE_PROFIT_PCT + slippage_buffer), 2)

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


def place_limit_buy(trading_client: TradingClient, equity: float,
                    limit_price: float, symbol: str,
                    stop_loss: float, take_profit: float,
                    consecutive_losses: int = 0) -> bool:
    """
    Place a GTC limit bracket order — sits waiting until the price hits.
    Used for prediction-based entries placed outside market hours.
    The order persists across sessions until filled or cancelled.
    """
    fraction = get_dynamic_fraction(consecutive_losses)
    qty = calculate_safe_qty(limit_price, equity, fraction=fraction)
    if qty < 1:
        log.warning("[bot] LIMIT BUY: qty=0 (price=%.2f equity=%.2f). Skipping.",
                    limit_price, equity)
        return False

    stop_price = round(stop_loss, 2)
    profit_price = round(take_profit, 2)

    log.info("[bot] LIMIT BUY (GTC): %d shares of %s @ $%.2f "
             "(fraction=%.1f%%) SL=$%.2f TP=$%.2f",
             qty, symbol, limit_price, fraction * 100, stop_price, profit_price)
    log_trade_event(log, "LIMIT_BUY_ATTEMPT", symbol=symbol, qty=qty,
                    limit_price=f"{limit_price:.2f}", tif="GTC")

    order = trading_client.submit_order(
        LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
            limit_price=limit_price,
            order_class=OrderClass.BRACKET,
            stop_loss=StopLossRequest(stop_price=stop_price),
            take_profit=TakeProfitRequest(limit_price=profit_price),
        )
    )
    log_trade_event(log, "LIMIT_BUY_SUBMITTED", symbol=symbol, qty=qty,
                    order_id=order.id, status=order.status,
                    limit_price=f"{limit_price:.2f}")

    log.info("[bot] GTC limit order placed: %s %d sh @ $%.2f — "
             "will fill when price drops to limit. SL=$%.2f TP=$%.2f",
             symbol, qty, limit_price, stop_price, profit_price)

    shared_state.update(
        bracket_info={symbol: {
            "stop_loss_price": stop_price,
            "take_profit_price": profit_price,
            "status": "pending_limit",
            "limit_price": limit_price,
        }}
    )

    shared_state.push_trade(
        time=datetime.now(timezone.utc).strftime("%H:%M:%S"),
        event="LIMIT_BUY",
        detail=f"{symbol} {qty}sh limit@${limit_price:.2f} GTC | SL=${stop_price:.2f} TP=${profit_price:.2f}",
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


# ── Prediction-based entry ───────────────────────────────────────────────────

# Minimum requirements for auto-trading from predictions
PRED_MIN_CONFIDENCE = 8        # out of 10
PRED_MIN_ACCURACY   = 0.55     # 55% historical hit rate
PRED_ALLOWED_STAGES = {"launch_zone", "pre_breakout"}


def _get_prediction_candidate() -> dict | None:
    """
    Check overnight/prediction picks for a trade-ready candidate.
    Only returns a candidate if it meets strict confidence + accuracy filters
    and the price is within the predicted entry zone.

    Returns a dict shaped like a scanner result, or None.
    """
    try:
        from data_provider import fetch_bars

        snap = shared_state.snapshot()
        preds = snap.get("predictions", [])
        if not preds:
            return None

        all_picks = preds  # predictions already filtered/ranked in shared_state
        if not all_picks:
            return None

        # Deduplicate by symbol, keep first (highest ranked)
        seen = set()
        unique = []
        for p in all_picks:
            if p["symbol"] not in seen:
                seen.add(p["symbol"])
                unique.append(p)

        for p in unique:
            sym        = p["symbol"]
            confidence = p.get("confidence", 0)
            stage      = p.get("stage", "")
            hist_acc   = p.get("historical_accuracy", 0)
            entry_low  = p.get("entry_low", 0)
            entry_high = p.get("entry_high", 0)

            # Filter: must be high confidence + right stage
            if confidence < PRED_MIN_CONFIDENCE:
                continue
            if stage not in PRED_ALLOWED_STAGES:
                continue
            if hist_acc > 0 and hist_acc < PRED_MIN_ACCURACY:
                continue

            # Get live price and check it's in the entry zone
            try:
                hist = fetch_bars(sym, period="1d", interval="1m")
                if hist is None or hist.empty:
                    continue
                live_price = float(hist["close"].iloc[-1])
            except Exception:
                continue

            # Price must be within entry zone (with 1% tolerance)
            zone_low  = entry_low * 0.99
            zone_high = entry_high * 1.01
            if not (zone_low <= live_price <= zone_high):
                log.debug("[bot] Prediction %s: price $%.2f outside entry zone $%.2f–$%.2f",
                          sym, live_price, entry_low, entry_high)
                continue

            # Build a scanner-compatible candidate dict
            patterns = [pt["name"] for pt in p.get("patterns", []) if pt.get("detected")]
            log.info(
                "[bot] PREDICTION CANDIDATE: %s @ $%.2f (conf=%d, stage=%s, "
                "accuracy=%.0f%%, patterns=%s, target=$%.2f)",
                sym, live_price, confidence, stage,
                hist_acc * 100, "+".join(patterns),
                p.get("target_price", 0),
            )

            return {
                "symbol": sym,
                "price": live_price,
                "score": confidence * 10,   # map 1-10 to 10-100
                "signal": "BUY",
                "rsi": p.get("patterns", [{}])[0].get("details", {}).get("rsi", 50),
                "volume_ratio": 1.5,  # prediction already verified volume
                "macd_hist": 0.0,
                "conviction": {
                    "composite": confidence,
                    "technical": confidence,
                    "volume": 5.0,
                    "sentiment": 5.0,
                    "sector": 5.0,
                    "strategies_fired": ["prediction:" + stage],
                },
            }

        return None

    except Exception as exc:
        log.debug("[bot] Prediction candidate check failed: %s", exc)
        return None


# ── Per-cycle context ───────────────────────────────────────────────────────

@dataclass
class _CycleContext:
    """Per-cycle state passed between phase functions."""
    trading_client: TradingClient = None
    data_client: StockHistoricalDataClient = None
    session_start_equity: float = 0.0
    cycle_start: datetime = None
    scan_results: list = field(default_factory=list)
    catalysts: dict = field(default_factory=dict)
    equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0
    consecutive_losses: int = 0
    all_positions: list = field(default_factory=list)
    held_symbol: str = ""
    held_qty: float = 0.0
    avg_cost: float = 0.0
    pos_pnl: float = 0.0
    held_result: dict = None
    price: float = 0.0
    sig: str = "HOLD"
    pdt: dict = field(default_factory=dict)
    peak: float = None
    trail_level: float = None
    s_sma: float = 0.0
    l_sma: float = 0.0


# ── Extracted phase functions ───────────────────────────────────────────────

def _phase_1_scan_watchlist(ctx: _CycleContext) -> None:
    """Phase 1: Scan watchlist and fetch catalysts."""
    watchlist = get_watchlist()
    ctx.catalysts = get_catalysts(watchlist)
    ctx.scan_results = scan(watchlist, catalysts=ctx.catalysts)
    shared_state.update(watchlist=[
        {k: v for k, v in r.items() if k != "df"}
        for r in ctx.scan_results
    ])


def _phase_2_check_market_hours(ctx: _CycleContext) -> bool:
    """Phase 2: Verify market is open. Returns False if should skip cycle."""
    if not assert_market_open(ctx.trading_client):
        shared_state.push_trade(
            time=ctx.cycle_start.strftime("%H:%M:%S"),
            event="MARKET_CLOSED", detail="Waiting for open",
        )
        return False
    return True


def _phase_3_get_account_info(ctx: _CycleContext) -> None:
    """Phase 3: Fetch account equity, cash, buying power."""
    account = ctx.trading_client.get_account()
    ctx.equity = float(account.equity)
    ctx.cash = float(account.cash)
    ctx.buying_power = float(account.buying_power)


def _phase_4_check_daily_loss(ctx: _CycleContext) -> bool:
    """Phase 4: Check daily loss limit. Returns True if limit hit (should break)."""
    if daily_loss_exceeded(ctx.equity):
        log.critical("[bot] Daily loss limit hit. Kill switch.")
        shared_state.update(status="loss_limit_hit")
        shared_state.push_trade(
            time=ctx.cycle_start.strftime("%H:%M:%S"),
            event="DAILY_LOSS_LIMIT",
            detail=f"Loss exceeded ${config.DAILY_LOSS_LIMIT:.2f}.",
        )
        kill_switch(ctx.trading_client)
        return True
    return False


def _phase_5_update_pdt(ctx: _CycleContext) -> None:
    """Phase 5: Fetch and update PDT status."""
    ctx.pdt = get_pdt_info(ctx.trading_client)
    shared_state.update(
        pdt_applies=ctx.pdt["applies"],
        pdt_used=ctx.pdt["used"],
        pdt_remaining=ctx.pdt["remaining"],
    )


def _phase_6_get_losses(ctx: _CycleContext) -> None:
    """Phase 6: Get consecutive losses for position sizing."""
    snap = shared_state.snapshot()
    ctx.consecutive_losses = snap.get("consecutive_losses", 0)


def _phase_7_agent_cycle(ctx: _CycleContext) -> None:
    """Phase 7a: Run agent coordinator cycle."""
    if _coordinator:
        try:
            cycle_result = _coordinator.run_cycle()
            log.info("[bot] Agent cycle result: %s", cycle_result.get("action", "UNKNOWN"))
        except Exception as exc:
            log.error("[bot] Coordinator cycle error: %s", exc, exc_info=True)


def _phase_8_find_positions(ctx: _CycleContext) -> None:
    """Phase 8: Find current open positions."""
    ctx.all_positions = get_all_positions_data(ctx.trading_client)
    shared_state.update(positions=ctx.all_positions)

    # Determine what we're currently holding
    snap = shared_state.snapshot()
    ctx.held_symbol = snap.get("symbol") or config.SYMBOL
    # If we have an open position, use that symbol
    if ctx.all_positions:
        ctx.held_symbol = ctx.all_positions[0]["symbol"]
        shared_state.update(symbol=ctx.held_symbol)

    ctx.held_qty, ctx.avg_cost, ctx.pos_pnl = get_held_position(
        ctx.trading_client, ctx.held_symbol
    )

    # Get scan result for held symbol
    ctx.held_result = next(
        (r for r in ctx.scan_results if r["symbol"] == ctx.held_symbol), None
    )

    ctx.price = ctx.held_result["price"] if ctx.held_result else 0.0
    ctx.sig = ctx.held_result["signal"] if ctx.held_result else "HOLD"
    ctx.s_sma = ctx.held_result.get("short_sma", 0.0) if ctx.held_result else 0.0
    ctx.l_sma = ctx.held_result.get("long_sma", 0.0) if ctx.held_result else 0.0


def _phase_9_update_trailing_stop(ctx: _CycleContext) -> None:
    """Phase 9: Update trailing stop peak price."""
    if ctx.held_qty > 0 and ctx.price > 0:
        update_peak_price(ctx.held_symbol, ctx.price)

    ctx.peak = get_peak_price(ctx.held_symbol)
    ctx.trail_level = round(ctx.peak * (1 - config.TRAILING_STOP_PCT), 4) if ctx.peak else None

    log.info(
        "[bot] %s qty=%.0f equity=$%.2f | PDT %d/3 | losses=%d | peak=%s trail=%s",
        ctx.held_symbol, ctx.held_qty, ctx.equity,
        ctx.pdt["used"], ctx.consecutive_losses,
        f"${ctx.peak:.2f}" if ctx.peak else "—",
        f"${ctx.trail_level:.2f}" if ctx.trail_level else "—",
    )


def _phase_10_update_state(ctx: _CycleContext) -> None:
    """Phase 10: Push all data to shared state."""
    daily_pnl = ctx.equity - ctx.session_start_equity

    ind = {}
    if ctx.held_result and ctx.held_result.get("df") is not None:
        ind = compute_indicators(ctx.held_result["df"])

    cat = ctx.catalysts.get(ctx.held_symbol, {})

    shared_state.update(
        equity=ctx.equity, cash=ctx.cash, buying_power=ctx.buying_power,
        symbol=ctx.held_symbol,
        shares_held=ctx.held_qty, avg_cost=ctx.avg_cost, position_pnl=ctx.pos_pnl,
        signal=ctx.sig, price=ctx.price, short_sma=ctx.s_sma, long_sma=ctx.l_sma,
        daily_pnl=round(daily_pnl, 2),
        session_start_equity=ctx.session_start_equity,
        peak_price=ctx.peak, trailing_stop_price=ctx.trail_level,
        rsi=ctx.held_result.get("rsi") if ctx.held_result else None,
        macd_hist=ctx.held_result.get("macd_hist") if ctx.held_result else None,
        bb_upper=ctx.held_result.get("bb_upper") if ctx.held_result else None,
        bb_lower=ctx.held_result.get("bb_lower") if ctx.held_result else None,
        volume_ratio=ctx.held_result.get("volume_ratio", 1.0) if ctx.held_result else 1.0,
        catalyst_ark=cat.get("ark_buying", False),
        catalyst_upgrade=cat.get("analyst_upgrade", False),
        _rsi_series=ind.get("_rsi_series", []),
        _macd_series=ind.get("_macd_series", []),
        _macd_sig_series=ind.get("_macd_sig_series", []),
        _macd_hist_series=ind.get("_macd_hist_series", []),
        _bb_upper_series=ind.get("_bb_upper_series", []),
        _bb_lower_series=ind.get("_bb_lower_series", []),
    )


def _phase_11_sell_logic(ctx: _CycleContext) -> bool:
    """Phase 11: Evaluate sell signals (trailing stop, take profit, SMA signal).
    Returns True if a sell action was taken or blocked (caller should sleep+continue)."""
    # Trailing stop
    if ctx.held_qty > 0 and ctx.price > 0:
        if trailing_stop_triggered(ctx.held_symbol, ctx.price):
            if check_pdt_allows_sell(ctx.trading_client, ctx.held_symbol):
                place_sell(ctx.trading_client, ctx.held_qty, ctx.price,
                           reason="TRAILING_STOP", symbol=ctx.held_symbol,
                           avg_cost=ctx.avg_cost)
            else:
                log.warning("[bot] PDT: trailing stop blocked on %s.", ctx.held_symbol)
                shared_state.push_trade(
                    time=ctx.cycle_start.strftime("%H:%M:%S"),
                    event="PDT_HOLD",
                    detail=f"Trailing stop triggered on {ctx.held_symbol} but PDT blocked.",
                )
            return True

    # Take-profit
    if ctx.held_qty > 0 and ctx.avg_cost > 0 and ctx.price:
        pnl_pct = (ctx.price - ctx.avg_cost) / ctx.avg_cost

        if config.TAKE_PROFIT_PCT > 0 and pnl_pct >= config.TAKE_PROFIT_PCT:
            log.info("[bot] TAKE PROFIT: +%.2f%% on %s", pnl_pct * 100, ctx.held_symbol)
            if check_pdt_allows_sell(ctx.trading_client, ctx.held_symbol):
                place_sell(ctx.trading_client, ctx.held_qty, ctx.price,
                           reason="TAKE_PROFIT", symbol=ctx.held_symbol,
                           avg_cost=ctx.avg_cost)
            else:
                log.warning("[bot] PDT: take-profit blocked on %s.", ctx.held_symbol)
            return True

    # SMA sell signal
    if ctx.held_qty > 0 and ctx.sig == "SELL":
        if check_pdt_allows_sell(ctx.trading_client, ctx.held_symbol):
            place_sell(ctx.trading_client, ctx.held_qty, ctx.price,
                       reason="SIGNAL", symbol=ctx.held_symbol,
                       avg_cost=ctx.avg_cost)
        else:
            log.info("[bot] PDT: holding %s — sell blocked.", ctx.held_symbol)
            shared_state.push_trade(
                time=ctx.cycle_start.strftime("%H:%M:%S"),
                event="PDT_HOLD",
                detail=f"SELL signal on {ctx.held_symbol} blocked by PDT.",
            )
        return True

    return False


def _phase_12_buy_logic(ctx: _CycleContext) -> None:
    """Phase 12: Evaluate buy signals and place orders."""
    if ctx.held_qty == 0:
        if not check_pdt_allows_buy(ctx.trading_client):
            log.info("[bot] PDT: 3/3 day trades used. No new positions today.")
            shared_state.push_trade(
                time=ctx.cycle_start.strftime("%H:%M:%S"),
                event="PDT_HOLD",
                detail="3/3 day trades used — no new positions today.",
            )
        else:
            candidates = best_buy(ctx.scan_results)
            candidate = None
            source = "watchlist"

            if candidates:
                candidate = candidates[0]
            else:
                # Check prediction engine picks
                pred_candidate = _get_prediction_candidate()
                if pred_candidate:
                    candidate = pred_candidate
                    source = "prediction"

            if candidate:
                buy_sym = candidate["symbol"]
                buy_price = candidate["price"]
                conv = candidate.get("conviction", {})
                cat_info = ctx.catalysts.get(buy_sym, {})
                cat_str = []
                if cat_info.get("ark_buying"):
                    cat_str.append("ARK")
                if cat_info.get("analyst_upgrade"):
                    cat_str.append("Upgrade")
                if cat_str:
                    log.info("[bot] Catalysts for %s: %s", buy_sym, "+".join(cat_str))

                log.info("[bot] HIGH CONVICTION BUY: %s @ $%.2f "
                         "(score=%.1f rsi=%.1f vol=%.1fx macd=%.4f) "
                         "[source=%s, %d candidates available]",
                         buy_sym, buy_price,
                         candidate.get("score", 0),
                         candidate.get("rsi", 50),
                         candidate.get("volume_ratio", 1.0),
                         candidate.get("macd_hist", 0),
                         source, len(candidates) if candidates else 1)

                log.info("[bot] Best candidate: %s (conviction: %.1f/10 -- "
                         "tech:%.1f vol:%.1f sent:%.1f sec:%.1f)",
                         buy_sym, conv.get("composite", 0),
                         conv.get("technical", 0), conv.get("volume", 0),
                         conv.get("sentiment", 0), conv.get("sector", 0))

                log.info("[bot] Executing trade from %s strategy: %s",
                         source,
                         ", ".join(conv.get("strategies_fired", ["unknown"])))

                shared_state.update(symbol=buy_sym)
                place_buy(ctx.trading_client, ctx.equity, buy_price,
                          symbol=buy_sym,
                          consecutive_losses=ctx.consecutive_losses)
            else:
                log.info("[bot] No high-conviction BUY found. Patience. Holding cash.")
    else:
        log.info("[bot] Holding %s — signal=%s. Monitoring trailing stop @ $%s.",
                 ctx.held_symbol, ctx.sig,
                 f"{ctx.trail_level:.2f}" if ctx.trail_level else "—")


def _phase_13_push_history(ctx: _CycleContext) -> None:
    """Phase 13: Push chart history to shared state."""
    if ctx.price and ctx.s_sma and ctx.l_sma:
        last_bar = ctx.held_result["df"].iloc[-1] if ctx.held_result else None
        shared_state.push_history(
            time=ctx.cycle_start.isoformat(), price=ctx.price,
            short_sma=ctx.s_sma, long_sma=ctx.l_sma,
            bb_upper=ctx.held_result.get("bb_upper") if ctx.held_result else None,
            bb_lower=ctx.held_result.get("bb_lower") if ctx.held_result else None,
            open_=float(last_bar["open"]) if last_bar is not None else None,
            high=float(last_bar["high"]) if last_bar is not None else None,
            low=float(last_bar["low"]) if last_bar is not None else None,
            volume=float(last_bar["volume"]) if last_bar is not None else None,
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

    if _coordinator:
        try:
            _coordinator.startup_sequence()
        except Exception as exc:
            log.error("[bot] Coordinator startup failed: %s", exc, exc_info=True)

    while not _shutdown_requested:
        ctx = _CycleContext(
            trading_client=trading_client,
            data_client=data_client,
            session_start_equity=session_start_equity,
            cycle_start=datetime.now(timezone.utc),
        )
        log.info("[bot] ── Cycle: %s ──", ctx.cycle_start.strftime("%Y-%m-%dT%H:%M:%SZ"))

        try:
            _phase_1_scan_watchlist(ctx)
            if not _phase_2_check_market_hours(ctx):
                _interruptible_sleep(config.POLL_INTERVAL)
                continue
            _phase_3_get_account_info(ctx)
            if _phase_4_check_daily_loss(ctx):
                break
            _phase_5_update_pdt(ctx)
            _phase_6_get_losses(ctx)
            _phase_7_agent_cycle(ctx)
            _phase_8_find_positions(ctx)
            _phase_9_update_trailing_stop(ctx)
            _phase_10_update_state(ctx)
            if _phase_11_sell_logic(ctx):
                _phase_13_push_history(ctx)
                _interruptible_sleep(config.POLL_INTERVAL)
                continue
            _phase_12_buy_logic(ctx)
            _phase_13_push_history(ctx)
        except Exception as exc:
            log.error("[bot] Unhandled exception: %s", exc, exc_info=True)

        log.info("[bot] Sleeping %ds...", config.POLL_INTERVAL)
        _interruptible_sleep(config.POLL_INTERVAL)

    if _coordinator:
        try:
            _coordinator.shutdown_sequence()
        except Exception as exc:
            log.error("[bot] Coordinator shutdown failed: %s", exc, exc_info=True)

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
