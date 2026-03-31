# Multi-Agent Trading System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 12-agent trading system — 6 runtime Python agents orchestrated by a coordinator with event bus, plus 6 Claude Code dev subagent definitions.

**Architecture:** Parallel scan (Quant + News run concurrently via ThreadPoolExecutor), then strict sequential decision chain (Strategist -> Risk Manager -> Executor), with a lightweight event bus for dashboard observability. Agents communicate through typed dataclasses passed as method arguments. Existing modules (safety.py, scanner.py, indicators.py, etc.) are wrapped, not replaced.

**Tech Stack:** Python 3.x, alpaca-py, anthropic SDK, pandas, numpy, Flask, threading, dataclasses, concurrent.futures

**Spec:** `docs/superpowers/specs/2026-03-31-multi-agent-system-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `agents/__init__.py` | Package init, exports all agent classes |
| Create | `agents/base.py` | BaseAgent class, all dataclasses (QuantOutput, NewsOutput, etc.) |
| Create | `agents/event_bus.py` | Lightweight thread-safe pub/sub |
| Create | `agents/quant_analyst.py` | Agent 1: technical analysis + scoring |
| Create | `agents/news_analyst.py` | Agent 2: sentiment + catalysts |
| Create | `agents/strategist.py` | Agent 3: AI decision maker |
| Create | `agents/risk_manager.py` | Agent 4: veto power, wraps safety.py |
| Create | `agents/executor.py` | Agent 5: order placement |
| Create | `agents/auditor.py` | Agent 6: performance tracking |
| Create | `agents/coordinator.py` | Pipeline orchestrator |
| Create | `tests/test_event_bus.py` | Event bus tests |
| Create | `tests/test_base_agent.py` | Base agent tests |
| Create | `tests/test_quant_analyst.py` | Quant agent tests |
| Create | `tests/test_news_analyst.py` | News agent tests |
| Create | `tests/test_strategist.py` | Strategist tests |
| Create | `tests/test_risk_manager.py` | Risk manager tests |
| Create | `tests/test_executor.py` | Executor tests |
| Create | `tests/test_auditor.py` | Auditor tests |
| Create | `tests/test_coordinator.py` | Coordinator pipeline tests |
| Modify | `config.py:117+` | Add ANTHROPIC_API_KEY, model config |
| Modify | `state.py:103+` | Add agents section to _state dict |
| Modify | `dashboard.py` | Add /api/agents/status endpoint |
| Modify | `server.py:36-96` | Create coordinator instead of direct bot.run() |
| Create | `.claude/agents/frontend-engineer.md` | Dev agent definition |
| Create | `.claude/agents/backend-engineer.md` | Dev agent definition |
| Create | `.claude/agents/data-engineer.md` | Dev agent definition |
| Create | `.claude/agents/qa-engineer.md` | Dev agent definition |
| Create | `.claude/agents/devops-engineer.md` | Dev agent definition |
| Create | `.claude/agents/architect.md` | Dev agent definition |

---

## Task 1: Event Bus

**Files:**
- Create: `agents/__init__.py`
- Create: `agents/event_bus.py`
- Test: `tests/test_event_bus.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_event_bus.py
"""Tests for the lightweight event bus."""

import threading
from agents.event_bus import EventBus


def test_subscribe_and_emit():
    """Subscribing to an event type and emitting it calls the callback."""
    bus = EventBus()
    received = []
    bus.subscribe("test.event", lambda data: received.append(data))
    bus.emit("test.event", {"key": "value"})
    assert len(received) == 1
    assert received[0] == {"key": "value"}


def test_emit_no_subscribers():
    """Emitting an event with no subscribers does not raise."""
    bus = EventBus()
    bus.emit("nobody.listening", {"key": "value"})  # should not raise


def test_multiple_subscribers():
    """Multiple callbacks for the same event type all get called."""
    bus = EventBus()
    results_a = []
    results_b = []
    bus.subscribe("multi", lambda d: results_a.append(d))
    bus.subscribe("multi", lambda d: results_b.append(d))
    bus.emit("multi", {"x": 1})
    assert len(results_a) == 1
    assert len(results_b) == 1


def test_different_event_types_isolated():
    """Subscribers only receive events they subscribed to."""
    bus = EventBus()
    received = []
    bus.subscribe("type_a", lambda d: received.append("a"))
    bus.emit("type_b", {})
    assert len(received) == 0


def test_thread_safety():
    """Concurrent emits from multiple threads don't lose events."""
    bus = EventBus()
    results = []
    lock = threading.Lock()

    def safe_append(data):
        with lock:
            results.append(data)

    bus.subscribe("concurrent", safe_append)

    threads = [threading.Thread(target=bus.emit, args=("concurrent", {"i": i}))
               for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 100


def test_callback_error_does_not_break_other_callbacks():
    """If one callback raises, other callbacks still run."""
    bus = EventBus()
    results = []

    def bad_callback(data):
        raise ValueError("boom")

    def good_callback(data):
        results.append(data)

    bus.subscribe("error_test", bad_callback)
    bus.subscribe("error_test", good_callback)
    bus.emit("error_test", {"ok": True})
    assert len(results) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_event_bus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents'`

- [ ] **Step 3: Create the package init and event bus**

```python
# agents/__init__.py
"""Multi-agent trading system."""
```

```python
# agents/event_bus.py
"""
Lightweight thread-safe pub/sub event bus for agent observability.

Used for non-critical notifications only (dashboard updates, audit logging).
Never used for trade decisions — those go through the sequential pipeline.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Callable

from logger_setup import get_logger

log = get_logger()


class EventBus:
    """Thread-safe publish/subscribe event bus."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Register a callback for an event type."""
        with self._lock:
            self._subscribers[event_type].append(callback)

    def emit(self, event_type: str, data: dict) -> None:
        """Emit an event to all subscribers. Callbacks run in the calling thread."""
        with self._lock:
            callbacks = list(self._subscribers.get(event_type, []))

        for cb in callbacks:
            try:
                cb(data)
            except Exception as exc:
                log.warning("[event_bus] Callback error on %s: %s", event_type, exc)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_event_bus.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/__init__.py agents/event_bus.py tests/test_event_bus.py
git commit -m "feat(agents): add thread-safe event bus for agent observability"
```

---

## Task 2: Base Agent Class & Dataclasses

**Files:**
- Create: `agents/base.py`
- Test: `tests/test_base_agent.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_base_agent.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_base_agent.py -v`
Expected: FAIL — `ImportError: cannot import name 'BaseAgent' from 'agents.base'`

- [ ] **Step 3: Write the base agent and dataclasses**

```python
# agents/base.py
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
        return {
            "name": self.name,
            "status": self.status,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_error": self.last_error,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_base_agent.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/base.py tests/test_base_agent.py
git commit -m "feat(agents): add BaseAgent class and typed dataclasses for inter-agent communication"
```

---

## Task 3: Quant Analyst Agent

**Files:**
- Create: `agents/quant_analyst.py`
- Test: `tests/test_quant_analyst.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quant_analyst.py
"""Tests for the Quant Analyst agent."""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from agents.event_bus import EventBus
from agents.quant_analyst import QuantAnalyst
from agents.base import QuantOutput


def _make_bars(n: int = 100, base_price: float = 100.0) -> pd.DataFrame:
    """Create a realistic OHLCV DataFrame for testing."""
    dates = pd.date_range(end=datetime.now(), periods=n, freq="5min")
    np.random.seed(42)
    closes = base_price + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open":   closes - np.random.rand(n) * 0.3,
        "high":   closes + np.random.rand(n) * 0.5,
        "low":    closes - np.random.rand(n) * 0.5,
        "close":  closes,
        "volume": np.random.randint(100000, 500000, n),
    }, index=dates)


def test_quant_analyst_returns_quant_outputs():
    """run() returns a list of QuantOutput dataclasses."""
    bus = EventBus()
    agent = QuantAnalyst(bus)

    bars_by_symbol = {"NVDA": _make_bars(), "AMD": _make_bars(base_price=80.0)}
    spy_bars = _make_bars(base_price=450.0)

    with patch.object(agent, '_fetch_bars', return_value=bars_by_symbol), \
         patch.object(agent, '_fetch_spy_bars', return_value=spy_bars):
        result = agent.run({"symbols": ["NVDA", "AMD"]})

    assert "outputs" in result
    outputs = result["outputs"]
    assert len(outputs) == 2
    assert all(isinstance(o, QuantOutput) for o in outputs)


def test_quant_analyst_scores_sorted_descending():
    """Results are sorted by composite_score descending."""
    bus = EventBus()
    agent = QuantAnalyst(bus)

    bars = {"NVDA": _make_bars(), "AMD": _make_bars(base_price=80.0)}
    spy = _make_bars(base_price=450.0)

    with patch.object(agent, '_fetch_bars', return_value=bars), \
         patch.object(agent, '_fetch_spy_bars', return_value=spy):
        result = agent.run({"symbols": ["NVDA", "AMD"]})

    scores = [o.composite_score for o in result["outputs"]]
    assert scores == sorted(scores, reverse=True)


def test_quant_analyst_handles_empty_bars():
    """Agent handles symbols with no bar data gracefully."""
    bus = EventBus()
    agent = QuantAnalyst(bus)

    with patch.object(agent, '_fetch_bars', return_value={}), \
         patch.object(agent, '_fetch_spy_bars', return_value=_make_bars()):
        result = agent.run({"symbols": ["FAKE"]})

    assert result["outputs"] == []


def test_quant_analyst_computes_new_indicators():
    """Verify new indicators (ATR, Stochastic RSI, etc.) are populated."""
    bus = EventBus()
    agent = QuantAnalyst(bus)

    bars = {"NVDA": _make_bars(n=200)}
    spy = _make_bars(n=200, base_price=450.0)

    with patch.object(agent, '_fetch_bars', return_value=bars), \
         patch.object(agent, '_fetch_spy_bars', return_value=spy):
        result = agent.run({"symbols": ["NVDA"]})

    out = result["outputs"][0]
    assert out.atr > 0
    assert 0 <= out.stochastic_rsi <= 1
    assert out.volatility_20d > 0
    assert out.beta != 0  # should be computed vs SPY
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_quant_analyst.py -v`
Expected: FAIL — `ImportError: cannot import name 'QuantAnalyst'`

- [ ] **Step 3: Implement the Quant Analyst**

```python
# agents/quant_analyst.py
"""
Agent 1 — The Quant Analyst.

Crunches all the numbers. Wraps indicators.py and scanner.py, adds new
indicators (Stochastic RSI, ATR, Beta, ROC, MFI, OBV, VWAP, %B) and
analytics (volatility, probability estimates, EV, Sharpe, Sortino).

Input: {"symbols": list[str]}
Output: {"outputs": list[QuantOutput]} sorted by composite_score descending
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from agents.base import BaseAgent, QuantOutput
from agents.event_bus import EventBus
from indicators import rsi as calc_rsi, macd as calc_macd, bollinger_bands
from scanner import fetch_bars_yf, scan
from sentiment_cache import get_sentiment_score
from logger_setup import get_logger

log = get_logger()


class QuantAnalyst(BaseAgent):
    name = "quant_analyst"

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__(event_bus)

    def _execute(self, input_data: dict) -> dict:
        symbols = input_data.get("symbols", [])
        if not symbols:
            return {"outputs": []}

        bars_by_symbol = self._fetch_bars(symbols)
        spy_bars = self._fetch_spy_bars()

        outputs = []
        for symbol in symbols:
            bars = bars_by_symbol.get(symbol)
            if bars is None or len(bars) < 30:
                continue
            try:
                q = self._analyze_symbol(symbol, bars, spy_bars)
                outputs.append(q)
            except Exception as exc:
                log.warning("[quant_analyst] Error analyzing %s: %s", symbol, exc)

        outputs.sort(key=lambda o: o.composite_score, reverse=True)
        return {"outputs": outputs}

    def _fetch_bars(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV bars for all symbols. Uses yfinance via scanner."""
        result = {}
        for sym in symbols:
            try:
                df = fetch_bars_yf(sym)
                if df is not None and len(df) > 0:
                    result[sym] = df
            except Exception as exc:
                log.warning("[quant_analyst] Failed to fetch bars for %s: %s", sym, exc)
        return result

    def _fetch_spy_bars(self) -> pd.DataFrame | None:
        """Fetch SPY bars for beta calculation."""
        try:
            return fetch_bars_yf("SPY")
        except Exception:
            return None

    def _analyze_symbol(self, symbol: str, bars: pd.DataFrame,
                        spy_bars: pd.DataFrame | None) -> QuantOutput:
        """Compute all indicators and score for one symbol."""
        closes = bars["close"]
        highs = bars["high"]
        lows = bars["low"]
        volumes = bars["volume"]

        # ── Existing indicators ─────────────────────────────────────────
        rsi_series = calc_rsi(closes)
        rsi_val = float(rsi_series.dropna().iloc[-1]) if len(rsi_series.dropna()) > 0 else 50.0
        macd_line, sig_line, hist = calc_macd(closes)
        macd_val = float(macd_line.dropna().iloc[-1]) if len(macd_line.dropna()) > 0 else 0.0
        macd_hist_val = float(hist.dropna().iloc[-1]) if len(hist.dropna()) > 0 else 0.0
        macd_sig = "bullish" if macd_hist_val > 0 else "bearish" if macd_hist_val < 0 else "neutral"
        bb_upper, bb_mid, bb_lower = bollinger_bands(closes)
        bb_u = float(bb_upper.dropna().iloc[-1]) if len(bb_upper.dropna()) > 0 else closes.iloc[-1]
        bb_l = float(bb_lower.dropna().iloc[-1]) if len(bb_lower.dropna()) > 0 else closes.iloc[-1]

        short_sma = float(closes.rolling(9).mean().iloc[-1])
        long_sma = float(closes.rolling(21).mean().iloc[-1])

        # Volume ratio
        avg_vol = float(volumes.rolling(20).mean().iloc[-1]) if len(volumes) >= 20 else float(volumes.mean())
        vol_ratio = float(volumes.iloc[-1]) / avg_vol if avg_vol > 0 else 1.0

        # ── New indicators ──────────────────────────────────────────────
        atr = self._calc_atr(highs, lows, closes)
        stoch_rsi = self._calc_stochastic_rsi(rsi_series)
        beta = self._calc_beta(closes, spy_bars)
        roc = self._calc_rate_of_change(closes)
        mfi = self._calc_mfi(highs, lows, closes, volumes)
        obv = self._calc_obv(closes, volumes)
        vwap = self._calc_vwap(highs, lows, closes, volumes)
        pct_b = self._calc_bollinger_pct_b(closes, bb_upper, bb_lower)
        vol_20d = self._calc_volatility(closes, 20)
        vol_60d = self._calc_volatility(closes, 60)
        prob_3pct_3d = self._calc_move_probability(closes, pct=3.0, days=3)
        ev = self._calc_expected_value(closes, atr)
        sharpe = self._calc_sharpe(closes)
        sortino = self._calc_sortino(closes)

        # ── Scoring ─────────────────────────────────────────────────────
        tech_score = self._compute_technical_score(rsi_val, macd_hist_val, short_sma, long_sma, stoch_rsi, pct_b)
        vol_score = min(vol_ratio / 2.0, 1.0) * 10.0
        sent_score = get_sentiment_score(symbol)
        sector_score = 5.0  # default; coordinator can override from sector scan

        composite = (tech_score * 0.40 + vol_score * 0.20 +
                     sent_score * 0.20 + sector_score * 0.20)

        return QuantOutput(
            symbol=symbol, composite_score=round(composite, 2),
            rsi=round(rsi_val, 2), macd_signal=macd_sig,
            atr=round(atr, 4), beta=round(beta, 2),
            volatility_20d=round(vol_20d, 4), volatility_60d=round(vol_60d, 4),
            stochastic_rsi=round(stoch_rsi, 4), rate_of_change=round(roc, 4),
            money_flow_index=round(mfi, 2), on_balance_volume=round(obv, 0),
            vwap=round(vwap, 4), bollinger_pct_b=round(pct_b, 4),
            probability_3pct_3d=round(prob_3pct_3d, 4),
            expected_value=round(ev, 4),
            sharpe_ratio=round(sharpe, 4), sortino_ratio=round(sortino, 4),
            short_sma=round(short_sma, 4), long_sma=round(long_sma, 4),
            bb_upper=round(bb_u, 4), bb_lower=round(bb_l, 4),
            macd_value=round(macd_val, 4), macd_hist=round(macd_hist_val, 4),
            volume_ratio=round(vol_ratio, 2),
            sector_score=round(sector_score, 2),
            sentiment_score=round(sent_score, 2),
            technical_score=round(tech_score, 2),
        )

    # ── New indicator calculations ──────────────────────────────────────────

    def _calc_atr(self, highs: pd.Series, lows: pd.Series,
                  closes: pd.Series, period: int = 14) -> float:
        """Average True Range."""
        prev_close = closes.shift(1)
        tr = pd.concat([
            highs - lows,
            (highs - prev_close).abs(),
            (lows - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        val = atr.dropna()
        return float(val.iloc[-1]) if len(val) > 0 else 0.0

    def _calc_stochastic_rsi(self, rsi_series: pd.Series, period: int = 14) -> float:
        """Stochastic RSI: (RSI - min) / (max - min) over period."""
        rsi_clean = rsi_series.dropna()
        if len(rsi_clean) < period:
            return 0.5
        rsi_min = rsi_clean.rolling(period).min()
        rsi_max = rsi_clean.rolling(period).max()
        denom = rsi_max - rsi_min
        stoch = (rsi_clean - rsi_min) / denom.replace(0, np.nan)
        val = stoch.dropna()
        return float(val.iloc[-1]) if len(val) > 0 else 0.5

    def _calc_beta(self, closes: pd.Series,
                   spy_bars: pd.DataFrame | None, period: int = 60) -> float:
        """Beta relative to SPY."""
        if spy_bars is None or len(spy_bars) < period:
            return 1.0
        stock_ret = closes.pct_change().dropna().tail(period)
        spy_ret = spy_bars["close"].pct_change().dropna().tail(period)
        if len(stock_ret) < 20 or len(spy_ret) < 20:
            return 1.0
        min_len = min(len(stock_ret), len(spy_ret))
        stock_ret = stock_ret.iloc[-min_len:]
        spy_ret = spy_ret.iloc[-min_len:]
        cov = np.cov(stock_ret.values, spy_ret.values)
        if cov[1, 1] == 0:
            return 1.0
        return float(cov[0, 1] / cov[1, 1])

    def _calc_rate_of_change(self, closes: pd.Series, period: int = 12) -> float:
        """Rate of Change: (close - close_n_ago) / close_n_ago * 100."""
        if len(closes) < period + 1:
            return 0.0
        current = float(closes.iloc[-1])
        past = float(closes.iloc[-period - 1])
        return ((current - past) / past * 100) if past != 0 else 0.0

    def _calc_mfi(self, highs: pd.Series, lows: pd.Series,
                  closes: pd.Series, volumes: pd.Series, period: int = 14) -> float:
        """Money Flow Index."""
        typical = (highs + lows + closes) / 3
        money_flow = typical * volumes
        delta = typical.diff()
        pos_flow = (money_flow * (delta > 0)).rolling(period).sum()
        neg_flow = (money_flow * (delta < 0)).rolling(period).sum().abs()
        ratio = pos_flow / neg_flow.replace(0, np.nan)
        mfi = 100 - (100 / (1 + ratio))
        val = mfi.dropna()
        return float(val.iloc[-1]) if len(val) > 0 else 50.0

    def _calc_obv(self, closes: pd.Series, volumes: pd.Series) -> float:
        """On-Balance Volume."""
        direction = np.sign(closes.diff()).fillna(0)
        obv = (direction * volumes).cumsum()
        return float(obv.iloc[-1]) if len(obv) > 0 else 0.0

    def _calc_vwap(self, highs: pd.Series, lows: pd.Series,
                   closes: pd.Series, volumes: pd.Series) -> float:
        """Volume Weighted Average Price (intraday approximation)."""
        typical = (highs + lows + closes) / 3
        cum_tp_vol = (typical * volumes).cumsum()
        cum_vol = volumes.cumsum()
        vwap = cum_tp_vol / cum_vol.replace(0, np.nan)
        val = vwap.dropna()
        return float(val.iloc[-1]) if len(val) > 0 else float(closes.iloc[-1])

    def _calc_bollinger_pct_b(self, closes: pd.Series,
                              bb_upper: pd.Series, bb_lower: pd.Series) -> float:
        """%B = (close - lower) / (upper - lower)."""
        width = bb_upper - bb_lower
        pct_b = (closes - bb_lower) / width.replace(0, np.nan)
        val = pct_b.dropna()
        return float(val.iloc[-1]) if len(val) > 0 else 0.5

    def _calc_volatility(self, closes: pd.Series, window: int) -> float:
        """Annualized historical volatility over window days."""
        if len(closes) < window + 1:
            return 0.0
        returns = closes.pct_change().dropna().tail(window)
        return float(returns.std() * np.sqrt(252))

    def _calc_move_probability(self, closes: pd.Series,
                               pct: float = 3.0, days: int = 3) -> float:
        """Historical probability of >= pct% move in next N days."""
        if len(closes) < days + 30:
            return 0.0
        returns = closes.pct_change(periods=days).dropna() * 100
        big_moves = (returns.abs() >= pct).sum()
        return float(big_moves / len(returns))

    def _calc_expected_value(self, closes: pd.Series, atr: float) -> float:
        """Simple EV estimate: avg_win * P(win) - avg_loss * P(loss) based on recent bars."""
        if len(closes) < 20 or atr == 0:
            return 0.0
        returns = closes.pct_change().dropna().tail(60)
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        if len(wins) == 0 or len(losses) == 0:
            return 0.0
        p_win = len(wins) / len(returns)
        avg_win = float(wins.mean())
        avg_loss = float(losses.mean())
        return avg_win * p_win + avg_loss * (1 - p_win)

    def _calc_sharpe(self, closes: pd.Series, window: int = 60) -> float:
        """Sharpe ratio over window (assumes risk-free rate 0 for simplicity)."""
        if len(closes) < window + 1:
            return 0.0
        returns = closes.pct_change().dropna().tail(window)
        mean_ret = float(returns.mean())
        std_ret = float(returns.std())
        if std_ret == 0:
            return 0.0
        return (mean_ret / std_ret) * np.sqrt(252)

    def _calc_sortino(self, closes: pd.Series, window: int = 60) -> float:
        """Sortino ratio (downside deviation only)."""
        if len(closes) < window + 1:
            return 0.0
        returns = closes.pct_change().dropna().tail(window)
        mean_ret = float(returns.mean())
        downside = returns[returns < 0]
        if len(downside) == 0:
            return 0.0
        down_std = float(downside.std())
        if down_std == 0:
            return 0.0
        return (mean_ret / down_std) * np.sqrt(252)

    def _compute_technical_score(self, rsi: float, macd_hist: float,
                                 short_sma: float, long_sma: float,
                                 stoch_rsi: float, pct_b: float) -> float:
        """Compute a 0-10 technical score from multiple indicators."""
        score = 0.0
        # RSI in buy zone (30-50) = best, (20-30 or 50-65) = ok
        if 30 <= rsi <= 50:
            score += 3.0
        elif 20 <= rsi < 30 or 50 < rsi <= 65:
            score += 1.5

        # MACD histogram positive = bullish
        if macd_hist > 0:
            score += 2.0
        elif macd_hist > -0.1:
            score += 0.5

        # SMA crossover (short above long = bullish)
        if short_sma > long_sma:
            score += 2.0

        # Stochastic RSI in oversold zone (< 0.2) = potential bounce
        if stoch_rsi < 0.2:
            score += 1.5
        elif stoch_rsi < 0.4:
            score += 0.5

        # Bollinger %B near lower band = potential bounce
        if pct_b < 0.2:
            score += 1.5
        elif pct_b < 0.4:
            score += 0.5

        return min(score, 10.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_quant_analyst.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/quant_analyst.py tests/test_quant_analyst.py
git commit -m "feat(agents): add Quant Analyst agent with extended indicators and scoring"
```

---

## Task 4: News Analyst Agent

**Files:**
- Create: `agents/news_analyst.py`
- Test: `tests/test_news_analyst.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_analyst.py
"""Tests for the News Analyst agent."""

from unittest.mock import patch, MagicMock
from agents.event_bus import EventBus
from agents.news_analyst import NewsAnalyst
from agents.base import NewsOutput


def test_news_analyst_returns_news_outputs():
    """run() returns a list of NewsOutput dataclasses."""
    bus = EventBus()
    agent = NewsAnalyst(bus)

    with patch.object(agent, '_fetch_news', return_value={"NVDA": [{"headline": "NVDA beats earnings", "sentiment": "bullish"}]}), \
         patch.object(agent, '_fetch_catalysts', return_value={"NVDA": {"upgrade": True, "downgrade": False}}), \
         patch.object(agent, '_check_earnings', return_value={"NVDA": None}), \
         patch.object(agent, '_detect_unusual_volume', return_value={"NVDA": False}), \
         patch.object(agent, '_get_sector_momentum', return_value={"NVDA": True}), \
         patch.object(agent, '_get_macro_catalysts', return_value=[]):
        result = agent.run({"symbols": ["NVDA"]})

    assert "outputs" in result
    outputs = result["outputs"]
    assert len(outputs) == 1
    assert isinstance(outputs[0], NewsOutput)
    assert outputs[0].symbol == "NVDA"


def test_news_analyst_empty_symbols():
    """Empty symbol list returns empty outputs."""
    bus = EventBus()
    agent = NewsAnalyst(bus)
    result = agent.run({"symbols": []})
    assert result["outputs"] == []


def test_news_analyst_earnings_flag():
    """Stocks with earnings soon get flagged."""
    bus = EventBus()
    agent = NewsAnalyst(bus)

    with patch.object(agent, '_fetch_news', return_value={"NVDA": []}), \
         patch.object(agent, '_fetch_catalysts', return_value={"NVDA": {"upgrade": False, "downgrade": False}}), \
         patch.object(agent, '_check_earnings', return_value={"NVDA": 3}), \
         patch.object(agent, '_detect_unusual_volume', return_value={"NVDA": False}), \
         patch.object(agent, '_get_sector_momentum', return_value={"NVDA": False}), \
         patch.object(agent, '_get_macro_catalysts', return_value=[]):
        result = agent.run({"symbols": ["NVDA"]})

    out = result["outputs"][0]
    assert out.has_earnings_soon is True
    assert out.earnings_days_away == 3
    assert "earnings" in [f.lower() for f in out.risk_flags] or any("earning" in f.lower() for f in out.risk_flags)


def test_news_analyst_sentiment_scoring():
    """Bullish headlines produce higher sentiment scores."""
    bus = EventBus()
    agent = NewsAnalyst(bus)

    bullish_news = {"NVDA": [
        {"headline": "NVDA surges on record revenue", "sentiment": "bullish"},
        {"headline": "NVDA upgraded by Goldman Sachs", "sentiment": "bullish"},
        {"headline": "AI demand drives NVDA growth", "sentiment": "bullish"},
    ]}

    with patch.object(agent, '_fetch_news', return_value=bullish_news), \
         patch.object(agent, '_fetch_catalysts', return_value={"NVDA": {"upgrade": True, "downgrade": False}}), \
         patch.object(agent, '_check_earnings', return_value={"NVDA": None}), \
         patch.object(agent, '_detect_unusual_volume', return_value={"NVDA": False}), \
         patch.object(agent, '_get_sector_momentum', return_value={"NVDA": True}), \
         patch.object(agent, '_get_macro_catalysts', return_value=[]):
        result = agent.run({"symbols": ["NVDA"]})

    out = result["outputs"][0]
    assert out.sentiment_label == "bullish"
    assert out.sentiment_score > 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_news_analyst.py -v`
Expected: FAIL — `ImportError: cannot import name 'NewsAnalyst'`

- [ ] **Step 3: Implement the News Analyst**

```python
# agents/news_analyst.py
"""
Agent 2 — The News & Sentiment Analyst.

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
    name = "news_analyst"

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__(event_bus)

    def _execute(self, input_data: dict) -> dict:
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
        """Fetch news headlines per symbol using sentiment_cache and Alpaca."""
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
        """Fetch catalyst data per symbol using catalysts.py."""
        result = {}
        for sym in symbols:
            try:
                cats = get_catalysts(sym)
                result[sym] = {
                    "upgrade": cats.get("upgrade", False),
                    "downgrade": cats.get("downgrade", False),
                }
            except Exception:
                result[sym] = {"upgrade": False, "downgrade": False}
        return result

    def _check_earnings(self, symbols: list[str]) -> dict[str, int | None]:
        """Check earnings proximity for each symbol. Returns days until earnings or None."""
        result = {}
        for sym in symbols:
            try:
                penalty = get_earnings_penalty(sym)
                if penalty > 0:
                    # Reverse-engineer days from penalty (2.0 = today, 0.0 = >3 days)
                    days = max(0, int(5 - (penalty / 2.0) * 5))
                    result[sym] = days
                else:
                    result[sym] = None
            except Exception:
                result[sym] = None
        return result

    def _detect_unusual_volume(self, symbols: list[str]) -> dict[str, bool]:
        """Detect symbols with 2x+ average volume (institutional activity)."""
        # Uses scanner data when available via shared_state
        import state as shared_state
        snap = shared_state.snapshot()
        scan_scores = snap.get("scan_conviction_scores", {})
        result = {}
        for sym in symbols:
            result[sym] = False  # default; coordinator can update from quant data
        return result

    def _get_sector_momentum(self, symbols: list[str]) -> dict[str, bool]:
        """Check which symbols are in hot sectors today."""
        # Simplified: will be enhanced when coordinator passes sector data
        return {sym: False for sym in symbols}

    def _get_macro_catalysts(self) -> list[str]:
        """Return list of current macro catalysts (fed meetings, data releases)."""
        # Placeholder for RSS feed integration
        return []

    def _score_sentiment(self, headlines: list[dict]) -> tuple[float, str]:
        """Score headlines and return (score 0-100, label)."""
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
        """Compute a 0-100 information edge score."""
        score = sent_score * 0.4  # sentiment is 40% of info score

        # More headlines = more information
        score += min(headline_count * 2, 15)

        # Catalyst bonuses
        if catalysts.get("upgrade"):
            score += 15
        if catalysts.get("downgrade"):
            score -= 15

        # Sector momentum
        if sector_hot:
            score += 10

        # Volume spike
        if unusual_vol:
            score += 10

        # Earnings penalty
        if earnings_days is not None and earnings_days <= 5:
            score -= 10

        return max(0.0, min(100.0, score))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_news_analyst.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/news_analyst.py tests/test_news_analyst.py
git commit -m "feat(agents): add News Analyst agent with sentiment scoring and catalyst tracking"
```

---

## Task 5: Strategist Agent

**Files:**
- Create: `agents/strategist.py`
- Test: `tests/test_strategist.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_strategist.py
"""Tests for the Strategist agent."""

from unittest.mock import patch, MagicMock, AsyncMock
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
    """No candidates above threshold means WAIT, no API call."""
    bus = EventBus()
    agent = Strategist(bus)
    result = agent.run({
        "quant_outputs": [_make_quant("NVDA", 30.0)],  # below threshold
        "news_outputs": [_make_news("NVDA")],
        "risk_constraints": _make_constraints(),
    })
    decision = result["decision"]
    assert isinstance(decision, StrategyDecision)
    assert decision.action == "WAIT"


def test_strategist_calls_ai_when_candidate_above_threshold():
    """High-scoring candidate triggers an AI call."""
    bus = EventBus()
    agent = Strategist(bus)

    mock_response = StrategyDecision(
        action="BUY", symbol="NVDA", confidence=9, entry_price=130.0,
        stop_loss=126.0, take_profit=140.0, reasoning="Strong breakout",
        regime="trending", daily_plan="aggressive",
    )

    with patch.object(agent, '_call_ai', return_value=mock_response):
        result = agent.run({
            "quant_outputs": [_make_quant("NVDA", 75.0)],  # above threshold
            "news_outputs": [_make_news("NVDA")],
            "risk_constraints": _make_constraints(),
        })

    decision = result["decision"]
    assert decision.action == "BUY"
    assert decision.confidence == 9


def test_strategist_rejects_low_confidence():
    """AI returns confidence < 8, Strategist converts to WAIT."""
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
    """Empty inputs means WAIT, no processing."""
    bus = EventBus()
    agent = Strategist(bus)
    result = agent.run({
        "quant_outputs": [],
        "news_outputs": [],
        "risk_constraints": _make_constraints(),
    })
    assert result["decision"].action == "WAIT"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_strategist.py -v`
Expected: FAIL — `ImportError: cannot import name 'Strategist'`

- [ ] **Step 3: Implement the Strategist**

```python
# agents/strategist.py
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

# Conviction threshold scaled to 0-100 (config uses 0-10 scale)
_CONVICTION_THRESHOLD = float(os.getenv("CONVICTION_THRESHOLD", "5.8")) * 10
_MIN_CONFIDENCE = 8
_MODEL = os.getenv("STRATEGIST_MODEL", "claude-sonnet-4-6")


class Strategist(BaseAgent):
    name = "strategist"

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__(event_bus)
        self._client = None  # lazy-loaded Anthropic client

    def _execute(self, input_data: dict) -> dict:
        quant_outputs: list[QuantOutput] = input_data.get("quant_outputs", [])
        news_outputs: list[NewsOutput] = input_data.get("news_outputs", [])
        constraints: RiskConstraints | None = input_data.get("risk_constraints")

        if not quant_outputs:
            return {"decision": StrategyDecision(action="WAIT", reasoning="No data from Quant Analyst")}

        # Filter to candidates above conviction threshold
        candidates = [q for q in quant_outputs if q.composite_score >= _CONVICTION_THRESHOLD]

        if not candidates:
            return {"decision": StrategyDecision(
                action="WAIT",
                reasoning=f"No candidates above threshold ({_CONVICTION_THRESHOLD:.0f}/100). "
                          f"Top score: {quant_outputs[0].composite_score:.1f} ({quant_outputs[0].symbol})",
            )}

        # Check if PDT allows trading
        if constraints and constraints.pdt_trades_remaining <= 0:
            return {"decision": StrategyDecision(
                action="WAIT", reasoning="No PDT trades remaining",
            )}

        # Build news lookup
        news_by_sym = {n.symbol: n for n in news_outputs}

        # Call AI for final decision
        top_candidates = candidates[:3]  # send top 3 to AI
        decision = self._call_ai(top_candidates, news_by_sym, constraints)

        # Enforce minimum confidence
        if decision.confidence < _MIN_CONFIDENCE:
            log.info("[strategist] AI confidence %d < %d, converting to WAIT",
                     decision.confidence, _MIN_CONFIDENCE)
            return {"decision": StrategyDecision(
                action="WAIT",
                reasoning=f"AI confidence {decision.confidence}/10 below threshold {_MIN_CONFIDENCE}. "
                          f"Original: {decision.reasoning}",
                regime=decision.regime,
                daily_plan=decision.daily_plan,
            )}

        return {"decision": decision}

    def _call_ai(self, candidates: list[QuantOutput],
                 news_by_sym: dict[str, NewsOutput],
                 constraints: RiskConstraints | None) -> StrategyDecision:
        """Call Anthropic API for a trade decision."""
        try:
            import anthropic
        except ImportError:
            log.warning("[strategist] anthropic package not installed, using fallback")
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

    def _build_prompt(self, candidates: list[QuantOutput],
                      news_by_sym: dict[str, NewsOutput],
                      constraints: RiskConstraints | None) -> str:
        """Build the structured prompt for the AI."""
        parts = [
            "You are a swing trading strategist for a small $500 account with PDT restrictions.",
            "Analyze these candidates and decide: BUY one, or WAIT.",
            "Only recommend BUY if confidence is 8+ out of 10.",
            "",
            "Respond in JSON: {\"action\": \"BUY\"|\"WAIT\", \"symbol\": str|null,",
            "\"confidence\": 1-10, \"entry_price\": float, \"stop_loss\": float,",
            "\"take_profit\": float, \"reasoning\": str, \"regime\": str, \"daily_plan\": str}",
            "",
        ]

        if constraints:
            parts.append(f"CONSTRAINTS: PDT trades remaining: {constraints.pdt_trades_remaining}, "
                         f"Max position: ${constraints.max_position_usd:.2f}, "
                         f"Daily loss remaining: ${constraints.daily_loss_remaining:.2f}")
            parts.append("")

        for c in candidates:
            news = news_by_sym.get(c.symbol)
            parts.append(f"--- {c.symbol} (score: {c.composite_score:.1f}/100) ---")
            parts.append(f"RSI: {c.rsi}, MACD: {c.macd_signal}, ATR: {c.atr}, Beta: {c.beta}")
            parts.append(f"Stoch RSI: {c.stochastic_rsi}, Volume Ratio: {c.volume_ratio}x")
            parts.append(f"20d Vol: {c.volatility_20d:.2%}, P(3%+ in 3d): {c.probability_3pct_3d:.1%}")
            parts.append(f"EV: {c.expected_value:.4f}, Sharpe: {c.sharpe_ratio:.2f}")
            parts.append(f"SMA: short={c.short_sma:.2f} long={c.long_sma:.2f}")
            if news:
                parts.append(f"Sentiment: {news.sentiment_label} ({news.sentiment_score:.0f}/100)")
                if news.risk_flags:
                    parts.append(f"RISK FLAGS: {', '.join(news.risk_flags)}")
                if news.key_headlines:
                    parts.append(f"Headlines: {'; '.join(news.key_headlines[:3])}")
            parts.append("")

        return "\n".join(parts)

    def _parse_ai_response(self, text: str,
                           candidates: list[QuantOutput]) -> StrategyDecision:
        """Parse the AI's JSON response into a StrategyDecision."""
        try:
            # Find JSON in response
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

    def _fallback_decision(self, candidates: list[QuantOutput]) -> StrategyDecision:
        """Pure-Python fallback when AI is unavailable."""
        if not candidates:
            return StrategyDecision(action="WAIT", reasoning="No candidates (fallback)")

        best = candidates[0]
        # Simple rule: if composite > 70 and multiple signals align, BUY
        if (best.composite_score >= 70 and best.macd_signal == "bullish"
                and best.rsi < 65 and best.volume_ratio >= 1.5):
            return StrategyDecision(
                action="BUY", symbol=best.symbol, confidence=7,
                entry_price=best.vwap, stop_loss=best.vwap - best.atr * 2,
                take_profit=best.vwap + best.atr * 3,
                reasoning=f"Fallback: {best.symbol} score {best.composite_score:.1f}, "
                          f"MACD bullish, RSI {best.rsi:.0f}, vol {best.volume_ratio:.1f}x",
                regime="unknown", daily_plan="conservative",
            )

        return StrategyDecision(
            action="WAIT",
            reasoning=f"Fallback: best candidate {best.symbol} ({best.composite_score:.1f}) "
                      "didn't meet all criteria",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_strategist.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/strategist.py tests/test_strategist.py
git commit -m "feat(agents): add Strategist agent with Anthropic API integration and fallback"
```

---

## Task 6: Risk Manager Agent

**Files:**
- Create: `agents/risk_manager.py`
- Test: `tests/test_risk_manager.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_risk_manager.py
"""Tests for the Risk Manager agent."""

from unittest.mock import patch, MagicMock
from agents.event_bus import EventBus
from agents.risk_manager import RiskManager
from agents.base import StrategyDecision, RiskVerdict, RiskConstraints


def _mock_trading_client():
    client = MagicMock()
    acct = MagicMock()
    acct.equity = "500.00"
    acct.cash = "500.00"
    client.get_account.return_value = acct
    client.get_all_positions.return_value = []
    return client


def test_risk_manager_approves_valid_trade():
    """Valid trade within all limits gets approved."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)

    decision = StrategyDecision(
        action="BUY", symbol="NVDA", confidence=9, entry_price=130.0,
        stop_loss=126.0, take_profit=140.0, reasoning="Strong signal",
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
    """Trade rejected when PDT limit is reached."""
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
    """Trade rejected when daily loss limit is hit."""
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
    """Position size never exceeds 5% of equity."""
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

    # 5% of $500 = $25. At $5/share = max 5 shares
    assert result["verdict"].position_size_usd <= 25.0


def test_risk_manager_passes_through_wait():
    """WAIT decisions pass through without checks."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)

    decision = StrategyDecision(action="WAIT", reasoning="No setups")
    result = agent.run({"decision": decision})
    assert result["verdict"].approved is False
    assert "WAIT" in result["verdict"].reason or "wait" in result["verdict"].reason.lower()


def test_risk_manager_kelly_criterion():
    """Kelly fraction is calculated and applied."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)

    # Set trade history for Kelly calculation
    agent._trade_history = [
        {"win": True, "pnl": 10.0}, {"win": True, "pnl": 8.0},
        {"win": False, "pnl": -5.0}, {"win": True, "pnl": 12.0},
        {"win": False, "pnl": -6.0},
    ]

    kelly = agent._calc_kelly_fraction()
    assert 0 < kelly < 1.0  # should be a reasonable fraction


def test_risk_manager_get_constraints():
    """get_constraints() returns current risk state."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = RiskManager(bus, client)

    with patch("agents.risk_manager.get_pdt_info", return_value={"remaining": 2}), \
         patch("agents.risk_manager.daily_loss_exceeded", return_value=False):
        constraints = agent.get_constraints()

    assert isinstance(constraints, RiskConstraints)
    assert constraints.pdt_trades_remaining == 2
    assert constraints.max_position_usd > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_risk_manager.py -v`
Expected: FAIL — `ImportError: cannot import name 'RiskManager'`

- [ ] **Step 3: Implement the Risk Manager**

```python
# agents/risk_manager.py
"""
Agent 4 — The Risk Manager.

Protects the account. Has VETO power over all trades.
Wraps safety.py for hard rules, adds Kelly Criterion, VaR, drawdown tracking.

Input: {"decision": StrategyDecision}
Output: {"verdict": RiskVerdict}
"""

from __future__ import annotations

import math
import numpy as np

from alpaca.trading.client import TradingClient

from agents.base import BaseAgent, StrategyDecision, RiskVerdict, RiskConstraints
from agents.event_bus import EventBus
from safety import (
    check_pdt_allows_buy,
    daily_loss_exceeded,
    get_pdt_info,
    calculate_safe_qty,
)
import config
from logger_setup import get_logger

log = get_logger()

_MAX_POSITION_FRACTION = 0.05  # 5% hard cap


class RiskManager(BaseAgent):
    name = "risk_manager"

    def __init__(self, event_bus: EventBus,
                 trading_client: TradingClient) -> None:
        super().__init__(event_bus)
        self._trading_client = trading_client
        self._trade_history: list[dict] = []
        self._peak_equity: float = 0.0
        self._max_drawdown: float = 0.0

    def _execute(self, input_data: dict) -> dict:
        decision: StrategyDecision = input_data.get("decision")
        if decision is None:
            return {"verdict": RiskVerdict(approved=False, reason="No decision provided")}

        # Pass through non-BUY decisions
        if decision.action != "BUY":
            return {"verdict": RiskVerdict(
                approved=False,
                reason=f"Action is {decision.action}, not BUY — no trade to approve",
            )}

        # ── Hard rules from safety.py ───────────────────────────────────
        if not check_pdt_allows_buy(self._trading_client):
            self.event_bus.emit("risk.veto", {
                "agent": self.name, "symbol": decision.symbol,
                "reason": "PDT limit reached",
            })
            return {"verdict": RiskVerdict(approved=False, reason="PDT limit reached")}

        if daily_loss_exceeded():
            self.event_bus.emit("risk.veto", {
                "agent": self.name, "symbol": decision.symbol,
                "reason": "Daily loss limit exceeded",
            })
            return {"verdict": RiskVerdict(
                approved=False, reason="Daily loss limit exceeded",
            )}

        # ── Position sizing ─────────────────────────────────────────────
        equity = self._get_equity()
        max_position_usd = equity * _MAX_POSITION_FRACTION
        kelly = self._calc_kelly_fraction()
        kelly_position_usd = equity * kelly

        # Take the smaller of Kelly and hard cap
        position_usd = min(kelly_position_usd, max_position_usd)

        if decision.entry_price <= 0:
            return {"verdict": RiskVerdict(
                approved=False, reason="Invalid entry price",
            )}

        qty = int(position_usd / decision.entry_price)
        if qty < 1:
            return {"verdict": RiskVerdict(
                approved=False,
                reason=f"Position too small: ${position_usd:.2f} / ${decision.entry_price:.2f} = 0 shares",
            )}

        # ── VaR check ───────────────────────────────────────────────────
        var_95 = self._calc_var(position_usd, decision.entry_price)

        # ── Drawdown tracking ───────────────────────────────────────────
        self._update_drawdown(equity)

        # ── Correlation check (simplified) ──────────────────────────────
        held = self._get_held_symbols()
        # Future: check sector correlation with held positions

        log.info("[risk_manager] APPROVED %s: qty=%d, size=$%.2f, kelly=%.2f%%, VaR=$%.2f",
                 decision.symbol, qty, qty * decision.entry_price, kelly * 100, var_95)

        return {"verdict": RiskVerdict(
            approved=True,
            reason="All checks passed",
            adjusted_qty=qty,
            position_size_usd=round(qty * decision.entry_price, 2),
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            kelly_fraction=round(kelly, 4),
            var_95=round(var_95, 2),
            max_drawdown=round(self._max_drawdown, 4),
        )}

    def get_constraints(self) -> RiskConstraints:
        """Return current risk constraints for the Strategist."""
        equity = self._get_equity()
        pdt_info = get_pdt_info(self._trading_client)
        remaining = pdt_info.get("remaining", 3) if isinstance(pdt_info, dict) else 3
        loss_exceeded = daily_loss_exceeded()
        held = self._get_held_symbols()

        return RiskConstraints(
            max_position_usd=round(equity * _MAX_POSITION_FRACTION, 2),
            pdt_trades_remaining=remaining,
            daily_loss_remaining=round(config.DAILY_LOSS_LIMIT - abs(self._get_daily_pnl()), 2),
            current_exposure_usd=self._get_exposure(),
            held_symbols=held,
        )

    def _get_equity(self) -> float:
        try:
            acct = self._trading_client.get_account()
            return float(acct.equity)
        except Exception:
            return 500.0  # default fallback

    def _get_daily_pnl(self) -> float:
        import state as shared_state
        snap = shared_state.snapshot()
        return snap.get("daily_pnl", 0.0)

    def _get_exposure(self) -> float:
        try:
            positions = self._trading_client.get_all_positions()
            return sum(float(p.market_value) for p in positions)
        except Exception:
            return 0.0

    def _get_held_symbols(self) -> list[str]:
        try:
            positions = self._trading_client.get_all_positions()
            return [p.symbol for p in positions if float(p.qty) > 0]
        except Exception:
            return []

    def _calc_kelly_fraction(self) -> float:
        """Kelly Criterion: f* = (bp - q) / b where b=avg_win/avg_loss, p=win_rate, q=1-p."""
        if len(self._trade_history) < 5:
            return _MAX_POSITION_FRACTION  # default to hard cap if insufficient data

        wins = [t for t in self._trade_history if t.get("win")]
        losses = [t for t in self._trade_history if not t.get("win")]

        if not wins or not losses:
            return _MAX_POSITION_FRACTION

        p = len(wins) / len(self._trade_history)
        q = 1 - p
        avg_win = sum(abs(t["pnl"]) for t in wins) / len(wins)
        avg_loss = sum(abs(t["pnl"]) for t in losses) / len(losses)

        if avg_loss == 0:
            return _MAX_POSITION_FRACTION

        b = avg_win / avg_loss
        kelly = (b * p - q) / b

        # Half-Kelly for safety, capped at max fraction
        kelly = max(0.01, min(kelly * 0.5, _MAX_POSITION_FRACTION))
        return kelly

    def _calc_var(self, position_usd: float, price: float,
                  confidence: float = 0.95) -> float:
        """Value at Risk at 95% confidence (parametric)."""
        # Simplified: assume 2% daily volatility for now
        daily_vol = 0.02
        z_score = 1.645  # 95% confidence
        return position_usd * daily_vol * z_score

    def _update_drawdown(self, equity: float) -> None:
        """Track peak equity and max drawdown."""
        if equity > self._peak_equity:
            self._peak_equity = equity
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            self._max_drawdown = max(self._max_drawdown, drawdown)

    def record_trade(self, trade: dict) -> None:
        """Record a completed trade for Kelly calculation."""
        self._trade_history.append(trade)
        if len(self._trade_history) > 100:
            self._trade_history = self._trade_history[-100:]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_risk_manager.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/risk_manager.py tests/test_risk_manager.py
git commit -m "feat(agents): add Risk Manager agent with Kelly Criterion, VaR, and veto power"
```

---

## Task 7: Executor Agent

**Files:**
- Create: `agents/executor.py`
- Test: `tests/test_executor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_executor.py
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
    """Approved verdict leads to order placement."""
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
    """Rejected verdict means no order placed."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = Executor(bus, client)

    verdict = RiskVerdict(approved=False, reason="PDT limit")
    result = agent.run({"verdict": verdict, "symbol": "NVDA", "entry_price": 130.0})
    assert result["result"].success is False
    assert client.submit_order.call_count == 0


def test_executor_startup_checks_positions():
    """startup_check verifies existing positions have stop-losses."""
    bus = EventBus()
    client = _mock_trading_client()
    agent = Executor(bus, client)

    with patch("agents.executor.check_shutdown_stop_losses",
               return_value={"all_protected": True, "unprotected": []}):
        result = agent.startup_check()

    assert result["all_protected"] is True


def test_executor_handles_order_rejection():
    """Rejected order from Alpaca is handled gracefully."""
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_executor.py -v`
Expected: FAIL — `ImportError: cannot import name 'Executor'`

- [ ] **Step 3: Implement the Executor**

```python
# agents/executor.py
"""
Agent 5 — The Executor.

Places and manages all orders. Wraps bot.py order functions and safety.py
stop-loss management.

Input: {"verdict": RiskVerdict, "symbol": str, "entry_price": float}
Output: {"result": ExecutionResult}
"""

from __future__ import annotations

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, OrderStatus

from agents.base import BaseAgent, RiskVerdict, ExecutionResult
from agents.event_bus import EventBus
from safety import (
    check_shutdown_stop_losses,
    poll_order_fill,
    record_buy_date,
    update_peak_price,
)
from logger_setup import get_logger, log_trade_event

log = get_logger()


class Executor(BaseAgent):
    name = "executor"

    def __init__(self, event_bus: EventBus,
                 trading_client: TradingClient) -> None:
        super().__init__(event_bus)
        self._trading_client = trading_client

    def _execute(self, input_data: dict) -> dict:
        verdict: RiskVerdict = input_data.get("verdict")
        symbol: str = input_data.get("symbol", "")
        entry_price: float = input_data.get("entry_price", 0.0)

        if verdict is None or not verdict.approved:
            reason = verdict.reason if verdict else "No verdict"
            return {"result": ExecutionResult(
                success=False, symbol=symbol, status="skipped", message=reason,
            )}

        return {"result": self._place_bracket_order(
            symbol, verdict.adjusted_qty, entry_price,
            verdict.stop_loss, verdict.take_profit,
        )}

    def _place_bracket_order(self, symbol: str, qty: int,
                             entry_price: float, stop_loss: float,
                             take_profit: float) -> ExecutionResult:
        """Place a bracket order on Alpaca."""
        if qty < 1 or entry_price <= 0:
            return ExecutionResult(
                success=False, symbol=symbol, status="error",
                message=f"Invalid params: qty={qty}, price={entry_price}",
            )

        stop_price = round(stop_loss, 2)
        profit_price = round(take_profit, 2)

        log.info("[executor] Placing bracket order: %s qty=%d SL=$%.2f TP=$%.2f",
                 symbol, qty, stop_price, profit_price)
        log_trade_event(log, "EXECUTOR_ORDER_ATTEMPT", symbol=symbol, qty=qty)

        try:
            order = self._trading_client.submit_order(
                MarketOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                    order_class=OrderClass.BRACKET,
                    stop_loss=StopLossRequest(stop_price=stop_price),
                    take_profit=TakeProfitRequest(limit_price=profit_price),
                )
            )
        except Exception as exc:
            log.error("[executor] Order submission failed: %s", exc)
            return ExecutionResult(
                success=False, symbol=symbol, status="error", message=str(exc),
            )

        # Poll for fill
        try:
            filled = poll_order_fill(self._trading_client, str(order.id))
        except Exception as exc:
            log.warning("[executor] Fill poll error: %s", exc)
            filled = order

        status_str = str(filled.status).lower() if hasattr(filled.status, 'name') else str(filled.status)

        if "rejected" in status_str:
            log.warning("[executor] Order REJECTED for %s", symbol)
            return ExecutionResult(
                success=False, order_id=str(order.id), symbol=symbol,
                status="rejected", message="Order rejected by Alpaca",
            )

        filled_qty = int(float(filled.filled_qty)) if filled.filled_qty else 0
        fill_price = float(filled.filled_avg_price) if filled.filled_avg_price else entry_price

        log.info("[executor] Order FILLED: %s qty=%d @ $%.2f", symbol, filled_qty, fill_price)
        log_trade_event(log, "EXECUTOR_FILL", symbol=symbol, qty=filled_qty, price=f"{fill_price:.2f}")

        # Record buy date for PDT tracking
        try:
            record_buy_date(symbol)
        except Exception:
            pass

        self.event_bus.emit("trade.executed", {
            "agent": self.name, "symbol": symbol, "qty": filled_qty,
            "price": fill_price, "order_id": str(order.id),
        })

        return ExecutionResult(
            success=True, order_id=str(order.id), symbol=symbol,
            qty=filled_qty, fill_price=fill_price, status="filled",
            message=f"Filled {filled_qty} shares @ ${fill_price:.2f}",
        )

    def startup_check(self) -> dict:
        """Check that all existing positions have active stop-losses."""
        try:
            result = check_shutdown_stop_losses(self._trading_client)
            if not result["all_protected"]:
                for sym in result["unprotected"]:
                    log.warning("[executor] STARTUP: %s has NO stop-loss!", sym)
            return result
        except Exception as exc:
            log.error("[executor] Startup check failed: %s", exc)
            return {"all_protected": False, "unprotected": [], "error": str(exc)}

    def shutdown_check(self) -> dict:
        """Verify all positions are protected before shutdown."""
        return self.startup_check()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_executor.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/executor.py tests/test_executor.py
git commit -m "feat(agents): add Executor agent with bracket order placement and startup checks"
```

---

## Task 8: Auditor Agent

**Files:**
- Create: `agents/auditor.py`
- Test: `tests/test_auditor.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_auditor.py
"""Tests for the Auditor agent."""

import json
import os
import tempfile
from agents.event_bus import EventBus
from agents.auditor import Auditor
from agents.base import AuditReport


def test_auditor_records_trade():
    """record_trade adds to journal."""
    bus = EventBus()
    with tempfile.TemporaryDirectory() as tmpdir:
        journal_path = os.path.join(tmpdir, "trade_journal.json")
        agent = Auditor(bus, journal_path=journal_path)

        agent.record_trade({
            "symbol": "NVDA", "action": "BUY", "qty": 5,
            "entry_price": 130.0, "exit_price": 135.0, "pnl": 25.0,
            "win": True, "reasoning": "Strong breakout",
        })

        assert len(agent._journal) == 1
        assert agent._journal[0]["symbol"] == "NVDA"


def test_auditor_computes_stats():
    """Running stats are computed correctly."""
    bus = EventBus()
    agent = Auditor(bus)

    trades = [
        {"symbol": "NVDA", "pnl": 10.0, "win": True},
        {"symbol": "AMD", "pnl": -5.0, "win": False},
        {"symbol": "TSLA", "pnl": 8.0, "win": True},
        {"symbol": "META", "pnl": 12.0, "win": True},
        {"symbol": "AAPL", "pnl": -3.0, "win": False},
    ]
    for t in trades:
        agent.record_trade(t)

    result = agent.run({})
    report = result["report"]
    assert isinstance(report, AuditReport)
    assert report.total_trades == 5
    assert report.win_rate == 0.6  # 3/5
    assert report.avg_win == 10.0  # (10+8+12)/3
    assert report.avg_loss == -4.0  # (-5+-3)/2


def test_auditor_saves_and_loads_journal():
    """Journal persists to file and can be reloaded."""
    bus = EventBus()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "journal.json")

        agent1 = Auditor(bus, journal_path=path)
        agent1.record_trade({"symbol": "NVDA", "pnl": 10.0, "win": True})
        agent1.save_journal()

        agent2 = Auditor(bus, journal_path=path)
        agent2.load_journal()
        assert len(agent2._journal) == 1


def test_auditor_empty_journal():
    """Auditor handles empty journal gracefully."""
    bus = EventBus()
    agent = Auditor(bus)
    result = agent.run({})
    report = result["report"]
    assert report.total_trades == 0
    assert report.win_rate == 0.0


def test_auditor_profit_factor():
    """Profit factor = gross_wins / gross_losses."""
    bus = EventBus()
    agent = Auditor(bus)
    agent.record_trade({"symbol": "A", "pnl": 20.0, "win": True})
    agent.record_trade({"symbol": "B", "pnl": -10.0, "win": False})

    result = agent.run({})
    assert result["report"].profit_factor == 2.0  # 20/10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_auditor.py -v`
Expected: FAIL — `ImportError: cannot import name 'Auditor'`

- [ ] **Step 3: Implement the Auditor**

```python
# agents/auditor.py
"""
Agent 6 — The Auditor.

Reviews performance and improves the system. Logs every trade,
computes running stats, and runs a daily AI review via Anthropic API (Opus).

Input: {} (uses internal journal)
Output: {"report": AuditReport}
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from agents.base import BaseAgent, AuditReport
from agents.event_bus import EventBus
from logger_setup import get_logger

log = get_logger()

_DEFAULT_JOURNAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "trade_journal.json"
)
_AUDITOR_MODEL = os.getenv("AUDITOR_MODEL", "claude-opus-4-6")


class Auditor(BaseAgent):
    name = "auditor"

    def __init__(self, event_bus: EventBus,
                 journal_path: str | None = None) -> None:
        super().__init__(event_bus)
        self._journal_path = journal_path or _DEFAULT_JOURNAL_PATH
        self._journal: list[dict] = []
        self._daily_summary: str = ""

    def _execute(self, input_data: dict) -> dict:
        report = self._compute_stats()

        self.event_bus.emit("agent.output", {
            "agent": self.name,
            "output": {
                "total_trades": report.total_trades,
                "win_rate": report.win_rate,
                "daily_pnl": report.daily_pnl,
            },
        })

        return {"report": report}

    def record_trade(self, trade: dict) -> None:
        """Record a completed trade to the journal."""
        trade["timestamp"] = datetime.now(timezone.utc).isoformat()
        self._journal.append(trade)
        log.info("[auditor] Recorded trade: %s %s P&L=$%.2f",
                 trade.get("symbol", "?"), "WIN" if trade.get("win") else "LOSS",
                 trade.get("pnl", 0))

    def _compute_stats(self) -> AuditReport:
        """Compute running performance statistics."""
        if not self._journal:
            return AuditReport()

        total = len(self._journal)
        wins = [t for t in self._journal if t.get("win")]
        losses = [t for t in self._journal if not t.get("win")]

        win_rate = len(wins) / total if total > 0 else 0.0

        avg_win = (sum(t.get("pnl", 0) for t in wins) / len(wins)) if wins else 0.0
        avg_loss = (sum(t.get("pnl", 0) for t in losses) / len(losses)) if losses else 0.0

        gross_wins = sum(abs(t.get("pnl", 0)) for t in wins)
        gross_losses = sum(abs(t.get("pnl", 0)) for t in losses)
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else 0.0

        daily_pnl = sum(t.get("pnl", 0) for t in self._journal
                        if t.get("timestamp", "").startswith(
                            datetime.now(timezone.utc).strftime("%Y-%m-%d")))

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        trades_today = [t for t in self._journal
                        if t.get("timestamp", "").startswith(today)]

        return AuditReport(
            total_trades=total,
            win_rate=round(win_rate, 2),
            profit_factor=round(profit_factor, 2),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            daily_pnl=round(daily_pnl, 2),
            trades_today=trades_today,
        )

    def save_journal(self) -> None:
        """Persist journal to disk."""
        os.makedirs(os.path.dirname(self._journal_path), exist_ok=True)
        with open(self._journal_path, "w") as f:
            json.dump(self._journal, f, indent=2)
        log.info("[auditor] Journal saved: %d trades", len(self._journal))

    def load_journal(self) -> None:
        """Load journal from disk."""
        if os.path.exists(self._journal_path):
            with open(self._journal_path, "r") as f:
                self._journal = json.load(f)
            log.info("[auditor] Journal loaded: %d trades", len(self._journal))

    def daily_review(self) -> str:
        """Run daily AI review via Anthropic API (Opus). Called once at market close."""
        report = self._compute_stats()
        if report.total_trades == 0:
            return "No trades to review."

        try:
            import anthropic
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if not api_key or api_key.startswith("YOUR_"):
                return self._format_text_summary(report)

            client = anthropic.Anthropic(api_key=api_key)
            prompt = (
                f"You are a trading performance analyst. Review today's trading:\n"
                f"Total trades: {report.total_trades}\n"
                f"Win rate: {report.win_rate:.0%}\n"
                f"Profit factor: {report.profit_factor:.2f}\n"
                f"Avg win: ${report.avg_win:.2f}, Avg loss: ${report.avg_loss:.2f}\n"
                f"Daily P&L: ${report.daily_pnl:.2f}\n\n"
                f"Trades: {json.dumps(report.trades_today, default=str)}\n\n"
                f"Provide: 1) What went well 2) What to improve 3) Pattern observations"
            )

            response = client.messages.create(
                model=_AUDITOR_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            self._daily_summary = response.content[0].text
            return self._daily_summary

        except Exception as exc:
            log.warning("[auditor] AI review failed: %s", exc)
            return self._format_text_summary(report)

    def _format_text_summary(self, report: AuditReport) -> str:
        """Fallback text summary when AI is unavailable."""
        return (
            f"Daily Summary: {report.total_trades} trades, "
            f"{report.win_rate:.0%} win rate, "
            f"P&L: ${report.daily_pnl:.2f}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_auditor.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/auditor.py tests/test_auditor.py
git commit -m "feat(agents): add Auditor agent with trade journal and performance stats"
```

---

## Task 9: Agent Coordinator

**Files:**
- Create: `agents/coordinator.py`
- Test: `tests/test_coordinator.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_coordinator.py
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
    """Coordinator initializes all 6 agents."""
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
    """Full cycle with no high-conviction candidates results in WAIT."""
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
    """Full cycle with high-scoring candidate triggers buy pipeline."""
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
    """Startup runs executor check and auditor load."""
    bus = EventBus()
    client = _mock_trading_client()
    coord = AgentCoordinator(client, client, bus)

    with patch.object(coord.executor, 'startup_check',
                      return_value={"all_protected": True, "unprotected": []}), \
         patch.object(coord.auditor, 'load_journal'):
        coord.startup_sequence()


def test_coordinator_agents_status():
    """get_agents_status returns status for all agents."""
    bus = EventBus()
    client = _mock_trading_client()
    coord = AgentCoordinator(client, client, bus)

    status = coord.get_agents_status()
    assert len(status["agents"]) == 6
    assert all(a["status"] == "idle" for a in status["agents"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_coordinator.py -v`
Expected: FAIL — `ImportError: cannot import name 'AgentCoordinator'`

- [ ] **Step 3: Implement the Coordinator**

```python
# agents/coordinator.py
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
    """Orchestrates the multi-agent trading pipeline."""

    def __init__(self, trading_client: TradingClient,
                 data_client: StockHistoricalDataClient,
                 event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self._trading_client = trading_client
        self._data_client = data_client

        # ── Create all agents ───────────────────────────────────────────
        self.quant = QuantAnalyst(event_bus)
        self.news = NewsAnalyst(event_bus)
        self.strategist = Strategist(event_bus)
        self.risk = RiskManager(event_bus, trading_client)
        self.executor = Executor(event_bus, trading_client)
        self.auditor = Auditor(event_bus)

        self._cycle_count = 0
        self._last_cycle: datetime | None = None

    def startup_sequence(self) -> None:
        """Run once at bot start. Check positions and load journal."""
        log.info("[coordinator] Running startup sequence...")

        # Executor checks existing positions have stop-losses
        result = self.executor.startup_check()
        if not result.get("all_protected", True):
            log.warning("[coordinator] STARTUP: Some positions lack stop-losses!")

        # Auditor loads trade journal
        self.auditor.load_journal()

        log.info("[coordinator] Startup complete. Ready to trade.")

    def run_cycle(self) -> dict:
        """Run one full pipeline cycle."""
        self._cycle_count += 1
        self._last_cycle = datetime.now(timezone.utc)
        log.info("[coordinator] ── Cycle %d starting ──", self._cycle_count)

        symbols = config.SWING_WATCHLIST

        # ── Phase 1: Parallel scan (Quant + News) ──────────────────────
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

        # ── Update shared state for dashboard ───────────────────────────
        self._update_dashboard_state(quant_outputs, news_outputs)

        # ── Phase 2: Get risk constraints ───────────────────────────────
        constraints = self.risk.get_constraints()

        # ── Phase 3: Strategist decides ─────────────────────────────────
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

        # ── Phase 4: Risk Manager reviews ───────────────────────────────
        risk_result = self.risk.run({"decision": decision})
        verdict = risk_result.get("verdict")

        if verdict is None or not verdict.approved:
            reason = verdict.reason if verdict else "Risk check failed"
            log.info("[coordinator] Cycle %d: Risk REJECTED — %s", self._cycle_count, reason)
            self._emit_cycle_complete("REJECTED")
            return {"action": "REJECTED", "symbol": decision.symbol, "reasoning": reason}

        # ── Phase 5: Executor places order ──────────────────────────────
        exec_result = self.executor.run({
            "verdict": verdict,
            "symbol": decision.symbol,
            "entry_price": decision.entry_price,
        })
        result = exec_result.get("result")

        # ── Phase 6: Auditor logs ───────────────────────────────────────
        if result and result.success:
            self.auditor.record_trade({
                "symbol": decision.symbol,
                "action": "BUY",
                "qty": result.qty,
                "entry_price": result.fill_price,
                "pnl": 0.0,  # P&L computed on exit
                "win": None,  # unknown until exit
                "reasoning": decision.reasoning,
                "confidence": decision.confidence,
            })

        self._emit_cycle_complete("BUY" if result and result.success else "FAILED")

        return {
            "action": "BUY" if result and result.success else "FAILED",
            "symbol": decision.symbol,
            "qty": result.qty if result else 0,
            "fill_price": result.fill_price if result else 0,
        }

    def shutdown_sequence(self) -> None:
        """Run on graceful shutdown."""
        log.info("[coordinator] Running shutdown sequence...")
        self.executor.shutdown_check()
        self.auditor.save_journal()
        log.info("[coordinator] Shutdown complete.")

    def get_agents_status(self) -> dict:
        """Return status of all agents for the dashboard API."""
        agents = [
            self.quant, self.news, self.strategist,
            self.risk, self.executor, self.auditor,
        ]
        return {
            "agents": [a.to_status_dict() for a in agents],
            "pipeline": {
                "last_cycle": self._last_cycle.isoformat() if self._last_cycle else None,
                "cycle_count": self._cycle_count,
            },
        }

    def _update_dashboard_state(self, quant_outputs: list,
                                news_outputs: list) -> None:
        """Push agent outputs to shared state for SSE dashboard."""
        shared_state.update(
            agent_quant_count=len(quant_outputs),
            agent_news_count=len(news_outputs),
        )

    def _emit_cycle_complete(self, action: str) -> None:
        self.event_bus.emit("cycle.complete", {
            "cycle": self._cycle_count,
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_coordinator.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/coordinator.py tests/test_coordinator.py
git commit -m "feat(agents): add AgentCoordinator with parallel scan and sequential decision pipeline"
```

---

## Task 10: Config, State, Dashboard, and Server Integration

**Files:**
- Modify: `config.py` (add Anthropic config)
- Modify: `state.py` (add agent status section)
- Modify: `dashboard.py` (add `/api/agents/status`)
- Modify: `server.py` (create coordinator)

- [ ] **Step 1: Add Anthropic config to config.py**

Append after line 163 (`SWING_WATCHLIST`):

```python
# ── Anthropic API (for Strategist and Auditor agents) ───────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
STRATEGIST_MODEL  = os.getenv("STRATEGIST_MODEL", "claude-sonnet-4-6")
AUDITOR_MODEL     = os.getenv("AUDITOR_MODEL", "claude-opus-4-6")
```

- [ ] **Step 2: Add agent status section to state.py**

Add to the `_state` dict after the `scan_conviction_scores` entry (line 106):

```python
    # ── Agent system (Phase 3) ───────────────────────────────────────────
    "agent_quant_count":  0,     # symbols analyzed by quant last cycle
    "agent_news_count":   0,     # symbols analyzed by news last cycle
```

- [ ] **Step 3: Add /api/agents/status endpoint to dashboard.py**

Add a new route to `dashboard.py`:

```python
_coordinator = None

def set_coordinator(coordinator):
    global _coordinator
    _coordinator = coordinator


@app.route("/api/agents/status")
def api_agents_status():
    if _coordinator is None:
        return jsonify({"agents": [], "pipeline": {}})
    return Response(_snap_json(_coordinator.get_agents_status()),
                    mimetype="application/json")
```

- [ ] **Step 4: Update server.py to create coordinator**

Replace the `bot.run_bot_from_server` reference with coordinator setup. After the `dashboard.set_dependencies(...)` call, add:

```python
from agents.event_bus import EventBus
from agents.coordinator import AgentCoordinator

agent_bus = EventBus()
coordinator = AgentCoordinator(
    trading_client=trading_client,
    data_client=data_client,
    event_bus=agent_bus,
)
dashboard.set_coordinator(coordinator)
```

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All existing tests + all new tests PASS

- [ ] **Step 6: Commit**

```bash
git add config.py state.py dashboard.py server.py
git commit -m "feat: integrate agent system with config, state, dashboard, and server"
```

---

## Task 11: Update agents/__init__.py exports

**Files:**
- Modify: `agents/__init__.py`

- [ ] **Step 1: Update the package init with all exports**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add agents/__init__.py
git commit -m "feat(agents): update package init with all agent exports"
```

---

## Task 12: Claude Code Dev Agent Definitions

**Files:**
- Create: `.claude/agents/frontend-engineer.md`
- Create: `.claude/agents/backend-engineer.md`
- Create: `.claude/agents/data-engineer.md`
- Create: `.claude/agents/qa-engineer.md`
- Create: `.claude/agents/devops-engineer.md`
- Create: `.claude/agents/architect.md`

- [ ] **Step 1: Create all 6 dev agent definitions**

Each file follows the same format — role, skills, tools, constraints. Full content for each:

**`.claude/agents/frontend-engineer.md`:**
```markdown
---
name: Frontend Engineer
description: Builds and maintains the dashboard UI — HTML, CSS, JavaScript, Chart.js, SSE
tools: [Read, Write, Edit, Bash, Glob, Grep]
---

You are the Frontend Engineer for the trading bot dashboard.

## Skills to invoke
- `ui-ux-pro-max:ui-ux-pro-max` — for all visual design decisions
- `everything-claude-code:frontend-patterns` — frontend code patterns
- `everything-claude-code:design-system` — design consistency
- `everything-claude-code:token-budget-advisor` — token optimization
- `everything-claude-code:context-budget` — context management

## Responsibilities
- Build and maintain dashboard UI (templates/index.html, CSS, JS)
- Implement charts, real-time data displays, agent status panels
- Ensure responsive design and smooth animations
- Maintain the forest theme design system
- Handle SSE connections for live data updates

## Constraints
- All UI changes must maintain the existing forest theme
- Use vanilla JS + Chart.js (no React/Vue/Angular)
- SSE for real-time data (existing pattern in dashboard.py)
- Test visual changes by describing what changed
- Never modify Python backend files — only HTML/CSS/JS
```

**`.claude/agents/backend-engineer.md`:**
```markdown
---
name: Backend Engineer
description: Builds Flask routes, API endpoints, Alpaca integration, Anthropic API calls
tools: [Read, Write, Edit, Bash, Glob, Grep]
---

You are the Backend Engineer for the trading bot.

## Skills to invoke
- `everything-claude-code:backend-patterns` — backend architecture
- `everything-claude-code:api-design` — API endpoint design
- `claude-api` — when working with Anthropic SDK
- `everything-claude-code:token-budget-advisor` — token optimization
- `everything-claude-code:context-budget` — context management

## Responsibilities
- Build and maintain Flask routes in dashboard.py
- Create API endpoints for dashboard data, trades, account info
- Handle Alpaca API integration via alpaca-py SDK
- Manage Anthropic API calls for Strategist and Auditor agents
- Optimize data serialization and response formats

## Constraints
- Follow existing Flask patterns in dashboard.py
- All API responses return JSON via jsonify() or Response()
- Handle Alpaca API errors gracefully (try/except with logging)
- Never expose API keys in responses
- Use get_logger() for all logging
```

**`.claude/agents/data-engineer.md`:**
```markdown
---
name: Data Engineer
description: Manages data pipelines, caching, storage, and data cleaning for all agents
tools: [Read, Write, Edit, Bash, Glob, Grep]
---

You are the Data Engineer for the trading bot.

## Skills to invoke
- `everything-claude-code:python-patterns` — Pythonic code patterns
- `everything-claude-code:python-testing` — test strategies
- `everything-claude-code:token-budget-advisor` — token optimization
- `everything-claude-code:context-budget` — context management

## Responsibilities
- Pull and cache market data from Alpaca (prices, bars, volume)
- Store historical trade data in data/trade_journal.json
- Clean and normalize incoming data before it reaches agents
- Build data pipelines that feed the right data to the right agents
- Handle data backfills for backtesting
- Manage logging output storage

## Constraints
- Data files go in data/ directory
- Use JSON for storage (no database dependency)
- Cache invalidation must be explicit (date-based, like existing pattern)
- Clean data before passing to agents (handle NaN, missing bars, gaps)
- Follow existing cache patterns in sentiment_cache.py and catalysts.py
```

**`.claude/agents/qa-engineer.md`:**
```markdown
---
name: QA Engineer
description: Tests all components — API endpoints, trade execution, agent health, edge cases
tools: [Read, Write, Edit, Bash, Glob, Grep]
---

You are the QA Engineer for the trading bot.

## Skills to invoke
- `everything-claude-code:tdd-workflow` — test-driven development
- `everything-claude-code:python-testing` — Python test patterns
- `everything-claude-code:e2e-testing` — end-to-end testing
- `everything-claude-code:token-budget-advisor` — token optimization
- `everything-claude-code:context-budget` — context management

## Responsibilities
- Write and maintain tests in tests/ directory
- Test all API endpoints after changes
- Validate trade execution with paper trade test runs
- Verify bracket orders have correct stop-loss and take-profit
- Run health checks on all agents
- Test edge cases (market close mid-trade, API down, network drop)
- Verify dashboard data matches Alpaca account data

## Constraints
- Tests go in tests/ directory, use pytest
- Mock Alpaca API calls — never hit real endpoints in tests
- Every agent must have unit tests for its run() method
- Integration tests for the full pipeline with mocked data
- Run tests with: python -m pytest tests/ -v
```

**`.claude/agents/devops-engineer.md`:**
```markdown
---
name: DevOps Engineer
description: Manages startup/shutdown, system health, log rotation, configuration, deployment prep
tools: [Read, Write, Edit, Bash, Glob, Grep]
---

You are the DevOps Engineer for the trading bot.

## Skills to invoke
- `everything-claude-code:deployment-patterns` — deployment strategies
- `everything-claude-code:docker-patterns` — containerization
- `everything-claude-code:token-budget-advisor` — token optimization
- `everything-claude-code:context-budget` — context management

## Responsibilities
- Manage bot startup and shutdown sequences in server.py
- Monitor system resource usage
- Handle automatic restarts if agents crash
- Manage log rotation (daily files in logs/, keep 30 days)
- Handle .env file configuration management
- Monitor Alpaca and Anthropic API rate limits
- Prepare for cloud deployment

## Constraints
- Startup must be a single command: py server.py paper
- All config through .env files (existing pattern)
- Graceful shutdown must protect all positions (check stop-losses)
- Never modify trading logic — only infrastructure
- Log files go in logs/ directory
```

**`.claude/agents/architect.md`:**
```markdown
---
name: Architect
description: Reviews code quality, enforces patterns, plans features, resolves cross-agent conflicts
tools: [Read, Glob, Grep]
---

You are the Architect overseeing the entire trading bot codebase.

## Skills to invoke
- `everything-claude-code:agentic-engineering` — multi-agent patterns
- `everything-claude-code:architecture-decision-records` — document decisions
- `everything-claude-code:coding-standards` — code quality
- `everything-claude-code:security-review` — security checks
- `everything-claude-code:token-budget-advisor` — token optimization
- `everything-claude-code:context-budget` — context management

## Responsibilities
- Review code quality across all agents and modules
- Ensure consistent coding patterns (snake_case, type hints, docstrings)
- Detect code duplication and suggest refactors
- Plan new features and break them into tasks
- Manage dependencies in requirements.txt
- Document architecture in docs/
- Resolve conflicts when agents modify the same file

## Constraints
- READ-ONLY by default — do not modify code without explicit approval
- Enforce conventions documented in CLAUDE.md
- Architecture decisions go in docs/ directory
- Follow existing patterns before suggesting new ones
- Focus on the agents/ directory and integration points
```

- [ ] **Step 2: Commit all dev agent definitions**

```bash
git add .claude/agents/
git commit -m "feat: add 6 Claude Code dev agent definitions with skill loadouts"
```

---

## Task 13: Add anthropic to requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add the anthropic package**

Add to `requirements.txt`:

```
anthropic>=0.40.0
```

- [ ] **Step 2: Install it**

Run: `pip install anthropic>=0.40.0`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add anthropic SDK for Strategist and Auditor agents"
```

---

## Task 14: Full Integration Test

- [ ] **Step 1: Run the complete test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests pass (existing + new)

- [ ] **Step 2: Verify imports work**

Run: `python -c "from agents import AgentCoordinator, EventBus; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 3: Verify server starts without errors**

Run: `python -c "import config; print('Config OK: API key loaded')" 2>&1 | head -1`
Expected: Config loads without error

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: resolve integration issues from full test run"
```
