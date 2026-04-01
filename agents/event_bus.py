"""
Lightweight thread-safe pub/sub event bus for agent observability.

Used for non-critical notifications only (dashboard updates, audit logging).
Never used for trade decisions — those go through the sequential pipeline.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Callable

from logger_setup import get_logger

log = get_logger()


class EventBus:
    """Thread-safe publish/subscribe event bus."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Register a callback for an event type."""
        with self._lock:
            self._subscribers[event_type].append(callback)

    def emit(self, event_type: str, data: dict) -> None:
        """Emit an event to all subscribers. Callbacks run in the calling thread."""
        with self._lock:
            callbacks = list(self._subscribers.get(event_type, []))

        for cb in callbacks:
            try:
                cb(data)
            except Exception as exc:
                log.warning("[event_bus] Callback error on %s: %s", event_type, exc)
