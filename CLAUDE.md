<!-- GSD:project-start source:PROJECT.md -->
## Project

**Trading Bot v2**

An automated swing-trading bot for a small ($500) Alpaca brokerage account constrained by PDT rules (3 trades per 5 business days). It scans for high-conviction stock setups across multiple strategies (momentum breakouts, mean reversion, catalyst-driven), executes 1-3 day holds, and incorporates simple options trading (buying calls/puts) to maximize returns with limited capital. Runs via a Flask dashboard with real-time data.

**Core Value:** Maximize the value of each of the 3 allowed trades per week by finding the highest-conviction swing trade setups across stocks and options, with aggressive position sizing appropriate for a small growth-focused account.

### Constraints

- **PDT**: Max 3 round-trip trades per 5 business days — every trade must count
- **Capital**: ~$500 — limits options to cheap contracts, small stock positions
- **Broker**: Alpaca API only — must use alpaca-py SDK for all trading
- **Hold time**: 1-3 days preferred — overnight holds acceptable
- **Risk**: Aggressive growth mode, but still respect daily loss limits
<!-- GSD:project-end -->

## Prediction Bot Identity

This is a **PREDICTION bot**. The entire purpose is to PREDICT which stocks will spike BEFORE they spike, and buy them BEFORE the move happens.

The mean reversion engine is ONE tool in the toolbox, not the whole identity. The bot must:

- **PREDICT**: Use historical pattern matching, CVD divergence, LVN detection, AMT analysis, volume accumulation patterns, news sentiment, and the multi-strategy scoring engine to PREDICT what a stock will do in the next 1-3 days
- **BUY BEFORE THE MOVE**: Identify stocks in the accumulation/setup phase BEFORE the breakout or bounce happens. Not after.
- **EXPLAIN THE PREDICTION**: Every trade the bot takes or recommends must come with a prediction statement. Example: "PREDICTION: NVDA will bounce 3-5% within 2 days. REASON: RSI(2) at 4.8, 3 consecutive down days, price touching lower Bollinger Band, CVD showing hidden buying, price sitting at LVN with institutional defense detected. Historical accuracy of this setup: 71% over 83 occurrences."
- **TRACK PREDICTION ACCURACY**: Log every prediction with the predicted move and actual outcome. Show running accuracy on the dashboard: "Last 30 predictions: 21 correct (70%)"
- **THE MEAN REVERSION ENGINE IS A PREDICTION**: When all 3-of-4 oversold gates fire, the bot is PREDICTING a bounce. Frame it that way: "PREDICTION: Stock is extremely oversold with 3/4 signals firing. Predicting mean reversion to middle Bollinger Band within 3 days."
- **THE EXPANDED SCANNER IS A PREDICTION**: When it filters 2600 stocks down to 50 survivors, it is PREDICTING those 50 have the best setups. Frame it that way.
- **THE PREDICTION SCANNER IS A PREDICTION**: When it ranks and scores the survivors, it is PREDICTING which ones will move first and hardest. Frame it that way.

**This bot predicts. It doesn't just react.**

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Language & Runtime
| Component | Value |
|-----------|-------|
| Language | Python 3.x |
| Runtime | CPython |
| Package manager | pip |
| Dependency file | `requirements.txt` |
## Core Dependencies
| Package | Version | Purpose |
|---------|---------|---------|
| alpaca-py | >=0.13.0 | Trading SDK (broker API, market data, WebSocket streaming) |
| python-dotenv | >=1.0.0 | Environment variable loading from `.env` files |
| numpy | >=1.24.0 | Numerical operations for indicator calculations |
| pandas | >=2.0.0 | OHLCV bar data manipulation |
## Implicit Dependencies (imported but not in requirements.txt)
| Package | Used In | Purpose |
|---------|---------|---------|
| flask | `dashboard.py` | Web dashboard server |
| requests | `sentiment.py`, `scanner.py`, `catalysts.py` | HTTP requests to external APIs |
| yfinance | `scanner.py` | Yahoo Finance data (bars, top movers) |
| beautifulsoup4 | `scanner.py` | HTML parsing for Yahoo Finance scraping |
## Configuration
- **Credential management**: `.env`, `.env.paper`, `.env.live` files
- **Config pattern**: Module-level constants loaded at import time via `_require()`, `_float()`, `_int()` helpers
- **Validation**: Required keys raise `ValueError` if missing or placeholder
- **Mode selection**: `server.py` loads the correct `.env.{mode}` file before importing `config`
### Key Config Parameters
| Parameter | Default | Purpose |
|-----------|---------|---------|
| `PAPER_TRADING` | `true` | Paper vs live trading mode |
| `SYMBOL` | `SOFI` | Default trading symbol |
| `WATCHLIST` | 14 stocks | Mixed large-cap + high-vol watchlist |
| `SHORT_WINDOW` / `LONG_WINDOW` | 9 / 21 | SMA crossover windows |
| `BAR_TIMEFRAME` | `5Min` | OHLCV bar interval |
| `MAX_POSITION_VALUE` | $200 | Max per-trade value |
| `TRAILING_STOP_PCT` | 3% | Trailing stop loss |
| `TAKE_PROFIT_PCT` | 6% | Take profit target |
| `DAILY_LOSS_LIMIT` | $50 | Daily loss limit |
| `DASHBOARD_PORT` | 5000 | Flask dashboard port |
## Entry Points
| Entry Point | Command | Purpose |
|-------------|---------|---------|
| `server.py` | `py server.py paper` / `py server.py live` | Main entry — starts dashboard + bot |
| `bot.py` | Imported by server | Core trading loop (not run directly) |
## Logging
- Custom logger via `logger_setup.py` using `get_logger()`
- Trade events logged via `log_trade_event()`
- Logs directory: `logs/`
- Werkzeug logging suppressed to ERROR level
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- snake_case (e.g., `bot.py`, `logger_setup.py`, `config.py`)
- Descriptive, single-word or compound names (no abbreviations except config)
- Examples: `indicators.py`, `strategy.py`, `safety.py`, `catalysts.py`
- snake_case (e.g., `get_current_position()`, `place_buy()`, `compute_signals()`)
- Verb-first pattern for operations: `place_*`, `get_*`, `fetch_*`, `compute_*`, `check_*`
- Internal/helper functions prefixed with `_` (e.g., `_require()`, `_handle_signal()`, `_get_timeframe()`)
- Descriptive names that indicate action and subject: `record_session_start_equity()`, `daily_loss_exceeded()`
- snake_case for local and module variables (e.g., `short_sma`, `result`, `trading_client`)
- UPPER_CASE for constants and module-level configuration: `REQUEST_TIMEOUT`, `HISTORY_LIMIT`, `MIN_PRICE`
- Private/global variables prefixed with `_`: `_session_start_equity`, `_peak_prices`, `_shutdown_requested`
- Dict variables named with plurals for collections: `ark_buys`, `symbols`, `positions`, `results`
- Single underscore `_` used to discard unused values in unpacking
- Type hints with union syntax (Python 3.10+): `float | None`, `dict[str, bool]`, `tuple[pd.Series, pd.Series, pd.Series]`
- Used in function signatures for clarity (see `strategy.py:52` and `catalysts.py:34`)
## Code Style
- No explicit linter configuration found (no `.pylintrc`, `pyproject.toml`, or `.prettierrc`)
- Style appears to be manual following PEP 8
- Line length: typically stays under 100 characters; longer lines for URLs and multi-line calls allowed
- Indentation: 4 spaces (standard Python)
- No formal linting tool configured
- Manual code review appears to be the enforcement method
## Import Organization
- Used selectively for clarity: `state as shared_state`, `compute_all as compute_indicators`, `rsi as calc_rsi`
- Applies when avoiding name collisions or clarifying intent
- Used in modules with complex type hints (`catalysts.py`, `safety.py`, `scanner.py`, `strategy.py`)
- Enables forward references and modern Python 3.10+ type syntax
## Error Handling
- Broad `Exception` catching is standard: `except Exception as exc:` or `except Exception:`
- Exceptions are logged with context and details, using the logger's `log.error()` or `log.warning()`
- Trade-critical exceptions trigger detailed logging: `log.error("[bot] Unhandled exception: %s", exc, exc_info=True)`
- Graceful fallbacks: return sensible defaults (empty list, 0, False, empty dict) on error
- Examples:
- Logic failures (use `log.warning()` instead)
- Missing external API data (use graceful fallback)
- Configuration validation happens at import time in `config.py`; invalid values raise `ValueError` with clear messages
## Logging
- All modules import logger: `from logger_setup import get_logger` then `log = get_logger()` at module level
- Logger writes to both console (INFO+) and daily file (DEBUG+)
- Prefixed log messages with module context: `"[bot] ..."`, `"[strategy] ..."`, `"[scanner] ..."`, `"[safety] ..."`
- Structured trade events use `log_trade_event(log, "EVENT_NAME", key=value, ...)`
- `log.debug()`: Detailed technical info (e.g., trailing stop updates, partial order status)
- `log.info()`: Key events (buy/sell signals, orders placed, status changes)
- `log.warning()`: Recoverable issues (missing data, API timeouts, safety triggers)
- `log.critical()`: Critical failures (daily loss limit hit, shutdown triggered)
- `log.error()`: Unhandled exceptions with traceback
## Comments
- Module-level docstring explaining file purpose (all modules have one)
- Function docstrings for non-obvious behavior
- Inline comments for complex logic or business rules
- Section comments using visual separators: `# ── Section Name ────────────────────────────────────`
- Not used (Python project); standard Python docstrings with triple quotes
- `config.py`: Detailed comments explaining each config parameter's purpose
- `bot.py`: Section comments separating phases of trading loop (lines 220-456)
- `safety.py:34`: Comments explaining caching and state management
- `catalysts.py:13-16`: Comments explaining catalyst sources and usage
## Function Design
- Typical functions are 5-30 lines
- Longer functions (50+ lines) are reserved for main loops with clear step-by-step comments
- Example: `bot.py:207-456` (main trading loop broken into numbered phases)
- Usually 1-4 parameters; trading-client, symbol, price common
- Optional parameters use defaults: `def place_buy(..., consecutive_losses: int = 0) -> bool:`
- Type hints on all function signatures
- Explicit return types: `-> bool`, `-> dict`, `-> list`, `-> None`
- Functions return dict for complex data: `{"signal": "BUY", "short_sma": 100.5, "long_sma": 95.2}`
- Tuple returns for related values: `(qty, avg_entry_price, unrealized_pl)`
- `None` returned explicitly or implicitly (no value)
## Module Design
- No `__all__` defined; modules export all public functions
- Private functions prefixed with `_` for convention (not enforced)
- Examples:
- Not used; each module is imported directly (e.g., `from safety import liquidate_all`)
- Long imports grouped with parentheses: `from safety import (\n    assert_market_open,\n    ...` (see `bot.py:33-51`)
## Spacing and Formatting
- Two blank lines between top-level function definitions
- One blank line between sections (marked with `# ──` dividers)
- One blank line between logical blocks within functions
- Multi-line imports use parentheses: `from safety import (\n    assert_market_open,\n    ...)`
- Long function calls use indented arguments
- Long strings concatenate naturally: `url = ("https://..."\n       "?query=...")`
- f-strings used throughout: `f"Price: {price:.2f}"`
- `.format()` and `%` formatting used for logging: `log.info("[bot] BUY: qty=%d", qty)`
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- Polling loop architecture (not event-driven) — cycles every 60s to evaluate signals
- Swing trading strategy — holds overnight, high-conviction entries only
- Multi-signal confirmation required (SMA + RSI + Volume + MACD)
- Safety guardrails first — all risky operations guarded by checks
- Background threads for real-time data — WebSocket stream and sentiment polling run async
- Shared state pattern — thread-safe in-memory state accessed by bot, dashboard, and background tasks
## Layers
- Purpose: Fetch and normalize market data from Alpaca and free data sources
- Location: `strategy.py`, `scanner.py`, `stream.py`, `sentiment.py`, `catalysts.py`
- Contains: Bar fetching, technical indicator computation, watchlist scanning, catalyst lookups, real-time streaming
- Depends on: Alpaca SDK, yfinance, Yahoo Finance APIs, arkfunds.io
- Used by: Bot core loop, dashboard
- Purpose: Compute trading signals by combining multiple filters
- Location: `strategy.py`, `indicators.py`, `scanner.py`
- Contains: SMA crossover detection, RSI filtering, volume ratio checks, MACD validation, catalyst scoring
- Depends on: Data layer (bar data), technical indicator functions
- Used by: Bot main loop, watchlist ranking
- Purpose: Enforce all risk controls before any trade execution
- Location: `safety.py`
- Contains: Daily loss limit tracking, position sizing (dynamic and capped), PDT rule checking, trailing stop management, market hours validation, emergency liquidation
- Depends on: Alpaca SDK, config
- Used by: Bot core loop (every decision point checks safety first)
- Purpose: Submit orders to Alpaca and record trade outcomes
- Location: `bot.py` (place_buy, place_sell functions), `safety.py` (liquidate_all)
- Contains: Market order submission, trade logging, PnL recording, consecutive loss tracking
- Depends on: Alpaca SDK, shared_state, logger
- Used by: Bot core loop
- Purpose: Load and validate all environment settings
- Location: `config.py`
- Contains: API credentials, trading parameters (SMA windows, RSI limits, position sizes), safety limits, timeframes, watchlists
- Depends on: python-dotenv
- Used by: All modules (imported globally)
- Purpose: Thread-safe in-memory state shared across all threads
- Location: `state.py`
- Contains: Account info, current position, technical indicators, signal history, trade log, growth metrics, P&L calendar, watchlist results
- Depends on: threading (Lock)
- Used by: Bot thread, dashboard thread, sentiment thread, stream thread
- Purpose: REST API and HTML dashboard for monitoring and control
- Location: `dashboard.py`, `templates/index.html`
- Contains: Flask routes for state snapshots, bar charts, order management, bot start/stop control
- Depends on: Flask, shared_state, Alpaca SDK (for position and order queries)
- Used by: Browser clients
- Purpose: Structured logging with event tracking
- Location: `logger_setup.py`, used throughout
- Contains: Logger configuration, trade event logging helpers
- Depends on: Python logging stdlib
- Used by: All modules
## Data Flow
- **Real-time price stream:** WebSocket to Alpaca → updates `state.price` every bar close (1-min cadence) → dashboard shows live price between polling cycles
- **Sentiment polling:** Every 5 minutes fetches Fear & Greed index + news headlines → updates state for dashboard display
- Shared state is a dictionary protected by a threading.Lock
- All reads/writes go through `state.update()` and `state.snapshot()`
- Trade history and chart history are deques with max length (prevents unbounded memory)
- PDT info cached per day (refreshed once at open)
- Catalyst caches expire (ARK per day, upgrades per hour)
## Key Abstractions
- Purpose: Central authority for all risk decisions
- Examples: `daily_loss_exceeded()`, `calculate_safe_qty()`, `check_pdt_allows_buy()`, `trailing_stop_triggered()`, `liquidate_all()`
- Pattern: Guard clauses checked before every risky action. Logs every safety event at WARNING+ level.
- Purpose: Pure calculation functions, no side effects
- Examples: `rsi()`, `macd()`, `bollinger_bands()`, `compute_all()`
- Pattern: Takes pandas Series, returns Series or tuple of Series. Full history available; caller picks last value for current signal.
- Purpose: Rank candidates by score
- Examples: `fetch_top_movers()`, `best_buy()`, `scan()`
- Pattern: Returns sorted list of candidates. Each candidate is scored 0-100 (sum of signal strength + catalyst bonus). Top scorer is "best buy".
- Purpose: Thread-safe read/write for all shared data
- Examples: `update()`, `snapshot()`, `push_history()`, `record_trade()`
- Pattern: Dictionary with Lock. Atomic operations only (no complex multi-step updates without lock). All datetimes are ISO strings in shared state (JSON-safe).
## Entry Points
- Location: `server.py`
- Triggers: `python server.py paper` or `python server.py live`
- Responsibilities:
- Location: `bot.py` (exported function)
- Triggers: Called from dashboard API `/api/start` endpoint
- Responsibilities:
- Location: `dashboard.py` (Flask app)
- Triggers: HTTP requests from browser
- Responsibilities:
## Error Handling
## Cross-Cutting Concerns
- Framework: Python `logging` module
- Setup: `logger_setup.py` configures console + file handlers
- Convention: All logs include module prefix `[bot]`, `[stream]`, `[strategy]`, etc.
- Event logging: `log_trade_event()` helper for structured event capture (BUY, SELL, SIGNAL, ERROR)
- Levels: DEBUG (data/ticks), INFO (cycle summary, signals), WARNING (recoverable issues), CRITICAL (loss limit, safety violations)
- Input: Config values validated at import time in `config.py`. Raises ValueError if invalid.
- Data: Bar DataFrame checked for size before computing indicators.
- Orders: Qty checked > 0 before submission. Price checked > 0.
- Alpaca API: API key + secret key from config (loaded from .env)
- Paper vs Live: Controlled by `PAPER_TRADING` flag (sets Alpaca SDK `paper=True/False`)
- Dashboard: No authentication (runs on localhost only, assumes trusted network)
- Shared state: Protected by Lock in `state.py`
- Global caches: ARK and upgrade caches guarded by date/timestamp checks (no Lock, tolerates stale reads)
- Signal handlers: Bot sets `_shutdown_requested` flag (atomic boolean, safe for signal handler)
- Background threads: All daemon threads, exit when main exits
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
