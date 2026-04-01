"""Tests for the Strategist agent."""

from unittest.mock import patch, MagicMock
from agents.event_bus import EventBus
from agents.strategist import Strategist
from agents.base import QuantOutput, NewsOutput, RiskConstraints, StrategyDecision


def _make_quant(symbol: str, score: float) -> QuantOutput:
    return QuantOutput(
        symbol=symbol, composite_score=score, rsi=45.0, macd_signal="bullish",
        atr=2.5, beta=1.1, volatility_20d=0.25, volatility_60d=0.20,
        stochastic_rsi=0.3, rate_of_change=5.0, money_flow_index=60.0,
        on_balance_volume=1000000, vwap=130.0, bollinger_pct_b=0.4,
        probability_3pct_3d=0.35, expected_value=0.02,
        sharpe_ratio=1.5, sortino_ratio=2.0,
        short_sma=131.0, long_sma=128.0, bb_upper=135.0, bb_lower=125.0,
        macd_value=1.2, macd_hist=0.4, volume_ratio=2.5,
        sector_score=7.0, sentiment_score=6.5, technical_score=8.0,
    )


def _make_news(symbol: str, score: float = 70.0) -> NewsOutput:
    return NewsOutput(
        symbol=symbol, sentiment_score=score, sentiment_label="bullish",
        headline_count=5, key_headlines=["Good news"], has_earnings_soon=False,
        earnings_days_away=None, analyst_upgrade=True, analyst_downgrade=False,
        unusual_volume=False, sector_hot=True, macro_catalysts=[], risk_flags=[],
    )


def _make_constraints() -> RiskConstraints:
    return RiskConstraints(
        max_position_usd=25.0, pdt_trades_remaining=2,
        daily_loss_remaining=20.0, current_exposure_usd=0.0, held_symbols=[],
    )


def test_strategist_returns_wait_when_no_candidates():
    """If no quant outputs or all below threshold, return WAIT."""
    bus = EventBus()
    agent = Strategist(bus)
    result = agent.run({
        "quant_outputs": [_make_quant("NVDA", 30.0)],
        "news_outputs": [_make_news("NVDA")],
        "risk_constraints": _make_constraints(),
    })
    decision = result["decision"]
    assert isinstance(decision, StrategyDecision)
    assert decision.action == "WAIT"


def test_strategist_calls_ai_when_candidate_above_threshold():
    """When a candidate exceeds threshold, AI is called."""
    bus = EventBus()
    agent = Strategist(bus)
    mock_response = StrategyDecision(
        action="BUY", symbol="NVDA", confidence=9, entry_price=130.0,
        stop_loss=126.0, take_profit=140.0, reasoning="Strong breakout",
        regime="trending", daily_plan="aggressive",
    )
    with patch.object(agent, '_call_ai', return_value=mock_response):
        result = agent.run({
            "quant_outputs": [_make_quant("NVDA", 75.0)],
            "news_outputs": [_make_news("NVDA")],
            "risk_constraints": _make_constraints(),
        })
    decision = result["decision"]
    assert decision.action == "BUY"
    assert decision.confidence == 9


def test_strategist_rejects_low_confidence():
    """AI response with confidence < 8 is converted to WAIT."""
    bus = EventBus()
    agent = Strategist(bus)
    mock_response = StrategyDecision(
        action="BUY", symbol="NVDA", confidence=5,
        entry_price=130.0, stop_loss=126.0, take_profit=140.0,
        reasoning="Weak signal", regime="choppy", daily_plan="conservative",
    )
    with patch.object(agent, '_call_ai', return_value=mock_response):
        result = agent.run({
            "quant_outputs": [_make_quant("NVDA", 75.0)],
            "news_outputs": [_make_news("NVDA")],
            "risk_constraints": _make_constraints(),
        })
    decision = result["decision"]
    assert decision.action == "WAIT"


def test_strategist_no_api_call_when_no_symbols():
    """No API call when no candidates pass threshold."""
    bus = EventBus()
    agent = Strategist(bus)
    result = agent.run({
        "quant_outputs": [],
        "news_outputs": [],
        "risk_constraints": _make_constraints(),
    })
    assert result["decision"].action == "WAIT"


def test_strategist_respects_pdt_constraint():
    """Returns WAIT when PDT trades remaining = 0."""
    bus = EventBus()
    agent = Strategist(bus)
    constraints = RiskConstraints(
        max_position_usd=25.0, pdt_trades_remaining=0,
        daily_loss_remaining=20.0, current_exposure_usd=0.0, held_symbols=[],
    )
    result = agent.run({
        "quant_outputs": [_make_quant("NVDA", 75.0)],
        "news_outputs": [_make_news("NVDA")],
        "risk_constraints": constraints,
    })
    assert result["decision"].action == "WAIT"
    assert "PDT" in result["decision"].reasoning


def test_strategist_fallback_on_missing_api_key():
    """When API key is missing, fallback strategy is used."""
    bus = EventBus()
    agent = Strategist(bus)

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
        result = agent.run({
            "quant_outputs": [_make_quant("NVDA", 75.0)],
            "news_outputs": [_make_news("NVDA")],
            "risk_constraints": _make_constraints(),
        })
    # Fallback should check if score >= 70 and other conditions
    decision = result["decision"]
    assert decision.action in ["BUY", "WAIT"]


def test_strategist_fallback_logic_high_score():
    """Fallback strategy BUYs if score >= 70 and conditions met."""
    bus = EventBus()
    agent = Strategist(bus)

    quant = QuantOutput(
        symbol="NVDA", composite_score=75.0, rsi=45.0, macd_signal="bullish",
        atr=2.5, beta=1.1, volatility_20d=0.25, volatility_60d=0.20,
        stochastic_rsi=0.3, rate_of_change=5.0, money_flow_index=60.0,
        on_balance_volume=1000000, vwap=130.0, bollinger_pct_b=0.4,
        probability_3pct_3d=0.35, expected_value=0.02,
        sharpe_ratio=1.5, sortino_ratio=2.0,
        short_sma=131.0, long_sma=128.0, bb_upper=135.0, bb_lower=125.0,
        macd_value=1.2, macd_hist=0.4, volume_ratio=2.0,  # >= 1.5
        sector_score=7.0, sentiment_score=6.5, technical_score=8.0,
    )

    # Test fallback directly instead of mocking exception
    fallback_result = agent._fallback_decision([quant])
    # With fallback, should return BUY if score >= 70, MACD bullish, RSI < 65, volume >= 1.5x
    assert fallback_result.action == "BUY"
    assert fallback_result.symbol == "NVDA"
    assert fallback_result.confidence == 7


def test_strategist_takes_top_3_candidates():
    """When multiple candidates, only top 3 are considered."""
    bus = EventBus()
    agent = Strategist(bus)

    candidates = [
        _make_quant("NVDA", 80.0),
        _make_quant("AMD", 75.0),
        _make_quant("INTC", 72.0),
        _make_quant("QCOM", 65.0),  # Below threshold
    ]

    mock_response = StrategyDecision(
        action="BUY", symbol="NVDA", confidence=9, entry_price=130.0,
        stop_loss=126.0, take_profit=140.0, reasoning="Top choice",
        regime="trending", daily_plan="aggressive",
    )

    with patch.object(agent, '_call_ai', return_value=mock_response) as mock_call:
        result = agent.run({
            "quant_outputs": candidates,
            "news_outputs": [_make_news(c.symbol) for c in candidates],
            "risk_constraints": _make_constraints(),
        })

    # Verify _call_ai was called with top 3
    assert mock_call.called
    call_args = mock_call.call_args
    passed_candidates = call_args[0][0]
    assert len(passed_candidates) == 3
    assert passed_candidates[0].symbol == "NVDA"
    assert passed_candidates[1].symbol == "AMD"
    assert passed_candidates[2].symbol == "INTC"
