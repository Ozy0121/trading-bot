# Architecture

**Analysis Date:** 2026-03-27

## Pattern Overview

**Overall:** Modular polling-based trading bot with layered signal processing

**Key Characteristics:**
- Polling loop architecture (not event-driven) — cycles every 60s to evaluate signals
- Swing trading strategy — holds overnight, high-conviction entries only
- Multi-signal confirmation required (SMA + RSI + Volume + MACD)
- Safety guardrails first — all risky operations guarded by checks
- Background threads for real-time data — WebSocket stream and sentiment polling run async
- Shared state pattern — thread-safe in-memory state accessed by bot, dashboard, and background tasks

## Layers

**Data/Market Layer:**
- Purpose: Fetch and normalize market data from Alpaca and free data sources
- Location: `strategy.py`, `scanner.py`, `stream.py`, `sentiment.py`, `catalysts.py`
- Contains: Bar fetching, technical indicator computation, watchlist scanning, catalyst lookups, real-time streaming
- Depends on: Alpaca SDK, yfinance, Yahoo Finance APIs, arkfunds.io
- Used by: Bot core loop, dashboard

**Signal Processing Layer:**
- Purpose: Compute trading signals by combining multiple filters
- Location: `strategy.py`, `indicators.py`, `scanner.py`
- Contains: SMA crossover detection, RSI filtering, volume ratio checks, MACD validation, catalyst scoring
- Depends on: Data layer (bar data), technical indicator functions
- Used by: Bot main loop, watchlist ranking

**Safety/Guardrails Layer:**
- Purpose: Enforce all risk controls before any trade execution
- Location: `safety.py`
- Contains: Daily loss limit tracking, position sizing (dynamic and capped), PDT rule checking, trailing stop management, market hours validation, emergency liquidation
- Depends on: Alpaca SDK, config
- Used by: Bot core loop (every decision point checks safety first)

**Trading Execution Layer:**
- Purpose: Submit orders to Alpaca and record trade outcomes
- Location: `bot.py` (place_buy, place_sell functions), `safety.py` (liquidate_all)
- Contains: Market order submission, trade logging, PnL recording, consecutive loss tracking
- Depends on: Alpaca SDK, shared_state, logger
- Used by: Bot core loop

**Configuration Layer:**
- Purpose: Load and validate all environment settings
- Location: `config.py`
- Contains: API credentials, trading parameters (SMA windows, RSI limits, position sizes), safety limits, timeframes, watchlists
- Depends on: python-dotenv
- Used by: All modules (imported globally)

**Shared State Layer:**
- Purpose: Thread-safe in-memory state shared across all threads
- Location: `state.py`
- Contains: Account info, current position, technical indicators, signal history, trade log, growth metrics, P&L calendar, watchlist results
- Depends on: threading (Lock)
- Used by: Bot thread, dashboard thread, sentiment thread, stream thread

**Web Interface Layer:**
- Purpose: REST API and HTML dashboard for monitoring and control
- Location: `dashboard.py`, `templates/index.html`
- Contains: Flask routes for state snapshots, bar charts, order management, bot start/stop control
- Depends on: Flask, shared_state, Alpaca SDK (for position and order queries)
- Used by: Browser clients

**Logging Layer:**
- Purpose: Structured logging with event tracking
- Location: `logger_setup.py`, used throughout
- Contains: Logger configuration, trade event logging helpers
- Depends on: Python logging stdlib
- Used by: All modules

## Data Flow

**Main Trading Cycle (Every 60 seconds):**

1. Check market hours → skip if closed
2. Fetch account state (equity, cash, buying_power)
3. Check daily loss limit → kill switch if exceeded
4. Query PDT status → enforce day-trade limits
5. Fetch latest bars from Alpaca
6. Compute technical indicators (SMA, RSI, MACD, Bollinger Bands)
7. Detect SMA signal (BUY/SELL/HOLD)
8. If BUY signal:
   - Check RSI < MAX_RSI_BUY (not overbought)
   - Check volume ratio >= MIN_VOLUME_RATIO
   - Check MACD histogram > 0
   - Fetch catalyst bonuses (ARK buys, analyst upgrades)
   - Score the candidate
   - If all conditions pass → place buy order
9. If position open:
   - Check if trailing stop triggered → sell if yes
   - Check if take-profit target hit → sell if yes
   - Track peak price for next cycle
10. Update shared state with current indicators
11. Sleep until next cycle

**Background Streams:**

- **Real-time price stream:** WebSocket to Alpaca → updates `state.price` every bar close (1-min cadence) → dashboard shows live price between polling cycles
- **Sentiment polling:** Every 5 minutes fetches Fear & Greed index + news headlines → updates state for dashboard display

**State Management:**

- Shared state is a dictionary protected by a threading.Lock
- All reads/writes go through `state.update()` and `state.snapshot()`
- Trade history and chart history are deques with max length (prevents unbounded memory)
- PDT info cached per day (refreshed once at open)
- Catalyst caches expire (ARK per day, upgrades per hour)

## Key Abstractions

**Safety Module (`safety.py`):**
- Purpose: Central authority for all risk decisions
- Examples: `daily_loss_exceeded()`, `calculate_safe_qty()`, `check_pdt_allows_buy()`, `trailing_stop_triggered()`, `liquidate_all()`
- Pattern: Guard clauses checked before every risky action. Logs every safety event at WARNING+ level.

**Indicator Computation (`indicators.py`):**
- Purpose: Pure calculation functions, no side effects
- Examples: `rsi()`, `macd()`, `bollinger_bands()`, `compute_all()`
- Pattern: Takes pandas Series, returns Series or tuple of Series. Full history available; caller picks last value for current signal.

**Scanner (`scanner.py`):**
- Purpose: Rank candidates by score
- Examples: `fetch_top_movers()`, `best_buy()`, `scan()`
- Pattern: Returns sorted list of candidates. Each candidate is scored 0-100 (sum of signal strength + catalyst bonus). Top scorer is "best buy".

**Shared State (`state.py`):**
- Purpose: Thread-safe read/write for all shared data
- Examples: `update()`, `snapshot()`, `push_history()`, `record_trade()`
- Pattern: Dictionary with Lock. Atomic operations only (no complex multi-step updates without lock). All datetimes are ISO strings in shared state (JSON-safe).

## Entry Points

**Bot Server Entry (`server.py`):**
- Location: `server.py`
- Triggers: `python server.py paper` or `python server.py live`
- Responsibilities:
  1. Load correct `.env.{mode}` file before importing config
  2. Initialize Alpaca clients (trading and data)
  3. Start background threads: real-time stream, sentiment polling
  4. Pass clients to bot and dashboard via dependency injection
  5. Start Flask server on DASHBOARD_PORT
  6. Blocks until server stops

**Bot Core Entry (`bot.run_bot()`):**
- Location: `bot.py` (exported function)
- Triggers: Called from dashboard API `/api/start` endpoint
- Responsibilities:
  1. Enter polling loop (checks `_shutdown_requested` flag)
  2. Each cycle: fetch data, compute signals, execute trades, update state
  3. Handle Ctrl-C gracefully (signal handlers call `_handle_signal()` which liquidates positions)
  4. Exit when goal reached or daily loss limit hit

**Dashboard API Entry (`dashboard.py`):**
- Location: `dashboard.py` (Flask app)
- Triggers: HTTP requests from browser
- Responsibilities:
  1. Serve static HTML and real-time API endpoints
  2. `/api/state` — snapshot of shared state
  3. `/api/stream` — Server-Sent Events (push updates every 1s)
  4. `/api/start`, `/api/kill`, `/api/sell_all` — control endpoints

## Error Handling

**Strategy:** Fail safely, log comprehensively, continue operating

**Patterns:**

1. **API failures (Alpaca, Yahoo Finance, arkfunds.io):** Catch at source, log warning, continue with cached/default data. Example: top movers fetch fails → fall back to static WATCHLIST.

2. **Data gaps (no bars, missing indicators):** Check before using. Example: if fewer bars than LONG_WINDOW, signal = HOLD.

3. **Market hours violations:** Assert at start of cycle. Prevent trades outside 9:30–16:00 EST.

4. **Trade rejection (insufficient funds, PDT, order canceled):** Alpaca SDK raises exception. Bot logs error and continues next cycle. Order status tracked but not retried automatically.

5. **Safety violations:** Always log at CRITICAL level and trigger kill switch (liquidate all + exit). Examples: daily loss limit, account balance negative.

6. **Background thread crashes (stream, sentiment):** Daemon threads log error but don't crash main bot. Stream disconnection → price stale but bot continues. Sentiment fetch fails → old data shown.

## Cross-Cutting Concerns

**Logging:**
- Framework: Python `logging` module
- Setup: `logger_setup.py` configures console + file handlers
- Convention: All logs include module prefix `[bot]`, `[stream]`, `[strategy]`, etc.
- Event logging: `log_trade_event()` helper for structured event capture (BUY, SELL, SIGNAL, ERROR)
- Levels: DEBUG (data/ticks), INFO (cycle summary, signals), WARNING (recoverable issues), CRITICAL (loss limit, safety violations)

**Validation:**
- Input: Config values validated at import time in `config.py`. Raises ValueError if invalid.
- Data: Bar DataFrame checked for size before computing indicators.
- Orders: Qty checked > 0 before submission. Price checked > 0.

**Authentication:**
- Alpaca API: API key + secret key from config (loaded from .env)
- Paper vs Live: Controlled by `PAPER_TRADING` flag (sets Alpaca SDK `paper=True/False`)
- Dashboard: No authentication (runs on localhost only, assumes trusted network)

**Thread Safety:**
- Shared state: Protected by Lock in `state.py`
- Global caches: ARK and upgrade caches guarded by date/timestamp checks (no Lock, tolerates stale reads)
- Signal handlers: Bot sets `_shutdown_requested` flag (atomic boolean, safe for signal handler)
- Background threads: All daemon threads, exit when main exits
