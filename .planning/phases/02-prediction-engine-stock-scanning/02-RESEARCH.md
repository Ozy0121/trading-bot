# Phase 2: Prediction Engine + Stock Scanning - Research

**Researched:** 2026-03-28
**Domain:** Multi-strategy stock scoring, parallel scanning, news sentiment, sector ETF momentum
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Use lightweight strategy functions (not ABC class hierarchy). A `strategies/` directory with one module per strategy, each exporting a `scan(symbol, df) -> Candidate` function. A simple registry dict maps strategy names to scan functions.
- **D-02:** Three strategies: MomentumStrategy (STRAT-02), MeanReversionStrategy (STRAT-03), CatalystStrategy wrapping existing `catalysts.py` (STRAT-04).
- **D-03:** 0-10 composite conviction score: technical 40%, volume 20%, sentiment 20%, sector 20%. Each sub-score is 0-10 independently, then combined.
- **D-04:** Weights stored in config (env vars) for tuning without code changes.
- **D-05:** Conviction breakdown dict with every candidate: `{"technical": 7.5, "volume": 8.0, "sentiment": 5.0, "sector": 6.0, "composite": 6.7}`.
- **D-06:** Alpaca news API as primary source for per-stock headlines. Supplement with existing Yahoo RSS feed from `sentiment.py`.
- **D-07:** Simple keyword/phrase scoring — no ML model, no external NLP API. Count bullish/bearish keywords in headlines, compute net sentiment score.
- **D-08:** Cache sentiment per symbol with 30-minute TTL.
- **D-09:** yfinance `Ticker.calendar` for earnings dates. Cache per day.
- **D-10:** Earnings within 3 days reduces conviction score (risk factor), not a hard block.
- **D-11:** Sector ETFs: XLK, XLE, XLF, XLV, XLI, XLC, XLY, XLP, XLU, XLRE, XLB. Map each watchlist stock to its sector ETF.
- **D-12:** Sector momentum = ETF % change over last 5 days. Top 3 sectors get a boost in sector sub-score for their member stocks.
- **D-13:** ThreadPoolExecutor for parallel bar fetching. Target < 15 seconds total scan time.
- **D-14:** yfinance remains the bar data source for scanning.
- **D-15:** Curated watchlist of 20-30 stocks in config (env var), same pattern as existing WATCHLIST. Dashboard UI editing comes in Phase 5.
- **D-16:** Every scan cycle logs: all candidates with scores, which signals fired/didn't fire, final composite score, threshold pass/fail.
- **D-17:** Skip reasoning logged at INFO level: `"Skipped AAPL (6.2/10): technical=7, volume=3, sentiment=8, sector=6 — volume sub-score below threshold."`

### Claude's Discretion

- Exact scoring formulas within each sub-score (how RSI maps to 0-10, how volume ratio maps to 0-10, etc.)
- Earnings date proximity penalty amount
- ThreadPoolExecutor max_workers count
- Whether to keep the existing `_score_symbol()` function or fully replace it
- Internal module organization (single file vs strategies/ directory)
- How to handle symbols that fail to fetch (skip silently vs log warning)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STRAT-01 | Strategy registry — each strategy implements `scan(symbol, df) -> Candidate` | Functional registry dict pattern; no ABC needed |
| STRAT-02 | MomentumStrategy: price breaking N-day high on >2x average volume | N-day rolling high via `closes.rolling(N).max()`, volume ratio vs 20-bar avg |
| STRAT-03 | MeanReversionStrategy: RSI < 35 at support (lower Bollinger Band) | Existing `indicators.py` RSI + BB functions reusable directly |
| STRAT-04 | CatalystStrategy wraps existing ARK/analyst scoring from `catalysts.py` | `get_catalysts()` already returns per-symbol flags; wrap into 0-10 score |
| STRAT-05 | Combined 0-10 conviction scoring with breakdown (technical, volume, sentiment, sector) | Weighted average formula verified; weights in config |
| STRAT-06 | Scanner aggregates all strategy results into unified ranked list | Replace `scan()` in `scanner.py` maintaining `scan(watchlist) -> list[dict]` interface |
| SCAN-01 | ThreadPoolExecutor parallel bar fetching | Verified: 35 symbols in ~1.5s parallel vs ~10s+ sequential |
| SCAN-02 | Sector/theme scanning via ETF performance (XLK, XLE, XLF, etc.) | `yf.download(etfs, period='5d', interval='1d')` in <1s; sector lookup via `Ticker.info` |
| SCAN-03 | Curated watchlist 20-30 stocks via config | Extend existing WATCHLIST env var pattern in `config.py` |
| SCAN-04 | Replace top-daily-movers with multi-day hold candidates scored for 1-3 day swing potential | Momentum/MeanReversion strategies inherently target 1-3 day swings |
| SCAN-05 | Scan completes in under 15 seconds for 35-40 symbols | Full scan simulation measured at 2.5s; well within budget |
| PRED-01 | News sentiment from Alpaca news API and financial RSS feeds | `NewsClient` + `NewsRequest` confirmed available in alpaca-py 0.43.2; Yahoo RSS fallback works |
| PRED-02 | Unusual volume spike detection (2x+ normal) factored into conviction | Volume sub-score formula: 2x=5/10 (threshold), 5x=10/10 |
| PRED-03 | Earnings date awareness factored into risk assessment | `yf.Ticker(sym).calendar['Earnings Date']` confirmed working; day-until calculation tested |
| PRED-04 | Only trades with conviction >= 7/10 executed; lower scores skipped with logged reasoning | Filter in `best_buy()`; log skip reason at INFO level |
| PRED-05 | Every trade entry and skip logged with full reasoning breakdown | `log_trade_event()` pattern already established; extend with breakdown dict |
</phase_requirements>

---

## Summary

Phase 2 replaces the current binary SMA-crossover scanner with a multi-strategy conviction scoring system. The existing codebase provides strong reusable foundations: `indicators.py` (RSI, MACD, Bollinger Bands), `catalysts.py` (ARK + analyst upgrade caching), and `scanner.py` (yfinance bar fetching, parallel architecture). The new system adds three independently-scored strategies that combine into a single 0-10 composite score.

Performance benchmarks on the actual machine confirm the 15-second target is achievable: parallel bar fetching for 35 symbols completes in ~1.5 seconds, sector ETF batch download in ~1 second, and a full simulated scan pipeline (bars + scoring) runs in ~2.5 seconds. The Alpaca `NewsClient` API is confirmed available in alpaca-py 0.43.2 with `symbols`, `limit`, and date filtering. Yahoo Finance RSS serves as the fallback sentiment source.

The critical integration constraint is backward compatibility: `bot.py` calls `scanner.scan(watchlist) -> list[dict]` and `scanner.best_buy(results) -> dict | None`. The new scanner must maintain these exact signatures. New keys (conviction breakdown, strategy name, skip reason) are additive extensions to the existing result dict format.

**Primary recommendation:** Replace `scanner._score_symbol()` with a multi-strategy orchestrator that calls all three strategy functions, aggregates sub-scores, and produces a conviction breakdown dict. Keep `scan()` and `best_buy()` signatures identical. Add new state keys for scan results without removing existing ones.

---

## Standard Stack

### Core (No New Dependencies Required)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| yfinance | 1.2.0 (installed) | Bar data, sector info, earnings dates | Already used in `scanner.py`; batch download confirmed fast |
| pandas | 3.0.1 (installed) | OHLCV DataFrame manipulation | Core data layer throughout codebase |
| numpy | 2.4.3 (installed) | Numerical indicator computations | Used in `indicators.py` |
| requests | 2.32.5 (installed) | Yahoo RSS news fetching | Already used in `catalysts.py` and `sentiment.py` |
| concurrent.futures | stdlib | ThreadPoolExecutor for parallel scanning | No install needed; Python stdlib |
| alpaca-py | 0.43.2 (installed) | Alpaca `NewsClient` for per-stock headlines | `NewsClient` + `NewsRequest` confirmed available |

### Supporting (Already Installed)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| xml.etree.ElementTree | stdlib | Parse Yahoo Finance RSS XML | Used in `catalysts.py` and `sentiment.py` |
| threading | stdlib | Cache TTL management, background threads | Module-level cache guards |

### What NOT to Install

| Avoided | Reason |
|---------|--------|
| pandas-ta | NOT installed; not needed — custom `indicators.py` handles RSI/MACD/BB |
| TA-Lib | Windows C extension — excluded from project (STATE.md decision) |
| NLTK / spaCy | Overkill — keyword counting is sufficient for D-07 |
| vaderSentiment | External dependency not justified — keyword list achieves same result |

**Installation:** No new packages required. All dependencies already installed.

**Version verification (confirmed 2026-03-28):**
- yfinance 1.2.0, alpaca-py 0.43.2, pandas 3.0.1, numpy 2.4.3, requests 2.32.5

---

## Architecture Patterns

### Recommended Project Structure

```
scanner.py          # Updated: orchestrator, keeps scan()/best_buy() interface
strategies/
├── __init__.py     # Registry dict: {"momentum": momentum_scan, ...}
├── momentum.py     # MomentumStrategy — N-day high breakout + volume
├── mean_reversion.py  # MeanReversionStrategy — RSI < 35 at lower BB
└── catalyst.py     # CatalystStrategy — wraps catalysts.py get_catalysts()
sentiment_cache.py  # Per-symbol news sentiment with 30-min TTL (NEW MODULE)
config.py           # Extended: SWING_WATCHLIST, conviction weights, CONVICTION_THRESHOLD
state.py            # Extended: add scan_results, last_scan_time keys
```

### Pattern 1: Strategy Function Signature

Each strategy module exports a single `scan` function:

```python
# strategies/momentum.py
from __future__ import annotations
import pandas as pd

def scan(symbol: str, df: pd.DataFrame) -> dict:
    """
    MomentumStrategy: price breaking N-day high on >2x average volume.
    Returns sub-score components (not the composite).
    """
    closes = df["close"]
    volumes = df["volume"]

    N = 20  # N-day high lookback
    rolling_high = closes.rolling(N).max()
    curr_close = float(closes.iloc[-1])
    prev_high = float(rolling_high.iloc[-2]) if len(rolling_high.dropna()) >= 2 else curr_close

    breakout = curr_close > prev_high

    avg_vol = float(volumes.tail(20).mean()) if len(volumes) >= 20 else float(volumes.mean())
    curr_vol = float(volumes.iloc[-1])
    volume_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0

    # Proximity to N-day high (0-10 technical sub-component)
    n_day_low = float(closes.rolling(N).min().iloc[-1])
    price_range = prev_high - n_day_low
    if price_range > 0:
        proximity_score = min(10.0, (curr_close - n_day_low) / price_range * 10)
    else:
        proximity_score = 5.0

    # Breakout bonus
    if breakout:
        proximity_score = min(10.0, proximity_score + 2.0)

    return {
        "strategy": "momentum",
        "fired": breakout and volume_ratio >= 2.0,
        "technical_score": round(proximity_score, 2),
        "volume_ratio": round(volume_ratio, 2),
        "details": {
            "breakout": breakout,
            "n_day_high": round(prev_high, 4),
            "curr_close": round(curr_close, 4),
        }
    }
```

### Pattern 2: Strategy Registry

```python
# strategies/__init__.py
from strategies.momentum import scan as momentum_scan
from strategies.mean_reversion import scan as mean_reversion_scan
from strategies.catalyst import scan as catalyst_scan

REGISTRY: dict[str, callable] = {
    "momentum":      momentum_scan,
    "mean_reversion": mean_reversion_scan,
    "catalyst":      catalyst_scan,
}
```

### Pattern 3: Conviction Score Composition

```python
# In scanner.py — the aggregator
def _compute_conviction(
    symbol: str,
    df: pd.DataFrame,
    sentiment_score: float,   # 0-10, from sentiment_cache
    sector_score: float,      # 0-10, from sector ETF ranking
) -> dict:
    """Run all strategies, combine into 0-10 composite conviction score."""
    from strategies import REGISTRY

    strategy_results = {}
    for name, strategy_fn in REGISTRY.items():
        try:
            result = strategy_fn(symbol, df)
            strategy_results[name] = result
        except Exception as exc:
            log.warning("[scanner] %s strategy failed for %s: %s", name, symbol, exc)
            strategy_results[name] = {"fired": False, "technical_score": 0.0, "volume_ratio": 1.0}

    # Best technical score across all strategies that fired
    fired_results = [r for r in strategy_results.values() if r.get("fired")]
    if fired_results:
        technical_score = max(r["technical_score"] for r in fired_results)
    else:
        # Partial credit even if no strategy fully fired
        technical_score = max(
            (r.get("technical_score", 0.0) * 0.5 for r in strategy_results.values()),
            default=0.0
        )

    # Volume score from best strategy's volume ratio
    best_vol_ratio = max(
        (r.get("volume_ratio", 1.0) for r in strategy_results.values()),
        default=1.0
    )
    volume_score = _volume_ratio_to_score(best_vol_ratio)

    # Composite (weighted average per D-03)
    composite = (
        technical_score * config.CONVICTION_WEIGHT_TECHNICAL +
        volume_score    * config.CONVICTION_WEIGHT_VOLUME    +
        sentiment_score * config.CONVICTION_WEIGHT_SENTIMENT +
        sector_score    * config.CONVICTION_WEIGHT_SECTOR
    )

    return {
        "technical":  round(technical_score, 2),
        "volume":     round(volume_score, 2),
        "sentiment":  round(sentiment_score, 2),
        "sector":     round(sector_score, 2),
        "composite":  round(composite, 2),
        "strategies_fired": [name for name, r in strategy_results.items() if r.get("fired")],
    }
```

### Pattern 4: Per-Symbol Sentiment Cache

```python
# sentiment_cache.py — new module
import time
from datetime import datetime, timezone, timedelta
import requests
import xml.etree.ElementTree as ET
from alpaca.data.historical import NewsClient
from alpaca.data.requests import NewsRequest
import config
from logger_setup import get_logger

log = get_logger()

SENTIMENT_TTL = 1800  # 30 minutes (D-08)
_cache: dict[str, tuple[float, float]] = {}  # symbol -> (timestamp, score)

_BULLISH_KEYWORDS = [
    "upgrade", "upgrades", "upgraded", "outperform", "overweight",
    "price target raised", "strong buy", "buy rating", "bullish", "rally",
    "beat", "beats", "record", "surges", "soars", "jumps", "initiates",
]
_BEARISH_KEYWORDS = [
    "downgrade", "downgrades", "downgraded", "underperform", "underweight",
    "price target cut", "sell rating", "bearish", "falls", "drops", "plunges",
    "misses", "miss", "warning", "concern", "decline",
]

def get_sentiment_score(symbol: str) -> float:
    """Return 0-10 sentiment score for symbol. Uses 30-min cache."""
    now = time.time()
    if symbol in _cache:
        ts, score = _cache[symbol]
        if now - ts < SENTIMENT_TTL:
            return score

    score = _fetch_sentiment(symbol)
    _cache[symbol] = (now, score)
    return score


def _fetch_sentiment(symbol: str) -> float:
    """Fetch from Alpaca news API, fall back to Yahoo RSS."""
    headlines = _fetch_alpaca_news(symbol) or _fetch_yahoo_rss(symbol)
    if not headlines:
        return 5.0  # neutral fallback

    bull = sum(1 for h in headlines if any(kw in h.lower() for kw in _BULLISH_KEYWORDS))
    bear = sum(1 for h in headlines if any(kw in h.lower() for kw in _BEARISH_KEYWORDS))
    total = bull + bear + max(0, len(headlines) - bull - bear)

    raw = (bull - bear) / total if total > 0 else 0.0  # -1 to +1
    return round((raw + 1) / 2 * 10, 2)  # map to 0-10


def _fetch_alpaca_news(symbol: str) -> list[str] | None:
    """Fetch headlines from Alpaca NewsClient."""
    try:
        client = NewsClient(api_key=config.API_KEY, secret_key=config.SECRET_KEY)
        start = datetime.now(timezone.utc) - timedelta(days=3)
        req = NewsRequest(symbols=symbol, limit=10, start=start)
        result = client.get_news(req)
        if hasattr(result, 'news') and result.news:
            return [n.headline for n in result.news]
    except Exception as exc:
        log.debug("[sentiment_cache] Alpaca news failed for %s: %s", symbol, exc)
    return None


def _fetch_yahoo_rss(symbol: str) -> list[str] | None:
    """Fallback: fetch headlines from Yahoo Finance RSS."""
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        return [(item.findtext("title") or "") for item in root.findall(".//item")[:10]]
    except Exception:
        return None
```

### Pattern 5: Sector Momentum Scoring

```python
# In scanner.py — sector scoring (run once per scan cycle, not per symbol)
import yfinance as yf

SECTOR_ETFS = ["XLK","XLE","XLF","XLV","XLI","XLC","XLY","XLP","XLU","XLRE","XLB"]

SECTOR_ETF_MAP = {
    "Technology": "XLK", "Energy": "XLE", "Financial Services": "XLF",
    "Financials": "XLF", "Healthcare": "XLV", "Industrials": "XLI",
    "Communication Services": "XLC", "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP", "Utilities": "XLU", "Real Estate": "XLRE",
    "Basic Materials": "XLB",
}

def _fetch_sector_scores() -> dict[str, float]:
    """
    Returns {etf_symbol: score} where score is 0-10.
    Top 3 ETFs by 5-day % change get high scores.
    Cached per scan cycle (passed as argument to avoid re-fetching).
    """
    df = yf.download(SECTOR_ETFS, period="5d", interval="1d",
                     group_by="ticker", auto_adjust=True, progress=False)
    etf_changes = {}
    for etf in SECTOR_ETFS:
        try:
            closes = df[etf]["Close"].dropna()
            if len(closes) >= 2:
                pct = (closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0]
                etf_changes[etf] = pct
        except Exception:
            etf_changes[etf] = 0.0

    # Rank: top 3 ETFs get 8-10, middle get 4-7, bottom get 0-3
    sorted_etfs = sorted(etf_changes.items(), key=lambda x: x[1], reverse=True)
    scores = {}
    n = len(sorted_etfs)
    for rank, (etf, _) in enumerate(sorted_etfs):
        # Linear: rank 0 = 10, rank n-1 = 0
        scores[etf] = round(max(0.0, 10.0 - (rank / max(n - 1, 1)) * 10), 2)
    return scores


def _get_stock_sector_score(symbol: str, etf_scores: dict[str, float]) -> float:
    """Map a stock to its sector ETF score. Default 5.0 if sector unknown."""
    try:
        info = yf.Ticker(symbol).info
        sector = info.get("sector", "")
        etf = SECTOR_ETF_MAP.get(sector)
        if etf:
            return etf_scores.get(etf, 5.0)
    except Exception:
        pass
    return 5.0  # neutral
```

### Pattern 6: Earnings Penalty

```python
# In scanner.py or strategies/catalyst.py
from datetime import date
import yfinance as yf

_earnings_cache: dict[str, tuple[date, date | None]] = {}  # symbol -> (fetch_date, next_earnings)

def _get_earnings_penalty(symbol: str) -> float:
    """
    Returns a conviction score REDUCTION (0.0 to 2.0) based on earnings proximity.
    Earnings within 3 days: reduce composite by up to 2.0 points.
    """
    today = date.today()
    if symbol in _earnings_cache:
        fetch_date, next_earnings = _earnings_cache[symbol]
        if fetch_date == today:  # per-day cache (D-09)
            if next_earnings is None:
                return 0.0
            days_until = (next_earnings - today).days
            if days_until <= 3:
                # 3 days: -0.5, 2 days: -1.0, 1 day: -1.5, 0 days: -2.0
                return round((3 - days_until) * 0.5 + 0.5, 2)
            return 0.0

    try:
        cal = yf.Ticker(symbol).calendar
        if cal and "Earnings Date" in cal:
            dates = cal["Earnings Date"]
            upcoming = [d for d in dates if d >= today]
            next_e = min(upcoming) if upcoming else None
        else:
            next_e = None
    except Exception:
        next_e = None

    _earnings_cache[symbol] = (today, next_e)
    return _get_earnings_penalty(symbol)  # recurse with fresh cache
```

### Pattern 7: Scoring Formulas (Claude's Discretion — Researched)

**RSI to technical score (MomentumStrategy):**
- RSI 0 → 6.9/10, RSI 30 → 5.4/10, RSI 55 → 1.5/10, RSI 65+ → 0/10
- Formula: `max(0.0, (MAX_RSI_BUY - rsi) / MAX_RSI_BUY * 10)` where MAX_RSI_BUY=65

**RSI to technical score (MeanReversionStrategy):**
- RSI 35+ → 0/10 (not oversold), RSI 20 → 4.3/10, RSI 0 → 10/10
- Formula: `max(0.0, (35 - rsi) / 35 * 10)` — only scores if RSI < 35

**Volume ratio to volume sub-score (shared across strategies):**
- 1.0x → 2.0/10, 2.0x → 5.0/10 (threshold), 3.0x → 6.7/10, 5.0x → 10/10
- Formula: `(vol_ratio / 2.0) * 4` if below threshold, else `5 + min(5, (vol - 2) / 3 * 5)`

**Earnings penalty (D-10, Claude's discretion):**
- 3 days out: -0.5, 2 days: -1.0, 1 day: -1.5, 0 days (day-of): -2.0

**ThreadPoolExecutor max_workers (D-13, Claude's discretion):**
- Recommend: `max_workers=10` — benchmarks show diminishing returns above 10 for yfinance I/O

### Pattern 8: Scan Loop with Parallel Execution

```python
# In scanner.py — new multi-strategy scan function
def scan(watchlist: list[str], catalysts: dict | None = None) -> list[dict]:
    """
    Multi-strategy scan. Maintains existing interface: returns list[dict] sorted by score.
    Each result dict includes backward-compatible keys PLUS new conviction breakdown.
    """
    log.info("[scanner] Multi-strategy scan: %d symbols", len(watchlist))

    # Pre-fetch sector scores (once for all symbols, ~1s)
    etf_scores = _fetch_sector_scores()

    # Parallel bar fetching + scoring
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_score_symbol_multi, sym, etf_scores): sym for sym in watchlist}
        results = []
        for future in futures:
            result = future.result()
            if result:
                results.append(result)

    results.sort(key=lambda r: r["conviction"]["composite"], reverse=True)
    _log_scan_results(results)
    return results


def best_buy(results: list[dict]) -> dict | None:
    """Return highest-conviction candidate at or above threshold. Logs skip reasons."""
    threshold = config.CONVICTION_THRESHOLD  # 7.0 (D-04)
    for r in results:
        score = r["conviction"]["composite"]
        if score >= threshold:
            return r
        # Log skip reasoning (D-17)
        breakdown = r["conviction"]
        log.info(
            "[scanner] Skipped %s (%.1f/10): technical=%.1f, volume=%.1f, "
            "sentiment=%.1f, sector=%.1f — composite below %.1f threshold",
            r["symbol"], score,
            breakdown["technical"], breakdown["volume"],
            breakdown["sentiment"], breakdown["sector"],
            threshold,
        )
    return None
```

### Anti-Patterns to Avoid

- **Fetching `.info` per symbol in the hot path:** `yf.Ticker(sym).info` is an HTTP call. Fetching sector info for 35 symbols in the main scan loop without caching adds ~1.8s parallel but can spike on slow connections. Cache sector info per symbol per day.
- **Calling `NewsClient` per symbol in the scan loop without TTL:** Alpaca news API is rate-limited. Always go through `sentiment_cache.get_sentiment_score()` which enforces the 30-minute TTL.
- **Running strategies sequentially inside the parallel worker:** Each `_score_symbol_multi` worker already executes in parallel across symbols. Within a single symbol, running all three strategies sequentially is fine — they all operate on the same pre-fetched `df`.
- **Breaking the `scan()`/`best_buy()` interface:** `bot.py` imports these by name and calls them directly. The new implementation must keep identical signatures.
- **Putting `df` in the conviction breakdown dict:** The existing `_score_symbol()` returns `"df": df` (the full bar DataFrame) for dashboard charting. The new result dict must preserve this for backward compatibility.
- **Using `yf.download()` batch mode for sector stocks during scan:** Batch download groups all symbols together and can fail silently for individual symbols. Per-ticker parallel `ThreadPoolExecutor` is more fault-tolerant and equally fast (1.4s vs 2.0s tested).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| RSS XML parsing | Custom XML parser | stdlib `xml.etree.ElementTree` | Already used in `catalysts.py`; handles malformed feeds gracefully |
| Per-symbol bar caching | Custom DataFrame store | Re-fetch each scan cycle via yfinance | Scan runs every 60s; bar data only adds 1.5s parallel — caching adds complexity without benefit |
| Custom threading pool | `threading.Thread` per symbol | `concurrent.futures.ThreadPoolExecutor` | Handles exceptions, timeouts, and result collection cleanly |
| Sentiment ML scoring | Train a model | Keyword counting | D-07 explicitly locks this; keyword lists are inspectable and tunable |
| Sector info HTTP client | Requests + parsing | `yf.Ticker(sym).info` | Already returns structured sector field; tested and working |

**Key insight:** The biggest reuse opportunity is `indicators.py` — RSI, MACD, and Bollinger Bands are pure functions that all three strategies can call without modification.

---

## Common Pitfalls

### Pitfall 1: yfinance Rate Limiting at High Concurrency

**What goes wrong:** Fetching 35+ symbols in parallel at max_workers > 15 triggers Yahoo Finance rate limits (HTTP 429 or empty responses).
**Why it happens:** yfinance sends separate HTTP requests per symbol; too many concurrent connections look like a scraper.
**How to avoid:** Cap `max_workers=10`. Tested at this level: 35 symbols in 1.4s with no rate limit errors.
**Warning signs:** `yf.Ticker(sym).history()` returns empty DataFrame for multiple symbols simultaneously.

### Pitfall 2: `yf.download()` Column Structure Changes

**What goes wrong:** `yf.download(symbols, group_by='ticker')` returns a MultiIndex DataFrame. Accessing `df['AAPL']['Close']` fails if yfinance changes column structure.
**Why it happens:** yfinance 1.x changed MultiIndex column ordering vs 0.x.
**How to avoid:** Use per-ticker `Ticker.history()` in the parallel worker function rather than batch `yf.download()` for the stock scan. Use `yf.download()` only for sector ETFs (where we control the symbol list and can validate).

### Pitfall 3: Alpaca NewsClient Auth in Paper Mode

**What goes wrong:** `NewsClient` uses the same API keys as the trading client but is a separate client instance. Paper trading credentials may have read-only news access.
**Why it happens:** Alpaca paper and live accounts share API keys but have different permission scopes.
**How to avoid:** Wrap `NewsClient` calls with try/except that falls back to Yahoo RSS. `sentiment_cache._fetch_alpaca_news()` already does this.
**Warning signs:** `NewsClient.get_news()` raises 403 or 401 — check `_fetch_yahoo_rss()` fallback activates.

### Pitfall 4: Earnings Calendar Returns Empty List

**What goes wrong:** `yf.Ticker(sym).calendar` returns `{}` or `{'Earnings Date': []}` for symbols where yfinance has no data.
**Why it happens:** Not all stocks have upcoming earnings on yfinance (ADRs, ETFs, small caps).
**How to avoid:** Always guard: `if cal and 'Earnings Date' in cal and cal['Earnings Date']`. Default to no penalty (return 0.0) when unavailable.

### Pitfall 5: Conviction Score All Zeros for Low-Volume Extended Hours

**What goes wrong:** Scanning outside market hours with 5m bars returns very low volume (pre/post market). Volume sub-score = 0/10, dragging composite below 7.0 for all candidates.
**Why it happens:** The bot polls every 60s and can trigger a scan outside hours when `assert_market_open()` hasn't short-circuited it.
**How to avoid:** The existing `assert_market_open()` in `bot.py` guards trade execution, not scanning. Scanning outside hours is acceptable behavior — just document that scan results outside market hours may show artificially low volume scores.

### Pitfall 6: State Key Not Found in `state.update()`

**What goes wrong:** `state.update(scan_results=[...])` silently no-ops if `"scan_results"` is not in `_state` dict.
**Why it happens:** `state.update()` only updates keys that already exist in `_state` (see line 108: `if k in _state`).
**How to avoid:** Add new state keys to `_state` in `state.py` before using them. Required new keys: `scan_results`, `last_scan_time`, `scan_conviction_scores`.

### Pitfall 7: `df` in Result Dict Is Not JSON-Serializable

**What goes wrong:** The existing `_score_symbol()` returns `"df": df` (pandas DataFrame). Dashboard's `/api/state` endpoint calls `state.snapshot()` which tries to JSON-serialize the watchlist. DataFrames are not JSON-serializable.
**Why it happens:** `scan()` stores results in `state.update(watchlist=results)` but the DataFrame inside each result breaks `json.dumps()`.
**How to avoid:** Strip `df` from results before storing in state (keep it only in the local scan loop for chart rendering). Already done in the existing code — verify it's maintained in the new orchestrator.

---

## Code Examples

### Minimal Strategy Module Template

```python
# strategies/mean_reversion.py
from __future__ import annotations
import pandas as pd
from indicators import rsi as calc_rsi, bollinger_bands

def scan(symbol: str, df: pd.DataFrame) -> dict:
    """
    MeanReversionStrategy: RSI < 35 at lower Bollinger Band support.
    Returns dict with fired flag and sub-score components.
    """
    if len(df) < 22:
        return {"strategy": "mean_reversion", "fired": False, "technical_score": 0.0, "volume_ratio": 1.0}

    closes = df["close"]
    volumes = df["volume"]

    rsi_s = calc_rsi(closes)
    rsi_val = float(rsi_s.dropna().iloc[-1]) if len(rsi_s.dropna()) > 0 else 50.0

    _, _, bb_lower_s = bollinger_bands(closes)
    bb_lower = float(bb_lower_s.dropna().iloc[-1]) if len(bb_lower_s.dropna()) > 0 else None

    curr_price = float(closes.iloc[-1])
    at_support = bb_lower is not None and curr_price <= bb_lower * 1.02  # within 2%
    oversold = rsi_val < 35.0

    # Volume ratio
    avg_vol = float(volumes.tail(20).mean()) if len(volumes) >= 20 else float(volumes.mean())
    curr_vol = float(volumes.iloc[-1])
    volume_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0

    # Technical sub-score: 0 unless RSI oversold
    if oversold:
        # RSI 35->0, RSI 0->10
        rsi_score = max(0.0, (35.0 - rsi_val) / 35.0 * 10)
        # Bonus for price at support
        if at_support:
            rsi_score = min(10.0, rsi_score + 2.0)
    else:
        rsi_score = 0.0

    return {
        "strategy": "mean_reversion",
        "fired": oversold and at_support,
        "technical_score": round(rsi_score, 2),
        "volume_ratio": round(volume_ratio, 2),
        "details": {
            "rsi": round(rsi_val, 1),
            "at_bb_lower": at_support,
            "bb_lower": round(bb_lower, 4) if bb_lower else None,
        }
    }
```

### Conviction Threshold Filter in best_buy()

```python
# scanner.py — updated best_buy()
def best_buy(results: list[dict]) -> dict | None:
    """Return top-scoring candidate at or above CONVICTION_THRESHOLD (default 7.0)."""
    threshold = getattr(config, "CONVICTION_THRESHOLD", 7.0)
    for r in sorted(results, key=lambda x: x["conviction"]["composite"], reverse=True):
        score = r["conviction"]["composite"]
        if score >= threshold:
            log.info("[scanner] Best buy: %s (%.1f/10) — strategies: %s",
                     r["symbol"], score,
                     ", ".join(r["conviction"].get("strategies_fired", [])))
            return r
        b = r["conviction"]
        log.info(
            "[scanner] Skipped %s (%.1f/10): technical=%.1f, volume=%.1f, "
            "sentiment=%.1f, sector=%.1f",
            r["symbol"], score, b["technical"], b["volume"], b["sentiment"], b["sector"]
        )
    return None
```

### Config Extensions

```python
# config.py additions
# ── Multi-strategy conviction scoring ────────────────────────────────────────
CONVICTION_THRESHOLD        = _float("CONVICTION_THRESHOLD",        7.0)
CONVICTION_WEIGHT_TECHNICAL = _float("CONVICTION_WEIGHT_TECHNICAL", 0.40)
CONVICTION_WEIGHT_VOLUME    = _float("CONVICTION_WEIGHT_VOLUME",    0.20)
CONVICTION_WEIGHT_SENTIMENT = _float("CONVICTION_WEIGHT_SENTIMENT", 0.20)
CONVICTION_WEIGHT_SECTOR    = _float("CONVICTION_WEIGHT_SECTOR",    0.20)

# Validation: weights must sum to 1.0
_weight_sum = (CONVICTION_WEIGHT_TECHNICAL + CONVICTION_WEIGHT_VOLUME +
               CONVICTION_WEIGHT_SENTIMENT + CONVICTION_WEIGHT_SECTOR)
if abs(_weight_sum - 1.0) > 0.001:
    raise ValueError(f"[config] Conviction weights must sum to 1.0, got {_weight_sum:.3f}")

# ── Swing watchlist (20-30 stocks, config-editable) ───────────────────────────
_swing_raw = os.getenv(
    "SWING_WATCHLIST",
    "NVDA,AMD,TSLA,META,MSFT,PLTR,COIN,SOFI,HOOD,RIVN,"
    "SNAP,MARA,NIO,F,AAPL,GOOGL,AMZN,NFLX,DIS,CRWD,"
    "SHOP,UBER,LYFT,DKNG,RBLX"
)
SWING_WATCHLIST = [s.strip().upper() for s in _swing_raw.split(",") if s.strip()]
```

### State Extensions

```python
# state.py — add to _state dict
"scan_results":        [],   # list of candidate dicts from last scan (df stripped)
"last_scan_time":      None, # ISO timestamp of last scan completion
"scan_conviction_scores": {},  # {symbol: composite_score} for quick lookup
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single SMA crossover boolean | Multi-strategy 0-10 conviction score | Phase 2 | Candidates ranked by strength, not binary pass/fail |
| Binary BUY/SELL/HOLD signal | Composite score with breakdown | Phase 2 | Logged reasoning for every skip decision |
| All-or-nothing filter (4 conditions must pass) | Weighted scoring with partial credit | Phase 2 | More candidates surface; threshold gates execution |
| Sequential symbol scanning | ThreadPoolExecutor parallel fetch | Phase 2 | 10x speedup: 35 symbols in ~1.5s |
| Catalyst as binary bonus (+40 score) | CatalystStrategy as one of three weighted strategies | Phase 2 | Cleaner composition; catalyst weight tunable |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| yfinance | Bar data, sector info, earnings | Yes | 1.2.0 | None needed |
| alpaca-py NewsClient | Per-stock news sentiment | Yes | 0.43.2 | Yahoo RSS fallback |
| pandas | DataFrame manipulation | Yes | 3.0.1 | None needed |
| numpy | Indicator calculations | Yes | 2.4.3 | None needed |
| requests | Yahoo RSS fetching | Yes | 2.32.5 | None needed |
| ThreadPoolExecutor | Parallel scanning | Yes | stdlib | None needed |
| pytest | Tests | Yes | 9.0.2 | None needed |
| pandas-ta | Advanced indicators | No | not installed | Not needed — custom `indicators.py` sufficient |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** pandas-ta is not installed, but this phase does not require it — all indicator calculations are handled by the existing pure-pandas `indicators.py` module.

**Performance verified (2026-03-28, on target machine):**
- 35 symbols parallel bar fetch: 1.4s
- 11 sector ETF batch download: 0.9s
- 35 symbols parallel sector `.info` fetch: 1.8s
- Full scan simulation (bars + scoring): 2.5s
- Yahoo RSS per-symbol (3 symbols sequential): 3.1s — must use parallel or pre-cache per cycle

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | none (discovered by convention) |
| Quick run command | `pytest tests/test_scanner.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |
| Test directory | `tests/` (existing: conftest.py, test_safety.py, test_bracket.py) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STRAT-01 | Registry dict maps names to callables | unit | `pytest tests/test_strategies.py::test_registry -x` | No — Wave 0 |
| STRAT-02 | MomentumStrategy returns `fired=True` on breakout + 2x volume | unit | `pytest tests/test_strategies.py::test_momentum_fires -x` | No — Wave 0 |
| STRAT-03 | MeanReversionStrategy returns `fired=True` on RSI<35 + at BB lower | unit | `pytest tests/test_strategies.py::test_mean_reversion_fires -x` | No — Wave 0 |
| STRAT-04 | CatalystStrategy scores ARK+upgrade correctly | unit | `pytest tests/test_strategies.py::test_catalyst_score -x` | No — Wave 0 |
| STRAT-05 | Conviction breakdown dict has all 4 sub-scores + composite | unit | `pytest tests/test_scanner.py::test_conviction_breakdown -x` | No — Wave 0 |
| STRAT-06 | `scan()` returns list sorted by composite score descending | unit | `pytest tests/test_scanner.py::test_scan_sorted -x` | No — Wave 0 |
| SCAN-01 | Parallel scan completes (mocked yfinance) | unit | `pytest tests/test_scanner.py::test_parallel_scan -x` | No — Wave 0 |
| SCAN-03 | SWING_WATCHLIST loaded from env var | unit | `pytest tests/test_scanner.py::test_watchlist_config -x` | No — Wave 0 |
| PRED-01 | `get_sentiment_score()` returns 0-10 float, uses cache on second call | unit | `pytest tests/test_sentiment_cache.py -x` | No — Wave 0 |
| PRED-02 | Volume ratio 2x+ maps to volume score >= 5.0 | unit | `pytest tests/test_scanner.py::test_volume_score -x` | No — Wave 0 |
| PRED-03 | Earnings within 3 days reduces composite score | unit | `pytest tests/test_scanner.py::test_earnings_penalty -x` | No — Wave 0 |
| PRED-04 | `best_buy()` skips candidates below 7.0 threshold | unit | `pytest tests/test_scanner.py::test_conviction_threshold -x` | No — Wave 0 |
| PRED-05 | Skip reason logged with full breakdown | unit (log capture) | `pytest tests/test_scanner.py::test_skip_logging -x` | No — Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_strategies.py tests/test_scanner.py tests/test_sentiment_cache.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_strategies.py` — unit tests for all three strategy modules (STRAT-01 through STRAT-04)
- [ ] `tests/test_scanner.py` — conviction scoring, threshold filtering, scan interface (STRAT-05, STRAT-06, SCAN-01, SCAN-03, PRED-02, PRED-04, PRED-05)
- [ ] `tests/test_sentiment_cache.py` — sentiment scoring, TTL cache, Alpaca/RSS fallback (PRED-01)

Shared fixtures from `tests/conftest.py` (already exists) provide `mock_trading_client`. New fixture needed: `sample_df()` returning a 50-row OHLCV DataFrame for strategy testing.

---

## Open Questions

1. **Sentiment cache during parallel scan: thread safety**
   - What we know: `sentiment_cache._cache` is a module-level dict. Multiple `ThreadPoolExecutor` workers may call `get_sentiment_score()` simultaneously for different symbols.
   - What's unclear: Python's GIL protects dict operations, but two threads could both find an expired TTL for the same symbol and both trigger a fetch.
   - Recommendation: Use a `threading.Lock` inside `sentiment_cache` for the TTL check + update, or pre-warm sentiment cache sequentially before launching parallel bar fetchers. Pre-warming is simpler and eliminates the race.

2. **Alpaca NewsClient auth with paper credentials**
   - What we know: `NewsClient` is instantiated separately from `TradingClient`. Paper credentials are confirmed as not set in `.env.paper` (key is empty). Live credentials in `.env.live` may work.
   - What's unclear: Whether Alpaca news API access requires a paid data subscription or works with free-tier keys.
   - Recommendation: Implement with Yahoo RSS as the primary source and Alpaca as an optional enhancement. The `_fetch_alpaca_news()` → `_fetch_yahoo_rss()` fallback handles this automatically regardless.

3. **Sector info cache invalidation**
   - What we know: `yf.Ticker(sym).info` returns sector string. Fetching for 35 symbols takes 1.8s parallel.
   - What's unclear: Whether to cache this per symbol (day cache) or re-fetch every scan.
   - Recommendation: Cache sector info per symbol per trading day. Sector classification never changes intraday. Add a `_sector_cache: dict[str, tuple[date, str]]` dict in `scanner.py`.

---

## Sources

### Primary (HIGH confidence)

- alpaca-py 0.43.2 installed SDK — `NewsClient`, `NewsRequest` model fields inspected directly
- yfinance 1.2.0 installed SDK — `Ticker.history()`, `Ticker.calendar`, `Ticker.info`, `yf.download()` all tested live
- Python stdlib documentation — `concurrent.futures.ThreadPoolExecutor`, `threading.Lock`
- Live performance benchmarks on target machine (2026-03-28) — all timing figures are measured, not estimated

### Secondary (MEDIUM confidence)

- Alpaca documentation (inferred from SDK inspection) — `NewsRequest` supports `symbols`, `limit`, `start`, `end`, `include_content`
- yfinance sector field values — verified for 4 symbols (`NVDA`, `SOFI`, `XOM`, `JPM`) against SECTOR_ETF_MAP

### Tertiary (LOW confidence)

- Alpaca paper account news API access — unable to test (credentials not configured). The Yahoo RSS fallback makes this low-risk.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages tested live on target machine with version verification
- Architecture patterns: HIGH — patterns derived from existing codebase conventions + live SDK inspection
- Performance claims: HIGH — all timing figures measured on actual target machine
- Pitfalls: HIGH — most sourced from live testing or direct code inspection of existing modules
- Alpaca news API auth in paper mode: LOW — unable to test without configured credentials

**Research date:** 2026-03-28
**Valid until:** 2026-04-27 (30 days for stable stack; yfinance API patterns can shift)
