# Integrations

## Alpaca (Primary Broker)

**SDK**: `alpaca-py` (v3+)

### Trading Client (`TradingClient`)
- **Used in**: `server.py`, `bot.py`, `dashboard.py`, `safety.py`
- **Authentication**: API key + secret key from `.env`
- **Paper mode**: `paper=True` flag routes to paper trading endpoint
- **Operations**: Market orders (buy/sell), position queries, account info, order management
- **Order type**: `MarketOrderRequest` with `TimeInForce.DAY`

### Data Client (`StockHistoricalDataClient`)
- **Used in**: `server.py`, `dashboard.py`, `scanner.py`
- **Operations**: Historical bars (OHLCV), quotes (bid/ask)
- **Bar timeframes**: Configurable via `BAR_TIMEFRAME` (default 5Min)

### WebSocket Stream (`StockDataStream`)
- **Used in**: `stream.py`
- **Purpose**: Real-time 1-minute bar updates for dashboard price display
- **Pattern**: Daemon thread, subscribes to bar events for configured symbol
- **Failure mode**: Logs error, bot continues without live price updates

## Yahoo Finance

### yfinance Library
- **Used in**: `scanner.py` (`fetch_bars_yf()`)
- **Purpose**: Historical bar data for watchlist scanning (alternative to Alpaca data client)
- **No API key required**

### Yahoo Finance Web Scraping
- **Used in**: `scanner.py` (`get_watchlist()`)
- **Purpose**: Scrape top gainers page for dynamic watchlist when `USE_TOP_MOVERS=true`
- **URL**: `https://finance.yahoo.com/gainers`
- **Parser**: BeautifulSoup4

### Yahoo Finance RSS Feed
- **Used in**: `sentiment.py` (`fetch_news()`)
- **Purpose**: Latest news headlines for the trading symbol
- **URL**: `https://feeds.finance.yahoo.com/rss/2.0/headline?s={SYMBOL}`
- **No API key required**

## Alternative.me (Fear & Greed Index)

- **Used in**: `sentiment.py` (`fetch_fear_greed()`)
- **Purpose**: CNN Fear & Greed Index — maps 0-100 score to bull/bear sentiment
- **URL**: `https://api.alternative.me/fng/?limit=1&format=json`
- **No API key required**
- **Update interval**: Every 300 seconds (5 minutes)

## StockTwits (Documented but implementation unclear)

- **Referenced in**: `sentiment.py` docstring
- **URL**: `https://api.stocktwits.com/api/2/streams/symbol/{SYMBOL}.json`
- **Status**: Documented in module docstring but `fetch_fear_greed()` replaced StockTwits with Alternative.me Fear & Greed

## ARK Invest / Catalyst Sources

- **Used in**: `catalysts.py`
- **Purpose**: ARK buying activity and analyst upgrades as trade score boosters
- **Pattern**: Catalyst bonuses add to scanner score but cannot override missing conditions

## Dashboard (Internal Web Server)

- **Framework**: Flask
- **Port**: Configurable via `DASHBOARD_PORT` (default 5000)
- **SSE**: Server-Sent Events stream at `/api/stream` (1-second push)
- **API endpoints**: REST JSON endpoints for account, positions, bars, quotes, orders, performance
- **Manual trading**: POST endpoints for placing orders, killing positions, selling all

## Data Flow

```
External APIs → Background Threads → Shared State → Dashboard SSE → Browser
     |                                    |
     |                                    ↓
     └──── Scanner/Bot Loop ──────→ Trading Decisions → Alpaca Orders
```

### Background Threads
1. **Alpaca WebSocket** (`stream.py`) — real-time price to `state.price`
2. **Sentiment loop** (`sentiment.py`) — Fear & Greed + news to `state.sentiment_*` and `state.news`
3. **Bot loop** (`bot.py`) — polling loop for trading decisions
