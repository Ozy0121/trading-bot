---
phase: 11-signal-expansion
reviewed: 2026-05-29T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - prediction_signals.py
  - prediction.py
  - yf_limiter.py
  - signal_calibration.py
  - tests/test_prediction_signals.py
  - amt_engine.py
  - order_flow.py
  - volume_profile.py
findings:
  critical: 0
  warning: 6
  info: 5
  total: 11
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-05-29
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Phase 11 adds 6 new confirmation signal detectors (Stochastic RSI, MFI, VWAP, Keltner Lower, MACD Divergence, Support Level), a dual-path prediction engine (mean reversion + momentum breakout), market breadth/sector-strength multipliers, and a re-entry tracker. The architecture is sound and the code is generally well-structured. No critical security or data-loss issues were found.

Six warnings were identified. Two are logic bugs that can silently produce wrong results: (1) a score formula discontinuity in `_detect_stoch_rsi` that double-counts the 0.05 boundary, and (2) a `_compute_breadth_multiplier` counter that undercounts weak-sector ETFs because ETFs already counted as `down_5pct` are not also counted in the `down_2pct+down_5pct` majority check — this one is actually correct, but the code makes the intent unclear (see WR-04). The remaining warnings are a thread-safety gap in the sector cache, a dead code branch in `predict()`, a silent division-by-zero path in `volume_profile.py`, and a missing `flush_sector_cache()` call at shutdown.

---

## Warnings

### WR-01: Stochastic RSI score formula has a boundary discontinuity

**File:** `prediction_signals.py:161-168`
**Issue:** When `stoch_val` is exactly `0.05`, the first branch fires (`score = 10.0`). But when `stoch_val` is just above `0.05` (e.g. `0.051`), the second branch fires and computes `8.0 + (0.10 - 0.051) / 0.05 * 2.0 = 8.0 + 1.96 = 9.96` — correct. However, the linear formula for the range `[0.05, 0.10)` yields `10.0` at the lower bound and `8.0` at the upper bound. The intent is a smooth interpolation, but a stoch_val of exactly `0.05` exits in the first branch (constant 10.0) instead of the interpolation branch, while a value of `0.0499` also exits there. This is not a crash but produces a slight discontinuity at the boundary that differs from documented intent.

More critically: the third scoring branch (`stoch_val < 0.20`) starts at `score = 4.0 + (0.20 - stoch_val) / 0.10 * 4.0`. At `stoch_val = 0.10` this gives `4.0 + 4.0 = 8.0`, which matches the second branch's upper bound — so that boundary is smooth. However the scoring architecture means a value of exactly `0.10` falls into the second branch (yielding `8.0 + 0 = 8.0`), which is technically correct but subtle.

**Fix:** Restructure to use `<= 0.05` for the top tier and make boundaries explicit:
```python
if stoch_val <= 0.05:
    score = 10.0
elif stoch_val < 0.10:
    score = 8.0 + (0.10 - stoch_val) / 0.05 * 2.0
elif stoch_val < 0.20:
    score = 4.0 + (0.20 - stoch_val) / 0.10 * 4.0
else:
    score = 0.0
```

---

### WR-02: `get_sector_cached` has a TOCTOU race — sector may be fetched and stored twice

**File:** `yf_limiter.py:240-264`
**Issue:** The lock is released between the cache-miss check (line 249) and the network fetch (line 253). Two threads for the same symbol can both find a cache miss simultaneously, both call `yf.Ticker(symbol).info`, and both write to `_sector_mem_cache`. The second write silently overwrites the first. More importantly, the `% 50 == 0` flush counter check on line 261 can fire for both threads, causing two redundant disk writes in a race window. The disk writes are idempotent, but this is still a correctness concern when many threads scan simultaneously.

**Fix:** Double-check the cache after acquiring the lock on re-entry (double-checked locking pattern):
```python
def get_sector_cached(symbol: str) -> str:
    with _sector_lock:
        _load_sector_cache()
        if symbol in _sector_mem_cache:
            return _sector_mem_cache[symbol]

    # Fetch outside lock
    try:
        info = rate_limited_yf(lambda: yf.Ticker(symbol).info)
        sector = info.get("sector", "") or ""
    except Exception:
        sector = ""

    with _sector_lock:
        # Re-check: another thread may have fetched while we were waiting
        if symbol not in _sector_mem_cache:
            _sector_mem_cache[symbol] = sector
            if len(_sector_mem_cache) % 50 == 0:
                _save_sector_cache()
        return _sector_mem_cache[symbol]
```

---

### WR-03: Dead code — `mr_result` can never be falsy at the dual-path merge

**File:** `prediction.py:851-857`
**Issue:** At line 851, `if momentum_result and not mr_result:` — at this point in the code, `mr_result` is a freshly constructed `Prediction` dataclass (line 823). Dataclass instances are always truthy; this branch is unreachable. The intent is to handle the case where mean-reversion produced no result, but the function already returns `None` earlier (lines 635, 641, 645, 700) if primary signals, regime, confirmations, or confidence checks fail. By the time execution reaches line 851, `mr_result` is guaranteed to be a valid `Prediction` object.

This means the dual-path merge never returns `momentum_result` alone — the momentum path result is only ever returned when mean-reversion confidence is lower. If mean-reversion fires but momentum doesn't, that's fine. But if only momentum would have fired, the function returns `None` before ever reaching the momentum call.

**Fix:** Run the momentum path before the mean-reversion confidence cutoff, or restructure the dual-path logic:
```python
# Option A: run both paths independently and merge
mr_result = _build_mr_result(...)   # returns Prediction | None
momentum_result = _predict_momentum(symbol, df, spy_df, sector_etf_bars)

if mr_result and momentum_result:
    return mr_result if mr_result.confidence >= momentum_result.confidence else momentum_result
return mr_result or momentum_result
```

As written, `_predict_momentum` is called on line 848, but its result is only usable when `mr_result` also exists (line 855-856). The dead branch on line 851-852 should be removed.

---

### WR-04: `_compute_breadth_multiplier` miscounts weak-breadth tier

**File:** `prediction_signals.py:479-492`
**Issue:** ETFs that are `down_5pct` are correctly counted in `down_5pct`, but they are NOT incremented into `down_2pct` (the `elif` on line 481 prevents it). The majority check on line 491 is `down_2pct + down_5pct >= majority`. This means: to trigger the 0.5x multiplier, you need the combined count of ETFs down 2-5% AND ETFs down >5% to exceed majority. The logic is actually correct per the docstring intent — "majority of sectors down >2%" means either threshold.

However, the variable name `down_2pct` is misleading: it only holds ETFs in the range -5% to -2% (not all down >2%), creating a readability trap that could cause a future developer to "fix" the correct logic. This is a latent maintainability bug.

**Fix:** Rename for clarity:
```python
down_2_to_5pct = 0  # ETFs down between 2% and 5%
down_over_5pct = 0  # ETFs down more than 5%
# ...
if five_day_return < -0.05:
    down_over_5pct += 1
elif five_day_return < -0.02:
    down_2_to_5pct += 1
# ...
if down_over_5pct >= majority:
    return 0.25
if down_2_to_5pct + down_over_5pct >= majority:  # all sectors down >2%
    return 0.5
```

---

### WR-05: `volume_profile.py` — division by `poc` can produce `inf` when poc rounds to 0

**File:** `volume_profile.py:212`
**Issue:** `poc_dist_pct = abs(current_price - poc) / poc * 100 if poc > 0 else 100`. The guard `poc > 0` looks correct, but `poc` on line 201 is `float(bin_centers[poc_idx])` which can be zero when `price_min` is 0 (e.g. a synthetic test with prices starting at 0) or very near zero. With penny stocks or bad data, `bin_centers[0]` could be near zero, making `poc_dist_pct` extremely large but not `inf`. The more significant issue is line 102 in `pos_in_va = (current_price - val) / va_width if va_width > 0 else 0.5` in `amt_engine.py:102` — this is guarded. However in `score_volume_profile`, `poc_score` computes fine, but `val` on line 227 has `if val > 0` which is correctly guarded.

The actual unguarded path is in `score_volume_profile` line 212 inside the `below_value` branch:
```python
dist_below = (val - current_price) / val * 100 if val > 0 else 0
```
This is guarded. However, the same module's `_compute_value_area` (line 152) loops `while cumulative / total < target_pct` — if `total` is 0, this would divide by zero. The `total_volume <= 0` check on line 95 is the guard, but `_compute_value_area` is also called on line 104 before that check... wait: the check is on line 95-97 (`if total_volume <= 0: return _empty_profile()`), and `_compute_value_area` is called on line 104 — after that guard. So this is fine.

The actual issue: in `_compute_value_area`, line 151: `while cumulative / total < target_pct` — `total` is `bin_volumes.sum()`. If called directly with a zero-sum array, this divides by zero. The function is private and only called from `compute_volume_profile` which guards against zero total, but there is no guard inside `_compute_value_area` itself.

**Fix:** Add a guard at the top of `_compute_value_area`:
```python
def _compute_value_area(bin_volumes: np.ndarray, poc_idx: int, target_pct: float) -> tuple[int, int]:
    total = bin_volumes.sum()
    if total <= 0:
        return poc_idx, poc_idx
    # ... rest of function
```

---

### WR-06: `flush_sector_cache()` is never called — persistent sector cache never saves on clean exit

**File:** `yf_limiter.py:267-270`
**Issue:** `flush_sector_cache()` is defined and documented as "Call at shutdown or end of scan", but there is no call to it anywhere in the reviewed codebase. The in-memory sector cache is only saved to disk when `len(_sector_mem_cache) % 50 == 0` (every 50 new entries). For small scans (< 50 symbols), or between the last flush and process exit, all accumulated sector data is lost. A long-running process that caches 49 new sectors and then exits will lose all 49 entries.

**Fix:** Call `flush_sector_cache()` in `predict_batch()` after the batch completes:
```python
# In predict_batch(), after the prediction loop:
from yf_limiter import prefetch_sector_etf_bars, flush_sector_cache
# ... batch runs ...
flush_sector_cache()  # Persist any newly cached sector data
log.info("[prediction] Batch complete: ...")
```

---

## Info

### IN-01: `_detect_stoch_rsi` computes `stoch_val` twice on the non-flat path

**File:** `prediction_signals.py:149-158`
**Issue:** When `last_denom != 0.0`, the code recomputes the full stochastic series (`stoch = (rsi_clean - rsi_min) / denom.replace(...)`) even though `last_denom` was already computed from `denom.iloc[-1]`. The final value `stoch_val` could be extracted from the already-computed `denom` rather than recomputing the full series. Not a bug, just a minor efficiency and readability issue.

**Fix:** Extract `stoch_val` from the already-available `rsi_min`/`denom`:
```python
last_rsi_min = float(rsi_min.iloc[-1]) if not pd.isna(rsi_min.iloc[-1]) else float(rsi_clean.iloc[-1])
stoch_val = (last_rsi_val - last_rsi_min) / last_denom
```

---

### IN-02: `_detect_sector_strength` patches the wrong module path in tests

**File:** `tests/test_prediction_signals.py:635-636`
**Issue:** The test patches `yf_limiter.get_sector_cached` and `yf_limiter.SECTOR_ETF_MAP`, but `_detect_sector_strength` imports them via `from yf_limiter import get_sector_cached, SECTOR_ETF_MAP` (a local import inside the function at `prediction_signals.py:526`). Patching the module attribute directly (`yf_limiter.get_sector_cached`) works for `from-import` only when the import is done *after* the patch is applied. Because the import is inside the function body (lazy), this test pattern is correct. However, it's fragile — if the import is ever moved to module level, the patches would silently stop working. A more robust pattern is `patch("prediction_signals.get_sector_cached")` after confirming the symbol is importable at that level.

**Fix:** No immediate action required (the test is currently correct), but note the fragility for future refactors.

---

### IN-03: `signal_calibration.py` — `_append_accuracy_snapshot` computes `overall_accuracy` by averaging signal appearances, not unique predictions

**File:** `signal_calibration.py:101-111`
**Issue:** The "overall accuracy" snapshot sums wins and totals across all signals. Since each prediction typically fires multiple signals, a single winning prediction is counted multiple times (once per active signal). This inflates both `total_predictions` and `total_wins`, but since the ratio is computed consistently (wins/total per-signal contributions), the resulting `overall_accuracy_pct` is a signal-weighted accuracy average, not a per-prediction accuracy. The dashboard shows this as "overall accuracy", which may mislead users into thinking it is prediction-level win rate.

**Fix:** Track prediction-level win rates separately in the snapshot, or document the metric clearly:
```python
# Add a note in the snapshot
snapshot["accuracy_note"] = "signal-weighted average, not per-prediction win rate"
```

---

### IN-04: `_detect_vwap` uses multi-day cumulative VWAP but documents it as "cost basis"

**File:** `prediction_signals.py:221-269`
**Issue:** Cumulative VWAP across the full DataFrame is not a standard VWAP interpretation — standard VWAP resets daily. The note field ("multi-day VWAP (not intraday reset)") is correct but users of the output (dashboard consumers) may interpret "cost basis" as the institutional average cost, which is technically an approximation at best. The minimum 10 bars requirement means for a 60-day daily bar dataset, VWAP is computed across 60 days of data, making it a 3-month weighted average price rather than an intraday reference. This is intentional per the docstring but may produce counterintuitive scores when recent price action is very different from historical price.

**Fix:** No code change required, but ensure the dashboard label clearly states "60-day VWAP" rather than "VWAP" to avoid user confusion.

---

### IN-05: `predict_batch` catches `Exception` on `future.result()` at DEBUG level — prediction failures are silent

**File:** `prediction.py:1128`
**Issue:** `log.debug("[prediction] %s failed: %s", sym, exc)` at DEBUG level means that if a symbol's prediction raises an unexpected exception (e.g. a new signal detector throws on malformed data), it is silently discarded in production (where INFO is the typical log level). This makes debugging prediction failures very hard without changing log level.

**Fix:** Log at WARNING to make prediction failures visible in production:
```python
except Exception as exc:
    log.warning("[prediction] %s prediction failed: %s", sym, exc)
```

---

_Reviewed: 2026-05-29_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
