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

os.environ.setdefault("PYTHONUTF8", "1")

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

# ── Optional services (dashboard still starts on failure) ──────────────────

try:
    live_stream.start(config.API_KEY, config.SECRET_KEY)
    log.info("[server] Live stream started")
except Exception as exc:
    log.warning("[server] Live stream failed to start — continuing without live prices: %s", exc)

try:
    sentiment_feed.start()
    log.info("[server] Sentiment feed started")
except Exception as exc:
    log.warning("[server] Sentiment feed failed to start — continuing without sentiment: %s", exc)

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

# Hydrate shared_state with today's disk predictions (if any)
try:
    from prediction_scanner import load_predictions_into_state
    load_predictions_into_state()
except Exception as exc:
    log.warning("[server] Prediction hydration failed — continuing without cached predictions: %s", exc)

# ── Agent coordinator (optional — dashboard and bot skip agents on failure) ─
agent_bus = None
try:
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
    log.info("[server] Agent coordinator started")
except Exception as exc:
    log.warning("[server] Agent coordinator failed to start — continuing without agents: %s", exc)

# ── Launch claude-office backend + frontend for pixel art visualization ────

_office_procs = []

def _start_office():
    import subprocess
    import atexit

    office_dir = os.path.join(os.path.expanduser("~"), "claude-office")
    backend_dir = os.path.join(office_dir, "backend")
    frontend_dir = os.path.join(office_dir, "frontend")

    if not os.path.isdir(backend_dir) or not os.path.isdir(frontend_dir):
        log.warning("[server] claude-office not found at %s — skipping pixel art", office_dir)
        return

    try:
        bp = subprocess.Popen(
            ["uv", "run", "uvicorn", "app.main:app", "--port", "8000"],
            cwd=backend_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _office_procs.append(bp)
        log.info("[server] Claude Office backend started (pid %d, port 8000)", bp.pid)
    except Exception as exc:
        log.warning("[server] Failed to start claude-office backend: %s", exc)

    try:
        fp = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=frontend_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=True,
        )
        _office_procs.append(fp)
        log.info("[server] Claude Office frontend started (pid %d, port 3000)", fp.pid)
    except Exception as exc:
        log.warning("[server] Failed to start claude-office frontend: %s", exc)

    def _stop_office():
        for p in _office_procs:
            try:
                p.terminate()
            except Exception:
                pass

    atexit.register(_stop_office)

try:
    _start_office()
except Exception as exc:
    log.warning("[server] Claude Office failed to start — continuing without pixel art: %s", exc)

# ── Connect claude-office pixel art bridge ─────────────────────────────────
try:
    import office_bridge
    office_bridge.connect(agent_bus)
    log.info("[server] Claude Office bridge connected")
except Exception as exc:
    log.warning("[server] Office bridge failed — continuing without pixel art bridge: %s", exc)

# ── Start overnight scanner scheduler ────────────────────────────────────────
try:
    from prediction_scanner import start_scheduler as start_overnight_scheduler
    start_overnight_scheduler()
    log.info("[server] Overnight scanner scheduler started")
except Exception as exc:
    log.warning("[server] Overnight scheduler failed to start — continuing without overnight scans: %s", exc)

# ── Start expanded scanner overnight daemon (Phase 7) ───────────────────
try:
    from expanded_scanner import start_overnight_daemon
    start_overnight_daemon(trading_client)
    log.info("[server] Expanded scanner daemon started")
except Exception as exc:
    log.warning("[server] Expanded scanner daemon failed — continuing without expanded scans: %s", exc)

# ── Start stop-loss protection monitor ──────────────────────────────────────
try:
    start_protection_monitor(trading_client, interval=60)
    log.info("[server] Stop-loss protection monitor started (checks every 60s)")
except Exception as exc:
    log.warning("[server] Protection monitor failed to start — continuing without stop-loss monitoring: %s", exc)

print()
print("=" * 55)
print(f"  Mode    : {mode_label}")
print(f"  Symbol  : {config.SYMBOL}")
print(f"  Dashboard: http://localhost:{config.DASHBOARD_PORT}")
print("=" * 55)
print()

dashboard.run(port=config.DASHBOARD_PORT)
