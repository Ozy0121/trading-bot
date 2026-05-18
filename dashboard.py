"""
dashboard.py
------------
Flask web server — thin coordinator.

Registers three Blueprint modules:
  - routes.trading  (order, bot control, positions, account, performance, backtest)
  - routes.scanner  (predictions, overnight, expanded scan, intelligence, heatmaps)
  - routes.data     (index page, state, SSE stream, health, quotes, bars, agents)

Dependency injection globals (_trading_client, _data_client, _kill_fn,
_start_fn, _coordinator) are set by server.py at startup and lazy-imported
by Blueprint route handlers to avoid circular imports.
"""

import logging

from flask import Flask

import config
import state as shared_state
from logger_setup import get_logger

logging.getLogger("werkzeug").setLevel(logging.ERROR)

app = Flask(__name__)
log = get_logger()

# ── Dependency injection globals (set by server.py) ──────────────────────────

_trading_client = None
_data_client    = None
_kill_fn        = None
_start_fn       = None
_coordinator    = None


def set_coordinator(coordinator):
    global _coordinator
    _coordinator = coordinator


def set_dependencies(trading_client, data_client, kill_fn, start_fn):
    global _trading_client, _data_client, _kill_fn, _start_fn
    _trading_client = trading_client
    _data_client    = data_client
    _kill_fn        = kill_fn
    _start_fn       = start_fn


# ── Blueprint registration ───────────────────────────────────────────────────

from routes.trading import trading_bp
from routes.scanner import scanner_bp
from routes.data    import data_bp

app.register_blueprint(trading_bp)
app.register_blueprint(scanner_bp)
app.register_blueprint(data_bp)


# ── Server entry point ───────────────────────────────────────────────────────

def run(port: int = 5000):
    log.info("[dashboard] http://localhost:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
