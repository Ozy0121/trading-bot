# Coding Conventions

**Analysis Date:** 2026-03-27

## Naming Patterns

**Files:**
- snake_case (e.g., `bot.py`, `logger_setup.py`, `config.py`)
- Descriptive, single-word or compound names (no abbreviations except config)
- Examples: `indicators.py`, `strategy.py`, `safety.py`, `catalysts.py`

**Functions:**
- snake_case (e.g., `get_current_position()`, `place_buy()`, `compute_signals()`)
- Verb-first pattern for operations: `place_*`, `get_*`, `fetch_*`, `compute_*`, `check_*`
- Internal/helper functions prefixed with `_` (e.g., `_require()`, `_handle_signal()`, `_get_timeframe()`)
- Descriptive names that indicate action and subject: `record_session_start_equity()`, `daily_loss_exceeded()`

**Variables:**
- snake_case for local and module variables (e.g., `short_sma`, `result`, `trading_client`)
- UPPER_CASE for constants and module-level configuration: `REQUEST_TIMEOUT`, `HISTORY_LIMIT`, `MIN_PRICE`
- Private/global variables prefixed with `_`: `_session_start_equity`, `_peak_prices`, `_shutdown_requested`
- Dict variables named with plurals for collections: `ark_buys`, `symbols`, `positions`, `results`
- Single underscore `_` used to discard unused values in unpacking

**Types:**
- Type hints with union syntax (Python 3.10+): `float | None`, `dict[str, bool]`, `tuple[pd.Series, pd.Series, pd.Series]`
- Used in function signatures for clarity (see `strategy.py:52` and `catalysts.py:34`)

## Code Style

**Formatting:**
- No explicit linter configuration found (no `.pylintrc`, `pyproject.toml`, or `.prettierrc`)
- Style appears to be manual following PEP 8
- Line length: typically stays under 100 characters; longer lines for URLs and multi-line calls allowed
- Indentation: 4 spaces (standard Python)

**Linting:**
- No formal linting tool configured
- Manual code review appears to be the enforcement method

## Import Organization

**Order:**
1. Standard library imports (`import signal`, `import sys`, `import time`)
2. Third-party library imports (`from alpaca.trading.client import TradingClient`, `import pandas as pd`, `import numpy as np`)
3. Local module imports (`import config`, `from logger_setup import get_logger`)

**Path Aliases:**
- Used selectively for clarity: `state as shared_state`, `compute_all as compute_indicators`, `rsi as calc_rsi`
- Applies when avoiding name collisions or clarifying intent

**from __future__ import annotations:**
- Used in modules with complex type hints (`catalysts.py`, `safety.py`, `scanner.py`, `strategy.py`)
- Enables forward references and modern Python 3.10+ type syntax

## Error Handling

**Patterns:**
- Broad `Exception` catching is standard: `except Exception as exc:` or `except Exception:`
- Exceptions are logged with context and details, using the logger's `log.error()` or `log.warning()`
- Trade-critical exceptions trigger detailed logging: `log.error("[bot] Unhandled exception: %s", exc, exc_info=True)`
- Graceful fallbacks: return sensible defaults (empty list, 0, False, empty dict) on error
- Examples:
  - `bot.py:103-128`: try-except returns empty list if positions fetch fails
  - `catalysts.py:74-86`: try-except logs failure and continues with cached data or fallback
  - `safety.py` and `scanner.py`: broad Exception catching with logging, no exception re-raising

**No exceptions raised for:**
- Logic failures (use `log.warning()` instead)
- Missing external API data (use graceful fallback)
- Configuration validation happens at import time in `config.py`; invalid values raise `ValueError` with clear messages

## Logging

**Framework:** Python's standard `logging` module via `logger_setup.py`

**Patterns:**
- All modules import logger: `from logger_setup import get_logger` then `log = get_logger()` at module level
- Logger writes to both console (INFO+) and daily file (DEBUG+)
- Prefixed log messages with module context: `"[bot] ..."`, `"[strategy] ..."`, `"[scanner] ..."`, `"[safety] ..."`
- Structured trade events use `log_trade_event(log, "EVENT_NAME", key=value, ...)`
  - Example: `log_trade_event(log, "BUY_ORDER_ATTEMPT", symbol=symbol, qty=qty, approx_price=f"{price:.2f}")`
  - Produces: `[TRADE_EVENT] BUY_ORDER_ATTEMPT | symbol=NVDA qty=10 approx_price=150.25`

**Log levels used:**
- `log.debug()`: Detailed technical info (e.g., trailing stop updates, partial order status)
- `log.info()`: Key events (buy/sell signals, orders placed, status changes)
- `log.warning()`: Recoverable issues (missing data, API timeouts, safety triggers)
- `log.critical()`: Critical failures (daily loss limit hit, shutdown triggered)
- `log.error()`: Unhandled exceptions with traceback

## Comments

**When to Comment:**
- Module-level docstring explaining file purpose (all modules have one)
- Function docstrings for non-obvious behavior
- Inline comments for complex logic or business rules
- Section comments using visual separators: `# ── Section Name ────────────────────────────────────`

**JSDoc/TSDoc:**
- Not used (Python project); standard Python docstrings with triple quotes

**Example patterns:**
- `config.py`: Detailed comments explaining each config parameter's purpose
- `bot.py`: Section comments separating phases of trading loop (lines 220-456)
- `safety.py:34`: Comments explaining caching and state management
- `catalysts.py:13-16`: Comments explaining catalyst sources and usage

## Function Design

**Size:**
- Typical functions are 5-30 lines
- Longer functions (50+ lines) are reserved for main loops with clear step-by-step comments
- Example: `bot.py:207-456` (main trading loop broken into numbered phases)

**Parameters:**
- Usually 1-4 parameters; trading-client, symbol, price common
- Optional parameters use defaults: `def place_buy(..., consecutive_losses: int = 0) -> bool:`
- Type hints on all function signatures

**Return Values:**
- Explicit return types: `-> bool`, `-> dict`, `-> list`, `-> None`
- Functions return dict for complex data: `{"signal": "BUY", "short_sma": 100.5, "long_sma": 95.2}`
- Tuple returns for related values: `(qty, avg_entry_price, unrealized_pl)`
- `None` returned explicitly or implicitly (no value)

## Module Design

**Exports:**
- No `__all__` defined; modules export all public functions
- Private functions prefixed with `_` for convention (not enforced)
- Examples:
  - `safety.py`: Exports `daily_loss_exceeded()`, `trailing_stop_triggered()`, `liquidate_all()`, etc.
  - `indicators.py`: Exports `rsi()`, `macd()`, `bollinger_bands()`, `compute_all()`
  - `config.py`: Exports config constants (SYMBOL, MAX_POSITION_VALUE, etc.)

**Barrel Files:**
- Not used; each module is imported directly (e.g., `from safety import liquidate_all`)
- Long imports grouped with parentheses: `from safety import (\n    assert_market_open,\n    ...` (see `bot.py:33-51`)

## Spacing and Formatting

**Blank lines:**
- Two blank lines between top-level function definitions
- One blank line between sections (marked with `# ──` dividers)
- One blank line between logical blocks within functions

**Line continuations:**
- Multi-line imports use parentheses: `from safety import (\n    assert_market_open,\n    ...)`
- Long function calls use indented arguments
- Long strings concatenate naturally: `url = ("https://..."\n       "?query=...")`

**String formatting:**
- f-strings used throughout: `f"Price: {price:.2f}"`
- `.format()` and `%` formatting used for logging: `log.info("[bot] BUY: qty=%d", qty)`

---

*Convention analysis: 2026-03-27*
