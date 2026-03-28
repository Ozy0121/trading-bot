"""
safety.py
---------
All safety guardrails in one auditable place.

Guards:
  1. Daily loss limit
  2. Position size cap (with dynamic sizing for losing streaks)
  3. Market hours check
  4. PDT (Pattern Day Trader) rule
  5. Trailing stop tracking
  6. Emergency liquidation (kill_switch / liquidate_all)
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from datetime import date

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

import config
from logger_setup import get_logger, log_trade_event

log = get_logger()


# ── OCC options symbol detection ─────────────────────────────────────────────
_OCC_PATTERN = re.compile(r'^[A-Z]{1,6}\d{6}[CP]\d{8}$')


def is_options_symbol(symbol: str) -> bool:
    """True if symbol matches OCC format e.g. AAPL240119C00150000."""
    if not symbol:
        return False
    return bool(_OCC_PATTERN.match(symbol.upper().strip()))


# ── Options trading validation ────────────────────────────────────────────────

def validate_options_enabled(trading_client: TradingClient, live_mode: bool) -> None:
    """Check that the Alpaca account has options trading enabled (per SAFE-05, D-10).

    In paper mode, skip the check (paper accounts may not mirror live options approval).
    In live mode, require options_approved_level >= 2 or exit.
    """
    if not live_mode:
        log.info("[safety] Paper mode -- skipping options approval check.")
        return
    try:
        account = trading_client.get_account()
        level = getattr(account, "options_approved_level", None)
        if level is None or int(level) < 2:
            log.critical(
                "[safety] OPTIONS TRADING NOT ENABLED. "
                "Account options_approved_level=%s (need >= 2). "
                "Enable options in your Alpaca account before running live.",
                level,
            )
            raise SystemExit(1)
        log.info("[safety] Options trading enabled (level=%d).", int(level))
    except SystemExit:
        raise
    except Exception as exc:
        log.warning("[safety] Could not validate options level: %s. Proceeding with caution.", exc)


# ── State persistence ─────────────────────────────────────────────────────────
_state_lock = threading.Lock()
STATE_FILE = config.STATE_FILE_PATH


def _save_state() -> None:
    """Write current safety globals to disk. Call after every mutation."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    payload = {
        "date": date.today().isoformat(),
        "peak_prices": dict(_peak_prices),
        "positions_opened_today": list(_positions_opened_today),
        "session_start_equity": _session_start_equity,
    }
    try:
        with _state_lock:
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, STATE_FILE)
    except Exception as exc:
        log.warning("[safety] State save failed: %s", exc)


def load_state_from_file() -> None:
    """Load persisted state on startup. Log and ignore if file is missing/corrupt (per D-04)."""
    global _peak_prices, _positions_opened_today, _session_start_equity
    if not os.path.exists(STATE_FILE):
        log.info("[safety] No state file found -- starting fresh.")
        return
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        saved_date = data.get("date", "")
        if saved_date != date.today().isoformat():
            log.info("[safety] State file is from %s -- starting fresh (new day).", saved_date)
            return
        _peak_prices = data.get("peak_prices", {})
        _positions_opened_today = set(data.get("positions_opened_today", []))
        _session_start_equity = data.get("session_start_equity")
        log.info("[safety] State restored: %d peak prices, %d PDT entries.",
                 len(_peak_prices), len(_positions_opened_today))
    except Exception as exc:
        log.warning("[safety] State file corrupt -- starting fresh: %s", exc)


# ── Daily loss tracking ──────────────────────────────────────────────────────

_session_start_equity: float | None = None


def record_session_start_equity(equity: float) -> None:
    global _session_start_equity
    _session_start_equity = equity
    log.info("[safety] Session start equity: $%.2f", equity)
    _save_state()


def daily_loss_exceeded(current_equity: float) -> bool:
    if _session_start_equity is None:
        log.warning("[safety] Session start equity not recorded.")
        return False
    loss = _session_start_equity - current_equity
    if loss >= config.DAILY_LOSS_LIMIT:
        log.critical("[safety] DAILY LOSS LIMIT HIT. Loss=$%.2f / Limit=$%.2f.",
                     loss, config.DAILY_LOSS_LIMIT)
        log_trade_event(log, "DAILY_LOSS_LIMIT_HIT",
                        loss=f"{loss:.2f}", limit=f"{config.DAILY_LOSS_LIMIT:.2f}")
        return True
    return False


# ── Trailing stop ────────────────────────────────────────────────────────────
# Tracks the highest price seen since a position was opened.
# Triggers when price drops TRAILING_STOP_PCT% from the peak.

_peak_prices: dict[str, float] = {}   # symbol -> highest price since entry


def record_peak_price(symbol: str, price: float) -> None:
    """Call when a position is first opened to set the initial peak."""
    _peak_prices[symbol.upper()] = price
    log.debug("[safety] Trailing stop initialized: %s @ %.4f", symbol, price)
    _save_state()


def update_peak_price(symbol: str, price: float) -> None:
    """Call each cycle to ratchet the peak higher as price rises."""
    sym = symbol.upper()
    if sym not in _peak_prices or price > _peak_prices[sym]:
        _peak_prices[sym] = price
        _save_state()


def trailing_stop_triggered(symbol: str, price: float) -> bool:
    """True if price has fallen >= TRAILING_STOP_PCT from the peak."""
    sym  = symbol.upper()
    peak = _peak_prices.get(sym)
    if peak is None or peak <= 0:
        return False
    drawdown = (peak - price) / peak
    if drawdown >= config.TRAILING_STOP_PCT:
        log.info(
            "[safety] TRAILING STOP: %s peak=%.4f current=%.4f drawdown=%.2f%%",
            sym, peak, price, drawdown * 100,
        )
        return True
    return False


def clear_peak_price(symbol: str) -> None:
    """Call when a position is closed."""
    _peak_prices.pop(symbol.upper(), None)
    _save_state()


def get_peak_price(symbol: str) -> float | None:
    return _peak_prices.get(symbol.upper())


# ── PDT (Pattern Day Trader) protection ──────────────────────────────────────

_positions_opened_today: set[str] = set()


def record_buy_date(symbol: str) -> None:
    _positions_opened_today.add(symbol.upper())
    _save_state()


def clear_position_date(symbol: str) -> None:
    _positions_opened_today.discard(symbol.upper())
    _save_state()


def would_be_day_trade(symbol: str) -> bool:
    return symbol.upper() in _positions_opened_today


def check_pdt_allows_sell(trading_client: TradingClient, symbol: str) -> bool:
    if not would_be_day_trade(symbol):
        return True
    try:
        account = trading_client.get_account()
        equity  = float(account.equity)
        if equity >= 25_000:
            return True
        dt_count = int(getattr(account, 'daytrade_count', 0) or 0)
        if dt_count >= 3:
            log.warning("[safety] PDT BLOCKED sell on %s: %d/3 day trades used.", symbol, dt_count)
            log_trade_event(log, "PDT_SELL_BLOCKED", symbol=symbol, daytrade_count=dt_count)
            return False
    except Exception as exc:
        log.warning("[safety] PDT sell check failed: %s. Allowing.", exc)
    return True


def check_pdt_allows_buy(trading_client: TradingClient) -> bool:
    try:
        account = trading_client.get_account()
        equity  = float(account.equity)
        if equity >= 25_000:
            return True
        dt_count = int(getattr(account, 'daytrade_count', 0) or 0)
        if dt_count >= 3:
            log.warning("[safety] PDT BLOCKED buy: %d/3 day trades used.", dt_count)
            log_trade_event(log, "PDT_BUY_BLOCKED", daytrade_count=dt_count)
            return False
    except Exception as exc:
        log.warning("[safety] PDT buy check failed: %s. Allowing.", exc)
    return True


def get_pdt_info(trading_client: TradingClient) -> dict:
    try:
        account  = trading_client.get_account()
        equity   = float(account.equity)
        if equity >= 25_000:
            return {"applies": False, "used": 0, "remaining": 999}
        dt_count = int(getattr(account, 'daytrade_count', 0) or 0)
        return {"applies": True, "used": dt_count, "remaining": max(0, 3 - dt_count)}
    except Exception:
        return {"applies": False, "used": 0, "remaining": 3}


# ── Dynamic position sizing ──────────────────────────────────────────────────

def get_dynamic_fraction(consecutive_losses: int) -> float:
    """
    Return the position size fraction adjusted for the current losing streak.
    Base: MAX_POSITION_FRACTION (5%)
    After LOSING_STREAK_THRESHOLD consecutive losses: halved to protect capital.
    """
    fraction = config.MAX_POSITION_FRACTION
    if consecutive_losses >= config.LOSING_STREAK_THRESHOLD:
        fraction *= config.LOSING_STREAK_SIZE_FACTOR
        log.warning(
            "[safety] Losing streak (%d losses). Cutting position size to %.1f%% of equity.",
            consecutive_losses, fraction * 100,
        )
    return fraction


def calculate_safe_qty(price: float, equity: float,
                       fraction: float | None = None) -> int:
    """
    Return the maximum number of whole shares we can buy.
    fraction: override for dynamic position sizing (defaults to config.MAX_POSITION_FRACTION)
    """
    if price <= 0:
        return 0
    if fraction is None:
        fraction = config.MAX_POSITION_FRACTION

    cap_by_dollar   = config.MAX_POSITION_VALUE / price
    cap_by_fraction = (equity * fraction) / price
    qty = math.floor(min(cap_by_dollar, cap_by_fraction))

    log.debug("[safety] qty: price=%.2f equity=%.2f frac=%.3f -> cap_$=%.1f cap_pct=%.1f -> qty=%d",
              price, equity, fraction, cap_by_dollar, cap_by_fraction, qty)

    if qty < 1:
        log.warning("[safety] qty=%d (< 1) at price=%.2f. Skipping.", qty, price)
    return qty


# ── Market hours ─────────────────────────────────────────────────────────────

def assert_market_open(trading_client: TradingClient) -> bool:
    clock = trading_client.get_clock()
    if not clock.is_open:
        log.warning("[safety] Market CLOSED. Next open: %s.",
                    clock.next_open.strftime("%Y-%m-%dT%H:%M:%S%z"))
        return False
    return True


# ── Kill switch (single symbol) ──────────────────────────────────────────────

def kill_switch(trading_client: TradingClient) -> None:
    """Emergency stop for config.SYMBOL only."""
    log.critical("[KILL SWITCH] Liquidating %s", config.SYMBOL)
    log_trade_event(log, "KILL_SWITCH_ACTIVATED", symbol=config.SYMBOL)

    try:
        orders = trading_client.get_orders(
            filter=GetOrdersRequest(status=QueryOrderStatus.OPEN,
                                    symbols=[config.SYMBOL])
        )
        for o in orders:
            trading_client.cancel_order_by_id(o.id)
    except Exception as exc:
        log.error("[kill_switch] Cancel orders failed: %s", exc)

    try:
        positions = trading_client.get_all_positions()
        held = next((p for p in positions if p.symbol == config.SYMBOL), None)
        if held and float(held.qty) > 0:
            qty = float(held.qty)
            order = trading_client.submit_order(
                MarketOrderRequest(symbol=config.SYMBOL, qty=qty,
                                   side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
            )
            log_trade_event(log, "KILL_SWITCH_SELL", symbol=config.SYMBOL,
                            qty=qty, order_id=order.id)
    except Exception as exc:
        log.error("[kill_switch] Liquidation failed: %s", exc)


# ── Graceful shutdown (ALL positions) ────────────────────────────────────────

def liquidate_all(trading_client: TradingClient) -> None:
    """
    Cancel ALL open orders + market-sell ALL positions.
    Called on Ctrl-C / SIGTERM / 'Sell All & Stop' button.
    """
    log.critical("=" * 60)
    log.critical("[SHUTDOWN] Cancelling ALL orders + liquidating ALL positions")
    log.critical("=" * 60)
    log_trade_event(log, "GRACEFUL_SHUTDOWN_STARTED")

    try:
        orders = trading_client.get_orders(
            filter=GetOrdersRequest(status=QueryOrderStatus.OPEN)
        )
        for o in orders:
            try:
                trading_client.cancel_order_by_id(o.id)
                log_trade_event(log, "ORDER_CANCELLED_SHUTDOWN",
                                order_id=o.id, symbol=o.symbol)
            except Exception as e:
                log.error("[shutdown] Cancel %s failed: %s", o.id, e)
    except Exception as exc:
        log.error("[shutdown] Fetch orders failed: %s", exc)

    try:
        positions = trading_client.get_all_positions()
        longs = [p for p in positions if float(p.qty) > 0]
        for pos in longs:
            try:
                sym = pos.symbol
                qty = float(pos.qty)
                if is_options_symbol(sym):
                    # Options: use LimitOrderRequest at current price (per D-08: mid-price approx)
                    limit_price = round(float(pos.current_price), 2)
                    if limit_price <= 0:
                        limit_price = 0.01  # floor to avoid zero-price limit
                    order = trading_client.submit_order(
                        LimitOrderRequest(
                            symbol=sym,
                            qty=qty,
                            side=OrderSide.SELL,
                            time_in_force=TimeInForce.DAY,
                            limit_price=limit_price,
                        )
                    )
                    log.info("[shutdown] Options LIMIT sell: %s %.0f @ $%.2f -> %s",
                             sym, qty, limit_price, order.id)
                    log_trade_event(log, "SHUTDOWN_OPTIONS_SELL", symbol=sym,
                                    qty=qty, limit_price=f"{limit_price:.2f}",
                                    order_id=str(order.id))
                else:
                    # Stocks: keep existing MarketOrderRequest
                    order = trading_client.submit_order(
                        MarketOrderRequest(symbol=sym, qty=qty,
                                           side=OrderSide.SELL,
                                           time_in_force=TimeInForce.DAY)
                    )
                    log.info("[shutdown] Sell submitted: %s %.0f -> %s", sym, qty, order.id)
                    log_trade_event(log, "SHUTDOWN_SELL", symbol=sym,
                                    qty=qty, order_id=str(order.id))
            except Exception as e:
                log.error("[shutdown] Sell %s failed: %s", pos.symbol, e)
        if longs:
            time.sleep(2)
    except Exception as exc:
        log.error("[shutdown] Fetch positions failed: %s", exc)

    log.critical("[SHUTDOWN] Done. All positions submitted for liquidation.")
    log_trade_event(log, "GRACEFUL_SHUTDOWN_COMPLETE")
