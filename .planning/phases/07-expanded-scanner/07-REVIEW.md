---
phase: 07-expanded-scanner
reviewed: 2026-04-18T12:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - expanded_scanner.py
  - tests/test_expanded_scanner.py
  - state.py
  - config.py
  - server.py
  - dashboard.py
findings:
  critical: 1
  warning: 4
  info: 3
  total: 8
status: issues_found
---

# Phase 07: Code Review Report

**Reviewed:** 2026-04-18T12:00:00Z
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

The Phase 07 expanded scanner introduces a four-tier cascading stock scanner with overnight daemon, JSON persistence, and dashboard integration. The pipeline architecture is well-structured with clear tier separation, deadline enforcement, and graceful degradation. The integration into server.py, dashboard.py, and state.py follows existing project conventions cleanly.

Key concerns: a path traversal vulnerability via the `/api/bars/<symbol>` endpoint (pre-existing but relevant since expanded scanner feeds symbols into this flow), a potential data corruption issue in `save_overnight_results` due to `scan_meta` keys colliding with the payload structure, and several robustness gaps in the daemon loop and error handling.

## Critical Issues

### CR-01: scan_meta dict-merge can overwrite payload fields (data corruption)

**File:** `expanded_scanner.py:356-361`
**Issue:** `save_overnight_results` uses `**scan_meta` to merge arbitrary keys from `scan_meta` into the payload dict. If `scan_meta` contains keys like `"results"`, `"scan_time"`, or `"expires_at"`, they will silently overwrite the payload's own values. While the current callers pass safe keys (`universe`, `t1`, `t2`, `t3`, `survivors`), this is a latent bug -- any future caller passing a dict with conflicting keys will cause silent data loss or corrupt the TTL mechanism.
**Fix:**
```python
payload = {
    "results": results,
    "scan_time": datetime.now(timezone.utc).isoformat(),
    "expires_at": time.time() + _RESULTS_TTL_HOURS * 3600,
    "funnel": scan_meta,  # nest under a dedicated key instead of merging
}
```

## Warnings

### WR-01: Overnight daemon sleeps 20 hours unconditionally after scan, can miss next day

**File:** `expanded_scanner.py:472-473`
**Issue:** After a successful scan, the daemon sleeps for exactly 20 hours (`time.sleep(20 * 3600)`). If the scan ran late (e.g., started at 8 PM ET and finished at 9 PM), sleeping 20 hours lands at 5 PM ET the next day -- past the scan window. The "too late today" check on line 443 then sleeps until midnight, causing the scan to skip a full day. The logic should sleep until the next day's expected scan time, not a fixed duration.
**Fix:**
```python
# Instead of: time.sleep(20 * 3600)
# Sleep until tomorrow's expected close time minus a buffer
tomorrow_close = _get_market_close_today(trading_client)  # will be None until tomorrow
# Safer: sleep until midnight, then let the loop re-evaluate
tomorrow = datetime.combine(
    date.today() + timedelta(days=1),
    datetime.min.time(),
    tzinfo=timezone.utc,
)
sleep_secs = max(60, (tomorrow - datetime.now(timezone.utc)).total_seconds())
time.sleep(sleep_secs)
```

### WR-02: `_get_market_close_today` uses `date.today()` without timezone awareness

**File:** `expanded_scanner.py:411`
**Issue:** `date.today()` returns the local date of the machine running the bot. If the server is in a timezone ahead of Eastern (e.g., UTC), after 7 PM UTC on a Friday, `date.today()` returns Saturday in UTC but the daemon is asking for Saturday's calendar -- which returns None (weekend). This is correct in that specific case, but on weekdays with timezone skew, the daemon could query the wrong day's calendar. For example, at 1 AM UTC on a Tuesday, it queries Tuesday's calendar but the scan should have already run for Monday's close.
**Fix:**
```python
import zoneinfo
eastern = zoneinfo.ZoneInfo("America/New_York")
today = datetime.now(eastern).date()
```

### WR-03: Thread pool futures not cancelled on deadline in T4 ETF check

**File:** `expanded_scanner.py:243-253`
**Issue:** When the deadline is reached inside the `as_completed` loop (line 247), the loop breaks but submitted futures continue running in the background. The `ThreadPoolExecutor` context manager will block on `__exit__` until all submitted futures complete (or the 10-second timeout per future triggers). This could delay the pipeline beyond the deadline by up to `200 * 10 = 2000 seconds` in the worst case. Use `executor.shutdown(wait=False, cancel_futures=True)` (Python 3.9+) or restructure to avoid blocking.
**Fix:**
```python
with ThreadPoolExecutor(max_workers=min(workers, 5)) as executor:
    futures = {executor.submit(_check_etf, item): item for item in to_check}
    for future in as_completed(futures):
        if time.time() >= deadline:
            # Cancel remaining futures
            for f in futures:
                f.cancel()
            break
        try:
            result = future.result(timeout=10)
            if result:
                etf_symbols.add(result)
        except Exception:
            pass
```

### WR-04: `/api/expanded-scan/run` lacks authentication -- any HTTP client can trigger expensive scan

**File:** `dashboard.py:781-799`
**Issue:** The POST endpoint `/api/expanded-scan/run` does not require the `confirm: "YES"` guard that other mutation endpoints use (e.g., `/api/start`, `/api/kill`, `/api/order`). This means any client that can reach the dashboard (the app binds to `0.0.0.0` on line 993) can trigger a 2-hour CPU/network-intensive scan. While the dashboard has no formal auth (noted in project docs), other dangerous endpoints at least require explicit confirmation.
**Fix:**
```python
@app.route("/api/expanded-scan/run", methods=["POST"])
def api_expanded_scan_run():
    body = request.get_json(silent=True) or {}
    if body.get("confirm") != "YES":
        abort(400, "Confirmation required.")
    # ... rest of handler
```

## Info

### IN-01: Unused `workers` variable in `_score_quant_multifactor`

**File:** `expanded_scanner.py:204`
**Issue:** `workers` is assigned from config but never used in the scoring loop (the loop is sequential). It is only used later for the ETF check thread pool, but its name and position suggest it was intended for parallel scoring.
**Fix:** Move the `workers` assignment to where it is actually used (line 243), or add a comment clarifying its purpose.

### IN-02: `_SYMBOL_RE` only allows 1-5 uppercase letters, rejecting valid tickers

**File:** `expanded_scanner.py:41`
**Issue:** Some valid stock symbols are longer than 5 characters (e.g., `GOOGL` is 5 but `BRK.A` or `BF.B` have dots). The regex `^[A-Z]{1,5}$` will also reject any symbol with digits. This is likely intentional for the scanner's scope but worth documenting.
**Fix:** Add a comment: `# Intentionally strict: rejects special classes (BRK.A, warrants with digits)`

### IN-03: Test helper `_make_ohlcv` hardcodes end date to 2026-04-17

**File:** `tests/test_expanded_scanner.py:24`
**Issue:** The hardcoded date `pd.Timestamp("2026-04-17")` will work now but creates a time-dependent test fixture. If tests ever validate time-sensitive logic, this could cause subtle failures. Not a bug today, just a maintainability note.
**Fix:** Use `pd.Timestamp.now().normalize()` or keep as-is with a comment explaining the fixed date is intentional for reproducibility.

---

_Reviewed: 2026-04-18T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
