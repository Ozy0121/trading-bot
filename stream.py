"""
stream.py
---------
Opens a WebSocket connection to Alpaca's real-time data feed.
Streams 1-minute bars for the configured symbol.

On each completed bar:
  - Updates state.price with the latest close (so the dashboard shows live price)
  - Logs the tick at DEBUG level

The stream runs in a daemon thread so it dies automatically when the main
process exits. Trading decisions are still made by the polling loop in bot.py
--- the stream is purely for keeping the dashboard price display live between
polling cycles.
"""

import threading
import time
from logger_setup import get_logger
import config
import state as shared_state

log = get_logger()

MAX_BACKOFF = 120


def start(api_key: str, secret_key: str) -> None:
    """
    Start the real-time bar stream in a background daemon thread.
    Safe to call once at startup.
    """
    from alpaca.data.live import StockDataStream

    async def bar_handler(bar):
        price = float(bar.close)
        shared_state.update(price=price)
        log.debug(
            "[stream] Live bar --- %s close=%.4f high=%.4f low=%.4f vol=%s",
            config.SYMBOL, price,
            float(bar.high),
            float(bar.low),
            bar.volume,
        )

    def _run():
        backoff = 5
        while True:
            try:
                stream = StockDataStream(api_key, secret_key)
                stream.subscribe_bars(bar_handler, config.SYMBOL)
                log.info("[stream] Connecting to Alpaca real-time feed for %s...", config.SYMBOL)
                stream.run()
                # Connection was stable --- reset backoff only after confirmed success
                backoff = 5
            except ValueError as exc:
                if "connection limit" in str(exc).lower():
                    log.warning("[stream] Connection limit exceeded --- retrying in %ds", backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF)
                else:
                    log.error("[stream] Stream error: %s", exc)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF)
            except Exception as exc:
                log.error("[stream] Stream disconnected: %s. Retrying in %ds.", exc, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)

    t = threading.Thread(target=_run, name="alpaca-stream", daemon=True)
    t.start()
    log.info("[stream] Real-time bar stream thread started for %s", config.SYMBOL)
