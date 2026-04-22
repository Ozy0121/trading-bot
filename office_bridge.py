"""
Bridge between trading bot agent coordinator and claude-office visualization.

Listens to the agent event bus and sends corresponding events to the
claude-office backend so trading agents appear as animated pixel art
characters in the office.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import requests

from agents.event_bus import EventBus
from logger_setup import get_logger

log = get_logger()

OFFICE_URL = "http://localhost:8000/api/v1/events"
SESSION_ID = f"trading-bot-{uuid.uuid4().hex[:8]}"

AGENT_DESK_MAP = {
    "QuantAnalyst": 1,
    "NewsAnalyst": 2,
    "RiskManager": 3,
    "Strategist": 4,
    "Executor": 5,
    "Auditor": 6,
}

AGENT_IDS: dict[str, str] = {}


def _agent_id(name: str) -> str:
    if name not in AGENT_IDS:
        AGENT_IDS[name] = f"agent-{name.lower()}-{uuid.uuid4().hex[:6]}"
    return AGENT_IDS[name]


def _send(event_type: str, data: dict) -> None:
    """Fire-and-forget POST to claude-office backend."""
    payload = {
        "event_type": event_type,
        "session_id": SESSION_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    try:
        requests.post(OFFICE_URL, json=payload, timeout=2)
    except Exception:
        pass


def _on_agent_status(event: dict) -> None:
    """Handle agent.status events from the trading bot event bus."""
    name = event.get("agent", "")
    status = event.get("status", "")
    aid = _agent_id(name)

    if status == "running":
        _send("subagent_start", {
            "agent_id": aid,
            "agent_name": name,
            "task_description": f"{name} analyzing...",
        })
    elif status == "idle":
        _send("subagent_stop", {
            "agent_id": aid,
            "agent_name": name,
            "success": True,
            "result_summary": event.get("summary", f"{name} complete"),
        })
    elif status == "error":
        _send("subagent_stop", {
            "agent_id": aid,
            "agent_name": name,
            "success": False,
            "result_summary": event.get("error", "Error"),
        })


def _on_agent_output(event: dict) -> None:
    """Show a tool-use bubble when agents produce output."""
    name = event.get("agent", "")
    aid = _agent_id(name)

    summary = ""
    output = event.get("output", {})
    if "outputs" in output:
        count = len(output["outputs"])
        summary = f"Processed {count} symbols"
    elif "decision" in output:
        d = output["decision"]
        summary = f"Decision: {d.action} {d.symbol or ''}" if hasattr(d, "action") else "Deciding..."
    elif "verdict" in output:
        v = output["verdict"]
        summary = f"{'Approved' if hasattr(v, 'approved') and v.approved else 'Blocked'}" if v else ""
    elif "result" in output:
        r = output["result"]
        summary = f"Executed: {r.status}" if hasattr(r, "status") else ""

    if summary:
        _send("pre_tool_use", {
            "agent_id": aid,
            "tool_name": name,
            "tool_input": {"description": summary},
        })


def _on_cycle_complete(event: dict) -> None:
    """Flash the boss bubble when a cycle completes."""
    action = event.get("action", "WAIT")
    cycle = event.get("cycle", 0)
    _send("notification", {
        "message": f"Cycle {cycle}: {action}",
        "notification_type": "cycle_complete",
    })


def connect(event_bus: EventBus) -> None:
    """Wire the event bus to claude-office. Call once at startup."""
    _send("session_start", {
        "project_name": "Trading Bot v2",
        "project_dir": "C:\\Users\\btuo1\\trading-bot",
    })

    event_bus.subscribe("agent.status", _on_agent_status)
    event_bus.subscribe("agent.output", _on_agent_output)
    event_bus.subscribe("cycle.complete", _on_cycle_complete)
    log.info("[office] Bridge connected — session %s", SESSION_ID)


def disconnect() -> None:
    """Send session end to claude-office."""
    _send("session_end", {})
    log.info("[office] Bridge disconnected")
