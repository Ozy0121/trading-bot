"""
logger_setup.py
---------------
Configures two log streams:
  1. Console  – human-readable, INFO level and above
  2. File     – full DEBUG detail, written to logs/trading_YYYY-MM-DD.log

Every trade event (signal, order placed, fill, rejection, safety trigger)
is logged with an ISO-8601 timestamp so you have a complete audit trail.
"""

import logging
import os
from datetime import datetime


def get_logger(name: str = "trading_bot") -> logging.Logger:
    """
    Return a logger that writes to both stdout and a dated log file.
    Safe to call multiple times — handlers are only added once.
    """
    logger = logging.getLogger(name)

    # Only configure once (avoid duplicate handlers if module is re-imported)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # ── Formatter ───────────────────────────────────────────────────────────
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # ── Console handler (INFO+) ──────────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    # ── File handler (DEBUG+, daily rotation by filename) ───────────────────
    logs_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(logs_dir, exist_ok=True)

    log_filename = os.path.join(
        logs_dir, f"trading_{datetime.now().strftime('%Y-%m-%d')}.log"
    )
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    logger.info("Logger initialized. Writing to: %s", log_filename)

    logging.getLogger("websockets").setLevel(logging.ERROR)
    logging.getLogger("alpaca").setLevel(logging.WARNING)

    return logger


# ── Convenience trade-event logger ──────────────────────────────────────────

def log_trade_event(logger: logging.Logger, event: str, **kwargs) -> None:
    """
    Log a structured trade event.  All keyword arguments are appended as
    key=value pairs so every event is easy to grep from the log file.

    Example:
        log_trade_event(log, "ORDER_PLACED", side="buy", qty=10, symbol="SPY")
    Produces:
        2024-03-15T14:32:01 | INFO     | [TRADE_EVENT] ORDER_PLACED | symbol=SPY side=buy qty=10
    """
    detail = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.info("[TRADE_EVENT] %s | %s", event, detail)
