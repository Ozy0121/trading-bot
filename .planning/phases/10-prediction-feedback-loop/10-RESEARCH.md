# Phase 10: Prediction Feedback Loop - Research

**Researched:** 2026-05-25
**Domain:** Signal accuracy tracking, adaptive weight recalibration, prediction outcome monitoring, dashboard stats display
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Win = stock reaches predicted target price within 3 days. Binary pass/fail.
- **D-02:** Outcome tracker records: target hit (yes/no), actual max price reached, actual close price on day 3, which primary/confirmation signals were active.
- **D-03:** Outcome checking runs at 9:35 AM ET daily alongside existing accuracy check. Predictions checked daily until target hit or 3-day expiry.
- **D-04:** Weekly recalibration runs Sunday at midnight ET (before Monday open).
- **D-05:** Recalibration uses last 30 days of resolved predictions; minimum 20 required — skip if fewer.
- **D-06:** Per-signal accuracy: for each signal (rsi2, ibs, consec_down, bb_lower, volume_profile, order_flow, amt_state, volume_spike) compute total predictions where signal was active, wins where signal was active, signal-specific accuracy %.
- **D-07:** New weights proportional to signal accuracy. Clamped to [1.0, 6.0]. No single signal dominates or zeroes out.
- **D-08:** Updated weights saved to a config file. `prediction.py` reads from file at startup, falls back to hardcoded defaults if file missing.
- **D-09:** Recalibration logs: "Weekly recalibration: RSI(2) weight 4.0->4.6, consec_down 3.0->2.1". Dashboard shows last recalibration timestamp.
- **D-10:** Always-visible accuracy banner: "Last 50 predictions: 34 correct (68%)" — updates on resolution.
- **D-11:** Full stats section (collapsible or dedicated area): per-signal accuracy table, accuracy trend over time, best/worst performing signals, calibrated weights vs defaults.
- **D-12:** Stats section includes "last recalibrated" timestamp and what changed.

### Claude's Discretion

- **Storage format:** JSON files in `data/` preferred (matches existing codebase pattern). Use SQLite only if there is a strong reason.
- **Accuracy trend visualization:** Chart type for accuracy over time is Claude's call (line chart, sparkline, etc.).
- **Minimum sample sizes:** Claude decides minimum samples per signal before including in recalibration.

### Deferred Ideas (OUT OF SCOPE)

- Level 2 auto-enable/disable of signals based on accuracy thresholds
- Level 3 autonomous strategy evolution with hypothesis generation
- Backtest integration where run_backtest results auto-update weights (kept as optional add-on if scope stays tight)

</user_constraints>

---

## Summary

Phase 10 closes the prediction feedback loop: every prediction is tracked to resolution, per-signal accuracy is maintained, and signal weights auto-recalibrate weekly based on what actually worked. The result is a prediction engine that improves over time without manual tuning.

The codebase already has strong scaffolding. `prediction_log.py` logs predictions to `data/prediction_history.json` and resolves outcomes via `check_outcomes()`. `prediction_scanner.py` already runs a scheduler at 9:35 AM ET and 4:05 PM ET. `prediction.py` has `PRIMARY_WEIGHTS` and `CONFIRM_BONUS` dicts at lines 63-74 that are currently hardcoded. The gap is: (1) per-signal breakdown not stored when a prediction is logged, (2) no weekly recalibration scheduler, (3) no calibrated weights config file, and (4) no signal-level accuracy stats surface in the dashboard.

**Primary recommendation:** Extend `prediction_log.py` to store active signals per prediction at log time. Add a `signal_calibration.py` module for recalibration logic and a `data/signal_weights.json` file for persistence. Wire the Sunday midnight scheduler into the existing `prediction_scanner.py` scheduler loop. Add three new API routes and update the dashboard accuracy section.

---

## Standard Stack

No new packages required. All needed tools are already in the project.

### Core (existing, verified in codebase)
| Library | Purpose | Used In |
|---------|---------|---------|
| `json` | Persist signal accuracy stats and calibrated weights | All data files in `data/` |
| `threading` | Background daemon for recalibration scheduler | `prediction_scanner.py` scheduler pattern |
| `pytz` | Timezone-aware scheduling (Sunday midnight ET) | `prediction_scanner.py` `_schedule_loop()` |
| `datetime` | Timestamp comparison, day-of-week checks | Throughout |
| `dataclasses` | `PredictionRecord` in `prediction_log.py` | `prediction_log.py` |
| Chart.js 4.4.0 | Line chart for accuracy trend sparkline | Already loaded in `index.html` |

[VERIFIED: codebase grep] — all imports confirmed present in working files.

### New Files to Create
| File | Purpose |
|------|---------|
| `data/signal_weights.json` | Calibrated weights saved by recalibration, read by `prediction.py` |
| `data/signal_accuracy_stats.json` | Per-signal accuracy stats (sample counts, win rates) |
| `signal_calibration.py` | Recalibration logic: compute per-signal accuracy, update weights, log changes |

---

## Architecture Patterns

### Recommended File Layout (new additions only)
```
trading-bot/
├── signal_calibration.py          # New: recalibration engine
├── data/
│   ├── signal_weights.json        # New: calibrated weights output
│   ├── signal_accuracy_stats.json # New: per-signal accuracy data
│   └── prediction_history.json    # Existing: extend with active_signals field
├── prediction_log.py              # Extend: store active_signals at log time
├── prediction.py                  # Extend: load weights from file at startup
├── prediction_scanner.py          # Extend: add Sunday recalibration to scheduler
├── routes/scanner.py              # Extend: 3 new API endpoints
└── templates/index.html           # Extend: accuracy banner + stats section
```

### Pattern 1: Storing Active Signals at Prediction Log Time

The most critical fix. `PredictionRecord` currently has no `active_signals` field. When `log_prediction()` is called, the caller must pass which signals fired. The `reasons` list is text and is not machine-parseable.

**What to add to `PredictionRecord`:**
```python
# prediction_log.py — add to PredictionRecord dataclass
active_signals: list[str] = field(default_factory=list)
# e.g. ["rsi2", "ibs", "consec_down", "bb_lower", "volume_profile"]
```

**What to add to `log_prediction()` signature:**
```python
def log_prediction(
    symbol: str,
    direction: str,
    predicted_move_pct: float,
    timeframe_days: int,
    confidence: int,
    reasons: list[str],
    source: str,
    entry_price: float = 0.0,
    active_signals: list[str] | None = None,   # NEW
) -> PredictionRecord:
```

**Where `log_prediction` is called** — verified in codebase:
- `bot.py` calls it when executing a trade (search for `log_prediction`)
- `prediction.py` calls `log_prediction` after scoring (verified lines 681-690 region)

The caller already knows which `PatternResult.detected == True` at scoring time (lines 597-614 of `prediction.py`). Pass the list of detected signal names when calling `log_prediction`.

[VERIFIED: codebase read] — `PredictionRecord` defined in `prediction_log.py` lines 34-56, `log_prediction` defined lines 75-114.

### Pattern 2: Calibrated Weights Config File

`prediction.py` currently uses module-level dicts `PRIMARY_WEIGHTS` (line 63) and `CONFIRM_BONUS` (line 70). These need to be loaded from file at startup, with fallback to hardcoded defaults.

```python
# signal_weights.json schema
{
  "version": 1,
  "generated_at": "2026-05-25T00:00:00Z",
  "recalibration_date": "2026-05-25",
  "changes": [
    {"signal": "rsi2", "old_weight": 4.0, "new_weight": 4.6},
    {"signal": "consec_down", "old_weight": 3.0, "new_weight": 2.1}
  ],
  "primary_weights": {
    "rsi2": 4.6,
    "ibs": 3.5,
    "consec_down": 2.1,
    "bb_lower": 3.5
  },
  "confirm_bonus": {
    "volume_profile": 1.5,
    "order_flow": 1.0,
    "amt_state": 1.0,
    "volume_spike": 1.5
  }
}
```

**Loading pattern in `prediction.py`:**
```python
# At module level, after hardcoded DEFAULT_PRIMARY_WEIGHTS / DEFAULT_CONFIRM_BONUS
import os as _os, json as _json

_WEIGHTS_FILE = _os.path.join(_os.path.dirname(__file__), "data", "signal_weights.json")

def _load_weights() -> tuple[dict, dict]:
    try:
        with open(_WEIGHTS_FILE) as f:
            w = _json.load(f)
        return w["primary_weights"], w["confirm_bonus"]
    except (FileNotFoundError, KeyError, _json.JSONDecodeError):
        return dict(DEFAULT_PRIMARY_WEIGHTS), dict(DEFAULT_CONFIRM_BONUS)

PRIMARY_WEIGHTS, CONFIRM_BONUS = _load_weights()
```

[ASSUMED] — The specific loading location (module-level vs. per-call) is a design choice. Module-level loading means weights are fixed until restart. Per-call loading allows weights to update live. Recommendation: module-level is fine because the bot restarts daily; recalibration runs Sunday midnight before Monday open.

### Pattern 3: Signal Accuracy Stats Storage

`data/signal_accuracy_stats.json` is the source of truth for per-signal accuracy. It is rebuilt from `prediction_history.json` every recalibration run.

```python
# signal_accuracy_stats.json schema
{
  "computed_at": "2026-05-25T00:00:00Z",
  "window_days": 30,
  "total_resolved_in_window": 47,
  "signals": {
    "rsi2": {
      "total_predictions": 45,
      "wins": 34,
      "accuracy_pct": 75.6,
      "sample_count": 45
    },
    "ibs": {
      "total_predictions": 38,
      "wins": 26,
      "accuracy_pct": 68.4,
      "sample_count": 38
    },
    "consec_down": {...},
    "bb_lower": {...},
    "volume_profile": {...},
    "order_flow": {...},
    "amt_state": {...},
    "volume_spike": {...}
  }
}
```

### Pattern 4: Recalibration Weight Formula

Decision D-07 specifies weights proportional to accuracy, clamped to [1.0, 6.0]. Recommended formula:

```python
# signal_calibration.py
DEFAULT_PRIMARY_WEIGHTS = {"rsi2": 4.0, "ibs": 3.5, "consec_down": 3.0, "bb_lower": 3.5}
DEFAULT_CONFIRM_BONUS   = {"volume_profile": 1.5, "order_flow": 1.0, "amt_state": 1.0, "volume_spike": 1.5}
MIN_SAMPLES_PER_SIGNAL  = 10   # see discretion note below

def _compute_new_weight(
    accuracy_pct: float,
    current_weight: float,
    default_weight: float,
    clamp_min: float = 1.0,
    clamp_max: float = 6.0,
) -> float:
    """
    Scale default_weight proportionally to accuracy.
    Baseline accuracy = 50% (random) → weight unchanged.
    Accuracy 75% → weight *= 1.5. Accuracy 25% → weight *= 0.5.
    """
    ratio = accuracy_pct / 50.0          # 1.0 at 50%, 1.5 at 75%, 0.5 at 25%
    new_weight = default_weight * ratio
    return round(max(clamp_min, min(clamp_max, new_weight)), 2)
```

[ASSUMED] — The specific scaling formula (linear from 50% baseline) is a reasonable default. If user sees unexpected behavior, the formula is easy to tune in one place.

### Pattern 5: Sunday Midnight Scheduler Hook

The existing `_schedule_loop()` in `prediction_scanner.py` (lines 459-521) already uses `pytz` and `time.sleep(60)` polling. Adding Sunday midnight recalibration follows the same pattern:

```python
# Add to _schedule_loop() alongside existing accuracy_time / scan_time checks
from datetime import time as dtime

recalib_time = dtime(0, 0)   # midnight ET
last_recalib_date = None

# Inside the while True loop:
is_sunday = now_et.weekday() == 6
if is_sunday and current_time >= recalib_time and last_recalib_date != today:
    log.info("[overnight] Running weekly signal recalibration...")
    try:
        from signal_calibration import run_recalibration
        result = run_recalibration()
        last_recalib_date = today
        import state as shared_state
        shared_state.update(last_recalibration=result)
    except Exception as exc:
        log.error("[overnight] Recalibration failed: %s", exc)
```

[VERIFIED: codebase read] — `_schedule_loop` exists at `prediction_scanner.py:459`, uses `pytz` and `dtime`. Pattern is correct.

### Pattern 6: New API Routes

Three new routes in `routes/scanner.py`:

```python
@scanner_bp.route("/api/prediction-log/signal-accuracy")
def api_signal_accuracy():
    """Return per-signal accuracy stats."""

@scanner_bp.route("/api/prediction-log/signal-weights")
def api_signal_weights():
    """Return current calibrated weights vs defaults."""

@scanner_bp.route("/api/prediction-log/recalibrate", methods=["POST"])
def api_trigger_recalibration():
    """Manually trigger a recalibration run (for testing)."""
```

### Dashboard Accuracy Banner Pattern

The existing `#sc-accuracy` element in the prediction section (line 1558 of `index.html`) shows overall accuracy. The banner text per D-10 is:

```
"Last 50 predictions: 34 correct (68%)"
```

This extends the existing scorecard UI at lines 1544-1576 rather than replacing it.

The per-signal table (D-11) renders as a `<table>` inside the existing collapsible stats section.

### Anti-Patterns to Avoid

- **Rebuilding signal stats from text reasons:** The `reasons` field in `PredictionRecord` is human-readable text (`"RSI(2) oversold at 1.6"`). Do NOT try to parse it to extract signal names — store `active_signals` as a machine-readable list at log time.
- **Reloading weights mid-session:** Loading `signal_weights.json` once at module import is correct. Reloading on every `predict()` call adds file I/O to the hot path for no benefit (recalibration only matters before Monday open).
- **Recalibrating with < 20 predictions:** D-05 requires minimum 20 resolved predictions in window. Skip recalibration and log a warning if the threshold is not met. Do not silently apply weights from an insufficient sample.
- **Weight swings from single-signal dominance:** The [1.0, 6.0] clamp in D-07 prevents zeroing out or over-weighting. Never remove the clamp.
- **Blocking the scheduler thread on recalibration:** Recalibration is a file read + write + computation, typically < 1 second. It's safe to run inline in the scheduler thread since it runs only once per week. No need for a sub-thread.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Timezone-aware scheduling | Custom clock logic | `pytz` already imported in scheduler | DST-safe, already proven in `_schedule_loop()` |
| JSON file locking | Custom file lock | `threading.Lock()` pattern from `prediction_log.py:_log_lock` | Already established, thread-safe |
| Chart rendering | Custom canvas drawing | Chart.js 4.4.0 already loaded in `index.html` | Line chart for accuracy trend takes 10 lines of JS |
| Accuracy formula | Complex Bayesian scoring | Simple ratio (wins / predictions) | Simpler is more interpretable; bot is small-sample |

---

## Common Pitfalls

### Pitfall 1: Missing `active_signals` in Existing Records

**What goes wrong:** `prediction_history.json` already has 316 records (315 pending, 1 resolved) but none have an `active_signals` field. When recalibration runs for the first time, there are no per-signal data points to work from.

**Why it happens:** The field doesn't exist yet. Old records can't be retroactively tagged because the information isn't in `reasons` in parseable form.

**How to avoid:** Recalibration must silently skip records with no `active_signals`. The 30-day rolling window means this is self-healing — within 30 days of deployment, old records roll off. For the 315 pending records that will resolve after deployment, the caller of `log_prediction` must pass `active_signals` going forward.

**Warning signs:** `signal_accuracy_stats.json` shows 0 samples for all signals after first recalibration. That's normal if all resolved predictions are pre-deployment records. Check that new predictions have `active_signals` populated.

### Pitfall 2: `log_prediction` Caller Doesn't Pass `active_signals`

**What goes wrong:** `prediction.py` generates signals in the `predict()` function (lines 526-614), but the `log_prediction()` call happens outside that scope. If the caller doesn't propagate the signal list, `active_signals` will always be empty.

**Why it happens:** `log_prediction` is called by `bot.py` at trade time (when auto-trade fires a buy), not by `predict()` itself. `bot.py` may not have access to the `PatternResult` objects.

**How to avoid:** One of:
1. Have `predict()` call `log_prediction()` internally and pass its own `[p.name for p in primaries + confirms if p.detected]` list.
2. Return `active_signals` as part of `Prediction.to_dict()` and have `bot.py` forward it.

Option 1 is cleaner — `predict()` already knows which signals fired (lines 597-614).

**Warning signs:** `active_signals` is `[]` on all new records in `prediction_history.json`.

### Pitfall 3: Signal Name Mismatch Between `prediction.py` and Recalibration

**What goes wrong:** `PRIMARY_WEIGHTS` keys are `"rsi2"`, `"ibs"`, `"consec_down"`, `"bb_lower"`. `CONFIRM_BONUS` keys are `"volume_profile"`, `"order_flow"`, `"amt_state"`, `"volume_spike"`. If `active_signals` stores names that don't exactly match these keys, recalibration will silently produce 0-sample stats for all signals.

**How to avoid:** Use the `PatternResult.name` field directly from each detector (`_detect_rsi2` returns `PatternResult("rsi2", ...)`, etc.). These are the ground-truth names. Do not rename during storage.

**Warning signs:** Signal accuracy stats show 0 samples for signals you know fired.

### Pitfall 4: Only 1 Resolved Record in the Existing Log

**What goes wrong:** The current `prediction_history.json` has 316 records but only 1 is resolved. All 315 others have `outcome: "pending"` with `timeframe_days: 1` and timestamps from May 8 and May 22 — they are well past their resolution window but `check_outcomes()` hasn't run to resolve them.

**Why it happens:** `check_outcomes()` only runs when the API endpoint `/api/prediction-log/accuracy` is hit. The daily 9:35 AM scheduler calls `check_prediction_accuracy()` (the `prediction_scanner.py` version, which operates on `overnight_predictions.json`), not `prediction_log.check_outcomes()` (which operates on `prediction_history.json`). These are two separate tracking systems.

**How to avoid:** Wave 0 or Wave 1 of the plan must wire `check_outcomes()` from `prediction_log.py` into the daily 9:35 AM scheduler so stale pending records get resolved automatically. Currently only the manual API call triggers it.

**Warning signs:** Hundreds of records stuck at `"outcome": "pending"` after 3+ days.

### Pitfall 5: Two Parallel Accuracy Tracking Systems

**What goes wrong:** There are currently two separate tracking systems:
1. `prediction_log.py` + `data/prediction_history.json` — formal, individual records, per-symbol accuracy
2. `prediction_scanner.py` + `data/prediction_accuracy.json` — batch, overnight-only, cumulative

They track different populations of predictions (mean-reversion `log_prediction` vs. overnight scanner batch). The dashboard shows both. Recalibration should be based on `prediction_history.json` (system 1) since it has per-signal signal data. Don't confuse the two.

**How to avoid:** `signal_calibration.py` reads exclusively from `data/prediction_history.json`. The dashboard banner (D-10) should pull from the `prediction_log.get_accuracy()` function, not from the overnight scanner cumulative.

### Pitfall 6: Recalibration Date Tracking on Restart

**What goes wrong:** The scheduler uses `last_recalib_date = None` as a local variable. If the bot restarts on Sunday, `last_recalib_date` resets to `None` and recalibration runs again on the next loop iteration.

**How to avoid:** Store `recalibration_date` inside `signal_weights.json` (already in the schema above). On scheduler startup, check if `signal_weights.json` has today as the recalibration date and skip if so.

---

## Code Examples

### Detecting Active Signals in `predict()` (verified pattern)

```python
# From prediction.py lines 597-614 — signals are already computed here
# Source: codebase read, prediction.py:596-615
primaries = [rsi2_result, ibs_result, consec_result, bb_result]
confirms  = [vp_result, cvd_result, amt_result, vol_spike_result]

active_signals = (
    [p.name for p in primaries if p.detected] +
    [c.name for c in confirms  if c.detected]
)
# e.g. ["rsi2", "ibs", "bb_lower", "volume_profile"]
```

### Recalibration Core Logic

```python
# signal_calibration.py — core recalibration function
# Source: pattern derived from codebase analysis [ASSUMED formula, VERIFIED structure]

import json, os
from datetime import datetime, timezone, timedelta

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
HISTORY_FILE = os.path.join(DATA_DIR, "prediction_history.json")
STATS_FILE   = os.path.join(DATA_DIR, "signal_accuracy_stats.json")
WEIGHTS_FILE = os.path.join(DATA_DIR, "signal_weights.json")

DEFAULT_PRIMARY  = {"rsi2": 4.0, "ibs": 3.5, "consec_down": 3.0, "bb_lower": 3.5}
DEFAULT_CONFIRM  = {"volume_profile": 1.5, "order_flow": 1.0, "amt_state": 1.0, "volume_spike": 1.5}
MIN_SAMPLES      = 10    # minimum per-signal samples before including in recalibration
WINDOW_DAYS      = 30
MIN_PREDICTIONS  = 20    # D-05: skip recalibration if fewer resolved


def run_recalibration() -> dict:
    """Compute per-signal accuracy and update signal_weights.json."""
    records = json.load(open(HISTORY_FILE)) if os.path.exists(HISTORY_FILE) else []

    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    resolved = [
        r for r in records
        if r.get("outcome") in ("correct", "incorrect")
        and r.get("active_signals")
        and datetime.fromisoformat(r["timestamp"]) >= cutoff
    ]

    if len(resolved) < MIN_PREDICTIONS:
        return {"skipped": True, "reason": f"Only {len(resolved)} resolved predictions (need {MIN_PREDICTIONS})"}

    # Compute per-signal stats
    stats = {}
    for sig in list(DEFAULT_PRIMARY) + list(DEFAULT_CONFIRM):
        active = [r for r in resolved if sig in r.get("active_signals", [])]
        wins   = [r for r in active   if r["outcome"] == "correct"]
        acc    = round(len(wins) / len(active) * 100, 1) if active else None
        stats[sig] = {"total_predictions": len(active), "wins": len(wins), "accuracy_pct": acc}

    # Compute new weights
    new_primary = {}
    for sig, default_w in DEFAULT_PRIMARY.items():
        sig_stats = stats[sig]
        if sig_stats["total_predictions"] < MIN_SAMPLES or sig_stats["accuracy_pct"] is None:
            new_primary[sig] = default_w
        else:
            ratio = sig_stats["accuracy_pct"] / 50.0
            new_primary[sig] = round(max(1.0, min(6.0, default_w * ratio)), 2)

    new_confirm = {}
    for sig, default_w in DEFAULT_CONFIRM.items():
        sig_stats = stats[sig]
        if sig_stats["total_predictions"] < MIN_SAMPLES or sig_stats["accuracy_pct"] is None:
            new_confirm[sig] = default_w
        else:
            ratio = sig_stats["accuracy_pct"] / 50.0
            new_confirm[sig] = round(max(1.0, min(6.0, default_w * ratio)), 2)

    # Load current weights to compute diffs
    try:
        current = json.load(open(WEIGHTS_FILE))
        cur_primary = current.get("primary_weights", DEFAULT_PRIMARY)
        cur_confirm = current.get("confirm_bonus", DEFAULT_CONFIRM)
    except (FileNotFoundError, json.JSONDecodeError):
        cur_primary, cur_confirm = DEFAULT_PRIMARY, DEFAULT_CONFIRM

    changes = []
    for sig in list(DEFAULT_PRIMARY) + list(DEFAULT_CONFIRM):
        old = {**cur_primary, **cur_confirm}.get(sig)
        new = {**new_primary, **new_confirm}.get(sig)
        if old is not None and new is not None and abs(old - new) >= 0.05:
            changes.append({"signal": sig, "old_weight": old, "new_weight": new})

    result = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recalibration_date": datetime.now(timezone.utc).date().isoformat(),
        "window_days": WINDOW_DAYS,
        "resolved_predictions_used": len(resolved),
        "changes": changes,
        "primary_weights": new_primary,
        "confirm_bonus": new_confirm,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(WEIGHTS_FILE, "w") as f:
        json.dump(result, f, indent=2)
    with open(STATS_FILE, "w") as f:
        json.dump({"computed_at": result["generated_at"], "signals": stats}, f, indent=2)

    return result
```

### Dashboard Accuracy Banner (JS pattern)

```javascript
// Extends existing checkLiveAccuracy() in index.html
// Source: existing pattern at index.html:3751 [VERIFIED]
async function loadAccuracyBanner() {
    const res = await fetch('/api/prediction-log/accuracy');
    const data = await res.json();
    const n = data.last_30_count || data.resolved || 0;
    const correct = data.correct || 0;
    const pct = data.accuracy_pct || 0;
    $('accuracy-banner').textContent = `Last ${n} predictions: ${correct} correct (${pct}%)`;
}
```

---

## Data Flow

```
predict() in prediction.py
    → PatternResult objects for each signal
    → active_signals = [p.name for p in primaries+confirms if p.detected]
    → log_prediction(..., active_signals=active_signals) in prediction_log.py
    → PredictionRecord saved with active_signals to prediction_history.json

Daily at 9:35 AM ET (prediction_scanner.py scheduler)
    → check_outcomes() from prediction_log.py
    → Resolves expired predictions: sets outcome="correct"/"incorrect"
    → Updates prediction_history.json

Sunday midnight ET (prediction_scanner.py scheduler — new hook)
    → run_recalibration() from signal_calibration.py
    → Reads last 30 days of resolved records from prediction_history.json
    → Computes per-signal accuracy
    → Writes signal_accuracy_stats.json
    → Writes signal_weights.json
    → Logs weight changes
    → Updates shared_state(last_recalibration=...)

prediction.py at module import (or bot restart)
    → _load_weights() reads signal_weights.json
    → PRIMARY_WEIGHTS, CONFIRM_BONUS populated from file
    → Falls back to hardcoded defaults if file missing
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcoded fixed weights in prediction.py | Calibrated weights from `signal_weights.json` | Phase 10 | Weights improve weekly based on actual win rates |
| No per-signal tracking | `active_signals` field on every prediction | Phase 10 | Enables per-signal accuracy attribution |
| Manual weight tuning (quick task 260426-kqf) | Auto-recalibration every Sunday | Phase 10 | Removes manual intervention from weight maintenance |
| Two disconnected outcome trackers | Both run on schedule, banner shows prediction_log system | Phase 10 | Single authoritative source for dashboard accuracy |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Weight scaling formula: `default_weight * (accuracy_pct / 50.0)` is a linear ratio from 50% baseline | Code Examples — recalibration | Weights could swing too aggressively or too slowly. Mitigated by [1.0, 6.0] clamp. |
| A2 | Module-level weight loading (once at import) is sufficient — no need for per-call reload | Architecture Pattern 2 | Weights updated on Sunday would not take effect until bot restarts. If bot runs 24/7 without restart, weights won't update until next restart. Add a weekly reload hook if needed. |
| A3 | `predict()` is the right place to call `log_prediction()` (versus `bot.py` at trade time) | Pitfall 2 | If `predict()` calls `log_prediction()`, every scan result gets logged, not just trades. This is by design (we want to track all predictions, not just executed ones). Verify with user if scan-only predictions (no trade taken) should be tracked. |
| A4 | Minimum 10 samples per signal before including in recalibration is appropriate | Code Examples | Too low: noisy weights from small samples. Too high: signals that fire rarely (amt_state, volume_spike) never get recalibrated. 10 is conservative. |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.

---

## Open Questions

1. **Should `log_prediction` be called from `predict()` for all scan results, or only when a trade is actually executed?**
   - What we know: Currently `log_prediction` is called by `bot.py` (auto-trade path) and the existing `/api/prediction-log/accuracy` endpoint surfaces 316 logged records.
   - What's unclear: Whether those 316 records are scan-only predictions or trade-executed predictions.
   - Recommendation: Call `log_prediction` from inside `predict()` for every stock that passes `MIN_CONFIDENCE`, not just trades. This gives more signal data. The `source` field distinguishes trade-executed from scan-only if needed.

2. **How should the accuracy banner handle "Last 50 predictions" when only 8 are resolved?**
   - What we know: D-10 says "Last 50 predictions: 34 correct (68%)". With 315 pending records, there's currently 1 resolved.
   - What's unclear: Should the banner show total predictions in window or resolved-only count?
   - Recommendation: Show resolved count only — "Last N resolved predictions: X correct (Y%)". A 0/315 banner would look broken. After `check_outcomes()` runs against the existing 315 pending records, most should resolve quickly (they're past their 3-day window).

3. **Do the 315 pending records with `timeframe_days: 1` need to be bulk-resolved on deploy?**
   - What we know: Records from May 8 and May 22 all have `outcome: "pending"` and `timeframe_days: 1`. These are well past their 3-day window. `check_outcomes()` will resolve them on the next manual call or the next day's scheduled check.
   - Recommendation: Wave 0 should include a manual `check_outcomes()` call on deploy to flush the backlog. Otherwise the first recalibration will have no data from these old records (they lack `active_signals` anyway).

---

## Environment Availability

Step 2.6: All dependencies verified present in the working environment.

| Dependency | Required By | Available | Notes |
|------------|------------|-----------|-------|
| `pytz` | Sunday scheduler | Yes | Used in existing `_schedule_loop()` |
| `json` (stdlib) | All data files | Yes | Standard library |
| `threading` (stdlib) | Scheduler thread | Yes | Already used throughout |
| `data/` directory | Calibrated weights files | Yes | Exists, contains prediction_history.json |
| Chart.js 4.4.0 | Accuracy trend chart | Yes | CDN-loaded in index.html line 7 |

No missing dependencies. No install steps required.

---

## Validation Architecture

No formal test framework is configured in this project (no pytest.ini, no test runner in the scheduler, tests exist in `tests/` but run manually). Following project convention:

### Phase Requirements Test Map

| Behavior | Test Type | How to Verify |
|----------|-----------|---------------|
| `active_signals` stored on new predictions | Manual | Log a prediction, check `prediction_history.json` for `active_signals` field |
| `check_outcomes()` resolves pending records | Manual | Call `/api/prediction-log/accuracy`, confirm pending count drops |
| `signal_weights.json` created on recalibration | Manual | Trigger `POST /api/prediction-log/recalibrate`, check file exists in `data/` |
| Weight clamp enforced [1.0, 6.0] | Unit | Test `_compute_new_weight()` with 0%, 50%, 100% accuracy inputs |
| Recalibration skips if < 20 resolved | Unit | Test `run_recalibration()` with 15-record fixture, assert `skipped: True` |
| `prediction.py` loads from file at startup | Integration | Delete `signal_weights.json`, restart bot, confirm fallback to defaults |
| Accuracy banner renders in dashboard | Manual | Open dashboard, verify banner text matches `get_accuracy()` response |
| Sunday scheduler triggers recalibration | Manual | Trigger manually via API, verify log line and `signal_weights.json` updated |

### Wave 0 Gaps

- [ ] `tests/test_signal_calibration.py` — unit tests for recalibration logic (clamp, skip threshold, formula)
- No framework install needed — project uses standard Python and manual testing

---

## Security Domain

This phase adds no authentication surfaces, external API calls, or user-supplied inputs to backend processing. All data flows are internal (JSON file reads/writes, scheduled tasks, dashboard display). No ASVS categories apply beyond existing baseline.

The calibrated weights file (`signal_weights.json`) is written by the backend scheduler. It is not user-controllable via the dashboard. No injection risk.

---

## Sources

### Primary (HIGH confidence)
- Codebase: `prediction_log.py` — full read, verified `PredictionRecord` fields, `log_prediction` signature, `check_outcomes` logic
- Codebase: `prediction.py` lines 63-75, 596-615 — verified `PRIMARY_WEIGHTS`, `CONFIRM_BONUS`, signal detection and scoring loop
- Codebase: `prediction_scanner.py` lines 459-521 — verified `_schedule_loop()` pattern, `pytz` usage, 9:35 AM ET accuracy check
- Codebase: `data/prediction_history.json` — verified 316 records, 315 pending, 1 resolved, no `active_signals` field
- Codebase: `routes/scanner.py` — verified existing `/api/prediction-log/accuracy` endpoint, blueprint pattern
- Codebase: `templates/index.html` — verified Chart.js 4.4.0 loaded, existing accuracy scorecard at lines 1544-1576

### Secondary (MEDIUM confidence)
- `data/prediction_accuracy.json` — verified two-system structure (overnight scanner vs prediction_log)
- `data/pattern_backtest_results.json` — verified existing backtest data format (not consumed by this phase per deferred scope)

### Tertiary (LOW confidence)
- Weight formula (linear ratio from 50% baseline) — [ASSUMED], no academic citation. Standard approach for simple accuracy-based scaling.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified in codebase
- Architecture: HIGH — patterns verified against actual code; two [ASSUMED] items flagged
- Pitfalls: HIGH — discovered by direct inspection of data files and code (not from training assumptions)
- Recalibration formula: MEDIUM — formula is reasonable but untested against actual signal distributions

**Research date:** 2026-05-25
**Valid until:** 2026-08-25 (stable domain; no external dependencies)
