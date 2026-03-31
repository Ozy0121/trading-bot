"""Tests for BaseAgent and dataclasses."""

from datetime import datetime
from dataclasses import asdict
from agents.base import (
    BaseAgent, QuantOutput, NewsOutput, StrategyDecision,
    RiskConstraints, RiskVerdict, ExecutionResult, AuditReport,
)
from agents.event_bus import EventBus


class DummyAgent(BaseAgent):
    name = "dummy"

    def _execute(self, input_data: dict) -> dict:
        return {"result": input_data.get("x", 0) * 2}


class FailingAgent(BaseAgent):
    name = "failing"

    def _execute(self, input_data: dict) -> dict:
        raise ValueError("intentional failure")


def test_agent_run_success():
    """Successful run updates status and last_output."""
    bus = EventBus()
    agent = DummyAgent(bus)
    result = agent.run({"x": 5})
    assert result == {"result": 10}
    assert agent.status == "idle"
    assert agent.last_output == {"result": 10}
    assert agent.last_error is None
    assert isinstance(agent.last_run, datetime)


def test_agent_run_error():
    """Failed run sets status to error and records the error message."""
    bus = EventBus()
    agent = FailingAgent(bus)
    result = agent.run({})
    assert result == {}
    assert agent.status == "error"
    assert "intentional failure" in agent.last_error


def test_agent_emits_status_events():
    """Agent emits agent.status events on start and finish."""
    bus = EventBus()
    events = []
    bus.subscribe("agent.status", lambda d: events.append(d))
    agent = DummyAgent(bus)
    agent.run({"x": 1})
    assert len(events) == 2
    assert events[0]["status"] == "running"
    assert events[1]["status"] == "idle"


def test_agent_emits_output_event():
    """Agent emits agent.output event on success."""
    bus = EventBus()
    outputs = []
    bus.subscribe("agent.output", lambda d: outputs.append(d))
    agent = DummyAgent(bus)
    agent.run({"x": 3})
    assert len(outputs) == 1
    assert outputs[0]["agent"] == "dummy"


def test_agent_health_check():
    """Health check returns True for idle/running, False for error."""
    bus = EventBus()
    agent = DummyAgent(bus)
    assert agent.health_check() is True
    agent.status = "error"
    assert agent.health_check() is False


def test_quant_output_dataclass():
    """QuantOutput can be created and serialized."""
    q = QuantOutput(
        symbol="NVDA", composite_score=82.3, rsi=45.2, macd_signal="bullish",
        atr=3.5, beta=1.2, volatility_20d=0.35, volatility_60d=0.28,
        stochastic_rsi=0.65, rate_of_change=5.2, money_flow_index=62.0,
        on_balance_volume=1500000, vwap=130.5, bollinger_pct_b=0.72,
        probability_3pct_3d=0.45, expected_value=1.25,
        sharpe_ratio=1.8, sortino_ratio=2.1,
        short_sma=128.0, long_sma=125.0, bb_upper=135.0, bb_lower=120.0,
        macd_value=1.5, macd_hist=0.3, volume_ratio=2.5,
        sector_score=7.0, sentiment_score=6.5, technical_score=8.0,
    )
    d = asdict(q)
    assert d["symbol"] == "NVDA"
    assert d["composite_score"] == 82.3


def test_strategy_decision_dataclass():
    """StrategyDecision can be created."""
    sd = StrategyDecision(
        action="BUY", symbol="NVDA", confidence=9, entry_price=130.0,
        stop_loss=126.0, take_profit=140.0, reasoning="Strong breakout",
        regime="trending", daily_plan="aggressive",
    )
    assert sd.action == "BUY"
    assert sd.confidence == 9


def test_risk_verdict_dataclass():
    """RiskVerdict can be created."""
    rv = RiskVerdict(
        approved=True, reason="All checks passed", adjusted_qty=5,
        position_size_usd=125.0, stop_loss=126.0, take_profit=140.0,
        kelly_fraction=0.08, var_95=15.0, max_drawdown=0.05,
    )
    assert rv.approved is True
