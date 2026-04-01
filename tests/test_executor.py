"""Tests for the Executor agent."""

from unittest.mock import patch, MagicMock
from agents.event_bus import EventBus
from agents.executor import Executor
from agents.base import RiskVerdict, ExecutionResult


def _mock_trading_client():
    client = MagicMock()
    order = MagicMock()
    order.id = "test-order-123"
    order.status = "filled"
    order.filled_qty = "5"
    order.filled_avg_price = "130.50"
    client.submit_order.return_value = order
    client.get_all_positions.return_value = []
    return client


def test_executor_places_bracket_order():
    bus = EventBus()
    events = []
    bus.subscribe("trade.executed", lambda d: events.append(d))
    client = _mock_trading_client()
    agent = Executor(bus, client)
    verdict = RiskVerdict(
        approved=True, reason="All checks passed", adjusted_qty=5,
        position_size_usd=650.0, stop_loss=126.0, take_profit=140.0,
        kelly_fraction=0.05, var_95=10.0, max_drawdown=0.02,
    )
    with patch("agents.executor.poll_order_fill", return_value=client.submit_order()):
        result = agent.run({"verdict": verdict, "symbol": "NVDA", "entry_price": 130.0})
    assert result["result"].success is True
    assert len(events) == 1


def test_executor_skips_rejected_verdict():
    bus = EventBus()
    client = _mock_trading_client()
    agent = Executor(bus, client)
    verdict = RiskVerdict(approved=False, reason="PDT limit")
    result = agent.run({"verdict": verdict, "symbol": "NVDA", "entry_price": 130.0})
    assert result["result"].success is False
    assert client.submit_order.call_count == 0


def test_executor_startup_checks_positions():
    bus = EventBus()
    client = _mock_trading_client()
    agent = Executor(bus, client)
    with patch("agents.executor.check_shutdown_stop_losses",
               return_value={"all_protected": True, "unprotected": []}):
        result = agent.startup_check()
    assert result["all_protected"] is True


def test_executor_handles_order_rejection():
    bus = EventBus()
    client = _mock_trading_client()
    rejected = MagicMock()
    rejected.id = "rej-123"
    rejected.status = "rejected"
    rejected.filled_qty = "0"
    client.submit_order.return_value = rejected
    agent = Executor(bus, client)
    verdict = RiskVerdict(
        approved=True, reason="OK", adjusted_qty=5,
        position_size_usd=650.0, stop_loss=126.0, take_profit=140.0,
    )
    with patch("agents.executor.poll_order_fill", return_value=rejected):
        result = agent.run({"verdict": verdict, "symbol": "NVDA", "entry_price": 130.0})
    assert result["result"].success is False
    assert result["result"].status == "rejected"
