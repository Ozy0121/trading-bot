"""
Agent 6 — The Risk Manager.

Protects the account. Has VETO power over all trades.
Wraps safety.py for hard rules, adds Kelly Criterion, VaR, drawdown tracking.

Input: {"decision": StrategyDecision}
Output: {"verdict": RiskVerdict}
"""

from __future__ import annotations

import math

from alpaca.trading.client import TradingClient

from agents.base import BaseAgent, StrategyDecision, RiskVerdict, RiskConstraints
from agents.event_bus import EventBus
from safety import (
    check_pdt_allows_buy,
    daily_loss_exceeded,
    get_pdt_info,
)
import config
from logger_setup import get_logger

log = get_logger()

_MAX_POSITION_FRACTION = 0.05


class RiskManager(BaseAgent):
    """Central risk authority. Approves or vetos all trades."""

    name = "risk_manager"

    def __init__(self, event_bus: EventBus, trading_client: TradingClient) -> None:
        super().__init__(event_bus)
        self._trading_client = trading_client
        self._trade_history: list[dict] = []
        self._peak_equity: float = 0.0
        self._max_drawdown: float = 0.0

    def _execute(self, input_data: dict) -> dict:
        """Evaluate decision and return approval verdict with risk constraints."""
        decision: StrategyDecision = input_data.get("decision")
        if decision is None:
            return {"verdict": RiskVerdict(approved=False, reason="No decision provided")}

        if decision.action != "BUY":
            return {"verdict": RiskVerdict(
                approved=False,
                reason=f"Action is {decision.action}, not BUY — no trade to approve",
            )}

        # ── Hard rules: PDT and daily loss ───────────────────────────────────

        if not check_pdt_allows_buy(self._trading_client):
            self.event_bus.emit("risk.veto", {
                "agent": self.name, "symbol": decision.symbol, "reason": "PDT limit reached",
            })
            return {"verdict": RiskVerdict(approved=False, reason="PDT limit reached")}

        if daily_loss_exceeded():
            self.event_bus.emit("risk.veto", {
                "agent": self.name, "symbol": decision.symbol, "reason": "Daily loss limit exceeded",
            })
            return {"verdict": RiskVerdict(approved=False, reason="Daily loss limit exceeded")}

        # ── Position sizing ──────────────────────────────────────────────────

        equity = self._get_equity()
        max_position_usd = equity * _MAX_POSITION_FRACTION
        kelly = self._calc_kelly_fraction()
        kelly_position_usd = equity * kelly
        position_usd = min(kelly_position_usd, max_position_usd)

        if decision.entry_price <= 0:
            return {"verdict": RiskVerdict(approved=False, reason="Invalid entry price")}

        qty = int(position_usd / decision.entry_price)
        if qty < 1:
            return {"verdict": RiskVerdict(
                approved=False,
                reason=f"Position too small: ${position_usd:.2f} / ${decision.entry_price:.2f} = 0 shares",
            )}

        # ── Risk metrics ─────────────────────────────────────────────────────

        var_95 = self._calc_var(position_usd, decision.entry_price)
        self._update_drawdown(equity)

        log.info(
            "[risk_manager] APPROVED %s: qty=%d, size=$%.2f, kelly=%.2f%%, VaR=$%.2f",
            decision.symbol, qty, qty * decision.entry_price, kelly * 100, var_95,
        )

        return {"verdict": RiskVerdict(
            approved=True,
            reason="All checks passed",
            adjusted_qty=qty,
            position_size_usd=round(qty * decision.entry_price, 2),
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            kelly_fraction=round(kelly, 4),
            var_95=round(var_95, 2),
            max_drawdown=round(self._max_drawdown, 4),
        )}

    def _summarize_output(self) -> str:
        v = self.last_output.get("verdict")
        if not v:
            return "No data yet"
        if v.approved:
            return f"Approved: {v.adjusted_qty} shares, ${v.position_size_usd:.0f} size, VaR ${v.var_95:.0f}"
        return f"Blocked: {v.reason}"

    def get_constraints(self) -> RiskConstraints:
        """Return current risk constraints for the Strategist."""
        equity = self._get_equity()
        pdt_info = get_pdt_info(self._trading_client)
        remaining = pdt_info.get("remaining", 3) if isinstance(pdt_info, dict) else 3
        loss_exceeded = daily_loss_exceeded(equity)
        held = self._get_held_symbols()
        return RiskConstraints(
            max_position_usd=round(equity * _MAX_POSITION_FRACTION, 2),
            pdt_trades_remaining=remaining,
            daily_loss_remaining=round(config.DAILY_LOSS_LIMIT - abs(self._get_daily_pnl()), 2),
            current_exposure_usd=self._get_exposure(),
            held_symbols=held,
        )

    def _get_equity(self) -> float:
        """Fetch current account equity. Fallback to $500 on error."""
        try:
            acct = self._trading_client.get_account()
            return float(acct.equity)
        except Exception:
            return 500.0

    def _get_daily_pnl(self) -> float:
        """Fetch daily PnL from shared state."""
        try:
            import state as shared_state
            snap = shared_state.snapshot()
            return snap.get("daily_pnl", 0.0)
        except Exception:
            return 0.0

    def _get_exposure(self) -> float:
        """Sum market value of all open positions."""
        try:
            positions = self._trading_client.get_all_positions()
            return sum(float(p.market_value) for p in positions)
        except Exception:
            return 0.0

    def _get_held_symbols(self) -> list[str]:
        """List of symbols currently held with qty > 0."""
        try:
            positions = self._trading_client.get_all_positions()
            return [p.symbol for p in positions if float(p.qty) > 0]
        except Exception:
            return []

    def _calc_kelly_fraction(self) -> float:
        """Calculate Kelly Criterion bet fraction from win rate and avg win/loss.

        f* = (bp - q) / b where:
        - p = win rate
        - q = loss rate (1 - p)
        - b = avg_win / avg_loss (payoff ratio)

        Returns clamped to [0.01, 0.05] with 50% safety margin.
        """
        if len(self._trade_history) < 5:
            return _MAX_POSITION_FRACTION

        wins = [t for t in self._trade_history if t.get("win")]
        losses = [t for t in self._trade_history if not t.get("win")]

        if not wins or not losses:
            return _MAX_POSITION_FRACTION

        p = len(wins) / len(self._trade_history)
        q = 1 - p
        avg_win = sum(abs(t["pnl"]) for t in wins) / len(wins)
        avg_loss = sum(abs(t["pnl"]) for t in losses) / len(losses)

        if avg_loss == 0:
            return _MAX_POSITION_FRACTION

        b = avg_win / avg_loss
        kelly = (b * p - q) / b

        # Apply 50% safety margin and cap at max
        kelly = max(0.01, min(kelly * 0.5, _MAX_POSITION_FRACTION))
        return kelly

    def _calc_var(self, position_usd: float, price: float, confidence: float = 0.95) -> float:
        """Calculate Value at Risk at 95% confidence level.

        VaR = Position * Daily Vol * Z-Score
        Assumes 2% daily volatility and 1.645 z-score for 95%.
        """
        daily_vol = 0.02
        z_score = 1.645
        return position_usd * daily_vol * z_score

    def _update_drawdown(self, equity: float) -> None:
        """Track peak equity and max drawdown."""
        if equity > self._peak_equity:
            self._peak_equity = equity

        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            self._max_drawdown = max(self._max_drawdown, drawdown)

    def record_trade(self, trade: dict) -> None:
        """Record a completed trade for Kelly Criterion calculation.

        Expected keys: win (bool), pnl (float).
        """
        self._trade_history.append(trade)
        if len(self._trade_history) > 100:
            self._trade_history = self._trade_history[-100:]
