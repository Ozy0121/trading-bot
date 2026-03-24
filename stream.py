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
— the stream is purely for keeping the dashboard price display live between
polling cycles.
"""

import threading
from logger_setup import get_logger
import config
import state as shared_state

log = get_logger()


def start(api_key: str, secret_key: str) -> None:
    """
    Start the real-time bar stream in a background daemon thread.
    Safe to call once at startup.
    """
    # Import here to avoid circular imports and to keep startup fast
    from alpaca.data.live import StockDataStream

    stream = StockDataStream(api_key, secret_key)

    async def bar_handler(bar):
        """
        Called by the Alpaca SDK each time a 1-minute bar completes.
        `bar` is an alpaca.data.models.Bar object.
        """
        price = float(bar.close)
        shared_state.update(price=price)
        log.debug(
            "[stream] Live bar — %s close=%.4f high=%.4f low=%.4f vol=%s",
            config.SYMBOL, price,
            float(bar.high),
            float(bar.low),
            bar.volume,
        )

    stream.subscribe_bars(bar_handler, config.SYMBOL)

    def _run():
        try:
            log.info("[stream] Connecting to Alpaca real-time feed for %s...", config.SYMBOL)
            stream.run()
        except Exception as exc:
            # Log the error but don't crash — the bot can continue without the stream
            log.error("[stream] Stream disconnected: %s. Dashboard price may lag.", exc)

    t = threading.Thread(target=_run, name="alpaca-stream", daemon=True)
    t.start()
    log.info("[stream] Real-time bar stream thread started for %s", config.SYMBOL)
