"""
server.py
---------
Starts the trading dashboard. Run with either:

    py server.py paper   →  http://localhost:5000  (paper / fake money)
    py server.py live    →  http://localhost:5001  (live  / real money)

You can run both at the same time in two separate terminal windows.
Fill in your API keys in .env.paper and .env.live before running.
"""

import sys
import os

# ── Determine mode from command-line argument ────────────────────────────────
mode = sys.argv[1].lower() if len(sys.argv) > 1 else "paper"

if mode not in ("paper", "live"):
    print("Usage: py server.py paper")
    print("       py server.py live")
    sys.exit(1)

env_file = os.path.join(os.path.dirname(__file__), f".env.{mode}")

if not os.path.exists(env_file):
    print(f"Error: {env_file} not found.")
    print(f"Create it by copying .env.paper or .env.live and filling in your API keys.")
    sys.exit(1)

# IMPORTANT: load env vars BEFORE importing config or any other local module,
# because config.py reads env vars at import time.
from dotenv import load_dotenv
load_dotenv(env_file, override=True)

# ── Now safe to import everything else ───────────────────────────────────────
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient

import config
import state as shared_state
import stream as live_stream
import sentiment as sentiment_feed
import dashboard
import bot
from safety import kill_switch
from logger_setup import get_logger

log = get_logger()

mode_label = "PAPER (fake money)" if config.PAPER_TRADING else "LIVE (real money)"
log.info("[server] Mode: %s | Symbol: %s | Port: %d", mode_label, config.SYMBOL, config.DASHBOARD_PORT)
log.info("[server] Connecting to Alpaca...")

trading_client = TradingClient(
    api_key=config.API_KEY,
    secret_key=config.SECRET_KEY,
    paper=config.PAPER_TRADING,
)

data_client = StockHistoricalDataClient(
    api_key=config.API_KEY,
    secret_key=config.SECRET_KEY,
)

log.info("[server] Connected. Starting background services...")

live_stream.start(config.API_KEY, config.SECRET_KEY)
sentiment_feed.start()

shared_state.update(
    status="idle",
    symbol=config.SYMBOL,
    paper_trading=config.PAPER_TRADING,
    use_top_movers=config.USE_TOP_MOVERS,
)

dashboard.set_dependencies(
    trading_client=trading_client,
    data_client=data_client,
    kill_fn=kill_switch,
    start_fn=bot.run_bot_from_server,
)

print()
print("=" * 55)
print(f"  Mode    : {mode_label}")
print(f"  Symbol  : {config.SYMBOL}")
print(f"  Dashboard: http://localhost:{config.DASHBOARD_PORT}")
print("=" * 55)
print()

dashboard.run(port=config.DASHBOARD_PORT)
