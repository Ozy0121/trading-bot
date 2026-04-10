"""
progress.py
-----------
Thread-safe progress tracking for long-running operations.
Backend operations report progress here; the dashboard SSE stream
picks it up and pushes to the frontend.

Usage:
    from progress import track, complete, fail

    track("scan", total=575, current=0, label="Scanning stocks...")
    for i, sym in enumerate(symbols):
        process(sym)
        track("scan", current=i+1)
    complete("scan", message="18 stocks passed filters")
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, asdict

_lock = threading.Lock()
_operations: dict[str, dict] = {}


def track(
    op_id: str,
    *,
    total: int | None = None,
    current: int | None = None,
    label: str | None = None,
    detail: str | None = None,
) -> None:
    """Update progress for an operation. Only provided fields are updated."""
    with _lock:
        if op_id not in _operations:
            _operations[op_id] = {
                "id": op_id,
                "status": "running",
                "total": 0,
                "current": 0,
                "pct": 0,
                "label": "",
                "detail": "",
                "started_at": time.time(),
                "finished_at": None,
                "message": "",
            }
        op = _operations[op_id]
        op["status"] = "running"
        if total is not None:
            op["total"] = total
        if current is not None:
            op["current"] = current
        if label is not None:
            op["label"] = label
        if detail is not None:
            op["detail"] = detail
        if op["total"] > 0:
            op["pct"] = round(op["current"] / op["total"] * 100, 1)


def complete(op_id: str, message: str = "") -> None:
    """Mark operation as completed with an optional result message."""
    with _lock:
        if op_id in _operations:
            op = _operations[op_id]
            op["status"] = "completed"
            op["pct"] = 100
            op["current"] = op["total"]
            op["message"] = message
            op["finished_at"] = time.time()


def fail(op_id: str, message: str = "") -> None:
    """Mark operation as failed."""
    with _lock:
        if op_id in _operations:
            op = _operations[op_id]
            op["status"] = "error"
            op["message"] = message
            op["finished_at"] = time.time()


def snapshot() -> dict[str, dict]:
    """Return current state of all active operations."""
    with _lock:
        # Clean up operations completed more than 10 seconds ago
        now = time.time()
        expired = [
            k for k, v in _operations.items()
            if v["finished_at"] is not None and now - v["finished_at"] > 10
        ]
        for k in expired:
            del _operations[k]
        return {k: dict(v) for k, v in _operations.items()}
