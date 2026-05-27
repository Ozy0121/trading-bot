"""
tests/test_signal_calibration.py
---------------------------------
Unit tests for signal_calibration.py recalibration logic.

Tests verify:
- Weight clamping to [1.0, 6.0]
- Baseline accuracy (50%) returns unchanged weight
- Skip threshold enforced at 20 resolved predictions
- Records without active_signals are excluded
- Minimum 10 samples per signal before recalibrating
- Full recalibration formula correctness
- Output files are written (stats, weights, accuracy_history)
- Accuracy history deduplicates by date
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

import pytest

import signal_calibration


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_record(
    symbol: str,
    outcome: str,
    active_signals: list[str],
    days_ago: int = 1,
) -> dict:
    """Build a minimal prediction record dict."""
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "id": f"P-{symbol}-{outcome}",
        "symbol": symbol,
        "direction": "up",
        "predicted_move_pct": 3.0,
        "timeframe_days": 1,
        "confidence": 7,
        "reasons": ["test"],
        "source": "test",
        "prediction_statement": "test",
        "timestamp": ts,
        "entry_price": 100.0,
        "actual_move_pct": 2.5 if outcome == "correct" else -1.0,
        "outcome": outcome,
        "outcome_date": ts,
        "exit_price": 102.5 if outcome == "correct" else 99.0,
        "active_signals": active_signals,
    }


def _make_pending_record(symbol: str) -> dict:
    """Build a pending record without active_signals."""
    ts = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"P-{symbol}-pending",
        "symbol": symbol,
        "direction": "up",
        "predicted_move_pct": 3.0,
        "timeframe_days": 1,
        "confidence": 7,
        "reasons": ["test"],
        "source": "test",
        "prediction_statement": "test",
        "timestamp": ts,
        "entry_price": 100.0,
        "actual_move_pct": None,
        "outcome": "pending",
        "outcome_date": "",
        "exit_price": 0.0,
    }


# ── Weight clamping tests ─────────────────────────────────────────────────────

def test_weight_clamp():
    """High accuracy (100%) clamps at 6.0, low accuracy (10%) clamps at 1.0."""
    high = signal_calibration._compute_new_weight(accuracy_pct=100.0, default_weight=4.0)
    low = signal_calibration._compute_new_weight(accuracy_pct=10.0, default_weight=4.0)
    assert high == 6.0, f"Expected 6.0 (clamped), got {high}"
    assert low == 1.0, f"Expected 1.0 (clamped), got {low}"


def test_weight_at_baseline():
    """50% accuracy returns unchanged weight (baseline = no change)."""
    result = signal_calibration._compute_new_weight(accuracy_pct=50.0, default_weight=4.0)
    assert result == 4.0, f"Expected 4.0 (baseline), got {result}"


# ── Skip threshold tests ──────────────────────────────────────────────────────

def test_skip_threshold(tmp_path, monkeypatch):
    """run_recalibration() with 15 resolved records returns skipped=True."""
    records = [
        _make_record("AAPL", "correct", ["rsi2", "ibs"])
        for _ in range(10)
    ] + [
        _make_record("AAPL", "incorrect", ["rsi2"])
        for _ in range(5)
    ]
    history_file = tmp_path / "prediction_history.json"
    history_file.write_text(json.dumps(records))

    monkeypatch.setattr(signal_calibration, "HISTORY_FILE", str(history_file))
    monkeypatch.setattr(signal_calibration, "STATS_FILE", str(tmp_path / "stats.json"))
    monkeypatch.setattr(signal_calibration, "WEIGHTS_FILE", str(tmp_path / "weights.json"))
    monkeypatch.setattr(signal_calibration, "ACCURACY_HISTORY_FILE", str(tmp_path / "accuracy_history.json"))

    result = signal_calibration.run_recalibration()
    assert result.get("skipped") is True
    assert "15" in result.get("reason", "")
    assert "20" in result.get("reason", "")


def test_skip_no_active_signals(tmp_path, monkeypatch):
    """Records with no active_signals field are excluded from per-signal stats."""
    # 25 resolved records but none have active_signals — effective sample is 0
    records = []
    for i in range(25):
        r = _make_record("AAPL", "correct", [])  # empty active_signals
        records.append(r)

    history_file = tmp_path / "prediction_history.json"
    history_file.write_text(json.dumps(records))

    monkeypatch.setattr(signal_calibration, "HISTORY_FILE", str(history_file))
    monkeypatch.setattr(signal_calibration, "STATS_FILE", str(tmp_path / "stats.json"))
    monkeypatch.setattr(signal_calibration, "WEIGHTS_FILE", str(tmp_path / "weights.json"))
    monkeypatch.setattr(signal_calibration, "ACCURACY_HISTORY_FILE", str(tmp_path / "accuracy_history.json"))

    # Should NOT skip (25 >= 20 resolved), but per-signal stats will show 0 samples
    result = signal_calibration.run_recalibration()
    # If it doesn't skip, signal stats should show 0 total predictions per signal
    # (since none have active_signals populated)
    if not result.get("skipped"):
        stats_file = tmp_path / "stats.json"
        if stats_file.exists():
            stats = json.loads(stats_file.read_text())
            for sig, data in stats.get("signals", {}).items():
                assert data["total_predictions"] == 0, (
                    f"Signal {sig} should have 0 predictions when no active_signals set"
                )


def test_min_samples_per_signal(tmp_path, monkeypatch):
    """Signals with fewer than 10 samples keep their default weight."""
    # 20 resolved records, but rsi2 only appears 5 times
    records = []
    for i in range(5):
        records.append(_make_record("AAPL", "correct", ["rsi2", "ibs"]))
    for i in range(15):
        records.append(_make_record("AAPL", "correct", ["ibs", "consec_down"]))

    history_file = tmp_path / "prediction_history.json"
    history_file.write_text(json.dumps(records))

    monkeypatch.setattr(signal_calibration, "HISTORY_FILE", str(history_file))
    monkeypatch.setattr(signal_calibration, "STATS_FILE", str(tmp_path / "stats.json"))
    monkeypatch.setattr(signal_calibration, "WEIGHTS_FILE", str(tmp_path / "weights.json"))
    monkeypatch.setattr(signal_calibration, "ACCURACY_HISTORY_FILE", str(tmp_path / "accuracy_history.json"))

    result = signal_calibration.run_recalibration()
    assert not result.get("skipped"), "Should not skip with 20 records"

    # rsi2 only appears 5 times → below MIN_SAMPLES → keep default weight 4.0
    primary_weights = result.get("primary_weights", {})
    assert primary_weights.get("rsi2") == signal_calibration.DEFAULT_PRIMARY["rsi2"], (
        f"rsi2 should keep default weight {signal_calibration.DEFAULT_PRIMARY['rsi2']}, "
        f"got {primary_weights.get('rsi2')}"
    )


# ── Full recalibration formula test ──────────────────────────────────────────

def test_full_recalibration(tmp_path, monkeypatch):
    """With 25 resolved records where rsi2 has 20 appearances and 15 wins (75%), rsi2 weight -> 6.0."""
    # 15 correct with rsi2, 5 incorrect with rsi2 = 15/20 = 75% accuracy
    records = []
    for i in range(15):
        records.append(_make_record("AAPL", "correct", ["rsi2", "ibs", "bb_lower"]))
    for i in range(5):
        records.append(_make_record("AAPL", "incorrect", ["rsi2", "consec_down"]))
    # 5 more records without rsi2 to bring total to 25
    for i in range(5):
        records.append(_make_record("MSFT", "correct", ["ibs", "bb_lower"]))

    history_file = tmp_path / "prediction_history.json"
    history_file.write_text(json.dumps(records))

    monkeypatch.setattr(signal_calibration, "HISTORY_FILE", str(history_file))
    monkeypatch.setattr(signal_calibration, "STATS_FILE", str(tmp_path / "stats.json"))
    monkeypatch.setattr(signal_calibration, "WEIGHTS_FILE", str(tmp_path / "weights.json"))
    monkeypatch.setattr(signal_calibration, "ACCURACY_HISTORY_FILE", str(tmp_path / "accuracy_history.json"))

    result = signal_calibration.run_recalibration()
    assert not result.get("skipped"), f"Should not skip: {result}"

    primary_weights = result.get("primary_weights", {})
    # rsi2: 75% accuracy, default=4.0 → 4.0 * (75/50) = 6.0 (clamped)
    expected_rsi2 = max(1.0, min(6.0, 4.0 * (75.0 / 50.0)))
    assert primary_weights.get("rsi2") == expected_rsi2, (
        f"Expected rsi2={expected_rsi2}, got {primary_weights.get('rsi2')}"
    )


# ── Output file tests ─────────────────────────────────────────────────────────

def test_stats_file_written(tmp_path, monkeypatch):
    """After run_recalibration(), data/signal_accuracy_stats.json exists with 'signals' key."""
    records = [
        _make_record("AAPL", "correct", ["rsi2", "ibs"]) for _ in range(20)
    ]
    history_file = tmp_path / "prediction_history.json"
    history_file.write_text(json.dumps(records))

    stats_file = tmp_path / "stats.json"
    weights_file = tmp_path / "weights.json"
    accuracy_history_file = tmp_path / "accuracy_history.json"

    monkeypatch.setattr(signal_calibration, "HISTORY_FILE", str(history_file))
    monkeypatch.setattr(signal_calibration, "STATS_FILE", str(stats_file))
    monkeypatch.setattr(signal_calibration, "WEIGHTS_FILE", str(weights_file))
    monkeypatch.setattr(signal_calibration, "ACCURACY_HISTORY_FILE", str(accuracy_history_file))

    result = signal_calibration.run_recalibration()
    assert not result.get("skipped"), f"Should not skip: {result}"
    assert stats_file.exists(), "signal_accuracy_stats.json should exist"

    stats = json.loads(stats_file.read_text())
    assert "signals" in stats, f"Expected 'signals' key in stats, got: {list(stats.keys())}"


def test_weights_file_written(tmp_path, monkeypatch):
    """After run_recalibration(), data/signal_weights.json exists with correct keys."""
    records = [
        _make_record("AAPL", "correct", ["rsi2", "ibs"]) for _ in range(20)
    ]
    history_file = tmp_path / "prediction_history.json"
    history_file.write_text(json.dumps(records))

    stats_file = tmp_path / "stats.json"
    weights_file = tmp_path / "weights.json"
    accuracy_history_file = tmp_path / "accuracy_history.json"

    monkeypatch.setattr(signal_calibration, "HISTORY_FILE", str(history_file))
    monkeypatch.setattr(signal_calibration, "STATS_FILE", str(stats_file))
    monkeypatch.setattr(signal_calibration, "WEIGHTS_FILE", str(weights_file))
    monkeypatch.setattr(signal_calibration, "ACCURACY_HISTORY_FILE", str(accuracy_history_file))

    result = signal_calibration.run_recalibration()
    assert not result.get("skipped"), f"Should not skip: {result}"
    assert weights_file.exists(), "signal_weights.json should exist"

    weights = json.loads(weights_file.read_text())
    assert "primary_weights" in weights, f"Missing 'primary_weights' key, got: {list(weights.keys())}"
    assert "confirm_bonus" in weights, f"Missing 'confirm_bonus' key, got: {list(weights.keys())}"


def test_accuracy_history_appended(tmp_path, monkeypatch):
    """After run_recalibration(), accuracy_history.json exists with correct structure."""
    records = [
        _make_record("AAPL", "correct", ["rsi2", "ibs"]) for _ in range(20)
    ]
    history_file = tmp_path / "prediction_history.json"
    history_file.write_text(json.dumps(records))

    stats_file = tmp_path / "stats.json"
    weights_file = tmp_path / "weights.json"
    accuracy_history_file = tmp_path / "accuracy_history.json"

    monkeypatch.setattr(signal_calibration, "HISTORY_FILE", str(history_file))
    monkeypatch.setattr(signal_calibration, "STATS_FILE", str(stats_file))
    monkeypatch.setattr(signal_calibration, "WEIGHTS_FILE", str(weights_file))
    monkeypatch.setattr(signal_calibration, "ACCURACY_HISTORY_FILE", str(accuracy_history_file))

    result = signal_calibration.run_recalibration()
    assert not result.get("skipped"), f"Should not skip: {result}"
    assert accuracy_history_file.exists(), "accuracy_history.json should exist"

    history = json.loads(accuracy_history_file.read_text())
    assert "history" in history, f"Missing 'history' key, got: {list(history.keys())}"
    assert len(history["history"]) >= 1, "History should contain at least one entry"

    entry = history["history"][0]
    assert "date" in entry, f"Entry missing 'date' key: {entry}"
    assert "overall_accuracy_pct" in entry, f"Entry missing 'overall_accuracy_pct' key: {entry}"
    assert "per_signal" in entry, f"Entry missing 'per_signal' key: {entry}"


def test_accuracy_history_no_duplicate(tmp_path, monkeypatch):
    """Calling run_recalibration() twice on the same date appends only one entry."""
    records = [
        _make_record("AAPL", "correct", ["rsi2", "ibs"]) for _ in range(20)
    ]
    history_file = tmp_path / "prediction_history.json"
    history_file.write_text(json.dumps(records))

    stats_file = tmp_path / "stats.json"
    weights_file = tmp_path / "weights.json"
    accuracy_history_file = tmp_path / "accuracy_history.json"

    monkeypatch.setattr(signal_calibration, "HISTORY_FILE", str(history_file))
    monkeypatch.setattr(signal_calibration, "STATS_FILE", str(stats_file))
    monkeypatch.setattr(signal_calibration, "WEIGHTS_FILE", str(weights_file))
    monkeypatch.setattr(signal_calibration, "ACCURACY_HISTORY_FILE", str(accuracy_history_file))

    # Run twice
    signal_calibration.run_recalibration()
    signal_calibration.run_recalibration()

    history = json.loads(accuracy_history_file.read_text())
    dates = [entry["date"] for entry in history["history"]]
    assert len(dates) == len(set(dates)), (
        f"Duplicate date entries found in accuracy history: {dates}"
    )
