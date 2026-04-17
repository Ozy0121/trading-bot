# Phase 7: Expanded Scanner - Research

**Researched:** 2026-04-17
**Domain:** Multi-factor quant scanning, SMC layer detection, NautilusTrader backtesting, overnight pipeline
**Confidence:** MEDIUM-HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Four-tier cascading pipeline: (1) Price gate $5-$200 + market cap >$100M, (2) Volume gate avg daily volume >500K, (3) Momentum gate — positive 5-day return OR volume >1.5x 20-day avg, (4) Heavy quant multi-factor model (momentum, value, quality, volatility factors)
- **D-02:** Heavy quant multi-factor model for tier 4 — researcher should investigate open-source Python quant libraries (pandas-ta, ta-lib, quantitative factor model repos) and GitHub strategy repos for reusable implementations
- **D-03:** Target ~50 survivors after full pipeline for deep ranking (matches UNIV-04)
- **D-04:** Expanded scanner does NOT affect the live 60s scanner — they are separate pipelines. Both can share utility functions but run independently.
- **D-05:** Trigger via Alpaca trading calendar API — scan starts 15 minutes after market close. DST-safe, handles early closes and holidays automatically.
- **D-06:** Hard 2-hour timeout on expanded scan. If not done, save partial results (whatever survived the pipeline so far) and stop. Live scanner resumes normally at open regardless.
- **D-07:** Add dashboard button for manual on-demand expanded scan trigger. Useful for testing, weekends, or mid-day runs.
- **D-08:** Keep full 2,500+ stock universe (S&P 500, NASDAQ 100, Russell 2000 proxy, top volume, leveraged ETFs, sector ETFs, discovery scans). 500+ was a floor, not a ceiling.
- **D-09:** ETFs are filtered out in the hard pre-filter gate (UNIV-03 compliance). No special exemptions — ETFs removed during tier 1 filtering.
- **D-10:** Quant-only ranking for overnight survivors — do NOT reuse the conviction scoring engine. Survivors are ranked purely by multi-factor quant scores from the pre-filter pipeline. This is a separate ranking system from the live scanner's tech/volume/sentiment/sector breakdown.
- **D-11:** Results stored in shared_state (for dashboard display) AND persisted to JSON file (survives restarts). Dashboard shows ranked candidates. Phase 9 later adds approve/reject UI on top.

### Claude's Discretion
- Batch size for bulk `yf.download()` calls (suggested ~200 per batch)
- Specific quant factor weights and thresholds (to be determined during research/planning)
- JSON file location and format for persisted results
- Thread pool worker count for overnight scan (previously reduced to 5 for live; overnight can potentially use more since it's not competing with the live loop)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UNIV-01 | Scanner fetches S&P 500 + NASDAQ 100 constituents (cached daily) and deduplicates into unified expanded watchlist | Already implemented in `stock_universe.py` — `get_sp500()`, `get_nasdaq100()`, `get_full_universe()` |
| UNIV-02 | Top daily volume and unusual volume (>2x 20-day avg) stocks added to expanded watchlist | `get_top_volume()` already exists; unusual volume (>2x 20-day avg) detection is new logic needed in tier 3 momentum gate |
| UNIV-03 | Hard pre-filters: price $5 to MAX_POSITION_VALUE, daily volume >500K, market cap >$100M, NYSE/NASDAQ only, no ETFs/preferred shares | Tier 1 and tier 2 pipeline gates; ETF detection via symbol suffix patterns and yfinance `quoteType` field |
| UNIV-04 | Two-tier scan: bulk `yf.download()` pre-filter culls to ~50 survivors, then full conviction scoring on survivors only | `fetch_bulk_bars()` already exists for bulk download; tier 3+4 in new `expanded_scanner.py` module |
| UNIV-05 | Expanded universe scan runs only during overnight window — live 60s bot loop keeps existing watchlist | Overnight daemon thread triggered by Alpaca calendar API; fully separate from existing `scanner.py` |
</phase_requirements>

---

## Summary

Phase 7 builds `expanded_scanner.py` — a new module that orchestrates a four-tier cascading pre-filter pipeline over 2,500+ stocks during the overnight window, then ranks survivors using a multi-factor quant model. The live scanner in `scanner.py` is untouched. This phase also integrates two external frameworks: MoneyAtlas SMC concepts (implemented as real Python detection functions) and NautilusTrader (backtesting validation layer for scanner pick quality).

The key implementation insight: the MoneyAtlas skill files are concept scaffolds (empty/mock Python classes) — the actual SMC algorithms must be written from scratch using OHLCV data. Three algorithmic patterns from the SMC domain are well-established and implementable with pure pandas/numpy: order block detection (via swing high/low identification), accumulation/distribution zone classification (via ADL + OBV divergence + price range compression), and liquidity sweep detection (price briefly exceeding prior swing highs/lows before reversing). A purpose-built open-source library (`smartmoneyconcepts` 0.0.27) provides exactly these functions as a pandas-based API.

NautilusTrader 1.225.0 is installable on Python 3.14 via pip but **requires pandas<3.0.0** — a version downgrade from the current pandas 3.0.1. This creates a hard environment conflict that makes NautilusTrader integration inadvisable for this phase. The planner must address this: either (a) skip NautilusTrader and use a simple pandas-based backtester instead, or (b) treat NautilusTrader as an isolated script run in a separate virtual environment. Option (a) is recommended given the constraint.

**Primary recommendation:** Build `expanded_scanner.py` with a four-tier pipeline using existing infra (`fetch_bulk_bars`, `get_full_universe`), implement SMC factor scoring using the `smartmoneyconcepts` package, and implement backtesting validation as a lightweight in-process pandas backtester rather than NautilusTrader (due to pandas version conflict).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `smartmoneyconcepts` | 0.0.27 | SMC layer detection: order blocks, liquidity sweeps, FVG, BOS/CHoCH | Pure Python, pandas-based, no Rust/C deps, Python 3 compatible, latest release April 3 2026 |
| `yfinance` (existing) | 1.2.0 | Bulk OHLCV download for pre-filter pipeline | Already in stack, `yf.download()` handles multi-symbol batches efficiently |
| `alpaca-py` (existing) | 0.43.2 | Trading calendar API for market close time detection | Already installed, `TradingClient.get_calendar()` is the DST-safe trigger mechanism |
| `pandas` (existing) | 3.0.1 | DataFrame operations throughout pipeline | Already in stack |
| `numpy` (existing) | 2.4.3 | Numerical factor calculations | Already in stack |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `concurrent.futures.ThreadPoolExecutor` (stdlib) | — | Parallel symbol fetching in overnight scan | Use for tier 4 deep scoring with up to 10-12 workers (overnight, no competition with live loop) |
| `json` (stdlib) | — | Results persistence to JSON file | For UNIV-05 restart survival |
| `threading` (stdlib) | — | Overnight daemon thread + timeout management | Same patterns as existing `bot.py` and `scanner.py` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `smartmoneyconcepts` | Custom hand-rolled SMC | smartmoneyconcepts is maintained, tested, pure pandas — hand-rolling adds weeks of complexity with no advantage |
| `smartmoneyconcepts` | `pandas-ta` | pandas-ta 0.4.71b0 CANNOT be installed on Python 3.14 — numba dependency fails build. Not an option. |
| In-process pandas backtester | NautilusTrader 1.225.0 | NautilusTrader requires `pandas<3.0.0`; project uses pandas 3.0.1. Downgrading would break the entire existing stack. Use pandas backtester instead. |
| `fetch_bulk_bars()` | Per-symbol sequential fetch | Bulk download is 10-50x faster; already implemented and tested in existing codebase |

### Installation

```bash
pip install smartmoneyconcepts==0.0.27
```

No other new packages required — all other dependencies are already installed.

**Version verification (executed 2026-04-17):**
- `smartmoneyconcepts`: 0.0.27 (latest, confirmed via `pip index versions`) [VERIFIED: pip registry]
- `nautilus_trader`: 1.225.0 available but conflicts with pandas 3.0.1 (requires `pandas<3.0.0`) [VERIFIED: pip dry-run]
- `pandas-ta`: 0.4.71b0 FAILS on Python 3.14 (numba build error) [VERIFIED: pip dry-run]

---

## Architecture Patterns

### Recommended Project Structure

The expanded scanner is a new standalone module. No existing files are modified except for integration hooks in `state.py`, `dashboard.py`, `server.py`, and `config.py`.

```
trading-bot/
├── expanded_scanner.py       # NEW — main module (tier pipeline + SMC scoring + overnight daemon)
├── smc_factors.py            # NEW — SMC layer detection functions using smartmoneyconcepts
├── quant_factors.py          # NEW — multi-factor quant model (momentum, value, quality, volatility)
├── data/
│   └── overnight_results.json  # NEW — persisted overnight scan results
├── scanner.py                # UNCHANGED — live 60s scanner
├── stock_universe.py         # UNCHANGED — universe builder (reused)
├── state.py                  # MODIFIED — add overnight_results, overnight_scan_status keys
├── dashboard.py              # MODIFIED — add /api/overnight/results and manual trigger routes
├── config.py                 # MODIFIED — add OVERNIGHT_SCAN_BATCH_SIZE, OVERNIGHT_SCAN_WORKERS, etc.
└── server.py                 # MODIFIED — start overnight daemon thread at startup
```

### Pattern 1: Four-Tier Cascading Pipeline

**What:** Each tier culls the symbol list before the next, more expensive tier runs. Data fetched once per tier is reused downstream.

**When to use:** Universal pattern for large-universe scanning where deep analysis is expensive.

```python
# Source: project pattern (matches existing scanner.py ThreadPoolExecutor approach)
def run_pipeline(universe: list[str]) -> list[dict]:
    # Tier 1: price + market cap gate (uses cached NASDAQ screener data already in stock_universe)
    t1 = _filter_price_mcap(universe)        # ~2500 → ~1500
    log.info("[expanded] T1 gate: %d survivors", len(t1))

    # Tier 2: volume gate — avg daily volume >500K
    bulk_5d = fetch_bulk_bars(t1, period="5d", interval="1d")  # single bulk download
    t2 = _filter_volume(t1, bulk_5d)         # ~1500 → ~600

    # Tier 3: momentum gate — positive 5-day return OR vol >1.5x 20-day avg
    bulk_20d = fetch_bulk_bars(t2, period="30d", interval="1d")  # bulk for 20-day avg
    t3 = _filter_momentum(t2, bulk_5d, bulk_20d)  # ~600 → ~200

    # Tier 4: heavy quant multi-factor scoring — produces ranked ~50
    survivors = _score_quant_multifactor(t3, bulk_20d)  # ~200 → top ~50
    return survivors
```

### Pattern 2: SMC Factor Scoring via `smartmoneyconcepts`

**What:** The `smartmoneyconcepts` library provides pandas-native functions for order block detection, liquidity level identification, BOS/CHoCH, and FVG. Each function returns a DataFrame with per-bar classification columns.

**When to use:** Tier 4 heavy quant scoring — extract latest values for each SMC indicator, normalize to 0-10 score, include as one factor in the multi-factor composite.

```python
# Source: [CITED: https://github.com/joshyattridge/smart-money-concepts]
import smartmoneyconcepts as smc

def compute_smc_score(df: pd.DataFrame) -> float:
    """
    Compute a 0-10 SMC factor score from OHLCV daily bars.
    Higher score = stronger accumulation evidence.
    """
    score = 0.0

    # Swing structure (required for order blocks and BOS)
    swings = smc.swing_highs_lows(df, swing_length=10)

    # Order blocks — look for bullish OB in recent bars
    ob = smc.ob(df, swings, close_mitigation=False)
    if ob is not None and not ob.empty:
        recent_ob = ob.tail(5)
        bullish_ob_count = (recent_ob["OB"] == 1).sum()
        score += min(bullish_ob_count * 1.5, 4.0)   # max 4 pts from OB

    # Liquidity sweeps — swept lows (bear traps = accumulation signal)
    liq = smc.liquidity(df, swings, range_percent=0.005)
    if liq is not None and not liq.empty:
        recent_swept = liq["Swept"].notna().tail(10).sum()
        score += min(recent_swept * 1.0, 3.0)   # max 3 pts from sweeps

    # BOS/CHoCH — break of structure confirms trend direction
    bos = smc.bos_choch(df, swings, close_break=True)
    if bos is not None and not bos.empty:
        recent = bos.tail(5)
        if (recent["BOS"] > 0).any():
            score += 2.0    # bullish BOS = strong momentum confirmation
        elif (recent["CHOCH"] > 0).any():
            score += 1.0    # CHoCH = potential reversal (weaker signal)

    # FVG — fair value gap indicates strong directional move
    fvg = smc.fvg(df)
    if fvg is not None and not fvg.empty:
        recent_bullish_fvg = (fvg["FVG"].tail(5) == 1).sum()
        score += min(recent_bullish_fvg * 0.5, 1.0)   # max 1 pt

    return round(min(score, 10.0), 2)
```

### Pattern 3: Multi-Factor Quant Score (Tier 4 Composite)

**What:** Four OHLCV-derived factors normalized to 0-10 and combined with weights. All factors computable from daily bars (no paid data required).

**Factors and derivation:**

| Factor | Derivation | Data Needed |
|--------|-----------|-------------|
| Momentum (30%) | 20-day return percentile rank across universe | 30-day daily bars |
| Quality (25%) | OBV trend slope + Accumulation/Distribution positive divergence from ADL | 30-day daily bars |
| SMC Layer (25%) | `compute_smc_score()` using `smartmoneyconcepts` | 30-day daily bars |
| Volatility/ATR (20%) | Inverse ATR% rank — lower recent volatility vs 20-day avg = higher score (steady accumulation) | 30-day daily bars |

```python
# Source: [ASSUMED] — standard quant factor scoring pattern
def compute_quant_score(symbol: str, df: pd.DataFrame,
                        momentum_rank: float,  # 0-1, pre-computed percentile rank
                        ) -> dict:
    closes = df["close"]

    # Momentum factor (pre-ranked outside this function for cross-sectional fairness)
    momentum_score = momentum_rank * 10.0

    # Quality factor: OBV rising + positive ADL slope
    obv_series = obv(df)
    adl_series = adl(df)
    obv_slope = float(np.polyfit(range(20), obv_series.tail(20), 1)[0])
    adl_slope = float(np.polyfit(range(20), adl_series.tail(20), 1)[0])
    quality_score = min(
        (5.0 if obv_slope > 0 else 0.0) + (5.0 if adl_slope > 0 else 0.0),
        10.0
    )

    # SMC factor
    smc_score = compute_smc_score(df)

    # Volatility factor: lower recent ATR% relative to 20-day baseline = higher score
    atr_series = atr(df, period=14)
    atr_pct = float(atr_series.iloc[-1]) / float(closes.iloc[-1])
    atr_20d_avg = float(atr_series.tail(20).mean()) / float(closes.tail(20).mean())
    vol_ratio = atr_pct / atr_20d_avg if atr_20d_avg > 0 else 1.0
    # vol_ratio < 1 = volatility contracting = accumulation signal
    volatility_score = max(0.0, min(10.0, (2.0 - vol_ratio) * 5.0))

    composite = (
        0.30 * momentum_score
        + 0.25 * quality_score
        + 0.25 * smc_score
        + 0.20 * volatility_score
    )

    return {
        "symbol":           symbol,
        "quant_score":      round(composite, 2),
        "momentum_score":   round(momentum_score, 2),
        "quality_score":    round(quality_score, 2),
        "smc_score":        round(smc_score, 2),
        "volatility_score": round(volatility_score, 2),
    }
```

### Pattern 4: Alpaca Calendar Trigger for Overnight Window

**What:** Use `TradingClient.get_calendar()` to find today's market close time, then compute `close_time + 15min` as the scan start.

**When to use:** Market close trigger in the overnight daemon thread.

```python
# Source: [CITED: https://alpaca.markets/sdks/python/api_reference/trading/calendar.html]
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetCalendarRequest
from datetime import date, datetime, timezone, timedelta

def get_market_close_today(trading_client: TradingClient) -> datetime | None:
    """Returns today's market close time as a UTC-aware datetime, or None if market closed."""
    today = date.today()
    try:
        req = GetCalendarRequest(start=today, end=today)
        calendar = trading_client.get_calendar(req)
        if not calendar:
            return None
        cal = calendar[0]
        # cal.close is a datetime.time in America/New_York
        close_dt = datetime.combine(today, cal.close)
        # Alpaca calendar times are Eastern; convert to UTC
        import pytz
        eastern = pytz.timezone("America/New_York")
        close_et = eastern.localize(close_dt)
        return close_et.astimezone(timezone.utc)
    except Exception as exc:
        log.warning("[expanded] Calendar fetch failed: %s", exc)
        return None

def _wait_for_scan_window(trading_client: TradingClient) -> bool:
    """Block until 15 minutes after market close. Returns True when ready."""
    close_utc = get_market_close_today(trading_client)
    if close_utc is None:
        return False
    scan_start = close_utc + timedelta(minutes=15)
    now = datetime.now(timezone.utc)
    if now < scan_start:
        wait_sec = (scan_start - now).total_seconds()
        log.info("[expanded] Waiting %.0f seconds until scan window...", wait_sec)
        time.sleep(wait_sec)
    return True
```

### Pattern 5: ETF Detection for UNIV-03

**What:** Filter out ETFs and preferred shares before tier 1 scoring.

```python
# Source: [ASSUMED] — standard pattern for ETF filtering without paid data
_ETF_KEYWORDS = frozenset(["ETF", "FUND", "TRUST", "INDEX", "PORTFOLIO"])
_ETF_SUFFIXES = frozenset(["Q", "P", "W"])  # warrants, preferred, rights — skip

def _is_etf_or_preferred(symbol: str, info: dict | None = None) -> bool:
    """Heuristic ETF/preferred filter. Info from yfinance.Ticker().info."""
    # Quote type check (most reliable when available)
    if info:
        quote_type = info.get("quoteType", "").upper()
        if quote_type in ("ETF", "MUTUALFUND", "MONEYMARKET", "CURRENCY"):
            return True
        name = info.get("longName", info.get("shortName", "")).upper()
        if any(kw in name for kw in _ETF_KEYWORDS):
            return True
    # Symbol heuristics for bulk pre-filter (when info not fetched yet)
    if len(symbol) > 4 and symbol[-1] in ("F",):  # some preferred share conventions
        return True
    return False
```

**Note:** For tier 1 bulk filtering, only symbol-based heuristics are available (no per-symbol info fetch yet). Per-symbol info fetches happen only in tier 4 for the ~200 survivors, making the `quoteType` check practical there.

### Pattern 6: JSON Persistence with Restart Survival

```python
# Source: [ASSUMED] — matches existing overnight_scanner.py DATA_DIR pattern
import json, os
from datetime import datetime, timezone

OVERNIGHT_RESULTS_PATH = os.path.join(os.path.dirname(__file__), "data", "overnight_results.json")

def save_overnight_results(results: list[dict], scan_meta: dict) -> None:
    os.makedirs(os.path.dirname(OVERNIGHT_RESULTS_PATH), exist_ok=True)
    payload = {
        "results": results,
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc).timestamp() + 18 * 3600),  # 18hr TTL
        **scan_meta,
    }
    with open(OVERNIGHT_RESULTS_PATH, "w") as f:
        json.dump(payload, f, indent=2)

def load_overnight_results() -> list[dict]:
    """Load cached overnight results if not expired (< 18 hours old)."""
    try:
        with open(OVERNIGHT_RESULTS_PATH) as f:
            payload = json.load(f)
        if datetime.now(timezone.utc).timestamp() < payload.get("expires_at", 0):
            return payload.get("results", [])
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return []
```

### Anti-Patterns to Avoid

- **Calling `fetch_bars()` per-symbol for 2,500+ stocks:** Use `fetch_bulk_bars()` for tiers 1-3 to avoid O(n) HTTP round-trips. Single `yf.download()` for batches of 200 is ~100x faster than sequential calls.
- **Fetching info for all 2,500 symbols:** `fetch_ticker_info()` is a per-symbol call. Only run it on tier 4 survivors (~200). Do NOT call it on the full universe.
- **Reusing `_score_symbol_multi()` from scanner.py for overnight:** D-10 explicitly forbids this. Build a separate quant-only scorer.
- **Installing pandas-ta or NautilusTrader without isolation:** Both create environment conflicts on Python 3.14. pandas-ta fails to build (numba). NautilusTrader downgrades pandas 3.0.1 → 2.3.3, breaking the existing stack.
- **Hardcoding 4PM ET as market close:** Use Alpaca calendar API. Early closes (Christmas Eve, day after Thanksgiving) end at 1PM ET — hardcoded 4PM misses those days.
- **Running overnight scan on the same ThreadPoolExecutor as live scanner:** They are separate pipelines (D-04). Overnight scan gets its own ThreadPoolExecutor with higher worker count (10-12) since it runs when the live loop is idle.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Order block detection from OHLCV | Custom swing + candle pattern logic | `smartmoneyconcepts.ob()` | Handles mitigation, returns structured DataFrame, tested across 27 versions |
| Liquidity sweep identification | Custom high/low tracking logic | `smartmoneyconcepts.liquidity()` | Returns `Swept` index per level — precisely what we need for accumulation scoring |
| BOS/CHoCH detection | Custom structure-break logic | `smartmoneyconcepts.bos_choch()` | Handles `close_break` parameter, directional, returns level and broken index |
| Fair Value Gap | Three-candle gap logic | `smartmoneyconcepts.fvg()` | Handles consecutive FVGs with `join_consecutive` option |
| Multi-symbol bulk bars | Per-symbol loop | `openbb_data.fetch_bulk_bars()` (existing) | Already rate-limited, FMP fallback included, tested |
| ETF constituent lists | Hard-coded lists | `stock_universe.get_full_universe()` (existing) | Already builds 2,500+ deduped list with breakdown stats |

**Key insight:** The MoneyAtlas SMC skill files are mock scaffolds (every method is either empty, returns hardcoded strings, or simulates with `"win/loss"` based on confidence threshold). Do not treat them as functional implementations — use `smartmoneyconcepts` for real OHLCV-based SMC detection.

---

## Runtime State Inventory

> Omitted — this is a greenfield module addition, not a rename/refactor phase. No existing stored strings, OS registrations, or build artifacts need migration.

---

## Common Pitfalls

### Pitfall 1: pandas-ta Cannot be Installed on Python 3.14
**What goes wrong:** `pip install pandas-ta` fails with `RuntimeError: Cannot install on Python version 3.14.3; only versions >=3.10,<3.14 are supported.` during numba wheel build.
**Why it happens:** `pandas-ta` 0.4.71b0 depends on `numba==0.61.2` which explicitly blocks Python 3.14+.
**How to avoid:** Use `smartmoneyconcepts` for SMC indicators. Do NOT use pandas-ta in this project.
**Warning signs:** Any attempt to `pip install pandas-ta` will fail immediately with the numba version error.

### Pitfall 2: NautilusTrader Downgrades pandas
**What goes wrong:** `pip install nautilus_trader` succeeds but downgrades pandas from 3.0.1 to 2.3.3. This breaks yfinance 1.2.0 (which expects pandas 3.x), `openbb_data.py`, and the entire existing codebase.
**Why it happens:** NautilusTrader 1.225.0 pins `pandas<3.0.0,>=2.3.3`.
**How to avoid:** Do NOT install NautilusTrader in the main project environment. If backtesting validation is desired, build a standalone `backtester.py` using pure pandas (already partially exists as `backtester.py` in the repo root).
**Warning signs:** After installing nautilus_trader, import errors in `openbb_data.py` or yfinance calls break.

### Pitfall 3: yfinance Rate Limiting at 2,500 Symbol Scale
**What goes wrong:** Bulk `yf.download()` calls for 200+ symbols trigger Yahoo Finance 429 (rate limit) errors after a few batches.
**Why it happens:** Yahoo Finance has tightened free-tier rate limits. The existing `yf_limiter.py` token bucket (2 req/sec) helps, but `yf.download()` counts as multiple internal requests.
**How to avoid:** Process symbols in batches of 100-150 (not 200+) with 2-3 second sleep between batches. Use `yf.download(group_by="ticker")` for clean per-symbol splitting. The existing `fetch_bulk_bars()` already handles this pattern.
**Warning signs:** `YFRateLimitError` in logs; partial results from `yf.download()` with many NaN columns.

### Pitfall 4: `smartmoneyconcepts.ob()` Requires Pre-computed Swings
**What goes wrong:** Calling `smc.ob(df, swings)` with a `swings` DataFrame that has no swing points (all NaN) causes empty output or exceptions.
**Why it happens:** Thinly-traded stocks or very short DataFrames (< 20 bars) may produce no detected swings with `swing_length=10`.
**How to avoid:** Check `swings["HighLow"].notna().any()` before passing to `ob()`, `bos_choch()`, and `liquidity()`. Return `smc_score = 0.0` (neutral, not penalized) if swings are empty.
**Warning signs:** Empty `ob` DataFrames for many small-cap stocks; silently zero SMC scores for all Russell 2000 names.

### Pitfall 5: `cal.close` on Alpaca Calendar Object is a `datetime.time`, Not UTC
**What goes wrong:** Treating `calendar[0].close` as UTC time causes the overnight scan to trigger 4-5 hours late (Eastern → UTC offset not applied).
**Why it happens:** Alpaca calendar API returns times in Eastern timezone (America/New_York). The `.close` attribute is a `datetime.time` object without timezone info.
**How to avoid:** Always localize with `pytz.timezone("America/New_York")` before converting to UTC. See Pattern 4 above.
**Warning signs:** Scan running at 9PM ET instead of 4:15PM ET.

### Pitfall 6: ETF-Heavy Russell 2000 Proxy Leaking Through Tier 1
**What goes wrong:** Russell 2000 proxy from `get_russell2000()` includes some ETFs because the NASDAQ screener doesn't always set `quoteType=ETF` for all fund-of-funds structures.
**Why it happens:** The screener data uses market cap range as a proxy, which catches some ETFs with mid-range market caps.
**How to avoid:** Apply symbol-pattern ETF filter in tier 1 (check for ETF name suffixes) AND apply `quoteType` check in tier 4 when `fetch_ticker_info()` is called per-symbol for finalists.
**Warning signs:** Symbols like `IBTK`, `SPDW` appearing in tier 4 survivors (these are ETFs).

### Pitfall 7: Two-Hour Timeout Must Save Partial Results
**What goes wrong:** If the scan hits the 2-hour timeout while still scoring tier 4 symbols, all work is discarded.
**Why it happens:** Not persisting intermediate results before the timeout expires.
**How to avoid:** After each tier completes, save the intermediate state to the JSON file (or at minimum after tier 3). Implement a `_scan_deadline` timestamp checked in the tier 4 scoring loop.
**Warning signs:** Overnight scan consistently timing out without saving any results.

---

## Code Examples

Verified patterns from official sources:

### Alpaca Calendar — Get Today's Close Time
```python
# Source: [CITED: https://alpaca.markets/sdks/python/api_reference/trading/calendar.html]
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetCalendarRequest
from datetime import date
import pytz

def get_today_close_utc(client: TradingClient):
    today = date.today()
    cal = client.get_calendar(GetCalendarRequest(start=today, end=today))
    if not cal:
        return None
    eastern = pytz.timezone("America/New_York")
    from datetime import datetime
    close_naive = datetime.combine(today, cal[0].close)
    return eastern.localize(close_naive).astimezone(__import__('datetime').timezone.utc)
```

### smartmoneyconcepts — Order Block Detection
```python
# Source: [CITED: https://github.com/joshyattridge/smart-money-concepts]
import smartmoneyconcepts as smc
import pandas as pd

# df must have lowercase columns: open, high, low, close, volume
swings = smc.swing_highs_lows(df, swing_length=10)
ob_df  = smc.ob(df, swings, close_mitigation=False)
liq_df = smc.liquidity(df, swings, range_percent=0.005)
bos_df = smc.bos_choch(df, swings, close_break=True)
fvg_df = smc.fvg(df, join_consecutive=False)

# ob_df columns: OB (1=bullish, -1=bearish), Top, Bottom, OBVolume, Percentage
# liq_df columns: Liquidity, Level, End, Swept
# bos_df columns: BOS, CHOCH, Level, BrokenIndex
# fvg_df columns: FVG (1=bullish, -1=bearish), Top, Bottom, MitigatedIndex
```

### yfinance Bulk Download — Batch Pattern
```python
# Source: [CITED: openbb_data.py fetch_bulk_bars + yfinance documented API]
import yfinance as yf

def _batch_download(symbols: list[str], period: str = "30d",
                    interval: str = "1d",
                    batch_size: int = 150) -> dict[str, pd.DataFrame]:
    import time
    result = {}
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        try:
            raw = yf.download(
                batch,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            for sym in batch:
                try:
                    sym_df = raw[sym].dropna(how="all")
                    sym_df.columns = [c.lower() for c in sym_df.columns]
                    if not sym_df.empty:
                        result[sym] = sym_df
                except (KeyError, TypeError):
                    pass
        except Exception as exc:
            log.warning("[expanded] Batch download failed (batch %d): %s", i // batch_size, exc)
        if i + batch_size < len(symbols):
            time.sleep(2.5)  # rate limiting between batches
    return result
```

### In-Process Backtester (pandas-only, avoids NautilusTrader conflict)
```python
# Source: [ASSUMED] — simple vectorized backtest pattern
def backtest_scanner_picks(results: list[dict],
                           forward_bars: dict[str, pd.DataFrame]) -> dict:
    """
    Measure scanner pick quality by computing forward 3-day returns for all
    overnight survivors. Outputs win rate and avg return.
    """
    wins, total, returns = 0, 0, []
    for r in results:
        sym = r["symbol"]
        fwd = forward_bars.get(sym)
        if fwd is None or len(fwd) < 4:
            continue
        entry_close = float(fwd["close"].iloc[0])
        exit_close  = float(fwd["close"].iloc[3])   # 3-bar forward
        ret = (exit_close - entry_close) / entry_close
        returns.append(ret)
        total += 1
        if ret > 0:
            wins += 1
    win_rate = wins / total if total > 0 else 0.0
    avg_ret = sum(returns) / len(returns) if returns else 0.0
    return {"win_rate": round(win_rate, 3), "avg_return": round(avg_ret, 4), "n": total}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| TA-Lib C extension for indicators | pandas-ta (pure Python) | 2021 onward | TA-Lib still requires compiled C; pandas-ta is pure Python — but fails on Python 3.14 due to numba |
| Manual order block logic | `smartmoneyconcepts` library | 2023 library, updated April 2026 | Purpose-built library with 27 versions; covers all main SMC indicators |
| NautilusTrader for lightweight backtesting | Simple pandas vectorized backtester | NautilusTrader added pandas version pin in 2024 | NautilusTrader is overkill for a validation layer and conflicts with pandas 3.x |
| `yf.Ticker(sym).history()` per-symbol | `yf.download([list], group_by="ticker")` | Always preferred; most relevant in 2,500+ stock context | Batch is essential at scale; sequential calls would take 20+ minutes for 2,500 stocks |

**Deprecated/outdated:**
- `pandas-ta` for Python 3.14+: numba blocks installation — use `smartmoneyconcepts` for SMC-specific indicators, and the existing `indicators.py` for RSI/MACD/ATR/OBV/ADL
- NautilusTrader in shared Python environment: pandas version conflict makes it unsafe to install without a separate venv

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | SMC factor weights (momentum 30%, quality 25%, SMC 25%, volatility 20%) produce meaningful differentiation | Pattern 3 | If wrong: rebalance weights during implementation, no structural change needed |
| A2 | Tier output sizes (T1: ~1500, T2: ~600, T3: ~200, T4: ~50) approximate correctly with chosen thresholds | Pattern 1 | If wrong: adjust thresholds; pipeline structure unchanged |
| A3 | `smartmoneyconcepts` works correctly with pandas 3.0.1 | Standard Stack | It uses pure pandas operations; `pip install` dry-run shows no pandas version constraint. Low risk. |
| A4 | `cal.close` on `alpaca-py` Calendar object returns a `datetime.time` in Eastern time | Pattern 4 | If the object returns UTC, pytz localize step would double-convert. Verify against actual Calendar model. |
| A5 | Batch size of 150 symbols per `yf.download()` call avoids rate limiting | Pattern (bulk download) | If too aggressive: reduce to 100. If too conservative: fine to increase. |
| A6 | `overnight_scanner.py` (already in repo) is the prior Phase 9 stub — it uses `predict_batch()` not the quant pipeline, and is not considered the Phase 7 implementation | Architecture | If it's meant to be the Phase 7 file: re-scope the new module to extend rather than replace it |

---

## Open Questions

1. **`overnight_scanner.py` already exists in the repo — is it Phase 7 or Phase 9 stub?**
   - What we know: The file exists, runs `predict_batch()` from `prediction.py`, and saves to `data/overnight_predictions.json`
   - What's unclear: CONTEXT.md says Phase 7 builds the "expanded scanner" (pipeline + quant scoring); Phase 9 (OVNT-01 through OVNT-05) adds the "tomorrow's game plan" dashboard UI. The existing `overnight_scanner.py` appears to be a Phase 9 partial implementation.
   - Recommendation: Build new `expanded_scanner.py` for Phase 7's pipeline+quant work. Leave `overnight_scanner.py` for Phase 9 to extend with the UI and approve/reject logic. Planner should confirm this separation.

2. **Thread pool worker count for overnight scan**
   - What we know: Live scanner uses 5 workers (avoids yfinance rate limits). Overnight runs when live loop is idle.
   - What's unclear: How many workers can overnight safely use? Claude's discretion per CONTEXT.md.
   - Recommendation: Use 8-10 workers for tier 4 deep scoring (fewer HTTP calls at that point, mostly CPU-bound factor computation). Keep bulk download batches at 150/batch with 2.5s sleep regardless of worker count.

3. **`smartmoneyconcepts` swing_length parameter for daily bars**
   - What we know: `swing_length=50` is the default (suitable for intraday). For daily bars with 30-day lookback, only 30 bars are available.
   - What's unclear: Appropriate `swing_length` for daily 30-day bars.
   - Recommendation: Use `swing_length=5` for daily bars (5-day swings = weekly structure) as a starting point. Adjust if SMC scores appear uniformly zero.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.14 | All | ✓ | 3.14.3 | — |
| yfinance | Tier 1-3 bulk download | ✓ | 1.2.0 | — |
| pandas | All factor calculations | ✓ | 3.0.1 | — |
| numpy | ATR, OBV, factor math | ✓ | 2.4.3 | — |
| alpaca-py | Calendar API trigger | ✓ | 0.43.2 | — |
| Flask | Dashboard integration routes | ✓ | 3.1.3 | — |
| `smartmoneyconcepts` | SMC factor scoring | ✗ (not yet installed) | — | Must install: `pip install smartmoneyconcepts==0.0.27` |
| `pandas-ta` | (considered for factors) | ✗ | BLOCKED | Use `smartmoneyconcepts` + existing `indicators.py` |
| `nautilus_trader` | (considered for backtest) | ✗ | CONFLICT | Use pandas vectorized backtester in `backtester.py` |
| `pytz` | Calendar timezone conversion | ✓ (implied by alpaca-py) | bundled | Use `zoneinfo` (stdlib Python 3.9+) if pytz absent |

**Missing dependencies with no fallback:**
- `smartmoneyconcepts` — must install before tier 4 SMC scoring works

**Missing dependencies with fallback:**
- `pytz` — can use `zoneinfo.ZoneInfo("America/New_York")` from Python stdlib if not available

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | none (pytest auto-discovers `tests/`) |
| Quick run command | `py -3 -m pytest tests/test_scanner.py -x -q` |
| Full suite command | `py -3 -m pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UNIV-01 | `get_full_universe()` includes S&P 500 and NASDAQ 100 | unit | `py -3 -m pytest tests/test_expanded_scanner.py::test_universe_includes_indices -x` | ❌ Wave 0 |
| UNIV-02 | Unusual volume (>2x 20-day avg) stocks included in T3 gate survivors | unit | `py -3 -m pytest tests/test_expanded_scanner.py::test_unusual_volume_passes_t3 -x` | ❌ Wave 0 |
| UNIV-03 | ETFs/preferred/OTC filtered at tier 1; price $5-$200; vol >500K; mcap >$100M | unit | `py -3 -m pytest tests/test_expanded_scanner.py::test_tier1_filters -x` | ❌ Wave 0 |
| UNIV-04 | Full pipeline produces ≤50 survivors; survivors have quant_score ≥ 0 | integration | `py -3 -m pytest tests/test_expanded_scanner.py::test_pipeline_produces_survivors -x` | ❌ Wave 0 |
| UNIV-05 | `expanded_scanner.py` has no imports from scanner.py scoring path; overnight daemon isolated | unit | `py -3 -m pytest tests/test_expanded_scanner.py::test_pipeline_isolation -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `py -3 -m pytest tests/test_expanded_scanner.py -x -q`
- **Per wave merge:** `py -3 -m pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_expanded_scanner.py` — covers UNIV-01 through UNIV-05
- [ ] `tests/test_smc_factors.py` — covers SMC score computation with mocked OHLCV data
- [ ] `tests/test_quant_factors.py` — covers momentum/quality/volatility factor computation

*(Existing `tests/test_scanner.py` tests the live scanner only — no overlap with expanded scanner tests needed)*

---

## Security Domain

> `security_enforcement` not explicitly set to false — including section.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Dashboard runs on localhost, no auth added |
| V3 Session Management | No | No sessions in bot |
| V4 Access Control | No | Local bot only |
| V5 Input Validation | Yes | Symbol strings validated (no `"."`, max 5 chars) before passing to yfinance or SMC functions |
| V6 Cryptography | No | No cryptographic operations |

### Known Threat Patterns for Overnight Scanner

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Symbol injection via NASDAQ screener API | Tampering | Filter symbol strings: `re.match(r'^[A-Z]{1,5}$', symbol)` before use in yfinance calls |
| JSON file path traversal | Tampering | Use `os.path.join(DATA_DIR, "overnight_results.json")` with fixed DATA_DIR; never user-supplied path |
| Unbounded result size in state | Tampering | Cap `overnight_results` list at 100 entries before writing to shared_state |

---

## Sources

### Primary (HIGH confidence)
- `smartmoneyconcepts` PyPI page + pip dry-run — package availability, version 0.0.27, release date April 3 2026 [VERIFIED: pip registry]
- `nautilus_trader` pip dry-run — confirms Python 3.14 wheel available but pandas 3.0.1 conflict [VERIFIED: pip dry-run]
- `pandas-ta` pip dry-run — confirms installation failure on Python 3.14 due to numba [VERIFIED: pip dry-run]
- Existing codebase (`openbb_data.py`, `stock_universe.py`, `scanner.py`, `indicators.py`) — reusable patterns and existing implementations [VERIFIED: codebase grep]

### Secondary (MEDIUM confidence)
- [smartmoneyconcepts GitHub README](https://github.com/joshyattridge/smart-money-concepts) — API signatures for `ob()`, `liquidity()`, `bos_choch()`, `fvg()`, `swing_highs_lows()`
- [Alpaca-py Calendar API docs](https://alpaca.markets/sdks/python/api_reference/trading/calendar.html) — `GetCalendarRequest`, `get_calendar()` usage
- [NautilusTrader backtesting docs](https://nautilustrader.io/docs/latest/getting_started/backtest_low_level/) — confirms BacktestEngine API structure

### Tertiary (LOW confidence)
- Factor weights (30%/25%/25%/20%) — training knowledge, no empirical validation in this session [ASSUMED: A1]
- Tier output size estimates (~1500/~600/~200/~50) — heuristic based on typical filter ratios [ASSUMED: A2]

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified via pip dry-run on actual project environment
- Architecture: MEDIUM — patterns derived from existing codebase conventions + official library docs
- Pitfalls: HIGH — environment conflicts confirmed via actual pip dry-run execution
- SMC factor scoring: MEDIUM — library API confirmed, factor weights are assumed starting points

**Research date:** 2026-04-17
**Valid until:** 2026-05-17 (30 days; `smartmoneyconcepts` is in active development, check for API changes)
