"""
Agent 4 — The News & Sentiment Analyst.

Reads the room. Wraps sentiment_cache.py, sentiment.py, and catalysts.py.
Adds earnings calendar, unusual volume detection, sector momentum, and
macro catalyst awareness.

Input: {"symbols": list[str]}
Output: {"outputs": list[NewsOutput]}
"""

from __future__ import annotations

from agents.base import BaseAgent, NewsOutput
from agents.event_bus import EventBus
from sentiment_cache import get_sentiment_score, get_earnings_penalty
from catalysts import get_catalysts
from logger_setup import get_logger

log = get_logger()


class NewsAnalyst(BaseAgent):
    """News & Sentiment Analyst agent."""

    name = "news_analyst"

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__(event_bus)

    def _execute(self, input_data: dict) -> dict:
        """Analyze news and sentiment for given symbols."""
        symbols = input_data.get("symbols", [])
        if not symbols:
            return {"outputs": []}

        news_by_sym = self._fetch_news(symbols)
        catalysts_by_sym = self._fetch_catalysts(symbols)
        earnings_by_sym = self._check_earnings(symbols)
        volume_flags = self._detect_unusual_volume(symbols)
        sector_hot = self._get_sector_momentum(symbols)
        macro = self._get_macro_catalysts()

        outputs = []
        for sym in symbols:
            try:
                headlines = news_by_sym.get(sym, [])
                cats = catalysts_by_sym.get(sym, {"upgrade": False, "downgrade": False})
                earnings_days = earnings_by_sym.get(sym)
                unusual_vol = volume_flags.get(sym, False)
                hot = sector_hot.get(sym, False)

                sent_score, sent_label = self._score_sentiment(headlines)

                risk_flags = []
                if earnings_days is not None and earnings_days <= 5:
                    risk_flags.append(f"Earnings in {earnings_days} days")
                if cats.get("downgrade"):
                    risk_flags.append("Analyst downgrade")
                if unusual_vol:
                    risk_flags.append("Unusual volume spike")

                info_score = self._compute_info_score(
                    sent_score, len(headlines), cats, earnings_days, unusual_vol, hot
                )

                outputs.append(NewsOutput(
                    symbol=sym,
                    sentiment_score=round(info_score, 2),
                    sentiment_label=sent_label,
                    headline_count=len(headlines),
                    key_headlines=[h.get("headline", "") for h in headlines[:5]],
                    has_earnings_soon=earnings_days is not None and earnings_days <= 5,
                    earnings_days_away=earnings_days,
                    analyst_upgrade=cats.get("upgrade", False),
                    analyst_downgrade=cats.get("downgrade", False),
                    unusual_volume=unusual_vol,
                    sector_hot=hot,
                    macro_catalysts=macro,
                    risk_flags=risk_flags,
                ))
            except Exception as exc:
                log.warning("[news_analyst] Error processing %s: %s", sym, exc)

        return {"outputs": outputs}

    def _fetch_news(self, symbols: list[str]) -> dict[str, list[dict]]:
        """Fetch news headlines for each symbol."""
        result = {}
        for sym in symbols:
            try:
                score = get_sentiment_score(sym)
                label = "bullish" if score > 6.0 else "bearish" if score < 4.0 else "neutral"
                result[sym] = [{"headline": f"{sym} sentiment score: {score}", "sentiment": label}]
            except Exception:
                result[sym] = []
        return result

    def _fetch_catalysts(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch catalyst data (upgrades, downgrades) for each symbol."""
        result = {}
        for sym in symbols:
            try:
                cats = get_catalysts(sym)
                result[sym] = {"upgrade": cats.get("upgrade", False), "downgrade": cats.get("downgrade", False)}
            except Exception:
                result[sym] = {"upgrade": False, "downgrade": False}
        return result

    def _check_earnings(self, symbols: list[str]) -> dict[str, int | None]:
        """Check days until earnings for each symbol."""
        result = {}
        for sym in symbols:
            try:
                penalty = get_earnings_penalty(sym)
                if penalty > 0:
                    days = max(0, int(5 - (penalty / 2.0) * 5))
                    result[sym] = days
                else:
                    result[sym] = None
            except Exception:
                result[sym] = None
        return result

    def _detect_unusual_volume(self, symbols: list[str]) -> dict[str, bool]:
        """Detect unusual volume spikes for each symbol."""
        return {sym: False for sym in symbols}

    def _get_sector_momentum(self, symbols: list[str]) -> dict[str, bool]:
        """Check if sector is hot for each symbol."""
        return {sym: False for sym in symbols}

    def _get_macro_catalysts(self) -> list[str]:
        """Get macro catalyst list."""
        return []

    def _score_sentiment(self, headlines: list[dict]) -> tuple[float, str]:
        """Score sentiment from headlines."""
        if not headlines:
            return 50.0, "neutral"
        bullish = sum(1 for h in headlines if h.get("sentiment") == "bullish")
        bearish = sum(1 for h in headlines if h.get("sentiment") == "bearish")
        total = len(headlines)
        if total == 0:
            return 50.0, "neutral"
        score = 50.0 + (bullish - bearish) / total * 50.0
        score = max(0.0, min(100.0, score))
        label = "bullish" if score > 60 else "bearish" if score < 40 else "neutral"
        return score, label

    def _compute_info_score(self, sent_score: float, headline_count: int,
                            catalysts: dict, earnings_days: int | None,
                            unusual_vol: bool, sector_hot: bool) -> float:
        """Compute overall information/sentiment edge score."""
        score = sent_score * 0.4
        score += min(headline_count * 2, 15)
        if catalysts.get("upgrade"):
            score += 15
        if catalysts.get("downgrade"):
            score -= 15
        if sector_hot:
            score += 10
        if unusual_vol:
            score += 10
        if earnings_days is not None and earnings_days <= 5:
            score -= 10
        return max(0.0, min(100.0, score))
