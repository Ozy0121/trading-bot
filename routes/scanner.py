"""
routes/scanner.py
-----------------
Flask Blueprint for scanner and prediction routes: predictions, overnight
scanner, expanded scanner, intelligence, heatmaps, scan logs, prediction log.
"""

import threading

from flask import Blueprint, jsonify, request

import config
import progress
import state as shared_state
from logger_setup import get_logger

log = get_logger()
scanner_bp = Blueprint("scanner", __name__)


# ── Prediction routes ────────────────────────────────────────────────────────

@scanner_bp.route("/api/predictions")
def api_predictions():
    """Return current pre-spike predictions from the prediction engine."""
    snap = shared_state.snapshot()
    return jsonify({
        "predictions": snap.get("predictions", []),
        "count": snap.get("prediction_count", 0),
        "scan_summary": snap.get("scan_summary", ""),
        "universe_size": snap.get("scan_universe_size", 0),
        "scan_funnel": snap.get("scan_funnel", {}),
    })


@scanner_bp.route("/api/predictions/run", methods=["POST"])
def api_predictions_run():
    """Trigger a prediction scan in the background."""
    def _do():
        try:
            from stock_universe import get_full_universe, get_scan_summary, get_funnel_stats
            from prediction import predict_batch
            from expanded_scanner import load_overnight_results, run_expanded_pipeline

            progress.track("predictions", total=0, current=0, label="Loading quant-filtered stocks...")
            progress.push_log("predictions", "Starting prediction scan...")

            survivors = load_overnight_results()
            if survivors:
                universe = [s["symbol"] for s in survivors if "symbol" in s]
                progress.push_log("predictions", f"Using {len(universe)} expanded scanner survivors")
            else:
                progress.track("predictions", total=0, current=0, label="Running quant filter on 2,500+ stocks...")
                progress.push_log("predictions", "No cached results — running quant filter on 2,500+ stocks...")
                scored = run_expanded_pipeline()
                universe = [s["symbol"] for s in scored if "symbol" in s]
                progress.push_log("predictions", f"Quant filter produced {len(universe)} survivors")

            if not universe:
                universe = get_full_universe(include_discovery=True)
                progress.push_log("predictions", f"No survivors — falling back to full universe ({len(universe)})", "warning")

            from config import WATCHLIST
            from stock_universe import get_sp500, get_nasdaq100
            seen = set(universe)
            extras = []
            for s in WATCHLIST + get_sp500() + get_nasdaq100():
                if s not in seen:
                    seen.add(s)
                    extras.append(s)
            if extras:
                universe.extend(extras)
                progress.push_log("predictions", f"Added {len(extras)} large-cap + watchlist stocks to universe")

            funnel = get_funnel_stats()
            progress.track("predictions", total=len(universe), current=0,
                           label=f"AI analyzing {len(universe):,} stocks...")
            predictions = predict_batch(universe,
                                        progress_cb=lambda cur, tot, label="": progress.track("predictions", current=cur, total=tot, label=label or f"AI analyzing {tot:,} stocks..."))

            pred_dicts = [p.to_dict() for p in predictions[:30]]
            shared_state.update(
                predictions=pred_dicts,
                prediction_count=len(predictions),
                scan_universe_size=len(universe),
                scan_funnel=funnel.get("breakdown", {}),
                scan_summary=get_scan_summary(len(universe), len(predictions), min(30, len(predictions))),
            )
            progress.complete("predictions", message=f"{len(predictions)} predictions generated")
        except Exception as exc:
            log.error("[dashboard] Prediction scan failed: %s", exc, exc_info=True)
            progress.fail("predictions", message=str(exc))

    threading.Thread(target=_do, daemon=True, name="prediction-scan").start()
    return jsonify({"ok": True, "message": "Prediction scan started."})


# ── Overnight scanner routes ─────────────────────────────────────────────────

@scanner_bp.route("/api/overnight")
def api_overnight():
    """Return the latest overnight predictions and accuracy stats."""
    from prediction_scanner import get_accuracy_summary
    snap = shared_state.snapshot()
    preds = snap.get("overnight_predictions")
    accuracy = get_accuracy_summary()
    return jsonify({
        "predictions": preds,
        "accuracy": accuracy,
    })


@scanner_bp.route("/api/overnight/run", methods=["POST"])
def api_overnight_run():
    """Trigger an overnight scan manually."""
    def _do():
        try:
            from prediction_scanner import run_overnight_scan
            progress.track("overnight", total=0, current=0, label="Running overnight analysis...")
            result = run_overnight_scan(
                progress_cb=lambda cur, tot, lbl=None: progress.track("overnight", current=cur, total=tot,
                                                                       label=lbl or f"Analyzing stock {cur}/{tot}..."))
            shared_state.update(overnight_predictions=result)
            count = len(result) if isinstance(result, list) else 0
            progress.complete("overnight", message=f"{count} picks for tomorrow")
        except Exception as exc:
            log.error("[dashboard] Overnight scan failed: %s", exc, exc_info=True)
            progress.fail("overnight", message=str(exc))

    threading.Thread(target=_do, daemon=True, name="manual-overnight").start()
    return jsonify({"ok": True, "message": "Overnight scan started."})


@scanner_bp.route("/api/overnight/accuracy")
def api_overnight_accuracy():
    """Check and return prediction accuracy."""
    from prediction_scanner import check_prediction_accuracy
    try:
        result = check_prediction_accuracy()
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)})


# ── Expanded scanner routes ──────────────────────────────────────────────────

@scanner_bp.route("/api/expanded-scan/run", methods=["POST"])
def api_expanded_scan_run():
    """Trigger an expanded scan manually (D-07)."""
    snap = shared_state.snapshot()
    if snap.get("expanded_scan_status") == "running":
        return jsonify({"ok": False, "message": "Scan already running."})

    def _do():
        try:
            from expanded_scanner import trigger_manual_scan
            progress.track("expanded_scan", total=0, current=0, label="Running expanded scan...")
            trigger_manual_scan()
            progress.complete("expanded_scan", message="Expanded scan complete")
        except Exception as exc:
            log.error("[dashboard] Expanded scan failed: %s", exc, exc_info=True)
            progress.fail("expanded_scan", message=str(exc))

    threading.Thread(target=_do, daemon=True, name="manual-expanded-scan").start()
    return jsonify({"ok": True, "message": "Expanded scan started."})


@scanner_bp.route("/api/expanded-scan")
def api_expanded_scan():
    """Return the latest expanded scanner results and funnel stats."""
    snap = shared_state.snapshot()
    return jsonify({
        "results": snap.get("expanded_scan_results", []),
        "scan_time": snap.get("expanded_scan_time"),
        "status": snap.get("expanded_scan_status", "idle"),
        "funnel": snap.get("expanded_scan_funnel", {}),
    })


@scanner_bp.route("/api/expanded-scan/cancel", methods=["POST"])
def api_expanded_scan_cancel():
    """Cancel a running expanded scan."""
    from expanded_scanner import cancel_scan
    cancel_scan()
    progress.fail("expanded_scan", message="Scan cancelled by user")
    return jsonify({"ok": True, "message": "Cancel requested."})


# ── Scan & Intelligence routes ───────────────────────────────────────────────

@scanner_bp.route("/api/scan")
def api_scan():
    """Trigger a one-off watchlist scan in the background. Results arrive via SSE."""
    def _do():
        try:
            from scanner import get_watchlist, scan as run_scan
            wl = get_watchlist()
            progress.track("scan", total=len(wl), current=0, label=f"Scanning {len(wl)} stocks...")
            results = run_scan(wl, progress_cb=lambda cur, tot: progress.track("scan", current=cur, total=tot))
            shared_state.update(
                watchlist=[{k: v for k, v in r.items() if k != "df"} for r in results],
                use_top_movers=config.USE_TOP_MOVERS,
            )
            passed = len([r for r in results if r.get("fired")])
            progress.complete("scan", message=f"{passed} stocks passed filters")
        except Exception as exc:
            log.warning("[dashboard] Background scan error: %s", exc)
            progress.fail("scan", message=str(exc))
    threading.Thread(target=_do, daemon=True, name="dashboard-scan").start()
    return jsonify({"ok": True, "message": "Scan started."})


@scanner_bp.route("/api/intelligence")
def api_intelligence():
    """Return intelligence data: treasury rates, insider trades, SEC filings, market movers."""
    from openbb_intel import get_intelligence_report, check_openbb_status
    try:
        watchlist = list(config.WATCHLIST) if hasattr(config, "WATCHLIST") else []
        # Use top prediction symbols if available
        snap = shared_state.snapshot()
        pred_symbols = [p.get("symbol", "") for p in snap.get("predictions", [])[:20]]
        symbols = list(dict.fromkeys(pred_symbols + watchlist))[:30]
        report = get_intelligence_report(symbols)
        report["openbb_check"] = check_openbb_status()
        return jsonify(report)
    except Exception as exc:
        log.error("[dashboard] Intelligence report failed: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)})


# ── Heatmap routes ───────────────────────────────────────────────────────────

@scanner_bp.route("/api/heatmap/market")
def api_heatmap_market():
    """Return market heatmap data for S&P 500 + NASDAQ 100."""
    snap = shared_state.snapshot()
    cached = snap.get("heatmap_data", [])
    if cached:
        return jsonify(cached)

    # Trigger background fetch if empty
    def _do():
        try:
            from stock_universe import fetch_heatmap_data
            data = fetch_heatmap_data()
            shared_state.update(heatmap_data=data)
        except Exception as exc:
            log.error("[dashboard] Heatmap fetch failed: %s", exc)

    threading.Thread(target=_do, daemon=True, name="heatmap-fetch").start()
    return jsonify([])


@scanner_bp.route("/api/heatmap/positions")
def api_heatmap_positions():
    """Return positions heatmap data (size=value, color=P&L)."""
    from dashboard import _trading_client
    if _trading_client is None:
        return jsonify([])
    try:
        positions = _trading_client.get_all_positions()
        bracket_info = shared_state.snapshot().get("bracket_info", {})
        result = []
        for p in positions:
            qty = float(p.qty)
            if qty <= 0:
                continue
            sym = p.symbol.upper()
            avg_entry = float(p.avg_entry_price)
            current = float(p.current_price)
            market_val = float(p.market_value)
            pnl = float(p.unrealized_pl)
            try:
                pnl_pct = float(p.unrealized_plpc) * 100
            except Exception:
                pnl_pct = ((current - avg_entry) / avg_entry * 100) if avg_entry > 0 else 0.0

            sym_bracket = bracket_info.get(sym, {})
            sl = sym_bracket.get("stop_loss_price",
                    round(avg_entry * (1 - config.TRAILING_STOP_PCT), 2) if avg_entry > 0 else None)
            tp = sym_bracket.get("take_profit_price",
                    round(avg_entry * (1 + config.TAKE_PROFIT_PCT), 2) if avg_entry > 0 else None)

            result.append({
                "symbol": sym,
                "qty": qty,
                "avg_entry": round(avg_entry, 4),
                "current_price": round(current, 4),
                "market_value": round(market_val, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "stop_loss": sl,
                "take_profit": tp,
            })
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)})


# ── Scan logs & prediction log ───────────────────────────────────────────────

@scanner_bp.route("/api/scan-logs", methods=["GET", "DELETE"])
def api_scan_logs():
    """Return or clear the scanner log buffer."""
    if request.method == "DELETE":
        progress.clear_logs()
        return jsonify({"ok": True})
    since = float(request.args.get("since", 0))
    return jsonify(progress.get_logs(since))


@scanner_bp.route("/api/prediction-log/accuracy")
def api_prediction_log_accuracy():
    """Live prediction accuracy from formal tracking system."""
    from prediction_log import get_accuracy, check_outcomes, get_recent_predictions
    try:
        resolved = check_outcomes()
        accuracy = get_accuracy()
        recent = get_recent_predictions(20)
        accuracy["recently_resolved"] = resolved
        accuracy["recent_predictions"] = recent
        return jsonify(accuracy)
    except Exception as exc:
        log.error("[dashboard] Prediction log accuracy failed: %s", exc)
        return jsonify({"error": str(exc)})
