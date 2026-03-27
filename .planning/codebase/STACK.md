# Stack

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

All configuration loaded via environment variables through `config.py`:

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
