"""
prediction_log.py
-----------------
Formal prediction logging and accuracy tracking.

Every time the prediction engine identifies a stock, it logs a formal prediction:
  - Ticker, direction, predicted move %, timeframe, confidence, reasons, timestamp
After the timeframe expires, compares prediction vs actual outcome and marks CORRECT/INCORRECT.
Provides rolling accuracy: last 10, last 30, last 100 predictions.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta

import pandas as pd

from logger_setup import get_logger
from openbb_data import fetch_bars

log = get_logger()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PREDICTIONS_FILE = os.path.join(DATA_DIR, "prediction_history.json")

_log_lock = threading.Lock()


@dataclass
class PredictionRecord:
    """A single logged prediction with outcome tracking."""
    id: str
    symbol: str
    direction: str                   # "up" or "down"
    predicted_move_pct: float        # expected % move
    timeframe_days: int              # 1, 2, or 3
    confidence: int                  # 1-10
    reasons: list[str]
    source: str                      # "mean_reversion", "expanded_scanner", "prediction_scanner"
    prediction_statement: str        # human-readable prediction
    timestamp: str                   # ISO format
    entry_price: float = 0.0
    # Outcome fields (filled after timeframe expires)
    actual_move_pct: float | None = None
    outcome: str = "pending"         # "pending", "correct", "incorrect"
    outcome_date: str = ""
    exit_price: float = 0.0

    def is_expired(self) -> bool:
        ts = datetime.fromisoformat(self.timestamp)
        deadline = ts + timedelta(days=self.timeframe_days + 1)
        return datetime.now(timezone.utc) > deadline


def _next_id(records: list[dict]) -> str:
    """Generate next prediction ID: P-0001, P-0002, etc."""
    if not records:
        return "P-0001"
    max_num = 0
    for r in records:
        pid = r.get("id", "P-0000")
        try:
            num = int(pid.split("-")[1])
            if num > max_num:
                max_num = num
        except (IndexError, ValueError):
            pass
    return f"P-{max_num + 1:04d}"


def log_prediction(
    symbol: str,
    direction: str,
    predicted_move_pct: float,
    timeframe_days: int,
    confidence: int,
    reasons: list[str],
    source: str,
    entry_price: float = 0.0,
) -> PredictionRecord:
    """Log a formal prediction. Returns the record."""
    records = _load_records()
    pid = _next_id(records)

    statement = (
        f"PREDICTION: {symbol} will {'bounce' if direction == 'up' else 'drop'} "
        f"{predicted_move_pct:.1f}% within {timeframe_days} day{'s' if timeframe_days > 1 else ''}. "
        f"REASON: {'; '.join(reasons[:4])}. "
        f"Confidence: {confidence}/10."
    )

    record = PredictionRecord(
        id=pid,
        symbol=symbol,
        direction=direction,
        predicted_move_pct=predicted_move_pct,
        timeframe_days=timeframe_days,
        confidence=confidence,
        reasons=reasons,
        source=source,
        prediction_statement=statement,
        timestamp=datetime.now(timezone.utc).isoformat(),
        entry_price=entry_price,
    )

    records.append(asdict(record))
    _save_records(records)

    log.info("[prediction_log] %s", statement)
    return record


def check_outcomes() -> int:
    """Check all pending predictions and resolve expired ones. Returns count resolved."""
    records = _load_records()
    resolved = 0

    for r in records:
        if r["outcome"] != "pending":
            continue

        rec = PredictionRecord(**r)
        if not rec.is_expired():
            continue

        try:
            df = fetch_bars(rec.symbol, period="10d", interval="1d")
            if df is None or df.empty:
                continue

            pred_time = datetime.fromisoformat(rec.timestamp)
            end_date = pred_time + timedelta(days=rec.timeframe_days + 1)

            mask = df.index >= pred_time
            fwd = df[mask]
            if len(fwd) < 2:
                continue

            if rec.entry_price > 0:
                entry = rec.entry_price
            else:
                entry = float(fwd["close"].iloc[0])

            best_close = float(fwd["close"].iloc[1:min(rec.timeframe_days + 1, len(fwd))].max())
            actual_move = (best_close - entry) / entry * 100

            r["actual_move_pct"] = round(actual_move, 2)
            r["exit_price"] = round(best_close, 2)
            r["outcome_date"] = datetime.now(timezone.utc).isoformat()

            if rec.direction == "up":
                r["outcome"] = "correct" if actual_move > 1.0 else "incorrect"
            else:
                r["outcome"] = "correct" if actual_move < -1.0 else "incorrect"

            resolved += 1
            log.info("[prediction_log] Resolved %s %s: predicted %+.1f%%, actual %+.1f%% -> %s",
                     rec.id, rec.symbol, rec.predicted_move_pct, actual_move, r["outcome"])

        except Exception as exc:
            log.debug("[prediction_log] Failed to resolve %s: %s", rec.id, exc)

    if resolved > 0:
        _save_records(records)

    return resolved


def get_accuracy(window: int = 30) -> dict:
    """Get rolling prediction accuracy stats."""
    records = _load_records()
    resolved = [r for r in records if r["outcome"] in ("correct", "incorrect")]

    if not resolved:
        return {
            "total_predictions": len(records),
            "resolved": 0,
            "pending": len(records),
            "accuracy_pct": 0.0,
            "correct": 0,
            "incorrect": 0,
            "last_10": 0.0,
            "last_30": 0.0,
            "last_100": 0.0,
            "avg_predicted_move": 0.0,
            "avg_actual_move": 0.0,
            "profit_factor": 0.0,
        }

    def _acc(recs):
        if not recs:
            return 0.0
        correct = sum(1 for r in recs if r["outcome"] == "correct")
        return round(correct / len(recs) * 100, 1)

    correct_count = sum(1 for r in resolved if r["outcome"] == "correct")
    incorrect_count = len(resolved) - correct_count

    wins = [r["actual_move_pct"] for r in resolved if r["outcome"] == "correct" and r.get("actual_move_pct") is not None]
    losses = [abs(r["actual_move_pct"]) for r in resolved if r["outcome"] == "incorrect" and r.get("actual_move_pct") is not None]

    total_wins = sum(wins) if wins else 0
    total_losses = sum(losses) if losses else 0
    profit_factor = round(total_wins / total_losses, 2) if total_losses > 0 else 999.0

    avg_win = round(sum(wins) / len(wins), 2) if wins else 0.0
    avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0

    return {
        "total_predictions": len(records),
        "resolved": len(resolved),
        "pending": len(records) - len(resolved),
        "accuracy_pct": _acc(resolved),
        "correct": correct_count,
        "incorrect": incorrect_count,
        "last_10": _acc(resolved[-10:]),
        "last_30": _acc(resolved[-30:]),
        "last_100": _acc(resolved[-100:]),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "profit_factor": profit_factor,
        "profit_factor_warning": profit_factor < 1.2 and len(resolved) >= 10,
    }


def get_symbol_accuracy(symbol: str, window: int = 50) -> dict:
    """Get prediction accuracy for a specific symbol.

    Returns dict with 'accuracy' (0.0-1.0) and 'samples' (int).
    """
    records = _load_records()
    sym = symbol.upper()
    resolved = [r for r in records
                if r.get("symbol", "").upper() == sym
                and r["outcome"] in ("correct", "incorrect")]
    if not resolved:
        return {"accuracy": 0.0, "samples": 0}
    recent = resolved[-window:]
    correct = sum(1 for r in recent if r["outcome"] == "correct")
    return {"accuracy": round(correct / len(recent), 3), "samples": len(recent)}


def get_recent_predictions(limit: int = 20) -> list[dict]:
    """Get most recent predictions for dashboard display."""
    records = _load_records()
    return records[-limit:][::-1]


def _load_records() -> list[dict]:
    with _log_lock:
        try:
            with open(PREDICTIONS_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []


def _save_records(records: list[dict]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with _log_lock:
        with open(PREDICTIONS_FILE, "w") as f:
            json.dump(records, f, indent=2, default=str)
