"""Tests for the Auditor agent."""

import json
import os
import tempfile
from agents.event_bus import EventBus
from agents.auditor import Auditor
from agents.base import AuditReport


def test_auditor_records_trade():
    bus = EventBus()
    with tempfile.TemporaryDirectory() as tmpdir:
        journal_path = os.path.join(tmpdir, "trade_journal.json")
        agent = Auditor(bus, journal_path=journal_path)
        agent.record_trade({
            "symbol": "NVDA", "action": "BUY", "qty": 5,
            "entry_price": 130.0, "exit_price": 135.0, "pnl": 25.0,
            "win": True, "reasoning": "Strong breakout",
        })
        assert len(agent._journal) == 1
        assert agent._journal[0]["symbol"] == "NVDA"


def test_auditor_computes_stats():
    bus = EventBus()
    agent = Auditor(bus)
    trades = [
        {"symbol": "NVDA", "pnl": 10.0, "win": True},
        {"symbol": "AMD", "pnl": -5.0, "win": False},
        {"symbol": "TSLA", "pnl": 8.0, "win": True},
        {"symbol": "META", "pnl": 12.0, "win": True},
        {"symbol": "AAPL", "pnl": -3.0, "win": False},
    ]
    for t in trades:
        agent.record_trade(t)
    result = agent.run({})
    report = result["report"]
    assert isinstance(report, AuditReport)
    assert report.total_trades == 5
    assert report.win_rate == 0.6
    assert report.avg_win == 10.0
    assert report.avg_loss == -4.0


def test_auditor_saves_and_loads_journal():
    bus = EventBus()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "journal.json")
        agent1 = Auditor(bus, journal_path=path)
        agent1.record_trade({"symbol": "NVDA", "pnl": 10.0, "win": True})
        agent1.save_journal()
        agent2 = Auditor(bus, journal_path=path)
        agent2.load_journal()
        assert len(agent2._journal) == 1


def test_auditor_empty_journal():
    bus = EventBus()
    agent = Auditor(bus)
    result = agent.run({})
    report = result["report"]
    assert report.total_trades == 0
    assert report.win_rate == 0.0


def test_auditor_profit_factor():
    bus = EventBus()
    agent = Auditor(bus)
    agent.record_trade({"symbol": "A", "pnl": 20.0, "win": True})
    agent.record_trade({"symbol": "B", "pnl": -10.0, "win": False})
    result = agent.run({})
    assert result["report"].profit_factor == 2.0
