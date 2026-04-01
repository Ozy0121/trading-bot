"""Tests for the AgentCoordinator pipeline."""

from unittest.mock import patch, MagicMock
from agents.event_bus import EventBus
from agents.coordinator import AgentCoordinator
from agents.base import (
    QuantOutput, NewsOutput, StrategyDecision, RiskVerdict,
    ExecutionResult, RiskConstraints,
)


def _mock_trading_client():
    client = MagicMock()
    acct = MagicMock()
    acct.equity = "500.00"
    acct.cash = "500.00"
    client.get_account.return_value = acct
    client.get_all_positions.return_value = []
    return client


def test_coordinator_creates_all_agents():
    bus = EventBus()
    client = _mock_trading_client()
    coord = AgentCoordinator(client, client, bus)
    assert coord.quant is not None
    assert coord.news is not None
    assert coord.strategist is not None
    assert coord.risk is not None
    assert coord.executor is not None
    assert coord.auditor is not None


def test_coordinator_run_cycle_wait():
    bus = EventBus()
    client = _mock_trading_client()
    coord = AgentCoordinator(client, client, bus)
    quant_result = {"outputs": []}
    news_result = {"outputs": []}
    with patch.object(coord.quant, 'run', return_value=quant_result), \
         patch.object(coord.news, 'run', return_value=news_result), \
         patch.object(coord.risk, 'get_constraints', return_value=RiskConstraints(
             max_position_usd=25.0, pdt_trades_remaining=2,
             daily_loss_remaining=20.0, current_exposure_usd=0.0, held_symbols=[],
         )):
        result = coord.run_cycle()
    assert result["action"] == "WAIT"


def test_coordinator_run_cycle_buy():
    bus = EventBus()
    client = _mock_trading_client()
    coord = AgentCoordinator(client, client, bus)
    quant_out = MagicMock(spec=QuantOutput)
    quant_out.symbol = "NVDA"
    quant_out.composite_score = 80.0
    decision = StrategyDecision(
        action="BUY", symbol="NVDA", confidence=9, entry_price=130.0,
        stop_loss=126.0, take_profit=140.0, reasoning="Strong",
        regime="trending", daily_plan="aggressive",
    )
    verdict = RiskVerdict(
        approved=True, reason="OK", adjusted_qty=3,
        position_size_usd=390.0, stop_loss=126.0, take_profit=140.0,
    )
    exec_result = ExecutionResult(
        success=True, order_id="123", symbol="NVDA", qty=3,
        fill_price=130.0, status="filled",
    )
    with patch.object(coord.quant, 'run', return_value={"outputs": [quant_out]}), \
         patch.object(coord.news, 'run', return_value={"outputs": []}), \
         patch.object(coord.risk, 'get_constraints', return_value=RiskConstraints(
             max_position_usd=25.0, pdt_trades_remaining=2,
             daily_loss_remaining=20.0, current_exposure_usd=0.0, held_symbols=[],
         )), \
         patch.object(coord.strategist, 'run', return_value={"decision": decision}), \
         patch.object(coord.risk, 'run', return_value={"verdict": verdict}), \
         patch.object(coord.executor, 'run', return_value={"result": exec_result}):
        result = coord.run_cycle()
    assert result["action"] == "BUY"
    assert result["symbol"] == "NVDA"


def test_coordinator_startup_sequence():
    bus = EventBus()
    client = _mock_trading_client()
    coord = AgentCoordinator(client, client, bus)
    with patch.object(coord.executor, 'startup_check',
                      return_value={"all_protected": True, "unprotected": []}), \
         patch.object(coord.auditor, 'load_journal'):
        coord.startup_sequence()


def test_coordinator_agents_status():
    bus = EventBus()
    client = _mock_trading_client()
    coord = AgentCoordinator(client, client, bus)
    status = coord.get_agents_status()
    assert len(status["agents"]) == 6
    assert all(a["status"] == "idle" for a in status["agents"])
