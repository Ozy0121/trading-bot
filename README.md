# Trading Bot v2

An automated swing-trading system for a small, PDT-restricted brokerage account. It scans thousands of stocks nightly, ranks setups with a multi-strategy prediction engine, and executes short (1–3 day) holds through the Alpaca API — with every signal logged as an explicit, falsifiable prediction rather than a black-box trade.

**Status:** actively developed, currently validating strategy performance in Alpaca **paper-trading** mode (no live capital at risk).

## What it does

- **Multi-strategy prediction engine** — combines momentum breakout, mean-reversion, and catalyst-driven strategies, each scored from technical indicators (RSI, MACD, Bollinger Bands, volume/CVD analysis) plus live news sentiment.
- **Explicit predictions, not black-box signals** — every trade candidate is logged with a direction, magnitude, timeframe, and historical base rate, so accuracy can be tracked and audited over time (90% win rate on logged directional predictions in paper-trading validation to date).
- **Safety-first architecture** — automated PDT (pattern-day-trader) rule enforcement, daily loss limits, trailing stops, and thread-safe shared state across a live WebSocket market-data stream, a Flask dashboard, and the trading loop.
- **Real-time dashboard** — Flask-based UI showing live price, current position, signal history, and tracked prediction accuracy.

## Tech stack

Python · Flask · [alpaca-py](https://github.com/alpacahq/alpaca-py) (broker API + real-time market data) · pandas/numpy (indicators) · yfinance + BeautifulSoup (supplementary market data) · WebSockets

## Architecture

- **Data layer** — fetches and normalizes bars from Alpaca and free data sources (`strategy.py`, `scanner.py`, `stream.py`, `sentiment.py`).
- **Strategy layer** — combines signals into a scored, ranked list of candidates (`strategy.py`, `indicators.py`, `scanner.py`).
- **Safety layer** — the gate every trade must pass before execution: loss limits, position sizing, PDT compliance, trailing stops (`safety.py`).
- **Execution layer** — submits orders and records outcomes (`bot.py`, `safety.py`).
- **Shared state** — a thread-safe, in-memory store read by the bot loop, dashboard, and background threads (`state.py`).
- **Dashboard** — Flask app + real-time WebSocket stream for monitoring and control (`dashboard.py`).

## Running it

```bash
pip install -r requirements.txt
# configure .env.paper with your Alpaca paper-trading API keys
python server.py paper
```

## Disclaimer

This is a personal research/engineering project, not financial advice. It currently trades in Alpaca's paper (simulated) environment only.
