"""Tests for the Risk Manager agent."""

from unittest.mock import patch, MagicMock
from agents.event_bus import EventBus
from agents.risk_manager import RiskManager
from agents.base import StrategyDecision, RiskVerdict, RiskConstraints


def _mock_trading_client():
    """Create a simple mock trading client with sensible defaults."""
    client = MagicMock()
    acct = MagicMock()
    acct.equity = "500.00"
    acct.cash = "500.00"
    client.get_account.return_value = acct
    client.get_all_positions.return_value = []
    return client


def test_risk_manager_approves_valid_trade():
    """Valid trade with checks passing should be approved."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)
    decision = StrategyDecision(
        action="BUY", symbol="SOFI", confidence=9, entry_price=8.0,
        stop_loss=7.5, take_profit=9.0, reasoning="Strong signal",
        regime="trending", daily_plan="aggressive",
    )
    with patch("agents.risk_manager.check_pdt_allows_buy", return_value=True), \
         patch("agents.risk_manager.daily_loss_exceeded", return_value=False):
        result = agent.run({"decision": decision})
    verdict = result["verdict"]
    assert isinstance(verdict, RiskVerdict)
    assert verdict.approved is True
    assert verdict.adjusted_qty > 0


def test_risk_manager_rejects_pdt_violation():
    """PDT limit reached should be rejected with veto."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)
    decision = StrategyDecision(
        action="BUY", symbol="NVDA", confidence=9, entry_price=130.0,
        stop_loss=126.0, take_profit=140.0, reasoning="Signal",
    )
    with patch("agents.risk_manager.check_pdt_allows_buy", return_value=False), \
         patch("agents.risk_manager.daily_loss_exceeded", return_value=False):
        result = agent.run({"decision": decision})
    assert result["verdict"].approved is False
    assert "PDT" in result["verdict"].reason


def test_risk_manager_rejects_daily_loss_exceeded():
    """Daily loss limit exceeded should be rejected."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)
    decision = StrategyDecision(
        action="BUY", symbol="NVDA", confidence=9, entry_price=130.0,
        stop_loss=126.0, take_profit=140.0, reasoning="Signal",
    )
    with patch("agents.risk_manager.check_pdt_allows_buy", return_value=True), \
         patch("agents.risk_manager.daily_loss_exceeded", return_value=True):
        result = agent.run({"decision": decision})
    assert result["verdict"].approved is False
    assert "loss" in result["verdict"].reason.lower()


def test_risk_manager_caps_position_at_5_pct():
    """Position size capped at 5% of equity."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)
    decision = StrategyDecision(
        action="BUY", symbol="NVDA", confidence=9, entry_price=5.0,
        stop_loss=4.8, take_profit=5.5, reasoning="Cheap stock",
    )
    with patch("agents.risk_manager.check_pdt_allows_buy", return_value=True), \
         patch("agents.risk_manager.daily_loss_exceeded", return_value=False):
        result = agent.run({"decision": decision})
    assert result["verdict"].position_size_usd <= 25.0


def test_risk_manager_passes_through_wait():
    """WAIT action should not be approved for trading."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)
    decision = StrategyDecision(action="WAIT", reasoning="No setups")
    result = agent.run({"decision": decision})
    assert result["verdict"].approved is False


def test_risk_manager_kelly_criterion():
    """Kelly fraction calculation from trade history."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)
    agent._trade_history = [
        {"win": True, "pnl": 10.0}, {"win": True, "pnl": 8.0},
        {"win": False, "pnl": -5.0}, {"win": True, "pnl": 12.0},
        {"win": False, "pnl": -6.0},
    ]
    kelly = agent._calc_kelly_fraction()
    assert 0 < kelly < 1.0


def test_risk_manager_get_constraints():
    """Get constraints includes PDT, position, and exposure limits."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)
    with patch("agents.risk_manager.get_pdt_info", return_value={"remaining": 2}), \
         patch("agents.risk_manager.daily_loss_exceeded", return_value=False):
        constraints = agent.get_constraints()
    assert isinstance(constraints, RiskConstraints)
    assert constraints.pdt_trades_remaining == 2
    assert constraints.max_position_usd > 0


def test_risk_manager_rejects_invalid_entry_price():
    """Entry price must be > 0."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)
    decision = StrategyDecision(
        action="BUY", symbol="NVDA", confidence=9, entry_price=0.0,
        stop_loss=126.0, take_profit=140.0, reasoning="Bad price",
    )
    with patch("agents.risk_manager.check_pdt_allows_buy", return_value=True), \
         patch("agents.risk_manager.daily_loss_exceeded", return_value=False):
        result = agent.run({"decision": decision})
    assert result["verdict"].approved is False
    assert "price" in result["verdict"].reason.lower()


def test_risk_manager_rejects_position_too_small():
    """Position must be at least 1 share."""
    bus = EventBus()
    client = _mock_trading_client()
    # Mock low equity to make position too small
    acct = MagicMock()
    acct.equity = "1.00"  # $1 equity = can't afford even 1 share at $130
    client.get_account.return_value = acct

    agent = RiskManager(bus, client)
    decision = StrategyDecision(
        action="BUY", symbol="NVDA", confidence=9, entry_price=130.0,
        stop_loss=126.0, take_profit=140.0, reasoning="Expensive stock",
    )
    with patch("agents.risk_manager.check_pdt_allows_buy", return_value=True), \
         patch("agents.risk_manager.daily_loss_exceeded", return_value=False):
        result = agent.run({"decision": decision})
    assert result["verdict"].approved is False
    assert "too small" in result["verdict"].reason.lower()


def test_risk_manager_no_decision_provided():
    """Missing decision should be rejected."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)
    result = agent.run({})
    assert result["verdict"].approved is False
    assert "No decision" in result["verdict"].reason


def test_risk_manager_includes_var_calculation():
    """Approved verdict includes VaR calculation."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)
    decision = StrategyDecision(
        action="BUY", symbol="SOFI", confidence=9, entry_price=8.0,
        stop_loss=7.5, take_profit=9.0, reasoning="Strong signal",
    )
    with patch("agents.risk_manager.check_pdt_allows_buy", return_value=True), \
         patch("agents.risk_manager.daily_loss_exceeded", return_value=False):
        result = agent.run({"decision": decision})
    verdict = result["verdict"]
    assert verdict.var_95 > 0
    assert verdict.kelly_fraction > 0


def test_risk_manager_tracks_drawdown():
    """Max drawdown tracking across trades."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)

    # Simulate equity changes
    agent._peak_equity = 100.0
    agent._update_drawdown(90.0)  # 10% drawdown
    assert agent._max_drawdown == 0.10

    agent._update_drawdown(95.0)  # Better, but still drawdown
    assert agent._max_drawdown == 0.10  # No change

    agent._update_drawdown(110.0)  # New peak
    assert agent._peak_equity == 110.0
    assert agent._max_drawdown == 0.10  # Preserved


def test_risk_manager_trade_history_capped():
    """Trade history limited to 100 entries."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)

    # Add 110 trades
    for i in range(110):
        agent.record_trade({"win": True, "pnl": 10.0})

    # Should only keep last 100
    assert len(agent._trade_history) == 100


def test_risk_manager_emits_veto_event():
    """Risk rejection should emit veto event."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)

    veto_events = []
    bus.subscribe("risk.veto", lambda e: veto_events.append(e))

    decision = StrategyDecision(
        action="BUY", symbol="NVDA", confidence=9, entry_price=130.0,
        stop_loss=126.0, take_profit=140.0, reasoning="Signal",
    )
    with patch("agents.risk_manager.check_pdt_allows_buy", return_value=False), \
         patch("agents.risk_manager.daily_loss_exceeded", return_value=False):
        result = agent.run({"decision": decision})

    assert len(veto_events) == 1
    assert veto_events[0]["symbol"] == "NVDA"
    assert "PDT" in veto_events[0]["reason"]


def test_risk_manager_kelly_with_insufficient_history():
    """With < 5 trades, use max position fraction."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)
    agent._trade_history = [{"win": True, "pnl": 10.0}]  # Only 1 trade

    kelly = agent._calc_kelly_fraction()
    assert kelly == 0.05  # Should be _MAX_POSITION_FRACTION


def test_risk_manager_kelly_with_no_wins_or_losses():
    """Kelly with all wins or all losses falls back to max."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)
    agent._trade_history = [
        {"win": True, "pnl": 10.0}, {"win": True, "pnl": 8.0},
        {"win": True, "pnl": 12.0}, {"win": True, "pnl": 5.0},
        {"win": True, "pnl": 7.0},
    ]

    kelly = agent._calc_kelly_fraction()
    assert kelly == 0.05  # Falls back to max
