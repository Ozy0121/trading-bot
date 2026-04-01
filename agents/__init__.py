# agents/__init__.py
"""Multi-agent trading system.

Trading agents:
  - QuantAnalyst: Technical analysis and scoring
  - NewsAnalyst: Sentiment, catalysts, and news
  - Strategist: AI-powered trade decisions
  - RiskManager: Veto power and position sizing
  - Executor: Order placement and management
  - Auditor: Performance tracking and review

Coordination:
  - AgentCoordinator: Pipeline orchestrator
  - EventBus: Lightweight pub/sub for observability
"""

from agents.event_bus import EventBus
from agents.base import (
    BaseAgent,
    QuantOutput,
    NewsOutput,
    RiskConstraints,
    StrategyDecision,
    RiskVerdict,
    ExecutionResult,
    AuditReport,
)
from agents.quant_analyst import QuantAnalyst
from agents.news_analyst import NewsAnalyst
from agents.strategist import Strategist
from agents.risk_manager import RiskManager
from agents.executor import Executor
from agents.auditor import Auditor
from agents.coordinator import AgentCoordinator
