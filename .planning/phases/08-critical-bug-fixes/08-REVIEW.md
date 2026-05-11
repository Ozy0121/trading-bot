---
phase: 08-critical-bug-fixes
reviewed: 2026-05-10T12:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - prediction.py
  - prediction_log.py
  - dashboard.py
  - stream.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 08: Code Review Report

**Reviewed:** 2026-05-10T12:00:00Z
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Reviewed prediction.py, prediction_log.py, dashboard.py, and stream.py after Phase 08 critical bug fixes. The fixes for CVD/AMT veto logic, stream backoff reset, and hardcoded accuracy appear to have landed correctly. However, one critical issue remains: `prediction.py` imports a function (`get_symbol_accuracy`) from `prediction_log.py` that does not exist in that module, which will cause an `ImportError` at runtime every time a prediction is generated. Additionally, there are thread-safety gaps in `prediction_log.py` and minor code quality issues in `dashboard.py`.

## Critical Issues

### CR-01: Missing function `get_symbol_accuracy` causes silent fallback on every prediction

**File:** `prediction.py:683-689`
**Issue:** Lines 683-684 import `get_symbol_accuracy` from `prediction_log`, but this function is not defined anywhere in the codebase. The broad `except Exception` on line 687 silently catches the `ImportError`, causing every prediction to fall back to `historical_accuracy=0.0` and `historical_samples=0`. This defeats the purpose of the Phase 08 fix that replaced hardcoded accuracy with live tracking. The prediction accuracy display and risk-reward EV calculations all use fabricated data.
**Fix:** Add `get_symbol_accuracy` to `prediction_log.py`:
```python
def get_symbol_accuracy(symbol: str, window: int = 50) -> dict:
    """Get accuracy stats for a specific symbol."""
    records = _load_records()
    resolved = [r for r in records
                if r["outcome"] in ("correct", "incorrect")
                and r["symbol"] == symbol]
    if not resolved:
        return {"accuracy": 0.0, "samples": 0}
    recent = resolved[-window:]
    correct = sum(1 for r in recent if r["outcome"] == "correct")
    return {
        "accuracy": round(correct / len(recent), 3),
        "samples": len(recent),
    }
```

## Warnings

### WR-01: TOCTOU race in `log_prediction` — load and save not atomic

**File:** `prediction_log.py:86-113`
**Issue:** `log_prediction` calls `_load_records()` (which acquires and releases the lock), then appends to the list, then calls `_save_records()` (which acquires and releases the lock again). If two threads call `log_prediction` concurrently, both could load the same records, both append, and one write overwrites the other — losing a prediction record. The `predict_batch` function uses `ThreadPoolExecutor` with 8 workers, and `_log_predictions` is called from the same context, so concurrent access is plausible.
**Fix:** Make the entire load-modify-save sequence atomic:
```python
def log_prediction(...) -> PredictionRecord:
    with _log_lock:
        records = _load_records_unlocked()
        pid = _next_id(records)
        # ... build record ...
        records.append(asdict(record))
        _save_records_unlocked(records)
    return record
```
Or refactor `_load_records`/`_save_records` to accept an `already_locked` parameter.

### WR-02: Same TOCTOU race in `check_outcomes`

**File:** `prediction_log.py:117-170`
**Issue:** `check_outcomes` loads records (line 119), mutates them in a loop (lines 151-158), then saves (line 168). If `log_prediction` runs concurrently between the load and save, the new prediction is lost. This function is called from the dashboard endpoint `/api/prediction-log/accuracy` (dashboard.py:806) which runs in Flask's threaded request handler.
**Fix:** Same as WR-01 — wrap the entire load-mutate-save cycle in a single `_log_lock` acquisition.

### WR-03: Unused variable `distance_below` in `_detect_bb_touch`

**File:** `prediction.py:256`
**Issue:** `distance_below` is computed but only used in the return dict's `distance_pct` detail field. However, the variable is computed *before* the `detected` and `score` logic, and the scoring logic on lines 259-266 re-derives the distance inline rather than using `distance_below`. This is not a bug per se, but the score computation on line 266 uses `(current_price - lower_val) / bb_width` which is the *inverse sign* of `distance_below` (which is `(lower_val - current_price) / bb_width`). This inconsistency makes the code harder to maintain and could introduce bugs if someone refactors using `distance_below` in the scoring path.
**Fix:** Use `distance_below` consistently or rename for clarity. The scoring path should reference the same computed value.

## Info

### IN-01: Broad `except Exception` hides import failures

**File:** `prediction.py:687`
**Issue:** The `except Exception` on line 687 silently swallows `ImportError`, `KeyError`, `TypeError`, and any other failure from the accuracy lookup. This is what makes CR-01 silent rather than loud. While the project convention allows broad exception handling with fallbacks, this specific case hides a missing function definition — a development-time bug that should fail loudly.
**Fix:** At minimum, log the exception:
```python
except Exception as exc:
    log.debug("[prediction] Failed to get symbol accuracy for %s: %s", symbol, exc)
    historical_accuracy = 0.0
    historical_samples = 0
```

### IN-02: `_hist_cache` and `_hist_lock` are defined but never used

**File:** `prediction.py:110-111`
**Issue:** `_hist_cache` and `_hist_lock` are module-level variables that are never referenced anywhere in the file. They appear to be remnants of a removed historical lookup feature.
**Fix:** Remove both lines to reduce dead code.

---

_Reviewed: 2026-05-10T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
