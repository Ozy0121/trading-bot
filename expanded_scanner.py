"""
expanded_scanner.py
-------------------
Four-tier cascading pipeline for overnight expanded stock scanning.
Separate from live scanner.py (D-04). Uses quant-only ranking (D-10),
not conviction scoring.

Pipeline tiers:
  T1: Price + ETF gate ($5-$200, no ETFs/preferred)
  T2: Volume gate (avg daily volume >= 500K)
  T3: Momentum gate (positive 5-day return OR unusual volume >1.5x)
  T4: Quant multi-factor scoring (top 50 survivors)
"""

from __future__ import annotations

import json
import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone, timedelta

import pandas as pd

from logger_setup import get_logger
from stock_universe import get_full_universe, get_funnel_stats, LEVERAGED_ETFS, FUTURES_SECTOR_ETFS
from openbb_data import fetch_bulk_bars, fetch_ticker_info
from quant_factors import compute_quant_score, rank_momentum
import config
import state as shared_state
import progress

log = get_logger()

_cancel_requested = threading.Event()


def cancel_scan() -> None:
    """Request cancellation of the running expanded scan."""
    _cancel_requested.set()


def _cancelled() -> bool:
    return _cancel_requested.is_set()


def _scan_log(message: str, level: str = "info") -> None:
    """Log to both standard logger and dashboard scan log buffer."""
    getattr(log, level)("[expanded] %s", message)
    progress.push_log("expanded", message, level)

# ── Constants ──────────────────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OVERNIGHT_RESULTS_PATH = os.path.join(DATA_DIR, "overnight_results.json")

_SYMBOL_RE = re.compile(r'^[A-Z]{1,5}$')

_ETF_KEYWORDS = frozenset([
    "ETF", "FUND", "TRUST", "INDEX", "PORTFOLIO",
    "PROSHARES", "DIREXION", "ISHARES", "VANGUARD", "SPDR",
])

_ETF_QUOTE_TYPES = frozenset(["ETF", "MUTUALFUND", "MONEYMARKET", "CURRENCY"])

_PREFERRED_SUFFIXES = frozenset(["P", "W", "R", "U"])

# Known ETF symbols (from stock_universe.py static lists)
_KNOWN_ETFS = frozenset(LEVERAGED_ETFS + FUTURES_SECTOR_ETFS + [
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "VEA", "VWO",
    "EEM", "HYG", "LQD", "AGG", "BND", "IEFA", "IEMG",
])

_MAX_SURVIVORS = 50
_RESULTS_TTL_HOURS = 18


# ── ETF / preferred share detection ───────────────────────────────────────────


def _is_etf_or_preferred(symbol: str, info: dict | None = None) -> bool:
    """Check if a symbol is an ETF, fund, or preferred share.

    Uses info dict (quoteType, longName) if available, otherwise falls
    back to symbol heuristics and the known ETF list.
    """
    # Check info dict if provided
    if info:
        quote_type = (info.get("quoteType") or "").upper()
        if quote_type in _ETF_QUOTE_TYPES:
            return True

        for field in ("longName", "shortName"):
            name = (info.get(field) or "").upper()
            if any(kw in name for kw in _ETF_KEYWORDS):
                return True

    # Symbol-level heuristics
    if symbol in _KNOWN_ETFS:
        return True

    # Preferred share suffix: 5-letter symbols ending in P/W/R/U
    if len(symbol) == 5 and symbol[-1] in _PREFERRED_SUFFIXES:
        return True

    return False


# ── Symbol validation (T-07-03 threat mitigation) ─────────────────────────────


def _valid_symbol(sym: str) -> bool:
    """Validate symbol: 1-5 uppercase letters only."""
    return bool(_SYMBOL_RE.match(sym))


# ── Tier 1: Price + ETF gate ──────────────────────────────────────────────────


def _filter_price_mcap(symbols: list[str], bars_dict: dict[str, pd.DataFrame]) -> list[str]:
    """Filter by price range ($5-$200) and reject ETFs/preferred shares."""
    survivors = []
    min_price = getattr(config, "MIN_PRICE", 5.0)

    for sym in symbols:
        if not _valid_symbol(sym):
            continue
        df = bars_dict.get(sym)
        if df is None or df.empty:
            continue

        last_close = float(df["close"].iloc[-1])
        if last_close < min_price or last_close > 200.0:
            continue

        if _is_etf_or_preferred(sym):
            continue

        survivors.append(sym)

    _scan_log(f"T1 price+ETF gate: {len(symbols)} -> {len(survivors)} ({len(symbols) - len(survivors)} filtered)")
    return survivors


# ── Tier 2: Volume gate ───────────────────────────────────────────────────────


def _filter_volume(symbols: list[str], bars_dict: dict[str, pd.DataFrame]) -> list[str]:
    """Filter by average daily volume >= 500K."""
    survivors = []

    for sym in symbols:
        df = bars_dict.get(sym)
        if df is None or df.empty:
            continue

        avg_vol = float(df["volume"].mean())
        if avg_vol < 500_000:
            continue

        survivors.append(sym)

    _scan_log(f"T2 volume gate: {len(symbols)} -> {len(survivors)} ({len(symbols) - len(survivors)} filtered)")
    return survivors


# ── Tier 3: Momentum gate ─────────────────────────────────────────────────────


def _filter_momentum(
    symbols: list[str],
    bars_5d: dict[str, pd.DataFrame],
    bars_20d: dict[str, pd.DataFrame],
) -> list[str]:
    """Filter by positive 5-day return OR unusual volume (>1.5x 20-day avg).

    Per UNIV-02: stocks with >2x average volume pass regardless of return.
    The 1.5x threshold catches those plus moderate volume spikes.
    """
    survivors = []

    for sym in symbols:
        df_5d = bars_5d.get(sym)
        df_20d = bars_20d.get(sym)

        if df_5d is None or df_5d.empty or len(df_5d) < 2:
            continue

        # 5-day return
        close_first = float(df_5d["close"].iloc[0])
        close_last = float(df_5d["close"].iloc[-1])
        ret_5d = (close_last - close_first) / close_first if close_first > 0 else 0.0

        if ret_5d > 0:
            survivors.append(sym)
            continue

        # Unusual volume check: last day volume vs 20-day average
        if df_20d is not None and not df_20d.empty:
            avg_vol_20d = float(df_20d["volume"].mean())
            last_vol = float(df_5d["volume"].iloc[-1])

            if avg_vol_20d > 0 and last_vol > 1.5 * avg_vol_20d:
                survivors.append(sym)
                continue

    _scan_log(f"T3 momentum gate: {len(symbols)} -> {len(survivors)} ({len(symbols) - len(survivors)} filtered)")
    return survivors


# ── Tier 4: Quant multi-factor scoring ────────────────────────────────────────


def _score_quant_multifactor(
    symbols: list[str],
    bars_dict: dict[str, pd.DataFrame],
    deadline: float,
) -> list[dict]:
    """Score symbols using multi-factor quant model and return top survivors."""
    workers = getattr(config, "EXPANDED_SCAN_WORKERS", 10)

    # First pass: cross-sectional momentum ranks
    rank_data = {sym: bars_dict[sym] for sym in symbols if sym in bars_dict}
    momentum_ranks = rank_momentum(rank_data)

    # Second pass: compute quant scores (checking deadline + cancel)
    scored: list[dict] = []
    for i, sym in enumerate(symbols):
        if _cancelled() or time.time() >= deadline:
            reason = "cancelled" if _cancelled() else "deadline"
            log.warning("[expanded] T4 %s after scoring %d/%d symbols",
                        reason, len(scored), len(symbols))
            break

        df = bars_dict.get(sym)
        if df is None or df.empty:
            continue

        try:
            result = compute_quant_score(sym, df, momentum_ranks.get(sym, 0.5))
            scored.append(result)
        except Exception as exc:
            log.debug("[expanded] T4 scoring failed for %s: %s", sym, exc)

        if i % 20 == 0:
            progress.track("expanded_scan", current=i, total=len(symbols),
                           label=f"T4 scoring: {i:,}/{len(symbols):,}")

    # ETF double-check via ticker info for survivors
    # Only check a manageable number in parallel
    to_check = scored[:200]
    etf_symbols: set[str] = set()

    def _check_etf(item: dict) -> str | None:
        sym = item["symbol"]
        try:
            info = fetch_ticker_info(sym)
            if info and _is_etf_or_preferred(sym, info):
                return sym
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=min(workers, 5)) as executor:
        futures = {executor.submit(_check_etf, item): item for item in to_check}
        for future in as_completed(futures):
            if time.time() >= deadline:
                break
            try:
                result = future.result(timeout=10)
                if result:
                    etf_symbols.add(result)
            except Exception:
                pass

    # Remove ETFs that leaked through
    if etf_symbols:
        log.info("[expanded] T4 ETF check removed %d symbols: %s",
                 len(etf_symbols), list(etf_symbols)[:10])
        scored = [s for s in scored if s["symbol"] not in etf_symbols]

    # Sort by quant_score descending, take top N
    scored.sort(key=lambda x: x.get("quant_score", 0), reverse=True)
    survivors = scored[:_MAX_SURVIVORS]

    _scan_log(f"T4 quant scoring: {len(symbols)} -> {len(survivors)} survivors (top {_MAX_SURVIVORS})")
    log.info("[expanded] T4 quant scoring: %d -> %d survivors",
             len(symbols), len(survivors))
    return survivors


# ── Main pipeline ──────────────────────────────────────────────────────────────


def run_expanded_pipeline(timeout_seconds: int | None = None) -> list[dict]:
    """Run the four-tier expanded scanner pipeline.

    Returns list of up to 50 survivor dicts with quant_score and factor
    breakdown. Saves results to JSON and updates shared state.
    """
    _cancel_requested.clear()
    default_timeout = getattr(config, "EXPANDED_SCAN_TIMEOUT", 7200)
    deadline = time.time() + (timeout_seconds or default_timeout)
    start_ts = time.time()
    progress.clear_logs()

    # Step 0: Get buying power for affordability filter
    snap = shared_state.snapshot()
    buying_power = float(snap.get("buying_power", 0) or snap.get("cash", 0) or 0)

    # Step 1: Get full universe
    universe = get_full_universe(include_discovery=False)
    _scan_log(f"Pipeline starting with {len(universe):,} symbols")
    progress.track("expanded_scan", total=len(universe), current=0,
                   label=f"Scanning {len(universe):,} stocks...")

    if _cancelled():
        _scan_log("Scan cancelled by user", "warning")
        progress.fail("expanded_scan", message="Cancelled")
        return []

    # Step 2: Fetch 5-day bars for initial filtering
    _scan_log("Fetching 5-day bars for initial filtering...")
    bars_5d = fetch_bulk_bars(universe, period="5d", interval="1d")
    _scan_log(f"Fetched bars for {len(bars_5d):,}/{len(universe):,} symbols")

    if _cancelled():
        _scan_log("Scan cancelled by user", "warning")
        progress.fail("expanded_scan", message="Cancelled")
        return []

    # T0: Buying power filter — drop stocks we can't afford
    if buying_power > 0:
        _scan_log(f"Running T0: Buying power filter (${buying_power:,.0f})...")
        pre_count = len(universe)
        affordable = []
        for sym in universe:
            df = bars_5d.get(sym)
            if df is None or df.empty:
                continue
            last_close = float(df["close"].iloc[-1])
            if last_close <= buying_power:
                affordable.append(sym)
        _scan_log(f"T0 affordability: {pre_count:,} -> {len(affordable):,} ({pre_count - len(affordable):,} too expensive)")
        universe = affordable
        progress.track("expanded_scan", total=len(universe), current=0,
                       label=f"T0 done: {len(universe):,} affordable stocks")

    # Tier 1: Price + ETF gate
    _scan_log("Running T1: Price range ($5-$200) + ETF filter...")
    t1 = _filter_price_mcap(universe, bars_5d)
    progress.track("expanded_scan", current=len(universe) - len(t1),
                   label=f"T1 complete: {len(t1):,} remain ({len(universe) - len(t1):,} filtered)")

    if _cancelled():
        _scan_log("Scan cancelled by user", "warning")
        progress.fail("expanded_scan", message="Cancelled")
        return []

    # Tier 2: Volume gate
    _scan_log("Running T2: Volume gate (avg daily >= 500K)...")
    t2 = _filter_volume(t1, bars_5d)
    progress.track("expanded_scan", current=len(universe) - len(t2),
                   label=f"T2 complete: {len(t2):,} remain ({len(t1) - len(t2):,} filtered)")

    # Check deadline after T2
    if _cancelled() or time.time() >= deadline:
        reason = "Cancelled" if _cancelled() else "Deadline reached after T2"
        _scan_log(f"{reason}, saving partial results", "warning")
        funnel = {"universe": len(universe), "t0_affordable": len(universe),
                  "t1": len(t1), "t2": len(t2), "t3": 0, "survivors": 0}
        save_overnight_results([], funnel)
        progress.fail("expanded_scan", message=reason)
        return []

    # Step 3: Fetch 30-day bars for T2 survivors only
    _scan_log(f"Fetching 30-day bars for {len(t2):,} T2 survivors...")
    bars_30d = fetch_bulk_bars(t2, period="30d", interval="1d")
    _scan_log(f"Fetched 30-day bars for {len(bars_30d):,}/{len(t2):,} symbols")

    if _cancelled():
        _scan_log("Scan cancelled by user", "warning")
        progress.fail("expanded_scan", message="Cancelled")
        return []

    # Tier 3: Momentum gate
    _scan_log("Running T3: Momentum gate (positive return OR unusual volume)...")
    t3 = _filter_momentum(t2, bars_5d, bars_30d)
    progress.track("expanded_scan", current=len(universe) - len(t3),
                   label=f"T3 complete: {len(t3):,} remain ({len(t2) - len(t3):,} filtered)")

    # Check deadline after T3
    if _cancelled() or time.time() >= deadline:
        reason = "Cancelled" if _cancelled() else "Deadline reached after T3"
        _scan_log(f"{reason}, saving partial results", "warning")
        funnel = {"universe": len(universe), "t0_affordable": len(universe),
                  "t1": len(t1), "t2": len(t2), "t3": len(t3), "survivors": 0}
        save_overnight_results([], funnel)
        progress.fail("expanded_scan", message=reason)
        return []

    # Tier 4: Quant multi-factor scoring
    _scan_log(f"Running T4: Quant multi-factor scoring on {len(t3):,} candidates...")
    survivors = _score_quant_multifactor(t3, bars_30d, deadline)

    # Build funnel stats
    funnel = {
        "universe": len(universe),
        "t1": len(t1),
        "t2": len(t2),
        "t3": len(t3),
        "survivors": len(survivors),
    }

    # Save results
    save_overnight_results(survivors, funnel)

    # Update shared state (cap at 100 entries for T-07-05)
    shared_state.update(
        expanded_scan_results=survivors[:100],
        expanded_scan_time=datetime.now(timezone.utc).isoformat(),
        expanded_scan_status="complete",
        expanded_scan_funnel=funnel,
    )

    duration = time.time() - start_ts
    _scan_log(f"Pipeline complete: {len(survivors)} survivors in {duration:.1f}s")
    _scan_log(f"Funnel: {funnel['universe']} -> {funnel['t1']} -> {funnel['t2']} -> {funnel['t3']} -> {funnel['survivors']}")
    if survivors:
        top3 = [s["symbol"] for s in survivors[:3]]
        _scan_log(f"Top picks: {', '.join(top3)}")

    return survivors


# ── JSON persistence ──────────────────────────────────────────────────────────


def save_overnight_results(results: list[dict], scan_meta: dict) -> None:
    """Save scan results to JSON with TTL for expiration."""
    os.makedirs(os.path.dirname(OVERNIGHT_RESULTS_PATH), exist_ok=True)

    payload = {
        "results": results,
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "expires_at": time.time() + _RESULTS_TTL_HOURS * 3600,
        "funnel": scan_meta,
    }

    try:
        with open(OVERNIGHT_RESULTS_PATH, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        log.info("[expanded] Saved %d results to %s", len(results), OVERNIGHT_RESULTS_PATH)
    except Exception as exc:
        log.error("[expanded] Failed to save results: %s", exc)


def load_overnight_results() -> list[dict]:
    """Load cached scan results. Returns [] if missing, corrupt, or expired."""
    try:
        with open(OVERNIGHT_RESULTS_PATH, "r") as f:
            payload = json.load(f)

        if time.time() >= payload.get("expires_at", 0):
            log.info("[expanded] Cached results expired, returning empty")
            return []

        return payload.get("results", [])
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, KeyError) as exc:
        log.warning("[expanded] Failed to load cached results: %s", exc)
        return []


# ── Manual trigger ─────────────────────────────────────────────────────────────


def trigger_manual_scan() -> None:
    """Trigger an expanded scan manually (called from dashboard route)."""
    shared_state.update(expanded_scan_status="running")
    try:
        run_expanded_pipeline()
    except Exception as exc:
        log.error("[expanded] Manual scan failed: %s", exc, exc_info=True)
        shared_state.update(expanded_scan_status="error")


# ── Overnight daemon ──────────────────────────────────────────────────────────


def _get_market_close_today(trading_client) -> datetime | None:
    """Get today's market close time as a UTC-aware datetime, or None if closed."""
    try:
        from alpaca.trading.requests import GetCalendarRequest
        import zoneinfo

        today = date.today()
        cal = trading_client.get_calendar(
            GetCalendarRequest(start=today, end=today)
        )
        if not cal:
            return None  # holiday or weekend

        close_time = cal[0].close
        eastern = zoneinfo.ZoneInfo("America/New_York")
        close_dt = datetime.combine(today, close_time, tzinfo=eastern)
        return close_dt.astimezone(timezone.utc)
    except Exception as exc:
        log.warning("[expanded] Failed to get market close time: %s", exc)
        return None


def _overnight_daemon_loop(trading_client) -> None:
    """Infinite loop that triggers expanded scan after market close each day."""
    while True:
        try:
            close_utc = _get_market_close_today(trading_client)

            if close_utc is None:
                # Holiday or weekend — check again in 1 hour
                log.debug("[expanded] No market close today, sleeping 1 hour")
                time.sleep(3600)
                continue

            delay_minutes = getattr(config, "EXPANDED_SCAN_DELAY_MINUTES", 15)
            scan_start = close_utc + timedelta(minutes=delay_minutes)
            now = datetime.now(timezone.utc)

            if now > scan_start + timedelta(hours=4):
                # Too late today — sleep until midnight and retry
                log.debug("[expanded] Past scan window, sleeping until midnight")
                tomorrow = datetime.combine(
                    date.today() + timedelta(days=1),
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                )
                sleep_secs = max(60, (tomorrow - now).total_seconds())
                time.sleep(sleep_secs)
                continue

            if now < scan_start:
                # Wait until scan start time
                wait_secs = (scan_start - now).total_seconds()
                log.info("[expanded] Waiting %.0f seconds until scan start", wait_secs)
                time.sleep(max(1, wait_secs))

            # Run quant filter, then overnight predictions on survivors
            log.info("[expanded] Overnight scan starting...")
            shared_state.update(expanded_scan_status="running")
            try:
                timeout = getattr(config, "EXPANDED_SCAN_TIMEOUT", 7200)
                results = run_expanded_pipeline(timeout_seconds=timeout)
                log.info("[expanded] Quant filter complete: %d survivors — running predictions...", len(results))

                from prediction_scanner import run_overnight_scan
                run_overnight_scan()
                log.info("[expanded] Overnight pipeline complete (quant + predictions)")
            except Exception as exc:
                log.error("[expanded] Overnight scan failed: %s", exc, exc_info=True)
                shared_state.update(expanded_scan_status="error")

            # Sleep until next day (rough: 20 hours from now)
            time.sleep(20 * 3600)

        except Exception as exc:
            log.error("[expanded] Daemon loop error: %s", exc, exc_info=True)
            time.sleep(3600)  # retry in 1 hour


def start_overnight_daemon(trading_client) -> None:
    """Start the overnight scanner daemon thread.

    Also loads any cached results from disk on startup.
    """
    cached = load_overnight_results()
    if cached:
        shared_state.update(
            expanded_scan_results=cached[:100],
            expanded_scan_status="cached",
        )
        log.info("[expanded] Loaded %d cached results from disk", len(cached))

    threading.Thread(
        target=_overnight_daemon_loop,
        args=(trading_client,),
        daemon=True,
        name="expanded-scanner-daemon",
    ).start()
    log.info("[expanded] Overnight scanner daemon started")
