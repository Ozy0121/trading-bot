"""
Base agent class and typed dataclasses for inter-agent communication.

All trading agents inherit from BaseAgent. Each agent implements _execute()
which takes input and returns output. The base class handles status tracking,
error handling, and event bus integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agents.event_bus import EventBus
from logger_setup import get_logger

log = get_logger()


# ── Data contracts ──────────────────────────────────────────────────────────

@dataclass
class QuantOutput:
    """Output from the Quant Analyst for a single symbol."""
    symbol: str
    composite_score: float       # 0-100
    rsi: float
    macd_signal: str             # "bullish" / "bearish" / "neutral"
    atr: float                   # Average True Range
    beta: float                  # vs SPY
    volatility_20d: float
    volatility_60d: float
    stochastic_rsi: float
    rate_of_change: float
    money_flow_index: float
    on_balance_volume: float
    vwap: float
    bollinger_pct_b: float
    probability_3pct_3d: float   # P(3%+ move in 3 days)
    expected_value: float        # EV of proposed trade
    sharpe_ratio: float
    sortino_ratio: float
    short_sma: float
    long_sma: float
    bb_upper: float
    bb_lower: float
    macd_value: float
    macd_hist: float
    volume_ratio: float
    sector_score: float          # 0-10
    sentiment_score: float       # 0-10
    technical_score: float       # 0-10


@dataclass
class NewsOutput:
    """Output from the News Analyst for a single symbol."""
    symbol: str
    sentiment_score: float       # 0-100 information edge score
    sentiment_label: str         # "bullish" / "neutral" / "bearish"
    headline_count: int
    key_headlines: list[str]
    has_earnings_soon: bool      # within 5 days
    earnings_days_away: int | None
    analyst_upgrade: bool
    analyst_downgrade: bool
    unusual_volume: bool         # 2x+ average
    sector_hot: bool
    macro_catalysts: list[str]
    risk_flags: list[str]


@dataclass
class RiskConstraints:
    """Current risk state passed to the Strategist."""
    max_position_usd: float
    pdt_trades_remaining: int
    daily_loss_remaining: float
    current_exposure_usd: float
    held_symbols: list[str]


@dataclass
class StrategyDecision:
    """Output from the Strategist."""
    action: str                  # "BUY" / "SELL" / "HOLD" / "WAIT"
    symbol: str | None = None
    confidence: int = 0          # 1-10
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reasoning: str = ""
    regime: str = ""             # "trending" / "mean_reverting" / "choppy"
    daily_plan: str = ""         # "aggressive" / "conservative" / "sit_out"


@dataclass
class RiskVerdict:
    """Output from the Risk Manager."""
    approved: bool
    reason: str
    adjusted_qty: int = 0
    position_size_usd: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    kelly_fraction: float = 0.0
    var_95: float = 0.0
    max_drawdown: float = 0.0


@dataclass
class ExecutionResult:
    """Output from the Executor."""
    success: bool
    order_id: str | None = None
    symbol: str | None = None
    qty: int = 0
    fill_price: float = 0.0
    status: str = ""             # "filled" / "partial" / "rejected" / "error"
    message: str = ""


@dataclass
class AuditReport:
    """Output from the Auditor."""
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    daily_pnl: float = 0.0
    trades_today: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    daily_summary: str = ""


# ── Base agent ──────────────────────────────────────────────────────────────

class BaseAgent:
    """Base class for all trading agents.

    Subclasses implement _execute(input_data) -> dict.
    The base class wraps it with status tracking, error handling, and events.
    """

    name: str = "unnamed"

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self.status: str = "idle"
        self.last_run: datetime | None = None
        self.last_output: dict = {}
        self.last_error: str | None = None

    def run(self, input_data: dict | None = None) -> dict:
        """Execute the agent's logic with status tracking and error handling."""
        if input_data is None:
            input_data = {}

        self.status = "running"
        self.last_run = datetime.now(timezone.utc)
        self.event_bus.emit("agent.status", {
            "agent": self.name, "status": "running",
            "timestamp": self.last_run.isoformat(),
        })

        try:
            result = self._execute(input_data)
            self.last_output = result
            self.last_error = None
            self.status = "idle"

            self.event_bus.emit("agent.output", {
                "agent": self.name, "output": result,
                "timestamp": self.last_run.isoformat(),
            })
            self.event_bus.emit("agent.status", {
                "agent": self.name, "status": "idle",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return result

        except Exception as exc:
            self.last_error = str(exc)
            self.status = "error"
            log.error("[%s] Agent error: %s", self.name, exc, exc_info=True)

            self.event_bus.emit("agent.status", {
                "agent": self.name, "status": "error", "error": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return {}

    def _execute(self, input_data: dict) -> dict:
        """Override in subclasses. Takes input, returns output dict."""
        raise NotImplementedError

    def health_check(self) -> bool:
        """Returns True if agent is healthy (not in error state)."""
        return self.status != "error"

    def to_status_dict(self) -> dict:
        """Return agent status for the dashboard API."""
        summary = self._summarize_output()
        return {
            "name": self.name,
            "status": self.status,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_error": self.last_error,
            "summary": summary,
        }

    def _summarize_output(self) -> str:
        """Generate a short human-readable summary of last output."""
        if not self.last_output:
            return "No data yet"
        return "Last run complete"
