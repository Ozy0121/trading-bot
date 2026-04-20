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

# ── Suppress noisy third-party loggers ──────────────────────────────────────
import logging
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("peewee").setLevel(logging.WARNING)

# ── Now safe to import everything else ───────────────────────────────────────
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient

import config
import state as shared_state
import stream as live_stream
import sentiment as sentiment_feed
import dashboard
import bot
from safety import kill_switch, validate_options_enabled, start_protection_monitor
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

# ── SAFE-05: Validate options trading is enabled ──────────────────────────────
validate_options_enabled(trading_client, live_mode=not config.PAPER_TRADING)

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

from agents.event_bus import EventBus
from agents.coordinator import AgentCoordinator

agent_bus = EventBus()
coordinator = AgentCoordinator(
    trading_client=trading_client,
    data_client=data_client,
    event_bus=agent_bus,
)
dashboard.set_coordinator(coordinator)
bot.set_coordinator(coordinator)

# ── Start overnight scanner scheduler ────────────────────────────────────────
from prediction_scanner import start_scheduler as start_overnight_scheduler
start_overnight_scheduler()
log.info("[server] Overnight scanner scheduler started")

# ── Start expanded scanner overnight daemon (Phase 7) ───────────────────
from expanded_scanner import start_overnight_daemon
start_overnight_daemon(trading_client)
log.info("[server] Expanded scanner daemon started")

# ── Start stop-loss protection monitor ──────────────────────────────────────
start_protection_monitor(trading_client, interval=60)
log.info("[server] Stop-loss protection monitor started (checks every 60s)")

print()
print("=" * 55)
print(f"  Mode    : {mode_label}")
print(f"  Symbol  : {config.SYMBOL}")
print(f"  Dashboard: http://localhost:{config.DASHBOARD_PORT}")
print("=" * 55)
print()

dashboard.run(port=config.DASHBOARD_PORT)
