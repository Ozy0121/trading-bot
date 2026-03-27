# Codebase Structure

**Analysis Date:** 2026-03-27

## Directory Layout

```
trading-bot/
├── bot.py                 # Main polling loop + trade execution
├── config.py              # Configuration and env validation
├── state.py               # Thread-safe shared state
├── strategy.py            # SMA crossover logic + bar fetching
├── indicators.py          # RSI, MACD, Bollinger Bands calculation
├── scanner.py             # Watchlist scanning + candidate ranking
├── catalysts.py           # ARK buys + analyst upgrade detection
├── safety.py              # All risk guardrails (position sizing, PDT, stops)
├── stream.py              # Real-time WebSocket connection to Alpaca
├── sentiment.py           # Fear & Greed + news fetching (background thread)
├── dashboard.py           # Flask web server + API routes
├── server.py              # Entry point (loads .env, starts bot/dashboard)
├── logger_setup.py        # Logging configuration
├── kill_switch.py         # Emergency liquidation (imported by safety.py)
├── requirements.txt       # Python dependencies
├── .env                   # Placeholder (not used, use .env.paper or .env.live)
├── .env.paper             # Paper trading credentials and config
├── .env.live              # Live trading credentials and config
├── .gitignore             # Git exclusions
├── .git/                  # Git history
├── .planning/             # GSD planning documents
│   └── codebase/          # Architecture/structure analysis
├── logs/                  # Runtime log files (generated)
├── templates/             # Web UI files
│   └── index.html         # Dashboard HTML
└── __pycache__/           # Python bytecode (generated)
```

## Directory Purposes

**Project Root:**
- Purpose: Contains all source files, config files, and entry point
- Key files: `server.py` (start here), `bot.py` (trading logic), `config.py` (settings)

**templates/ Directory:**
- Purpose: Static web UI and templates
- Contains: Single-page HTML dashboard
- Key files: `index.html` (rendered by Flask, contains inline CSS/JS)

**logs/ Directory:**
- Purpose: Runtime log output
- Generated: Yes (created by logger_setup.py)
- Committed: No (in .gitignore)

**.planning/codebase/ Directory:**
- Purpose: GSD analysis documents (this document, ARCHITECTURE.md, etc.)
- Generated: Yes (created by `/gsd:map-codebase`)
- Committed: Yes (git-tracked for team reference)

## Key File Locations

**Entry Points:**
- `server.py`: Start here. Usage: `python server.py paper` or `python server.py live`
- `dashboard.py`: Web server (started by server.py, not run directly)

**Configuration:**
- `config.py`: All trading parameters, safety limits, API credentials (reads from .env)
- `.env.paper` / `.env.live`: API keys and mode-specific settings (excluded from git)

**Core Logic:**
- `bot.py`: Main polling loop. Exports `run_bot(trading_client, data_client, session_start_equity)` and `run_bot_from_server()` (started from dashboard)
- `strategy.py`: SMA crossover. Exports `fetch_bars(data_client)` and `compute_signals(df)`
- `indicators.py`: Technical indicator calculations. Exports `rsi()`, `macd()`, `bollinger_bands()`, `compute_all(df)`
- `scanner.py`: Watchlist ranking. Exports `scan(symbol_list)`, `best_buy(watchlist)`, `fetch_top_movers()`
- `catalysts.py`: ARK and analyst upgrade checks. Exports `get_catalysts(symbol)`
- `safety.py`: Risk guards. Exports `daily_loss_exceeded()`, `check_pdt_allows_buy()`, `calculate_safe_qty()`, `trailing_stop_triggered()`, `liquidate_all()`

**Shared State:**
- `state.py`: Thread-safe state. Exports `update(**kwargs)`, `snapshot()`, `push_history()`, `push_trade()`, `record_trade()`

**Background Services:**
- `stream.py`: Real-time Alpaca feed. Exports `start(api_key, secret_key)`
- `sentiment.py`: Fear & Greed + news polling. Exports `start()`

**Web Interface:**
- `dashboard.py`: Flask app. Exports `run(port)` and `set_dependencies()`
- `templates/index.html`: Single-page HTML dashboard (CSS/JS inline)

**Utilities:**
- `logger_setup.py`: Logging configuration. Exports `get_logger()` and `log_trade_event()`
- `kill_switch.py`: Emergency exit. Exported by `safety.py`

## Naming Conventions

**Files:**
- Lowercase with underscores: `bot.py`, `strategy.py`, `safety.py`
- Single responsibility per file (e.g., `indicators.py` has only indicator functions, not mixed logic)

**Functions:**
- Lowercase with underscores: `place_buy()`, `compute_signals()`, `calculate_safe_qty()`
- Verb prefix for actions: `fetch_bars()`, `place_sell()`, `record_peak_price()`
- Boolean prefix for checks: `daily_loss_exceeded()`, `trailing_stop_triggered()`, `check_pdt_allows_buy()`
- Private functions prefixed with underscore: `_handle_signal()`, `_get_timeframe()`, `_run_loop()`

**Variables:**
- Lowercase with underscores: `equity`, `buying_power`, `consecutive_losses`
- Constants in UPPERCASE: `MAX_POSITION_VALUE`, `POLL_INTERVAL`, `WATCHLIST`
- Config values read via `config.SYMBOL`, `config.PAPER_TRADING`, etc.
- Global state access via `shared_state.update()` and `shared_state.snapshot()`

**Types:**
- Classes named CamelCase (rare in this codebase; mostly functional)
- Type hints used where helpful: `def place_buy(...) -> bool:`, `df: pd.DataFrame`
- Union types for optional values: `peak: float | None`

## Where to Add New Code

**New Trading Signal (additional filter/confirmation):**
- Add indicator function to `indicators.py` if needed
- Update `strategy.py:compute_signals()` to include new filter
- Add new filter check in `bot.py` main loop (in the multi-condition BUY check)
- Add corresponding state field in `state.py` for dashboard display

**New Catalyst Type (beyond ARK + upgrades):**
- Add fetch function to `catalysts.py` (follow ARK pattern: cache aggressively, timeout gracefully)
- Update `get_catalysts()` to call new function and aggregate score
- Add state field in `state.py` for the catalyst flag
- Update `scanner.py:best_buy()` scoring to include new catalyst bonus

**New Safety Guard (position limit, max trades, etc.):**
- Add function to `safety.py` (must be called before execution)
- Add helper like `record_*()` or `check_*()` for state tracking
- Call guard in `bot.py` main loop at appropriate check point
- Add corresponding state field for dashboard visibility

**New Dashboard Metric or API Endpoint:**
- Add route to `dashboard.py` (follow existing Flask pattern: `@app.route('/api/...', methods=['GET'])`)
- Add state fields to `state.py` if new data is needed
- Update `index.html` to display new metric
- Test via `GET http://localhost:5000/api/...`

**New Background Service (sentiment, stream, etc.):**
- Create module `new_service.py` with `start()` function
- Function must spawn a daemon thread that loops with error handling
- Call `start()` from `server.py` at startup
- Update shared state via `shared_state.update()` within the loop
- Log all events with consistent prefix `[new_service]`

## Special Directories

**logs/:**
- Purpose: Runtime log files
- Generated: Yes (created by `logger_setup.py` at startup)
- Committed: No (in .gitignore)
- Retention: Check manually; older logs can be deleted

**.planning/codebase/:**
- Purpose: GSD mapping documents (this file, ARCHITECTURE.md, etc.)
- Generated: Yes (created by `/gsd:map-codebase` command)
- Committed: Yes (git-tracked for team reference)
- Usage: Referenced by `/gsd:plan-phase` and `/gsd:execute-phase` to guide implementation

**.git/:**
- Purpose: Git history and metadata
- Committed: N/A (git system file)
- Note: `.gitignore` excludes `.env`, `.env.*`, `logs/`, `__pycache__`

## Import Organization

**Standard pattern across all modules:**

```python
"""Module docstring."""

from __future__ import annotations  # type hints

import [stdlib: os, sys, datetime, threading, etc.]
import [third-party: alpaca, pandas, requests, etc.]

import config
import state as shared_state
from [local_module] import func1, func2
from logger_setup import get_logger, log_trade_event

log = get_logger()
```

**Order:**
1. Module docstring (explains purpose + key patterns)
2. `from __future__ import annotations` (enables forward references)
3. Stdlib imports (os, sys, datetime, threading, etc.)
4. Third-party imports (alpaca, pandas, requests, yfinance, etc.)
5. Local imports (config, state, strategy, safety, etc.)
6. Logger setup

**Path Aliases:**
- `state as shared_state` — clarifies that `state.py` is the shared dictionary, not a local variable
- No wildcard imports (`from X import *`) — all imports are explicit

## Configuration Loading

**Entry point:** `server.py`

1. Read command-line mode: `python server.py paper`
2. Load `.env.{mode}` file (e.g., `.env.paper`)
3. Call `from dotenv import load_dotenv; load_dotenv(env_file, override=True)` BEFORE importing config
4. Now safe to `import config` — all env vars available
5. Pass config values to clients and bot

**Why this order matters:** `config.py` reads env vars at import time. If `.env` not loaded first, it sees empty values and raises ValueError.

## Testing

**Not detected** — no test files in codebase. Testing done manually via:
- Paper trading mode (`python server.py paper`)
- Dashboard manual testing (browser)
- Log inspection for trade execution verification
