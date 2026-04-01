"""
Agent Coordinator — orchestrates the 6-agent trading pipeline.

Pipeline: Quant + News (parallel) -> Strategist -> Risk Manager -> Executor
Event bus provides observability. Auditor logs everything.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient

from agents.event_bus import EventBus
from agents.quant_analyst import QuantAnalyst
from agents.news_analyst import NewsAnalyst
from agents.strategist import Strategist
from agents.risk_manager import RiskManager
from agents.executor import Executor
from agents.auditor import Auditor
import config
import state as shared_state
from logger_setup import get_logger

log = get_logger()


class AgentCoordinator:
    def __init__(self, trading_client: TradingClient,
                 data_client: StockHistoricalDataClient,
                 event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self._trading_client = trading_client
        self._data_client = data_client

        self.quant = QuantAnalyst(event_bus)
        self.news = NewsAnalyst(event_bus)
        self.strategist = Strategist(event_bus)
        self.risk = RiskManager(event_bus, trading_client)
        self.executor = Executor(event_bus, trading_client)
        self.auditor = Auditor(event_bus)

        self._cycle_count = 0
        self._last_cycle: datetime | None = None

    def startup_sequence(self) -> None:
        """Run all agents through startup checks and load journals."""
        log.info("[coordinator] Running startup sequence...")
        result = self.executor.startup_check()
        if not result.get("all_protected", True):
            log.warning("[coordinator] STARTUP: Some positions lack stop-losses!")
        self.auditor.load_journal()
        log.info("[coordinator] Startup complete. Ready to trade.")

    def run_cycle(self) -> dict:
        """Execute one full trading cycle: scan -> decide -> verify -> execute."""
        self._cycle_count += 1
        self._last_cycle = datetime.now(timezone.utc)
        log.info("[coordinator] ── Cycle %d starting ──", self._cycle_count)

        symbols = config.SWING_WATCHLIST

        # Phase 1: Parallel scan
        quant_result = {"outputs": []}
        news_result = {"outputs": []}
        with ThreadPoolExecutor(max_workers=2) as pool:
            quant_future = pool.submit(self.quant.run, {"symbols": symbols})
            news_future = pool.submit(self.news.run, {"symbols": symbols})
            for future in as_completed([quant_future, news_future]):
                try:
                    if future == quant_future:
                        quant_result = future.result()
                    else:
                        news_result = future.result()
                except Exception as exc:
                    log.error("[coordinator] Parallel scan error: %s", exc)

        quant_outputs = quant_result.get("outputs", [])
        news_outputs = news_result.get("outputs", [])
        self._update_dashboard_state(quant_outputs, news_outputs)

        # Phase 2: Risk constraints
        constraints = self.risk.get_constraints()

        # Phase 3: Strategist decides
        strat_result = self.strategist.run({
            "quant_outputs": quant_outputs,
            "news_outputs": news_outputs,
            "risk_constraints": constraints,
        })
        decision = strat_result.get("decision")

        if decision is None or decision.action != "BUY":
            action = decision.action if decision else "WAIT"
            reason = decision.reasoning if decision else "No decision"
            log.info("[coordinator] Cycle %d: %s — %s", self._cycle_count, action, reason)
            self._emit_cycle_complete(action)
            return {"action": action, "reasoning": reason}

        # Phase 4: Risk Manager reviews
        risk_result = self.risk.run({"decision": decision})
        verdict = risk_result.get("verdict")

        if verdict is None or not verdict.approved:
            reason = verdict.reason if verdict else "Risk check failed"
            log.info("[coordinator] Cycle %d: Risk REJECTED — %s", self._cycle_count, reason)
            self._emit_cycle_complete("REJECTED")
            return {"action": "REJECTED", "symbol": decision.symbol, "reasoning": reason}

        # Phase 5: Executor places order
        exec_result = self.executor.run({
            "verdict": verdict, "symbol": decision.symbol, "entry_price": decision.entry_price,
        })
        result = exec_result.get("result")

        # Phase 6: Auditor logs
        if result and result.success:
            self.auditor.record_trade({
                "symbol": decision.symbol, "action": "BUY", "qty": result.qty,
                "entry_price": result.fill_price, "pnl": 0.0, "win": None,
                "reasoning": decision.reasoning, "confidence": decision.confidence,
            })

        self._emit_cycle_complete("BUY" if result and result.success else "FAILED")
        return {
            "action": "BUY" if result and result.success else "FAILED",
            "symbol": decision.symbol,
            "qty": result.qty if result else 0,
            "fill_price": result.fill_price if result else 0,
        }

    def shutdown_sequence(self) -> None:
        """Run all agents through shutdown checks and save journals."""
        log.info("[coordinator] Running shutdown sequence...")
        self.executor.shutdown_check()
        self.auditor.save_journal()
        log.info("[coordinator] Shutdown complete.")

    def get_agents_status(self) -> dict:
        """Return status of all agents and pipeline state."""
        agents = [self.quant, self.news, self.strategist, self.risk, self.executor, self.auditor]
        return {
            "agents": [a.to_status_dict() for a in agents],
            "pipeline": {
                "last_cycle": self._last_cycle.isoformat() if self._last_cycle else None,
                "cycle_count": self._cycle_count,
            },
        }

    def _update_dashboard_state(self, quant_outputs: list, news_outputs: list) -> None:
        """Update shared state with scan results for dashboard display."""
        shared_state.update(
            agent_quant_count=len(quant_outputs),
            agent_news_count=len(news_outputs),
        )

    def _emit_cycle_complete(self, action: str) -> None:
        """Emit cycle completion event to bus."""
        self.event_bus.emit("cycle.complete", {
            "cycle": self._cycle_count, "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
