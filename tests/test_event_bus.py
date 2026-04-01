"""Tests for the lightweight event bus."""

import threading
from agents.event_bus import EventBus


def test_subscribe_and_emit():
    """Subscribing to an event type and emitting it calls the callback."""
    bus = EventBus()
    received = []
    bus.subscribe("test.event", lambda data: received.append(data))
    bus.emit("test.event", {"key": "value"})
    assert len(received) == 1
    assert received[0] == {"key": "value"}


def test_emit_no_subscribers():
    """Emitting an event with no subscribers does not raise."""
    bus = EventBus()
    bus.emit("nobody.listening", {"key": "value"})  # should not raise


def test_multiple_subscribers():
    """Multiple callbacks for the same event type all get called."""
    bus = EventBus()
    results_a = []
    results_b = []
    bus.subscribe("multi", lambda d: results_a.append(d))
    bus.subscribe("multi", lambda d: results_b.append(d))
    bus.emit("multi", {"x": 1})
    assert len(results_a) == 1
    assert len(results_b) == 1


def test_different_event_types_isolated():
    """Subscribers only receive events they subscribed to."""
    bus = EventBus()
    received = []
    bus.subscribe("type_a", lambda d: received.append("a"))
    bus.emit("type_b", {})
    assert len(received) == 0


def test_thread_safety():
    """Concurrent emits from multiple threads don't lose events."""
    bus = EventBus()
    results = []
    lock = threading.Lock()

    def safe_append(data):
        with lock:
            results.append(data)

    bus.subscribe("concurrent", safe_append)

    threads = [threading.Thread(target=bus.emit, args=("concurrent", {"i": i}))
               for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 100


def test_callback_error_does_not_break_other_callbacks():
    """If one callback raises, other callbacks still run."""
    bus = EventBus()
    results = []

    def bad_callback(data):
        raise ValueError("boom")

    def good_callback(data):
        results.append(data)

    bus.subscribe("error_test", bad_callback)
    bus.subscribe("error_test", good_callback)
    bus.emit("error_test", {"ok": True})
    assert len(results) == 1
