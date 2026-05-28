"""
signal_calibration.py
---------------------
Signal accuracy tracking and weight recalibration engine.

Reads resolved predictions from data/prediction_history.json and computes
per-signal accuracy. Updates signal_weights.json with calibrated weights
proportional to signal accuracy (clamped to [1.0, 6.0]).

Also maintains a daily accuracy snapshot in data/accuracy_history.json
for the dashboard trend sparkline.

Called weekly (Sunday midnight ET) by the prediction_scanner scheduler.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta

from logger_setup import get_logger

log = get_logger()

# ── Constants ─────────────────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
HISTORY_FILE = os.path.join(DATA_DIR, "prediction_history.json")
STATS_FILE = os.path.join(DATA_DIR, "signal_accuracy_stats.json")
WEIGHTS_FILE = os.path.join(DATA_DIR, "signal_weights.json")
ACCURACY_HISTORY_FILE = os.path.join(DATA_DIR, "accuracy_history.json")

DEFAULT_PRIMARY = {
    "rsi2":        4.0,
    "ibs":         3.5,
    "consec_down": 3.0,
    "bb_lower":    3.5,
}
DEFAULT_CONFIRM = {
    "volume_profile": 1.5,
    "order_flow":     1.0,
    "amt_state":      1.0,
    "volume_spike":   1.5,
    # Phase 11 — new confirmation signals (initial weight 0.5 per D-02)
    "stoch_rsi":       0.5,
    "mfi":             0.5,
    "vwap":            0.5,
    "keltner_lower":   0.5,
    "macd_divergence": 0.5,
    "support_level":   0.5,
}

MIN_SAMPLES = 10       # minimum per-signal appearances before recalibrating (D-06 discretion)
WINDOW_DAYS = 30       # rolling window for accuracy computation (D-05)
MIN_PREDICTIONS = 20   # minimum resolved predictions required (D-05)
CLAMP_MIN = 1.0        # minimum weight clamp (D-07)
CLAMP_MAX = 6.0        # maximum weight clamp (D-07)
HISTORY_LIMIT = 90     # maximum daily entries to keep in accuracy_history.json


# ── Core formula ──────────────────────────────────────────────────────────────

def _compute_new_weight(accuracy_pct: float, default_weight: float) -> float:
    """Compute a new signal weight proportional to accuracy.

    Formula: default_weight * (accuracy_pct / 50.0)
    Baseline: 50% accuracy → weight unchanged (ratio = 1.0)
    Clamped to [CLAMP_MIN, CLAMP_MAX] and rounded to 2 decimal places.

    Examples:
        50% accuracy, default 4.0 → 4.0 (unchanged)
        75% accuracy, default 4.0 → 6.0 (clamped from 6.0)
        100% accuracy, default 4.0 → 6.0 (clamped from 8.0)
        10% accuracy, default 4.0 → 1.0 (clamped from 0.8)
    """
    ratio = accuracy_pct / 50.0
    new_weight = default_weight * ratio
    return round(max(CLAMP_MIN, min(CLAMP_MAX, new_weight)), 2)


# ── Accuracy history snapshot ─────────────────────────────────────────────────

def _append_accuracy_snapshot(stats: dict) -> None:
    """Append a daily accuracy snapshot to accuracy_history.json.

    Used by the dashboard accuracy trend sparkline (D-11).
    Deduplicates by date — same-day calls replace the existing entry.
    Trims to last HISTORY_LIMIT entries.
    """
    # Load existing history
    try:
        with open(ACCURACY_HISTORY_FILE, "r") as f:
            history_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history_data = {"history": []}

    today = datetime.now(timezone.utc).date().isoformat()

    # Compute overall accuracy from stats
    total_predictions = sum(
        sig_data.get("total_predictions", 0)
        for sig_data in stats.get("signals", {}).values()
    )
    total_wins = sum(
        sig_data.get("wins", 0)
        for sig_data in stats.get("signals", {}).values()
    )
    overall_accuracy_pct = (
        round(total_wins / total_predictions * 100, 1)
        if total_predictions > 0 else 0.0
    )

    # Build per-signal snapshot
    per_signal = {}
    for sig, sig_data in stats.get("signals", {}).items():
        per_signal[sig] = {
            "accuracy_pct": sig_data.get("accuracy_pct"),
            "sample_count": sig_data.get("total_predictions", 0),
        }

    snapshot = {
        "date": today,
        "overall_accuracy_pct": overall_accuracy_pct,
        "per_signal": per_signal,
    }

    # Deduplicate: replace existing entry for today
    history_list = history_data.get("history", [])
    history_list = [e for e in history_list if e.get("date") != today]
    history_list.append(snapshot)

    # Trim to last HISTORY_LIMIT entries (oldest removed first)
    if len(history_list) > HISTORY_LIMIT:
        history_list = history_list[-HISTORY_LIMIT:]

    history_data["history"] = history_list

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ACCURACY_HISTORY_FILE, "w") as f:
        json.dump(history_data, f, indent=2)


# ── Main recalibration function ───────────────────────────────────────────────

def run_recalibration() -> dict:
    """Compute per-signal accuracy and update signal_weights.json.

    Steps:
    1. Load prediction_history.json records
    2. Filter to resolved records within last WINDOW_DAYS with active_signals
    3. Skip if fewer than MIN_PREDICTIONS resolved records
    4. Compute per-signal accuracy (wins / total for each signal)
    5. Compute new weights (clamped to [CLAMP_MIN, CLAMP_MAX])
    6. Write signal_accuracy_stats.json
    7. Write signal_weights.json
    8. Append daily accuracy snapshot to accuracy_history.json
    9. Log changes

    Returns the result dict (same as signal_weights.json content), or
    {"skipped": True, "reason": "..."} if skipping.
    """
    # 1. Load records
    try:
        with open(HISTORY_FILE, "r") as f:
            records = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        records = []

    # 2. Filter to resolved records within window with active_signals
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    resolved = []
    for r in records:
        if r.get("outcome") not in ("correct", "incorrect"):
            continue
        if not r.get("active_signals"):
            continue
        try:
            ts_str = r.get("timestamp", "")
            # Handle both naive and tz-aware timestamps
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                resolved.append(r)
        except (ValueError, TypeError):
            continue

    # 3. Skip if insufficient data
    if len(resolved) < MIN_PREDICTIONS:
        log.warning(
            "[recalibration] Skipping: only %d resolved predictions with active_signals (need %d)",
            len(resolved), MIN_PREDICTIONS,
        )
        return {
            "skipped": True,
            "reason": f"Only {len(resolved)} resolved predictions (need {MIN_PREDICTIONS})",
        }

    # 4. Compute per-signal stats
    all_signals = list(DEFAULT_PRIMARY) + list(DEFAULT_CONFIRM)
    signal_stats: dict[str, dict] = {}
    for sig in all_signals:
        active = [r for r in resolved if sig in r.get("active_signals", [])]
        wins = [r for r in active if r["outcome"] == "correct"]
        accuracy_pct = round(len(wins) / len(active) * 100, 1) if active else None
        signal_stats[sig] = {
            "total_predictions": len(active),
            "wins": len(wins),
            "accuracy_pct": accuracy_pct,
            "sample_count": len(active),
        }

    # 5. Compute new weights
    new_primary: dict[str, float] = {}
    for sig, default_w in DEFAULT_PRIMARY.items():
        stats = signal_stats[sig]
        if stats["total_predictions"] < MIN_SAMPLES or stats["accuracy_pct"] is None:
            new_primary[sig] = default_w
        else:
            new_primary[sig] = _compute_new_weight(stats["accuracy_pct"], default_w)

    new_confirm: dict[str, float] = {}
    for sig, default_w in DEFAULT_CONFIRM.items():
        stats = signal_stats[sig]
        if stats["total_predictions"] < MIN_SAMPLES or stats["accuracy_pct"] is None:
            new_confirm[sig] = default_w
        else:
            new_confirm[sig] = _compute_new_weight(stats["accuracy_pct"], default_w)

    # 6. Load current weights to compute diff
    try:
        with open(WEIGHTS_FILE, "r") as f:
            current_weights = json.load(f)
        cur_primary = current_weights.get("primary_weights", DEFAULT_PRIMARY)
        cur_confirm = current_weights.get("confirm_bonus", DEFAULT_CONFIRM)
    except (FileNotFoundError, json.JSONDecodeError):
        cur_primary = dict(DEFAULT_PRIMARY)
        cur_confirm = dict(DEFAULT_CONFIRM)

    old_all = {**cur_primary, **cur_confirm}
    new_all = {**new_primary, **new_confirm}
    changes = []
    for sig in all_signals:
        old_w = old_all.get(sig)
        new_w = new_all.get(sig)
        if old_w is not None and new_w is not None and abs(old_w - new_w) >= 0.05:
            changes.append({"signal": sig, "old_weight": old_w, "new_weight": new_w})

    now_iso = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()

    result = {
        "version": 1,
        "generated_at": now_iso,
        "recalibration_date": today,
        "window_days": WINDOW_DAYS,
        "resolved_predictions_used": len(resolved),
        "changes": changes,
        "primary_weights": new_primary,
        "confirm_bonus": new_confirm,
    }

    stats_payload = {
        "computed_at": now_iso,
        "window_days": WINDOW_DAYS,
        "total_resolved_in_window": len(resolved),
        "signals": signal_stats,
    }

    # 7. Write output files
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(WEIGHTS_FILE, "w") as f:
        json.dump(result, f, indent=2)
    with open(STATS_FILE, "w") as f:
        json.dump(stats_payload, f, indent=2)

    # 8. Append daily accuracy snapshot
    _append_accuracy_snapshot(stats_payload)

    # 9. Log changes
    if changes:
        change_log = ", ".join(
            f"{c['signal']} {c['old_weight']:.1f}->{c['new_weight']:.1f}"
            for c in changes
        )
        log.info("[recalibration] Weekly recalibration: %s", change_log)
    else:
        log.info("[recalibration] Weekly recalibration complete — no significant weight changes")

    return result


# ── Accessor functions ────────────────────────────────────────────────────────

def get_signal_stats() -> dict:
    """Load and return signal_accuracy_stats.json, or empty dict if not found."""
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_current_weights() -> dict:
    """Load and return signal_weights.json, or dict with defaults if not found."""
    try:
        with open(WEIGHTS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "version": 0,
            "generated_at": None,
            "recalibration_date": None,
            "primary_weights": dict(DEFAULT_PRIMARY),
            "confirm_bonus": dict(DEFAULT_CONFIRM),
        }


def get_accuracy_history() -> dict:
    """Load and return accuracy_history.json, or {'history': []} if not found."""
    try:
        with open(ACCURACY_HISTORY_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"history": []}
