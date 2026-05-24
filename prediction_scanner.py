"""
prediction_scanner.py
---------------------
Runs pattern-based predictions on quant-filtered stock survivors.

Takes ~50 stocks from the expanded scanner's quant pipeline and analyzes each
for entry setups using pattern signals (Keltner squeeze, OBV/ADL divergence).
Classifies picks by urgency tier, saves to disk, and tracks accuracy next morning.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import date, datetime, timezone, timedelta

from logger_setup import get_logger

log = get_logger()

# ── Paths ────────────────────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PREDICTIONS_FILE = os.path.join(DATA_DIR, "overnight_predictions.json")
ACCURACY_FILE = os.path.join(DATA_DIR, "prediction_accuracy.json")

# ── State ────────────────────────────────────────────────────────────────────

_scanner_thread: threading.Thread | None = None
_last_scan_result: dict | None = None
_last_scan_lock = threading.Lock()


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


# ── Core overnight scan ─────────────────────────────────────────────────────

def run_overnight_scan(progress_cb: callable | None = None) -> dict:
    """
    Run the full overnight scan. Scans the expanded universe, runs predictions,
    ranks by expected value, and saves results.

    Returns dict with predictions, summary, and metadata.
    """
    global _last_scan_result

    from stock_universe import get_full_universe, get_scan_summary
    from prediction import predict_batch
    from data_provider import fetch_bars
    from expanded_scanner import load_overnight_results, run_expanded_pipeline

    log.info("[overnight] Starting overnight scan...")
    scan_start = datetime.now(timezone.utc)

    # Use expanded scanner survivors if available, otherwise run it first
    survivors = load_overnight_results()
    if survivors:
        universe = [s["symbol"] for s in survivors if "symbol" in s]
        log.info("[overnight] Using %d expanded scanner survivors", len(universe))
    else:
        log.info("[overnight] No expanded scanner results — running quant filter first...")
        if progress_cb:
            progress_cb(0, 0, "Running quant filter on 2,500+ stocks...")
        scored = run_expanded_pipeline()
        universe = [s["symbol"] for s in scored if "symbol" in s]
        log.info("[overnight] Quant filter produced %d survivors", len(universe))

    if not universe:
        universe = get_full_universe(include_discovery=True)
        log.warning("[overnight] Expanded scanner returned empty — falling back to full universe (%d)", len(universe))

    total_scanned = len(universe)
    log.info("[overnight] Scanning %d stocks...", total_scanned)

    # Run predictions on survivors
    def _relay_progress(cur, tot, lbl=None):
        if progress_cb:
            progress_cb(cur, tot, lbl or f"Analyzing stock {cur}/{tot}...")

    predictions = predict_batch(universe, progress_cb=_relay_progress)

    # Filter to confidence >= 7
    high_confidence = [p for p in predictions if p.confidence >= 7]

    # Rank by expected value: historical_accuracy * expected_move_pct
    def _ev_key(p):
        if p.historical_accuracy > 0:
            return p.historical_accuracy * p.expected_move_pct
        return p.expected_move_pct * 0.5

    high_confidence.sort(key=_ev_key, reverse=True)

    # Classify into urgency tiers
    ready_tomorrow = []    # launch_zone or pre_breakout
    building = []          # accumulation
    early = []             # early_accumulation

    for p in high_confidence:
        if p.stage in ("launch_zone", "pre_breakout"):
            ready_tomorrow.append(p)
        elif p.stage == "accumulation":
            building.append(p)
        else:
            early.append(p)

    # Build result
    scan_end = datetime.now(timezone.utc)
    duration = (scan_end - scan_start).total_seconds()

    result = {
        "scan_date": date.today().isoformat(),
        "scan_time": scan_end.isoformat(),
        "duration_seconds": round(duration, 1),
        "total_scanned": total_scanned,
        "predictions_generated": len(predictions),
        "high_confidence_count": len(high_confidence),
        "summary": get_scan_summary(total_scanned, len(predictions), len(high_confidence)),
        "ready_tomorrow": [p.to_dict() for p in ready_tomorrow[:10]],
        "building_up": [p.to_dict() for p in building[:10]],
        "early_accumulation": [p.to_dict() for p in early[:10]],
        "all_predictions": [p.to_dict() for p in high_confidence[:30]],
    }

    # Save to disk
    _ensure_data_dir()
    try:
        with open(PREDICTIONS_FILE, "w") as f:
            json.dump(result, f, indent=2, default=str)
        log.info("[overnight] Predictions saved to %s", PREDICTIONS_FILE)
    except Exception as exc:
        log.error("[overnight] Failed to save predictions: %s", exc)

    # Update in-memory cache
    with _last_scan_lock:
        _last_scan_result = result

    # Push predictions to shared state so the dashboard can display them
    import state as shared_state
    from stock_universe import get_scan_summary
    all_pred_dicts = [p.to_dict() for p in high_confidence[:30]]
    shared_state.update(
        predictions=all_pred_dicts,
        prediction_count=len(predictions),
        scan_universe_size=total_scanned,
        scan_summary=get_scan_summary(total_scanned, len(predictions), len(high_confidence)),
    )
    log.info(
        "[prediction] Predictions saved to state: %d stocks in launch zone, "
        "%d building up, %d early accumulation",
        len(ready_tomorrow), len(building), len(early),
    )

    log.info(
        "[overnight] Scan complete in %.0fs: %d scanned → %d predictions → "
        "%d high confidence (%d ready, %d building, %d early)",
        duration, total_scanned, len(predictions), len(high_confidence),
        len(ready_tomorrow), len(building), len(early),
    )

    return result


# ── Accuracy tracking ────────────────────────────────────────────────────────

def check_prediction_accuracy() -> dict:
    """
    Check yesterday's predictions against today's actual prices.
    Updates the accuracy log.
    """
    from data_provider import fetch_bars

    _ensure_data_dir()

    # Load yesterday's predictions
    try:
        with open(PREDICTIONS_FILE, "r") as f:
            preds = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"error": "no predictions file found"}

    pred_date = preds.get("scan_date", "")
    if pred_date == date.today().isoformat():
        return {"error": "predictions are from today — check tomorrow"}

    all_preds = preds.get("all_predictions", [])
    if not all_preds:
        return {"error": "no predictions to check"}

    # Check each prediction
    results = []
    correct_count = 0
    wrong_count = 0

    for pred in all_preds:
        symbol = pred["symbol"]
        entry_high = pred["entry_high"]
        target = pred["target_price"]
        stop = pred["stop_loss"]
        expected_move = pred["expected_move_pct"]
        confidence = pred.get("confidence", 0)
        stage = pred.get("stage", "unknown")
        patterns = [p["name"] for p in pred.get("patterns", []) if p.get("detected")]

        try:
            hist = fetch_bars(symbol, period="5d", interval="1d")
            if hist is None or len(hist) < 2:
                continue

            # fetch_bars already returns lowercase columns
            # Get the max price in the 3 days after prediction
            recent_high = float(hist["high"].iloc[-3:].max()) if len(hist) >= 3 else float(hist["high"].iloc[-1])
            recent_low = float(hist["low"].iloc[-3:].min()) if len(hist) >= 3 else float(hist["low"].iloc[-1])
            current = float(hist["close"].iloc[-1])
            entry_price = entry_high  # assume entry at top of range

            actual_move = (recent_high - entry_price) / entry_price * 100 if entry_price > 0 else 0
            actual_close_move = (current - entry_price) / entry_price * 100 if entry_price > 0 else 0
            hit_target = recent_high >= target
            hit_stop = recent_low <= stop

            # Determine verdict and failure reason
            profitable = actual_move > 0
            if hit_target:
                verdict = "CORRECT"
                failure_reason = ""
                correct_count += 1
            elif profitable and actual_move >= expected_move * 0.5:
                verdict = "CORRECT"
                failure_reason = ""
                correct_count += 1
            else:
                verdict = "WRONG"
                wrong_count += 1
                # Diagnose WHY it was wrong
                if hit_stop and actual_close_move < 0:
                    failure_reason = f"Hit stop loss at ${stop:.2f}, dropped to ${recent_low:.2f} — price went against us"
                elif actual_close_move < -3:
                    failure_reason = f"Went sharply opposite: closed at {actual_close_move:+.1f}% instead of predicted +{expected_move:.1f}%"
                elif actual_close_move < 0:
                    failure_reason = f"Drifted down {actual_close_move:+.1f}% — no buying pressure materialized"
                elif actual_move < expected_move * 0.25:
                    failure_reason = f"Flat — only moved +{actual_move:.1f}% vs predicted +{expected_move:.1f}%, no spike occurred"
                elif hit_stop:
                    failure_reason = f"Whipsawed: hit stop ${stop:.2f} before recovering to +{actual_move:.1f}%"
                else:
                    failure_reason = f"Weak move: +{actual_move:.1f}% vs predicted +{expected_move:.1f}%, didn't reach target"

            # Log each prediction individually
            if verdict == "CORRECT":
                log.info(
                    "[accuracy] CORRECT $%s: predicted +%.1f%%, actual +%.1f%% "
                    "(conf=%d, stage=%s, patterns=%s)",
                    symbol, expected_move, actual_move, confidence, stage,
                    "+".join(patterns) if patterns else "none",
                )
            else:
                log.warning(
                    "[accuracy] WRONG   $%s: predicted +%.1f%%, actual %+.1f%% — %s "
                    "(conf=%d, stage=%s, patterns=%s)",
                    symbol, expected_move, actual_close_move, failure_reason,
                    confidence, stage, "+".join(patterns) if patterns else "none",
                )

            results.append({
                "symbol": symbol,
                "predicted_move": expected_move,
                "actual_max_move": round(actual_move, 2),
                "actual_close_move": round(actual_close_move, 2),
                "hit_target": hit_target,
                "hit_stop": hit_stop,
                "profitable": profitable,
                "confidence": confidence,
                "stage": stage,
                "verdict": verdict,
                "failure_reason": failure_reason,
                "patterns": patterns,
                "entry_price": round(entry_price, 2),
                "target_price": round(target, 2),
                "stop_loss": round(stop, 2),
                "recent_high": round(recent_high, 2),
                "recent_low": round(recent_low, 2),
                "current_close": round(current, 2),
            })
        except Exception:
            continue

    if not results:
        return {"error": "couldn't check any predictions"}

    # Compute accuracy stats
    total = len(results)
    profitable = sum(1 for r in results if r["profitable"])
    hit_targets = sum(1 for r in results if r["hit_target"])
    hit_stops = sum(1 for r in results if r["hit_stop"])

    # Group failure reasons to find common patterns
    failure_reasons = {}
    for r in results:
        if r["verdict"] == "WRONG" and r["failure_reason"]:
            # Extract the category from the reason
            reason = r["failure_reason"]
            if "stop loss" in reason or "Whipsawed" in reason:
                cat = "hit_stop_loss"
            elif "opposite" in reason or "Drifted down" in reason:
                cat = "went_opposite"
            elif "Flat" in reason:
                cat = "no_movement"
            else:
                cat = "weak_move"
            failure_reasons[cat] = failure_reasons.get(cat, 0) + 1

    accuracy = {
        "date_checked": date.today().isoformat(),
        "prediction_date": pred_date,
        "total_checked": total,
        "correct": correct_count,
        "wrong": wrong_count,
        "correct_pct": round(correct_count / total * 100, 1) if total > 0 else 0,
        "profitable": profitable,
        "profitable_pct": round(profitable / total * 100, 1) if total > 0 else 0,
        "hit_target": hit_targets,
        "hit_target_pct": round(hit_targets / total * 100, 1) if total > 0 else 0,
        "hit_stop": hit_stops,
        "avg_actual_move": round(sum(r["actual_max_move"] for r in results) / total, 2) if total > 0 else 0,
        "avg_predicted_move": round(sum(r["predicted_move"] for r in results) / total, 2) if total > 0 else 0,
        "failure_breakdown": failure_reasons,
        "results": results,
    }

    # Load historical accuracy log and append
    try:
        with open(ACCURACY_FILE, "r") as f:
            log_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        log_data = {"history": [], "cumulative": {"total": 0, "correct": 0, "wrong": 0, "profitable": 0, "hit_target": 0}}

    log_data["history"].append(accuracy)
    # Keep last 30 days
    log_data["history"] = log_data["history"][-30:]

    # Update cumulative
    cum = log_data["cumulative"]
    cum["total"] = cum.get("total", 0) + total
    cum["correct"] = cum.get("correct", 0) + correct_count
    cum["wrong"] = cum.get("wrong", 0) + wrong_count
    cum["profitable"] = cum.get("profitable", 0) + profitable
    cum["hit_target"] = cum.get("hit_target", 0) + hit_targets

    cum["correct_pct"] = round(cum["correct"] / cum["total"] * 100, 1) if cum["total"] > 0 else 0
    cum["profitable_pct"] = round(cum["profitable"] / cum["total"] * 100, 1) if cum["total"] > 0 else 0
    cum["hit_target_pct"] = round(cum["hit_target"] / cum["total"] * 100, 1) if cum["total"] > 0 else 0

    # Track cumulative failure patterns
    cum_failures = cum.get("failure_breakdown", {})
    for cat, count in failure_reasons.items():
        cum_failures[cat] = cum_failures.get(cat, 0) + count
    cum["failure_breakdown"] = cum_failures

    try:
        with open(ACCURACY_FILE, "w") as f:
            json.dump(log_data, f, indent=2)
    except Exception as exc:
        log.error("[overnight] Failed to save accuracy log: %s", exc)

    # Log detailed summary
    log.info(
        "[accuracy] === PREDICTION SCORECARD (%s) ===",
        pred_date,
    )
    log.info(
        "[accuracy] Score: %d correct / %d wrong out of %d checked (%.0f%% accuracy)",
        correct_count, wrong_count, total, accuracy["correct_pct"],
    )
    log.info(
        "[accuracy] %d/%d profitable (%.0f%%), %d hit full target, %d hit stop loss",
        profitable, total, accuracy["profitable_pct"], hit_targets, hit_stops,
    )
    log.info(
        "[accuracy] Avg predicted move: +%.1f%% | Avg actual move: %+.1f%%",
        accuracy["avg_predicted_move"], accuracy["avg_actual_move"],
    )
    if failure_reasons:
        parts = [f"{cat}: {count}" for cat, count in sorted(failure_reasons.items(), key=lambda x: -x[1])]
        log.info("[accuracy] Failure breakdown: %s", ", ".join(parts))

    # Log cumulative running totals
    log.info(
        "[accuracy] === CUMULATIVE: %d correct / %d wrong (%.0f%% all-time accuracy) ===",
        cum["correct"], cum["wrong"], cum["correct_pct"],
    )

    return accuracy


# ── Hydrate shared_state from disk ──────────────────────────────────────────

def load_predictions_into_state() -> bool:
    """Load today's disk predictions into shared_state on startup.
    Returns True if predictions were loaded, False if stale/missing."""
    import state as shared_state
    try:
        with open(PREDICTIONS_FILE) as f:
            data = json.load(f)
        scan_date = data.get("scan_date", "")
        if scan_date != date.today().isoformat():
            log.info("[prediction_scanner] Disk predictions from %s are stale, skipping", scan_date)
            return False
        preds = data.get("all_predictions", [])
        shared_state.update(
            predictions=preds[:30],
            prediction_count=len(preds),
        )
        log.info("[prediction_scanner] Loaded %d predictions from disk into shared_state", len(preds))
        return True
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        log.debug("[prediction_scanner] No disk predictions to load: %s", exc)
        return False


# ── Load saved predictions ───────────────────────────────────────────────────

def get_latest_predictions() -> dict | None:
    """Load the most recent overnight predictions from disk or memory."""
    global _last_scan_result

    with _last_scan_lock:
        if _last_scan_result is not None:
            return _last_scan_result

    try:
        with open(PREDICTIONS_FILE, "r") as f:
            result = json.load(f)
        with _last_scan_lock:
            _last_scan_result = result
        return result
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def get_accuracy_summary() -> dict:
    """Load cumulative accuracy stats."""
    try:
        with open(ACCURACY_FILE, "r") as f:
            data = json.load(f)
        return {
            "cumulative": data.get("cumulative", {}),
            "recent": data.get("history", [])[-7:],  # last 7 days
        }
    except (FileNotFoundError, json.JSONDecodeError):
        return {"cumulative": {"total": 0, "correct": 0, "wrong": 0, "profitable": 0, "hit_target": 0, "failure_breakdown": {}}, "recent": []}


# ── Scheduler ────────────────────────────────────────────────────────────────

def _schedule_loop():
    """
    Background thread that runs the overnight scan at 4:05 PM ET every weekday.
    Also checks yesterday's prediction accuracy at market open (9:35 AM ET).
    """
    from datetime import time as dtime
    import pytz

    et = pytz.timezone("US/Eastern")
    scan_time = dtime(16, 5)       # 4:05 PM ET
    accuracy_time = dtime(9, 35)   # 9:35 AM ET

    last_scan_date = None
    last_accuracy_date = None

    while True:
        try:
            now_et = datetime.now(et)
            today = now_et.date()
            current_time = now_et.time()

            # Skip weekends
            if now_et.weekday() >= 5:
                time.sleep(300)
                continue

            # Overnight scan is now triggered by expanded_scanner daemon
            # (quant filter → predictions pipeline). Skip standalone trigger.
            # Mark as done if expanded scanner already ran today.
            if last_scan_date != today:
                from expanded_scanner import load_overnight_results
                if load_overnight_results():
                    last_scan_date = today

            # Accuracy check at 9:35 AM ET
            if current_time >= accuracy_time and last_accuracy_date != today:
                log.info("[overnight] Checking yesterday's prediction accuracy")
                try:
                    check_prediction_accuracy()
                    last_accuracy_date = today
                except Exception as exc:
                    log.error("[overnight] Accuracy check failed: %s", exc)

            time.sleep(60)  # check every minute
        except Exception as exc:
            log.error("[overnight] Scheduler error: %s", exc)
            time.sleep(60)


def start_scheduler():
    """Start the overnight scanner scheduler in a background thread."""
    global _scanner_thread
    if _scanner_thread is not None and _scanner_thread.is_alive():
        log.debug("[overnight] Scheduler already running")
        return

    _scanner_thread = threading.Thread(
        target=_schedule_loop,
        daemon=True,
        name="overnight-scanner",
    )
    _scanner_thread.start()
    log.info("[overnight] Scheduler started — scans at 4:05 PM ET, accuracy at 9:35 AM ET")
