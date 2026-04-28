"""
Agent 3 — The Strategist.

Head decision maker. Receives analysis from Quant Analyst and News Analyst,
receives risk constraints from Risk Manager, and makes the final
BUY/SELL/HOLD/WAIT decision. Calls Anthropic API only when a candidate
passes the conviction threshold.

Input: {"quant_outputs": list[QuantOutput], "news_outputs": list[NewsOutput],
        "risk_constraints": RiskConstraints}
Output: {"decision": StrategyDecision}
"""

from __future__ import annotations

import json
import os

from agents.base import (
    BaseAgent, QuantOutput, NewsOutput, RiskConstraints, StrategyDecision,
)
from agents.event_bus import EventBus
from logger_setup import get_logger

log = get_logger()

import config
_CONVICTION_THRESHOLD = float(os.getenv("CONVICTION_THRESHOLD", "5.8")) * 10
_MIN_CONFIDENCE = 8
_MODEL = config.STRATEGIST_MODEL


class Strategist(BaseAgent):
    """Strategist agent — makes BUY/SELL/HOLD/WAIT decisions."""

    name = "strategist"

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__(event_bus)
        self._client = None

    def _execute(self, input_data: dict) -> dict:
        quant_outputs: list[QuantOutput] = input_data.get("quant_outputs", [])
        news_outputs: list[NewsOutput] = input_data.get("news_outputs", [])
        constraints: RiskConstraints | None = input_data.get("risk_constraints")

        if not quant_outputs:
            return {
                "decision": StrategyDecision(
                    action="WAIT", reasoning="No data from Quant Analyst"
                )
            }

        # Filter candidates by conviction threshold
        candidates = [q for q in quant_outputs
                      if q.composite_score >= _CONVICTION_THRESHOLD]

        if not candidates:
            top_score = quant_outputs[0].composite_score if quant_outputs else 0
            return {
                "decision": StrategyDecision(
                    action="WAIT",
                    reasoning=(
                        f"No candidates above threshold ({_CONVICTION_THRESHOLD:.0f}/100). "
                        f"Top score: {top_score:.1f} ({quant_outputs[0].symbol})"
                    ),
                )
            }

        # Check PDT constraint
        if constraints and constraints.pdt_trades_remaining <= 0:
            return {
                "decision": StrategyDecision(
                    action="WAIT", reasoning="No PDT trades remaining"
                )
            }

        # Build news dict for lookup
        news_by_sym = {n.symbol: n for n in news_outputs}

        # Take top 3 candidates
        top_candidates = candidates[:3]

        # Call AI to make decision
        decision = self._call_ai(top_candidates, news_by_sym, constraints)

        # Check confidence threshold
        if decision.confidence < _MIN_CONFIDENCE:
            log.info(
                "[strategist] AI confidence %d < %d, converting to WAIT",
                decision.confidence, _MIN_CONFIDENCE
            )
            return {
                "decision": StrategyDecision(
                    action="WAIT",
                    reasoning=(
                        f"AI confidence {decision.confidence}/10 below threshold "
                        f"{_MIN_CONFIDENCE}. Original: {decision.reasoning}"
                    ),
                    regime=decision.regime,
                    daily_plan=decision.daily_plan,
                )
            }

        return {"decision": decision}

    def _summarize_output(self) -> str:
        d = self.last_output.get("decision")
        if not d:
            return "No data yet"
        sym = d.symbol or "—"
        return f"Decision: {d.action} {sym} (confidence {d.confidence}/10)"

    def _call_ai(
        self,
        candidates: list[QuantOutput],
        news_by_sym: dict[str, NewsOutput],
        constraints: RiskConstraints | None,
    ) -> StrategyDecision:
        """Call Anthropic API with fallback to pure Python logic."""
        try:
            import anthropic
        except ImportError:
            log.warning(
                "[strategist] anthropic package not installed, using fallback"
            )
            return self._fallback_decision(candidates)

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key or api_key.startswith("YOUR_"):
            log.warning("[strategist] ANTHROPIC_API_KEY not set, using fallback")
            return self._fallback_decision(candidates)

        if self._client is None:
            self._client = anthropic.Anthropic(api_key=api_key)

        prompt = self._build_prompt(candidates, news_by_sym, constraints)

        try:
            response = self._client.messages.create(
                model=_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return self._parse_ai_response(response.content[0].text, candidates)
        except Exception as exc:
            log.error("[strategist] AI call failed: %s", exc)
            return self._fallback_decision(candidates)

    def _build_prompt(
        self,
        candidates: list[QuantOutput],
        news_by_sym: dict[str, NewsOutput],
        constraints: RiskConstraints | None,
    ) -> str:
        """Build the prompt for the AI to analyze candidates."""
        parts = [
            "You are an expert swing trading strategist for a small $500 account "
            "with PDT restrictions (max 3 round-trip trades per 5 business days). "
            "Every trade must be high-conviction because you have limited entries.",
            "",
            "## Your Analysis Framework",
            "",
            "**Technical Analysis (from indicators below):**",
            "- Multi-timeframe alignment: SMA9 > SMA21 > SMA50 = strong uptrend",
            "- ADX > 25 = trending market (good for momentum); ADX < 20 = choppy (avoid)",
            "- RSI 30-50 = ideal buy zone; RSI > 70 = overbought risk",
            "- MACD histogram positive + rising = bullish momentum confirmation",
            "- Stochastic RSI < 0.2 = oversold bounce potential",
            "- Volume ratio > 1.5x = institutional interest",
            "- Bollinger %B < 0.2 = near lower band (mean reversion setup)",
            "",
            "**Risk Assessment:**",
            "- Beta > 1.5 = high volatility, size down; Beta < 0.8 = low vol, may underperform",
            "- ATR determines stop-loss distance: stop = entry - 1.5*ATR",
            "- Sharpe > 1.0 = good risk-adjusted returns; < 0 = losing proposition",
            "- P(3%+ in 3d) > 30% = historically volatile enough for swing profits",
            "",
            "**Entry Quality Checklist (need 4+ of 6 for BUY):**",
            "1. Trend aligned (SMA stack or recovery confirmed)",
            "2. Momentum confirming (MACD bullish, RSI not overbought)",
            "3. Volume confirming (ratio > 1.3x average)",
            "4. Volatility sufficient (ATR supports 3%+ move potential)",
            "5. Risk/reward favorable (target > 2x stop distance)",
            "6. No adverse news or earnings within 3 days",
            "",
            "Analyze these candidates and decide: BUY one, or WAIT.",
            "Only recommend BUY if confidence is 8+ out of 10.",
            "",
            'Respond in JSON: {"action": "BUY"|"WAIT", "symbol": str|null, '
            '"confidence": 1-10, "entry_price": float, "stop_loss": float, '
            '"take_profit": float, "reasoning": str, "regime": str, '
            '"daily_plan": str}',
            "",
        ]

        if constraints:
            parts.append(
                f"CONSTRAINTS: PDT trades remaining: "
                f"{constraints.pdt_trades_remaining}, "
                f"Max position: ${constraints.max_position_usd:.2f}, "
                f"Daily loss remaining: ${constraints.daily_loss_remaining:.2f}"
            )
            parts.append("")

        for c in candidates:
            news = news_by_sym.get(c.symbol)
            parts.append(
                f"--- {c.symbol} (score: {c.composite_score:.1f}/100) ---"
            )
            parts.append(
                f"Trend: {c.trend_alignment} | ADX: {c.adx:.0f} "
                f"({'trending' if c.adx >= 25 else 'weak/choppy'})"
            )
            parts.append(
                f"RSI: {c.rsi:.1f}, MACD: {c.macd_signal} (hist={c.macd_hist:.4f}), "
                f"Stoch RSI: {c.stochastic_rsi:.2f}"
            )
            parts.append(
                f"SMA: 9d={c.short_sma:.2f}, 21d={c.long_sma:.2f} | "
                f"BB %B: {c.bollinger_pct_b:.2f}"
            )
            parts.append(
                f"ATR: {c.atr:.4f}, Beta: {c.beta:.2f}, "
                f"Volume: {c.volume_ratio:.1f}x avg"
            )
            parts.append(
                f"20d Vol: {c.volatility_20d:.2%}, "
                f"P(3%+ in 3d): {c.probability_3pct_3d:.1%}"
            )
            parts.append(
                f"EV: {c.expected_value:.4f}, Sharpe: {c.sharpe_ratio:.2f}, "
                f"Sortino: {c.sortino_ratio:.2f}"
            )
            parts.append(
                f"MFI: {c.money_flow_index:.0f}, VWAP: {c.vwap:.2f}"
            )
            if news:
                parts.append(
                    f"Sentiment: {news.sentiment_label} "
                    f"({news.sentiment_score:.0f}/100)"
                )
                if news.risk_flags:
                    parts.append(f"RISK FLAGS: {', '.join(news.risk_flags)}")
                if news.key_headlines:
                    parts.append(
                        f"Headlines: {'; '.join(news.key_headlines[:3])}"
                    )
            parts.append("")

        return "\n".join(parts)

    def _parse_ai_response(
        self, text: str, candidates: list[QuantOutput]
    ) -> StrategyDecision:
        """Parse JSON response from AI."""
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            data = json.loads(text[start:end])
            return StrategyDecision(
                action=data.get("action", "WAIT").upper(),
                symbol=data.get("symbol"),
                confidence=int(data.get("confidence", 0)),
                entry_price=float(data.get("entry_price", 0)),
                stop_loss=float(data.get("stop_loss", 0)),
                take_profit=float(data.get("take_profit", 0)),
                reasoning=data.get("reasoning", ""),
                regime=data.get("regime", ""),
                daily_plan=data.get("daily_plan", ""),
            )
        except (ValueError, json.JSONDecodeError, KeyError) as exc:
            log.warning("[strategist] Failed to parse AI response: %s", exc)
            return self._fallback_decision(candidates)

    def _fallback_decision(
        self, candidates: list[QuantOutput]
    ) -> StrategyDecision:
        """Pure Python fallback when API is unavailable."""
        if not candidates:
            return StrategyDecision(
                action="WAIT", reasoning="No candidates (fallback)"
            )

        best = candidates[0]

        # Heuristic: BUY if score >= 70 and bullish MACD and RSI < 65
        # and volume ratio >= 1.5x
        if (
            best.composite_score >= 70
            and best.macd_signal == "bullish"
            and best.rsi < 65
            and best.volume_ratio >= 1.5
        ):
            return StrategyDecision(
                action="BUY",
                symbol=best.symbol,
                confidence=7,
                entry_price=best.vwap,
                stop_loss=best.vwap - best.atr * 2,
                take_profit=best.vwap + best.atr * 3,
                reasoning=(
                    f"Fallback: {best.symbol} score {best.composite_score:.1f}, "
                    f"MACD bullish, RSI {best.rsi:.0f}, vol {best.volume_ratio:.1f}x"
                ),
                regime="unknown",
                daily_plan="conservative",
            )

        return StrategyDecision(
            action="WAIT",
            reasoning=(
                f"Fallback: best candidate {best.symbol} "
                f"({best.composite_score:.1f}) didn't meet all criteria"
            ),
        )
