# Testing Patterns

**Analysis Date:** 2026-03-27

## Test Framework

**Status:** No formal testing framework configured

**Finding:**
- No `pytest.ini`, `unittest` imports, or test files found in codebase
- No `tests/` directory present
- No testing dependencies in `requirements.txt` (numpy, pandas, alpaca-py, python-dotenv, requests only)
- No CI/CD pipeline configuration (no `.github/workflows/`, `tox.ini`, or similar)

**Implication:** This is a production-stage bot with manual testing only. No automated test suite exists.

## Testing Approach

**Current Strategy:**
- Manual testing in isolated paper trading account (`--paper` flag via `.env.paper`)
- Live trading separate from paper trading via environment file switching
- Dashboard provides real-time visual verification of signals and positions
- Logs (`logs/trading_YYYY-MM-DD.log`) serve as audit trail for verification

**Code patterns supporting testability (present but not used):**
- Pure functions with clear inputs/outputs (e.g., `indicators.py`, `strategy.py`)
- Dependency injection via function parameters (e.g., `place_buy(trading_client, ...)`)
- Centralized state management in `state.py` with thread-safe locks
- Configuration externalized to `config.py` and `.env` files

## Manual Testing Observations

**Logging for verification:**
- Every critical operation logged with ISO-8601 timestamps
- Trade events use structured format: `log_trade_event(log, "EVENT_NAME", key=value, ...)`
- Examples from `bot.py:145-153`:
  ```python
  log.info("[bot] BUY: %d shares of %s @ ~$%.2f (fraction=%.1f%%)",
           qty, symbol, price, fraction * 100)
  log_trade_event(log, "BUY_ORDER_ATTEMPT", symbol=symbol, qty=qty,
                  approx_price=f"{price:.2f}")
  ```
- Logs can be grepped for verification: `grep "BUY_ORDER_SUBMITTED" trading_*.log`

**State snapshots for debugging:**
- `state.py:163-169` provides `snapshot()` function returning JSON-serializable state
- Used by dashboard (`dashboard.py`) to display live state
- Allows inspecting intermediate state during manual testing

**Dashboard as test interface:**
- Real-time displays of:
  - Current position and P&L
  - Technical indicators (RSI, MACD, Bollinger Bands)
  - Watchlist scan results with scores
  - Trade history with entry/exit prices
  - PDT status and daily loss tracking
- Visual confirmation that signals are correctly computed

## Testing Gaps

**Unit Testing:**
- No isolated tests for core functions:
  - Indicator calculations (`indicators.py`: RSI, MACD, Bollinger Bands)
  - Signal generation (`strategy.py`: SMA crossover logic)
  - Safety checks (`safety.py`: trailing stop, PDT validation, daily loss)
  - Watchlist scoring (`scanner.py`: multi-condition filtering)

**Risk:** Bugs in indicator calculations or signal logic go undetected until live trading. Example:
- `strategy.py:130-135`: Crossover detection logic never unit-tested
- `indicators.py:16-19`: RSI calculation never verified against expected values
- `safety.py:76-82`: Trailing stop trigger logic has no test cases

**Integration Testing:**
- No tests verifying Alpaca API integration
- No tests for websocket stream handling (`stream.py`)
- No tests for external API fallbacks (ARK data, Yahoo Finance, sentiment API)
- Error handling in `catalysts.py:74-86` relies on manual verification that fallbacks work

**E2E Testing:**
- Live paper trading account serves as rough E2E environment
- No automated test suite runs through full trading cycles

## Test Coverage Status

**No coverage reporting:** Coverage metrics not configured or tracked

**High-risk untested areas:**
- `bot.py:203-456`: Main trading loop with complex state transitions
- `scanner.py`: Watchlist scoring with multiple condition checks
- `safety.py`: PDT rules, daily loss limits, position sizing
- `catalysts.py`: External API integration with fallbacks
- `state.py`: Thread-safety of shared state during concurrent updates

**Well-isolated (easier to test if needed):**
- `indicators.py`: Pure functions taking Series, returning Series or scalars
- `strategy.py`: Pure function `compute_signals()` taking DataFrame, returning dict
- `logger_setup.py`: Configuration function, no dependencies
- `config.py`: Configuration loading and validation

## Recommended Testing Approach

**For adding tests:** (If testing were to be implemented)

1. **Unit tests with pytest:**
   - Test pure functions first: `indicators.py`, `strategy.py`
   - Mock Alpaca client for `bot.py` and `safety.py`
   - Mock requests library for `catalysts.py` and `scanner.py`
   - Use fixtures for sample bar data (yfinance responses)

2. **Test structure pattern (example):**
   ```python
   # tests/test_indicators.py
   import pytest
   import pandas as pd
   from indicators import rsi, macd

   def test_rsi_simple():
       """RSI should be 50 on flat prices."""
       closes = pd.Series([100.0] * 14)
       result = rsi(closes)
       assert result.iloc[-1] == 50.0
   ```

3. **Mocking strategy:**
   - Use `unittest.mock.patch` for Alpaca API calls
   - Use `pytest-vcr` or `responses` library to mock HTTP requests
   - Inject test doubles via dependency injection (already used in design)

4. **Integration test pattern:**
   - Use `.env.test` with paper trading only
   - Run through 1-2 trading cycles checking:
     - Signals generated correctly
     - Orders placed with correct quantities
     - Safety guards trigger appropriately
     - State tracking updates correctly

---

*Testing analysis: 2026-03-27*

**Summary:** This codebase lacks automated testing infrastructure. Testing is manual (paper trading + dashboard + logs). Core indicator and strategy logic is written in testable form (pure functions) but no tests exist. Recommend adding pytest-based unit tests for high-risk areas (indicators, signal generation, safety rules) before expanding production trading.
