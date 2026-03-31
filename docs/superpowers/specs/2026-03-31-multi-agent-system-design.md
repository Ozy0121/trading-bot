# Multi-Agent Trading System Design Spec

**Date:** 2026-03-31
**Status:** Approved
**Branch:** master

---

## Overview

A 12-agent system for the trading bot split into two teams:

- **Trading agents (1-6):** Runtime Python classes that run during market hours. They scan, analyze, decide, risk-check, execute, and audit trades through a sequential pipeline with parallel scanning.
- **Dev agents (7-12):** Claude Code subagent definitions (`.claude/agents/*.md`) dispatched when working on the codebase. Each has a focused role, skill loadout, and constraints.

An `AgentCoordinator` orchestrates the trading pipeline. A lightweight event bus provides non-critical notifications to the dashboard and auditor.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Dev agents model | Claude Code subagents (`.claude/agents/`) | Dev work happens at development time, not runtime. Subagents are version-controlled and customizable. |
| AI call strategy | On trigger only | Python scoring filters first. Strategist only calls Anthropic API when a candidate passes the threshold. Saves cost. |
| Agent communication | Hybrid — direct method calls for pipeline, `state.py` for dashboard | Pipeline is explicit and testable. Dashboard integration uses existing pattern. |
| Risk Manager vs safety.py | Wrap, don't replace | `safety.py` is battle-tested with 88 tests. Risk Manager extends it with Kelly Criterion, VaR, drawdown, correlation. |
| Dashboard integration | API + simple status table (Phase 1) | Get agents working first, expose data via `/api/agents/status`. Fancy panel in a later phase. |
| AI model | Configurable — Sonnet default, Opus for Auditor | Sonnet for frequent trigger checks (cheap). Opus for daily review (one call, worth the quality). |
| Architecture | Parallel scan + sequential decision + event bus | Quant and News run in parallel. Decision chain is strict sequential. Event bus for observability only. |

## Architecture

### Pipeline Flow

```
Startup:
  Executor.check_positions() -> Risk Manager.verify_stops() -> Auditor.load_journal()

Each Cycle (every POLL_INTERVAL seconds):
  +-- Quant Analyst.run() --+
  |                         +--> Strategist.run() --> Risk Manager.review() --> Executor.execute()
  +-- News Analyst.run() ---+          |                     |                       |
                                       v                     v                       v
                                  event_bus.emit()     event_bus.emit()        event_bus.emit()
                                       |                     |                       |
                                  [Dashboard SSE]      [Auditor.log()]         [Status table]

Shutdown:
  Executor.verify_positions_protected() -> Auditor.write_daily_summary()
```

### Key Rules

- The decision chain (Strategist -> Risk Manager -> Executor) is **strictly sequential**. No concurrency on money decisions.
- The event bus is for **observability only** — dashboard updates, audit logging, status tracking. Never for trade decisions.
- Agents don't import each other. They only know about their input/output dataclasses.
- The coordinator owns all threading. Agents never spawn their own threads.

## Agent Base Class

All 6 trading agents inherit from `BaseAgent`:

```python
# agents/base.py

class BaseAgent:
    name: str              # "quant_analyst", "risk_manager", etc.
    status: str            # "idle", "running", "error", "disabled"
    last_run: datetime     # timestamp of last run() call
    last_output: dict      # most recent output (for dashboard)
    last_error: str | None # most recent error message

    def run(self, input_data: dict) -> dict:
        """Every agent takes a dict in, returns a dict out."""

    def health_check(self) -> bool:
        """Returns True if agent is functioning."""
```

Every `run()` call is wrapped by the base class in try/except that catches errors, updates agent status, and emits to the event bus. Agents return typed dataclasses, not raw dicts.

## Trading Agents

### Agent 1 — Quant Analyst (`agents/quant_analyst.py`)

**Role:** Crunches all the numbers.
**Input:** Watchlist of symbols + OHLCV bar data.
**Output:** `list[QuantOutput]` — one per symbol, sorted by composite score.

Calculates per symbol:
- Existing indicators via `indicators.compute_all()`: RSI, MACD, SMA crossovers, Bollinger Bands
- Existing scoring via `scanner.scan()`: composite conviction score, volume ratio, sector momentum
- **New indicators:** Stochastic RSI, ATR (for stop-loss sizing), Beta vs SPY, Rate of Change, Money Flow Index, On-Balance Volume, VWAP, Bollinger %B
- **New analytics:** 20-day and 60-day historical volatility, probability of X% move in 1/3/5 days (historical distribution), expected value of proposed trades, Sharpe Ratio, Sortino Ratio

Composite convergence score (0-100) uses the existing conviction framework: technical 40%, volume 20%, sentiment 20%, sector 20%.

**Wraps:** `scanner.py`, `indicators.py`, `strategies/*`. Does not replace them.

### Agent 2 — News Analyst (`agents/news_analyst.py`)

**Role:** Everything the numbers can't tell you.
**Input:** Watchlist of symbols.
**Output:** `list[NewsOutput]` — one per symbol with sentiment data.

Responsibilities:
- Alpaca news API headlines + free RSS feeds
- Headline sentiment scoring (bullish/neutral/bearish)
- Analyst upgrades/downgrades (from `catalysts.py`)
- Unusual volume spike detection (2x+ average = institutional activity flag)
- Earnings calendar — flags stocks with earnings in next 5 days as high risk
- Sector momentum tracking (which sectors are hot today)
- Macro catalyst awareness (fed meetings, economic data releases from free RSS)
- Information edge score (0-100)

**Wraps:** `sentiment.py`, `sentiment_cache.py`, `catalysts.py`. Does not replace them.

### Agent 3 — Strategist (`agents/strategist.py`)

**Role:** Head decision maker. Only agent that calls Anthropic API.
**Input:** `list[QuantOutput]` + `list[NewsOutput]` + `RiskConstraints`.
**Output:** `StrategyDecision` — BUY/SELL/HOLD/WAIT with full reasoning.

Logic flow:
1. Receives Quant + News data for all watchlist symbols
2. Filters to candidates with composite score above threshold (uses existing `CONVICTION_THRESHOLD` from config, currently 5.8/10 scaled to 58/100)
3. If candidates exist: calls Anthropic API (Sonnet by default, configurable) with structured prompt containing top candidates' full data packages
4. AI returns: trade decision, confidence score (1-10), entry price, stop-loss, take-profit, reasoning
5. Only acts on confidence 8+
6. Sets daily trading plan (aggressive/conservative/sit out) based on market regime detection (trending/mean-reverting/choppy using SPY volatility + breadth)

When no candidates pass the threshold: returns WAIT with "no high-conviction setups" — no API cost.

**Model config:** `STRATEGIST_MODEL` env var, defaults to `claude-sonnet-4-6`.

### Agent 4 — Risk Manager (`agents/risk_manager.py`)

**Role:** Protects the account. Has VETO power over all trades.
**Input:** `StrategyDecision` + current portfolio state.
**Output:** `RiskVerdict` — approved/rejected with reason, adjusted position size, stop-loss levels.

Hard rules (non-overridable, delegated to `safety.py`):
- Max 5% of account on any single trade
- Max 3 day trades per 5 business days (PDT) — `safety.check_pdt_allows_buy()`
- Daily loss limit of $25 — `safety.daily_loss_exceeded()`
- All positions must have bracket orders

New capabilities (on top of `safety.py`):
- Kelly Criterion position sizing (optimal bet size from win rate and payoff ratio)
- Value at Risk (VaR) — max loss estimate at 95% confidence
- Maximum drawdown tracking
- Portfolio correlation monitoring (don't hold 3 correlated tech stocks)
- Final position size = min(Kelly sizing, 5% hard cap)

**Wraps:** `safety.py`. Does not replace it.

### Agent 5 — Executor (`agents/executor.py`)

**Role:** Places and manages all orders.
**Input:** `RiskVerdict` (approved trades with adjusted sizing).
**Output:** `ExecutionResult` — order IDs, fill status, position updates.

Responsibilities:
- Places bracket orders on Alpaca (entry + stop-loss + take-profit)
- Monitors order status (filled, partial, rejected)
- Adjusts trailing stops as price moves (wraps `safety.update_peak_price()`, `safety.trailing_stop_triggered()`)
- On startup: checks all existing positions have active stop-losses (wraps `safety.check_shutdown_stop_losses()`)
- On shutdown: verifies all positions are protected, warns if not

**Wraps:** Order placement functions from `bot.py`, stop-loss management from `safety.py`.

### Agent 6 — Auditor (`agents/auditor.py`)

**Role:** Reviews performance and improves the system.
**Input:** All trade events from the day + historical performance data.
**Output:** `AuditReport` — performance metrics, improvement suggestions, daily report.

Responsibilities:
- Logs every trade: entry, exit, P&L, reasoning, signals that triggered it
- Running stats: win rate, profit factor, average win, average loss
- Pattern detection: which setups work best, time of day, market conditions
- Daily review via Anthropic API (Opus) — compares AI predictions vs actual outcomes
- Trade journal stored in `data/trade_journal.json`
- Daily summary pushed to dashboard via event bus

**Model config:** `AUDITOR_MODEL` env var, defaults to `claude-opus-4-6`.

## Event Bus

### `agents/event_bus.py`

Lightweight pub/sub for non-critical notifications.

```python
class EventBus:
    def subscribe(self, event_type: str, callback: Callable) -> None: ...
    def emit(self, event_type: str, data: dict) -> None: ...
```

Event types:
- `agent.status` — agent started/finished/errored
- `agent.output` — agent produced new output
- `trade.executed` — order placed
- `trade.filled` — order filled
- `risk.veto` — Risk Manager rejected a trade
- `cycle.complete` — full pipeline cycle finished

Thread-safe with a lock. Callbacks run in the emitting thread.

## Agent Coordinator

### `agents/coordinator.py`

Replaces the `bot.py` main loop. Owns all 6 agents, runs the pipeline.

```python
class AgentCoordinator:
    def __init__(self, trading_client, data_client, event_bus):
        self.quant = QuantAnalyst()
        self.news = NewsAnalyst()
        self.strategist = Strategist()
        self.risk = RiskManager(trading_client)
        self.executor = Executor(trading_client)
        self.auditor = Auditor()
        self.event_bus = event_bus

    def startup_sequence(self) -> None:
        """Executor checks positions, Risk Manager verifies stops, Auditor loads journal."""

    def run_cycle(self) -> None:
        """One scan cycle. Quant+News parallel, then sequential decision chain."""

    def shutdown_sequence(self) -> None:
        """Executor verifies positions protected, Auditor writes daily summary."""
```

Integration:
- `server.py` creates the coordinator instead of calling `bot.run()` directly
- `dashboard.py` subscribes to event bus for SSE updates
- `state.py` still used for dashboard-facing data — coordinator writes agent outputs there after each cycle
- `/api/start` calls `coordinator.startup_sequence()` then starts the polling loop

## Dashboard API

One new endpoint for Phase 1:

```
GET /api/agents/status
Response: {
    "agents": [
        {
            "name": "quant_analyst",
            "status": "idle",
            "last_run": "2026-03-31T10:15:00Z",
            "last_action": "Scored 60 symbols, top: NVDA (82.3)",
            "error": null
        },
        ...
    ],
    "pipeline": {
        "last_cycle": "2026-03-31T10:15:00Z",
        "cycle_count": 42,
        "next_cycle_in": 35
    }
}
```

Rendered as a simple status table in the existing dashboard: agent name, colored status dot (green/yellow/red), last action text, error if any.

## Dev Agents (Claude Code Subagents)

Six markdown files in `.claude/agents/` defining specialized Claude Code agents.

### Shared Skills (all dev agents)

- `everything-claude-code:token-budget-advisor`
- `everything-claude-code:context-budget`

### Agent Definitions

| Agent | File | Primary Skills |
|-------|------|---------------|
| Frontend Engineer | `frontend-engineer.md` | `ui-ux-pro-max`, `frontend-patterns`, `design-system` |
| Backend Engineer | `backend-engineer.md` | `backend-patterns`, `api-design`, `claude-api` |
| Data Engineer | `data-engineer.md` | `python-patterns`, `python-testing` |
| QA Engineer | `qa-engineer.md` | `tdd-workflow`, `python-testing`, `e2e-testing` |
| DevOps Engineer | `devops-engineer.md` | `deployment-patterns`, `docker-patterns` |
| Architect | `architect.md` | `agentic-engineering`, `architecture-decision-records`, `coding-standards`, `security-review` |

Dev agents are tools for Claude Code, not runtime processes. Dispatched based on task type:
- "Fix the dashboard layout" -> Frontend Engineer
- "Add a new API endpoint" -> Backend Engineer
- "Write tests for the Risk Manager" -> QA Engineer
- "Review the agent coordinator code" -> Architect

## File Structure

```
trading-bot/
+-- agents/                       # NEW - all trading agent code
|   +-- __init__.py
|   +-- base.py                   # BaseAgent class + dataclasses
|   +-- event_bus.py              # Lightweight pub/sub
|   +-- coordinator.py            # AgentCoordinator - runs the pipeline
|   +-- quant_analyst.py          # Agent 1
|   +-- news_analyst.py           # Agent 2
|   +-- strategist.py             # Agent 3
|   +-- risk_manager.py           # Agent 4
|   +-- executor.py               # Agent 5
|   +-- auditor.py                # Agent 6
+-- .claude/
|   +-- agents/                   # NEW - Claude Code dev agent definitions
|       +-- frontend-engineer.md
|       +-- backend-engineer.md
|       +-- data-engineer.md
|       +-- qa-engineer.md
|       +-- devops-engineer.md
|       +-- architect.md
+-- data/
|   +-- trade_journal.json        # NEW - Auditor's trade log
+-- bot.py                        # MODIFIED - delegates to coordinator
+-- server.py                     # MODIFIED - creates coordinator
+-- dashboard.py                  # MODIFIED - /api/agents/status endpoint
+-- state.py                      # MODIFIED - agent status section
+-- config.py                     # MODIFIED - Anthropic API config
+-- safety.py                     # UNCHANGED - wrapped by Risk Manager
+-- indicators.py                 # UNCHANGED - wrapped by Quant Analyst
+-- scanner.py                    # UNCHANGED - wrapped by Quant Analyst
+-- sentiment.py                  # UNCHANGED - wrapped by News Analyst
+-- sentiment_cache.py            # UNCHANGED - wrapped by News Analyst
+-- catalysts.py                  # UNCHANGED - wrapped by News Analyst
+-- strategies/                   # UNCHANGED - wrapped by Quant Analyst
```

### Changes to Existing Files

| File | Change | Scope |
|------|--------|-------|
| `server.py` | Create `AgentCoordinator` instead of calling `bot.run()` | ~20 lines |
| `dashboard.py` | Add `/api/agents/status`, subscribe to event bus | ~40 lines |
| `state.py` | Add `agents` section to `_state` dict | ~15 lines |
| `config.py` | Add `ANTHROPIC_API_KEY`, `STRATEGIST_MODEL`, `AUDITOR_MODEL` | ~10 lines |
| `bot.py` | Keep as-is. Coordinator calls its helper functions. Main loop moves to coordinator. | Minimal |

### Unchanged Files

`safety.py`, `indicators.py`, `scanner.py`, `sentiment.py`, `sentiment_cache.py`, `catalysts.py`, `strategies/*`, `logger_setup.py`, `stream.py`, `kill_switch.py` — all wrapped by agents, not modified.
