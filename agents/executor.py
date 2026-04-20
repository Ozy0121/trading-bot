"""
Agent 5 — The Executor.

Places and manages all orders. Wraps bot.py order functions and safety.py
stop-loss management.

Input: {"verdict": RiskVerdict, "symbol": str, "entry_price": float}
Output: {"result": ExecutionResult}
"""

from __future__ import annotations

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

from agents.base import BaseAgent, RiskVerdict, ExecutionResult
from agents.event_bus import EventBus
from safety import (
    check_shutdown_stop_losses,
    poll_order_fill,
    record_buy_date,
    update_peak_price,
)
from logger_setup import get_logger, log_trade_event

log = get_logger()


class Executor(BaseAgent):
    """Places and manages orders via Alpaca. Wraps safety.py guardrails."""

    name = "executor"

    def __init__(self, event_bus: EventBus, trading_client: TradingClient) -> None:
        super().__init__(event_bus)
        self._trading_client = trading_client

    def _execute(self, input_data: dict) -> dict:
        """Execute trade if verdict approved. Skip if rejected."""
        verdict: RiskVerdict = input_data.get("verdict")
        symbol: str = input_data.get("symbol", "")
        entry_price: float = input_data.get("entry_price", 0.0)

        if verdict is None or not verdict.approved:
            reason = verdict.reason if verdict else "No verdict"
            return {"result": ExecutionResult(
                success=False, symbol=symbol, status="skipped", message=reason,
            )}

        return {"result": self._place_bracket_order(
            symbol, verdict.adjusted_qty, entry_price,
            verdict.stop_loss, verdict.take_profit,
        )}

    def _summarize_output(self) -> str:
        r = self.last_output.get("result")
        if not r:
            return "No data yet"
        if r.success:
            return f"Filled {r.qty} {r.symbol} @ ${r.fill_price:.2f}"
        return f"{r.status}: {r.message}"

    def _place_bracket_order(self, symbol: str, qty: int,
                             entry_price: float, stop_loss: float,
                             take_profit: float) -> ExecutionResult:
        """Place a bracket order (market entry + stop loss + take profit)."""
        if qty < 1 or entry_price <= 0:
            return ExecutionResult(
                success=False, symbol=symbol, status="error",
                message=f"Invalid params: qty={qty}, price={entry_price}",
            )

        stop_price = round(stop_loss, 2)
        profit_price = round(take_profit, 2)

        log.info("[executor] Placing bracket order: %s qty=%d SL=$%.2f TP=$%.2f",
                 symbol, qty, stop_price, profit_price)
        log_trade_event(log, "EXECUTOR_ORDER_ATTEMPT", symbol=symbol, qty=qty)

        try:
            order = self._trading_client.submit_order(
                MarketOrderRequest(
                    symbol=symbol, qty=qty, side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY, order_class=OrderClass.BRACKET,
                    stop_loss=StopLossRequest(stop_price=stop_price),
                    take_profit=TakeProfitRequest(limit_price=profit_price),
                )
            )
        except Exception as exc:
            log.error("[executor] Order submission failed: %s", exc)
            return ExecutionResult(success=False, symbol=symbol, status="error", message=str(exc))

        try:
            filled = poll_order_fill(self._trading_client, str(order.id))
        except Exception as exc:
            log.warning("[executor] Fill poll error: %s", exc)
            filled = order

        status_str = str(filled.status).lower() if hasattr(filled.status, 'name') else str(filled.status)

        if "rejected" in status_str:
            log.warning("[executor] Order REJECTED for %s", symbol)
            return ExecutionResult(
                success=False, order_id=str(order.id), symbol=symbol,
                status="rejected", message="Order rejected by Alpaca",
            )

        filled_qty = int(float(filled.filled_qty)) if filled.filled_qty else 0
        fill_price = float(filled.filled_avg_price) if filled.filled_avg_price else entry_price

        log.info("[executor] Order FILLED: %s qty=%d @ $%.2f", symbol, filled_qty, fill_price)
        log_trade_event(log, "EXECUTOR_FILL", symbol=symbol, qty=filled_qty, price=f"{fill_price:.2f}")

        try:
            record_buy_date(symbol)
        except Exception:
            pass

        try:
            update_peak_price(symbol, fill_price)
        except Exception:
            pass

        self.event_bus.emit("trade.executed", {
            "agent": self.name, "symbol": symbol, "qty": filled_qty,
            "price": fill_price, "order_id": str(order.id),
        })

        return ExecutionResult(
            success=True, order_id=str(order.id), symbol=symbol,
            qty=filled_qty, fill_price=fill_price, status="filled",
            message=f"Filled {filled_qty} shares @ ${fill_price:.2f}",
        )

    def startup_check(self) -> dict:
        """Check that all open positions have stop-loss protection."""
        try:
            result = check_shutdown_stop_losses(self._trading_client)
            if not result["all_protected"]:
                for sym in result["unprotected"]:
                    log.warning("[executor] STARTUP: %s has NO stop-loss!", sym)
            return result
        except Exception as exc:
            log.error("[executor] Startup check failed: %s", exc)
            return {"all_protected": False, "unprotected": [], "error": str(exc)}

    def shutdown_check(self) -> dict:
        """Verify all positions protected before shutdown."""
        return self.startup_check()
