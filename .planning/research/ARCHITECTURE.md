# Architecture Patterns: Intelligence Suite (v2.0)

**Domain:** Intelligence Suite additions to an existing Python/Flask trading bot
**Researched:** 2026-04-02
**Confidence:** HIGH — based on direct codebase analysis of all affected modules

---

## Existing Architecture Snapshot

Before describing integration, here is what exists and must not break:

```
server.py              — entry point, loads env, wires clients + coordinator
bot.py                 — polling loop (60s), AgentCoordinator.run_cycle()
agents/coordinator.py  — 6-agent pipeline: Quant+News(parallel) → Strategist → Risk → Executor → Auditor
scanner.py             — multi-strategy scan, ThreadPoolExecutor(15 workers), 60-stock watchlist
sentiment_cache.py     — per-symbol news scoring, 30-min TTL, Alpaca primary / Yahoo RSS fallback
state.py               — threading.Lock dict, snapshot() returns JSON-safe copy
dashboard.py           — Flask app, ~20 routes, SSE stream, injected trading_client + coordinator
strategies/            — momentum.py, mean_reversion.py, catalyst.py + __init__.py registry
indicators.py          — pure functions: rsi(), macd(), bollinger_bands(), compute_all()
safety.py              — risk guards: PDT, position sizing, trailing stop, liquidation
config.py              — .env loader, module-level constants, validated at import time
```

**Key architectural constraints:**
- State is the single source of truth. All threads read/write through `state.update()` / `state.snapshot()`.
- Dashboard consumes state exclusively via `shared_state.snapshot()` — no direct DB reads.
- Flask runs in threaded mode. Long-running work must go in daemon threads, never block a route.
- The SSE stream pushes full state every second. Adding large blobs to state inflates every push.

---

## Feature-by-Feature Integration Analysis

### Feature 1: Score Recalibration (Weights, Letter Grades, Hover Breakdowns)

**What changes:** The conviction score display in dashboard and the score thresholds/labels.

**Modules modified:**
- `config.py` — add `GRADE_THRESHOLDS` dict (e.g. A=8.5, B=7.0, C=5.8, D=4.0, F=<4.0) as config constants
- `scanner.py` — `conviction` dict in `_score_symbol_multi()` already has all sub-scores; add `grade: str` field computed from composite score
- `state.py` — no changes needed; conviction breakdown already stored in `scan_results[*].conviction`
- `dashboard.py` — add `/api/scan/results` route (or extend existing `/api/scan`) that returns full conviction breakdown per symbol; the current `/api/scan` only triggers a scan, it does not return structured results
- `templates/index.html` — JS hover tooltip reads breakdown from scan_results in state

**No new modules needed.**

**Data flow:**
```
scanner._score_symbol_multi()
  → conviction dict: {technical, volume, sentiment, sector, composite, grade}
  → state.scan_results[*].conviction
  → dashboard /api/state or /api/scan/results
  → frontend tooltip on hover
```

**Integration risk:** LOW. The conviction dict is already well-structured. Adding `grade` is additive.

---

### Feature 2: Overnight Scanner (Post-Market Analysis, Tomorrow's Game Plan, Approve/Reject UI)

**What changes:** A new scheduled job that runs post-market (after 4:00 PM ET), uses the existing scanner, and persists a "game plan" that the user can approve or reject via the dashboard.

**New module needed:** `overnight_scanner.py`

**Responsibility:** Run after market close (configurable time, e.g. 4:30 PM ET), invoke `scanner.scan()` on the expanded watchlist, generate a structured "tomorrow's game plan" dict, and write it to `state` and a JSON file for persistence across restarts.

**How it runs:** Daemon thread launched at server startup (not tied to bot loop). Uses `threading.Event` or a simple sleep-loop checking `datetime.now()` against market-close threshold. Do NOT use APScheduler — it adds a dependency and the existing pattern is sleep-loop daemons (see `stream.py`, `sentiment.py`).

```python
# overnight_scanner.py — skeleton
def _overnight_loop():
    while True:
        now = datetime.now(ZoneInfo("America/New_York"))
        # Wait until 4:30 PM ET on a weekday
        if _is_post_market(now) and not _ran_today():
            game_plan = _run_overnight_scan()
            shared_state.update(overnight_plan=game_plan)
            _save_plan_to_file(game_plan)
        time.sleep(60)

def _run_overnight_scan() -> dict:
    watchlist = get_expanded_watchlist()   # Feature 3
    results = scan(watchlist)
    return {
        "date": today_str,
        "generated_at": iso_now,
        "candidates": [top N results with conviction > threshold],
        "market_summary": ...,
        "status": "pending",   # "approved" | "rejected" | "pending"
    }
```

**Modules modified:**
- `server.py` — launch `overnight_scanner` daemon thread at startup alongside `stream.py` and `sentiment.py`
- `state.py` — add `overnight_plan: dict | None` field (default `None`)
- `dashboard.py` — add two new routes:
  - `GET /api/overnight/plan` — returns current plan from state
  - `POST /api/overnight/plan/approve` — sets `overnight_plan.status = "approved"`
  - `POST /api/overnight/plan/reject` — sets `overnight_plan.status = "rejected"`, accepts optional `{"symbol": str}` for per-symbol rejection

**State payload concern:** The overnight plan stores full scan results (stripped of `df`). This is safe — scanner already strips `df` before writing to state. Cap the plan at top 10 candidates to limit SSE payload size.

**Data flow:**
```
4:30 PM ET trigger
  → overnight_scanner._run_overnight_scan()
  → scanner.scan(expanded_watchlist)       [existing scanner, new watchlist]
  → state.overnight_plan = {candidates, status: "pending"}
  → dashboard GET /api/overnight/plan
  → user clicks Approve/Reject
  → POST /api/overnight/plan/approve
  → state.overnight_plan.status = "approved"
  → bot.py checks overnight_plan.status on next morning cycle
```

**Bot integration point:** `bot.py` already calls `best_buy()` from scanner results. Add an optional "pre-approved candidates" gate: if an overnight plan exists and is approved, prioritize those symbols in the morning scan. This is additive — the bot still runs its own scan, but approved symbols get a score bonus or are kept even if slightly below threshold.

**Integration risk:** MEDIUM. The overnight scan calls `scanner.scan()` which uses `ThreadPoolExecutor(15)` — running it post-market while the bot is also potentially running could cause yfinance rate-limit conflicts. Mitigation: only run overnight scan when bot status is `idle` or `stopped`, or add a scan-exclusive lock.

---

### Feature 3: Expanded Stock Scanner (S&P 500 + NASDAQ 100 + Volume-Based + Unusual Volume, Hard Filters)

**What changes:** `scanner.py`'s `get_watchlist()` function and the data sources that feed it.

**New module needed:** `universe.py`

**Responsibility:** Fetch and cache the full S&P 500, NASDAQ 100, and high-volume screener lists. Return deduplicated, filtered symbol lists. The existing `scanner.py` calls `get_watchlist()` — `universe.py` replaces the internal logic.

```python
# universe.py
def get_sp500() -> list[str]:          # Wikipedia table via requests + html.parser (no BS4 needed)
def get_nasdaq100() -> list[str]:      # Wikipedia or Nasdaq FTP
def get_top_volume() -> list[str]:     # Yahoo Finance day_volume screener (existing pattern)
def get_unusual_volume() -> list[str]: # stocks with volume > 2x 20-day avg (yfinance scan)
def get_expanded_watchlist() -> list[str]:
    # deduplicate + apply hard filters, return <= MAX_UNIVERSE_SIZE symbols
```

**Hard filters (must apply before scan):**
- Price: $5 to $500 (existing MIN_PRICE/MAX_PRICE)
- Volume: >= 500K daily average (lower than current 1M to catch mid-caps)
- Market cap: >= $100M (prevent micro-cap garbage)
- Exchange: NYSE/NASDAQ only (existing filter)
- Exclude ETFs, funds, preferred shares (symbol pattern: no `-`, no suffix like `.A`)

**Performance concern — HIGH PRIORITY:** Scanning 500+ symbols with `ThreadPoolExecutor(15)` and yfinance `history()` per symbol will take 3-5 minutes. This is acceptable for the overnight scan but NOT for the intraday bot loop (which must complete in 30s).

**Solution: Two-tier scan architecture:**
- **Tier 1 (fast pre-filter):** Use `yf.download(symbols, period="5d", group_by="ticker")` for bulk download — yfinance batches these efficiently. Filter by: 5-day price change > 2%, recent volume > 1.5x avg. This culls 500+ to ~50 candidates in ~20s.
- **Tier 2 (full score):** Run existing `_score_symbol_multi()` on the ~50 survivors. Total time: ~30-45s.

**Config additions needed:**
```python
MAX_UNIVERSE_SIZE     = _int("MAX_UNIVERSE_SIZE", 600)   # hard cap on symbols fetched
UNIVERSE_PREFILTER_MIN_CHANGE = _float("UNIVERSE_PREFILTER_MIN_CHANGE", 0.02)
```

**Modules modified:**
- `scanner.py` — `get_watchlist()` delegates to `universe.get_expanded_watchlist()` when `USE_EXPANDED_UNIVERSE=true`; keep existing behavior as default
- `config.py` — add `USE_EXPANDED_UNIVERSE` flag, `MAX_UNIVERSE_SIZE`, pre-filter thresholds

**S&P 500 / NASDAQ 100 source — MEDIUM confidence:** Wikipedia tables (`https://en.wikipedia.org/wiki/List_of_S%26P_500_companies`) are stable and parseable with `html.parser` + `pandas.read_html()`. No API key required. Cache once per calendar day. `pandas.read_html()` is already a dependency (pandas is in requirements).

**Integration risk:** MEDIUM. The main risk is yfinance rate limits at scale. Use bulk `yf.download()` for pre-filter and cache aggressively. Never run expanded universe scan during market hours in the main bot loop.

---

### Feature 4: Multi-Source News (Finnhub API, MarketWatch/Reuters/Google News RSS, SEC EDGAR RSS, FRED Calendar)

**What changes:** `sentiment_cache.py` becomes inadequate as a news source — it only scores sentiment for the conviction engine. The new requirement is richer, displayable news with source attribution.

**New module needed:** `news_aggregator.py`

**Two separate concerns (must not conflate):**
1. **Conviction scoring news** (existing) — per-symbol headline scoring for the 0-10 sentiment sub-score. `sentiment_cache.py` handles this. Keep it.
2. **Display news** (new) — multi-source articles shown in Intelligence tab and overnight plan. `news_aggregator.py` handles this.

**`news_aggregator.py` responsibilities:**
- Fetch from multiple sources with TTL caching per source
- Return normalized `NewsItem` dicts: `{headline, source, url, published_at, category, symbols}`
- Categories: stock-specific, macro/market, sector, earnings, SEC filing, FRED event
- Sources and their access methods:

| Source | Access Method | Rate Limit | Confidence |
|--------|--------------|------------|------------|
| Alpaca News API | `NewsClient` (existing pattern) | 200 req/min | HIGH — already working |
| Yahoo Finance RSS | `https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}` | None | HIGH — existing fallback |
| Google News RSS | `https://news.google.com/rss/search?q={symbol}+stock&hl=en-US` | None (soft) | MEDIUM — may block scrapers |
| MarketWatch RSS | `https://feeds.marketwatch.com/marketwatch/marketpulse/` | None | MEDIUM — subject to change |
| SEC EDGAR RSS | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&dateb=&owner=include&count=10&output=atom` | Polite crawling | HIGH — stable government feed |
| FRED Calendar | `https://api.stlouisfed.org/fred/releases/dates?api_key={key}&realtime_start={date}` | 120 req/min | HIGH — requires free API key |
| Finnhub API | `https://finnhub.io/api/v1/company-news?symbol={sym}&from={date}&to={date}&token={key}` | 60 req/min (free) | HIGH — requires free API key |

**Caching strategy:**
- Per-source TTL: stock news = 15 min, macro = 30 min, SEC = 1 hour, FRED = 1 day
- Cache key: `(source, symbol_or_category, date_bucket)` in module-level dict with `threading.Lock`

**State integration:** Do NOT push all news items into `state` on every SSE tick. Instead:
- `state.news_feed` = last 20 headline dicts (trimmed, source-attributed) — updated every 15 min
- Dashboard fetches full news via `GET /api/news?symbol=X&source=all` on demand

**Modules modified:**
- `sentiment_cache.py` — optionally call `news_aggregator` as a third source fallback; or keep independent (preferred — simpler)
- `state.py` — rename/extend `news` field to `news_feed` as list of attributed dicts
- `dashboard.py` — add `GET /api/news` route with `?symbol=&source=&limit=` params
- `config.py` — add `FINNHUB_API_KEY`, `FRED_API_KEY` optional config keys

**Integration risk:** LOW for existing news path (additive). MEDIUM for Finnhub/FRED (new API keys required, graceful fallback needed if keys absent).

---

### Feature 5: Intelligence Tab (SPY/QQQ/DIA/IWM Charts, VIX Gauge, Sector Heatmap, Breadth, AI Brief)

**What changes:** A new dashboard tab with market-wide data that doesn't exist anywhere in the current system.

**New module needed:** `market_intelligence.py`

**Responsibilities:**
- Market breadth: SPY/QQQ/DIA/IWM price + indicators (using existing `dashboard.py /api/bars/<symbol>` — already works for any symbol)
- VIX data: `yf.Ticker("^VIX").history(period="5d")` — standard yfinance call
- Sector heatmap: sector ETF 5-day returns — this already exists in `scanner._fetch_sector_scores()`, just needs an API endpoint
- Market breadth indicators: advance/decline ratio, % above 200 SMA — requires pulling data for S&P 500 constituents (expensive; cache daily)
- AI Brief: call Anthropic API with market summary data as context, return 2-3 sentence brief

**Data flow:**

```
market_intelligence.py (new module)
  ├─ get_market_overview() → {spy, qqq, dia, iwm: {price, change_pct, 5d_chart}}
  ├─ get_vix() → {current, level: "low"|"moderate"|"high"|"extreme", 30d_history}
  ├─ get_sector_heatmap() → reuses scanner._fetch_sector_scores() + _fetch_sector_returns()
  ├─ get_market_breadth() → {adv_decline_ratio, pct_above_200sma} [DAILY CACHE]
  └─ get_ai_brief() → calls Anthropic API with above data as context

dashboard.py routes (new):
  GET /api/intelligence/overview   → market_intelligence.get_market_overview()
  GET /api/intelligence/vix        → market_intelligence.get_vix()
  GET /api/intelligence/sectors    → market_intelligence.get_sector_heatmap()
  GET /api/intelligence/breadth    → market_intelligence.get_market_breadth()
  GET /api/intelligence/brief      → market_intelligence.get_ai_brief()
```

**Scanner reuse:** `scanner._fetch_sector_scores()` is currently a private function. Promote it to `scanner.fetch_sector_scores()` (public) so `market_intelligence.py` can import and call it directly without duplication.

**AI Brief — Anthropic API integration:**
- `config.py` already has `ANTHROPIC_API_KEY` and `STRATEGIST_MODEL`
- `market_intelligence.get_ai_brief()` assembles a context dict (market overview + VIX + sector heatmap + top news) and calls `anthropic.Anthropic().messages.create()`
- Cache result for 15 minutes (same TTL as news)
- Graceful fallback: return `{"brief": null, "error": "API key not configured"}` if no key

**State integration:** Intelligence data is dashboard-only, not used by bot loop. Do NOT add to `state.py`. All intelligence routes are direct HTTP fetch from `market_intelligence.py` — not SSE-streamed.

**Integration risk:** LOW for market data (yfinance, no new auth). MEDIUM for AI brief (Anthropic API key, rate limits, response time may be 2-5s — must be async or cached).

---

### Feature 6: PDF Report (Account Summary, Positions, Trades, Charts, Performance Metrics)

**What changes:** A new Flask route that generates and returns a PDF on demand.

**New module needed:** `report_generator.py`

**PDF library recommendation:** Use `reportlab` (pure Python, no system dependencies, well-maintained). Do NOT use `weasyprint` — it requires `libcairo` and `libpango` C libraries which are painful on Windows (the project runs on Windows 11 per env). Do NOT use `pdfkit` — requires `wkhtmltopdf` binary.

**`reportlab` availability — MEDIUM confidence:** ReportLab is pure Python, widely used, and installable via `pip install reportlab`. The platypus layout engine handles multi-section reports. Charts require `reportlab.graphics` (included in base package). Confidence is MEDIUM because the specific API hasn't been verified against current version via Context7, but the library has been stable for 10+ years.

**What the report contains:**
- Account summary: equity, cash, buying power, daily P&L, total P&L
- Open positions: symbol, qty, entry price, current price, P&L, stop/take-profit
- Trade history: last 50 trades with date, symbol, side, entry, exit, P&L, win/loss
- Performance metrics: win rate, avg P&L, consecutive losses, projection
- Conviction chart: top 10 scan candidates with score bars

**Data sources:** All from `shared_state.snapshot()` + `_trading_client.get_all_positions()` + `_trading_client.get_orders(...)` — same sources as existing dashboard routes.

**Route:**
```python
GET /api/report/pdf       → streams PDF as application/pdf
GET /api/report/preview   → returns JSON summary of what the PDF will contain
```

**Report generation is synchronous** — PDF generation for this data volume takes < 1 second. No background thread needed. The route blocks for ~500ms while reportlab renders.

**Modules modified:**
- `dashboard.py` — add two routes; `report_generator` imported lazily inside routes (keeps startup fast)
- `requirements.txt` — add `reportlab>=4.0`

**Integration risk:** LOW. Completely isolated — reads existing state and API calls, produces a file, returns it. No state mutations.

---

## Full Integration Map: New vs Modified

### New Modules

| Module | Purpose | Depends On | Called By |
|--------|---------|-----------|-----------|
| `overnight_scanner.py` | Post-market scan, game plan persistence | `scanner.py`, `state.py` | `server.py` (daemon thread) |
| `universe.py` | S&P 500 / NASDAQ 100 / volume universe fetching | `yfinance`, `pandas`, `requests` | `scanner.py`, `overnight_scanner.py` |
| `news_aggregator.py` | Multi-source news fetching with TTL cache | `requests`, `config.py` | `dashboard.py` routes, optionally `sentiment_cache.py` |
| `market_intelligence.py` | VIX, sector heatmap, breadth, AI brief | `yfinance`, `scanner.py`, `anthropic` | `dashboard.py` routes |
| `report_generator.py` | PDF report assembly and rendering | `reportlab`, `state.py` | `dashboard.py` routes |

### Modified Modules

| Module | What Changes | Risk |
|--------|-------------|------|
| `scanner.py` | `get_watchlist()` delegates to `universe.py` when enabled; `_fetch_sector_scores()` promoted to public; optional two-tier scan for large universe | MEDIUM |
| `sentiment_cache.py` | Optional: add Finnhub as third source alongside Alpaca + Yahoo RSS | LOW |
| `state.py` | Add `overnight_plan` field; extend `news` to `news_feed` with attribution; add intelligence cache fields | LOW |
| `config.py` | Add `FINNHUB_API_KEY`, `FRED_API_KEY`, `USE_EXPANDED_UNIVERSE`, `MAX_UNIVERSE_SIZE`, grade thresholds | LOW |
| `dashboard.py` | Add ~10 new routes (overnight plan, news, intelligence, PDF); expose conviction breakdown route | LOW |
| `server.py` | Launch `overnight_scanner` daemon thread | LOW |
| `requirements.txt` | Add `reportlab>=4.0` | LOW |

---

## Component Architecture Diagram (Post-Intelligence Suite)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        server.py (entry)                             │
│   Launches: bot-loop, stream, sentiment, overnight-scanner daemons   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────┐   ┌──────────────────┐   ┌────────────────────┐   │
│  │ universe.py │   │overnight_scanner │   │market_intelligence │   │
│  │ (NEW)       │   │    .py (NEW)     │   │      .py (NEW)     │   │
│  └──────┬──────┘   └────────┬─────────┘   └────────┬───────────┘   │
│         │                   │                        │               │
│         └──────────┬────────┘              Anthropic API            │
│                    ▼                       yfinance (VIX/ETFs)      │
│            ┌──────────────┐                                          │
│            │  scanner.py  │  ←── news_aggregator.py (NEW)           │
│            │  (modified)  │       └─ Finnhub, RSS, EDGAR, FRED      │
│            └──────┬───────┘                                          │
│                   │                                                   │
│        ┌──────────┼──────────┐                                       │
│        ▼          ▼          ▼                                       │
│  ┌──────────┐ ┌──────┐ ┌──────────┐                                 │
│  │strategies│ │safety│ │sentiment │                                  │
│  │/registry │ │ .py  │ │_cache.py │                                  │
│  └────┬─────┘ └──────┘ └──────────┘                                 │
│       │                                                               │
│       ▼                                                               │
│  ┌────────────────────────────────────────────────┐                 │
│  │              agents/coordinator.py             │                  │
│  │  Quant + News (parallel) → Strategist →        │                  │
│  │  Risk → Executor → Auditor                     │                  │
│  └──────────────────┬─────────────────────────────┘                 │
│                     │                                                 │
│                     ▼                                                 │
│               ┌──────────┐                                           │
│               │  state.py│ ← thread-safe dict (Lock)                 │
│               └────┬─────┘                                           │
│                    │                                                  │
│                    ▼                                                  │
│          ┌──────────────────────────────────┐                       │
│          │         dashboard.py             │                        │
│          │  Flask + SSE + ~30 routes        │                        │
│          │  + report_generator.py (NEW)     │                        │
│          └──────────────────────────────────┘                       │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Changes

### SSE Stream Impact

The SSE stream (`/api/stream`) pushes `shared_state.snapshot()` every second. Adding large data to state bloats every push.

**SSE-safe state additions (small, always needed):**
- `overnight_plan: {status, candidate_count, date}` — summary only, not full results
- `news_feed: list[dict]` — capped at 10 items, each item max ~200 bytes

**Keep out of state (fetch on demand via dedicated routes):**
- Full overnight plan candidates (use `/api/overnight/plan`)
- Full news content (use `/api/news`)
- Intelligence data (use `/api/intelligence/*`)
- PDF content (use `/api/report/pdf`)

### Thread Safety

New modules that share mutable state must use `threading.Lock`:

| Module | Shared State | Lock Needed |
|--------|-------------|-------------|
| `overnight_scanner.py` | `_ran_today` flag, plan file | Yes — simple `threading.Lock` |
| `universe.py` | symbol caches (sp500, nasdaq100) | Yes — existing pattern from `scanner.py` |
| `news_aggregator.py` | per-source TTL caches | Yes — same pattern as `sentiment_cache.py` |
| `market_intelligence.py` | VIX cache, sector cache, AI brief cache | Yes |
| `report_generator.py` | Stateless — generates on demand | No |

---

## Build Order

The 6 features have a natural dependency ordering based on what each one needs to work correctly.

| Order | Feature | Why This Position | New Files | Modified Files |
|-------|---------|------------------|-----------|---------------|
| 1 | Score Recalibration | Pure display change, no new APIs, validates existing conviction data | None | `scanner.py`, `config.py`, `templates/index.html` |
| 2 | Expanded Scanner (`universe.py`) | Overnight scanner depends on it; multi-source news benefits from larger symbol set | `universe.py` | `scanner.py`, `config.py` |
| 3 | Multi-Source News (`news_aggregator.py`) | Overnight plan should include news context; Intelligence tab needs it | `news_aggregator.py` | `sentiment_cache.py` (optional), `state.py`, `dashboard.py`, `config.py` |
| 4 | Overnight Scanner (`overnight_scanner.py`) | Depends on expanded scanner (2) and news (3) for richer plans | `overnight_scanner.py` | `server.py`, `state.py`, `dashboard.py` |
| 5 | Intelligence Tab (`market_intelligence.py`) | Depends on news aggregator (3) for AI brief context; sector heatmap reuses scanner work | `market_intelligence.py` | `scanner.py` (promote public fn), `dashboard.py` |
| 6 | PDF Report (`report_generator.py`) | Purely additive, reads everything already built | `report_generator.py` | `dashboard.py`, `requirements.txt` |

**Rationale for this order:**
- Score recalibration first: it's the only feature with zero external dependencies and validates the conviction data that all other features display.
- Universe before overnight scanner: the overnight scanner's value comes from scanning broader lists.
- News before overnight/intelligence: both consume news data; building the aggregator first avoids building it twice.
- PDF last: it reads data, produces output, has no upstream dependencies on any of the other new features.

---

## Critical Pitfall: Two-Tier Scan is Not Optional

The expanded universe (500+ symbols) running through the existing `scanner.scan()` with one yfinance call per symbol will consume 5-8 minutes of I/O time. This is the highest-risk architectural decision in the entire milestone.

**Required approach for overnight scanner:**
```
Phase A: Bulk pre-filter (yf.download batch)
  → ~600 symbols → download("AAPL MSFT ...", period="5d", group_by="ticker")
  → Filter: volume spike, price change threshold
  → Output: ~40-60 survivors (~10-15s)

Phase B: Full score (existing scanner._score_symbol_multi per survivor)
  → 40-60 symbols × ~0.5s each = ~25s with 15 workers
  → Total overnight scan: ~35-40s
```

**Required approach for intraday bot loop:**
- Keep existing `SWING_WATCHLIST` (60 stocks) for all intraday scans
- Never run expanded universe during market hours
- Config flag `USE_EXPANDED_UNIVERSE=false` by default (only overnight)

This two-tier design is the most important architectural decision in this feature set. If it's not implemented, overnight scans will time out or hit yfinance rate limits.

---

## Conviction Score Letter Grade Mapping

Based on the 5.8/10 threshold decision (Phase 2, D-01 updated) and realistic score distribution:

| Grade | Score Range | Meaning |
|-------|------------|---------|
| A | 8.0 – 10.0 | Exceptional setup — all signals aligned, high conviction |
| B | 6.5 – 7.9 | Strong setup — most signals positive |
| C | 5.8 – 6.4 | Threshold pass — minimum viable signal |
| D | 4.0 – 5.7 | Below threshold — notable but not tradeable |
| F | 0.0 – 3.9 | Weak signal — no meaningful alignment |

Grade boundaries are config-driven (`GRADE_THRESHOLDS` in `config.py`), not hardcoded, so they can be adjusted after observing real score distributions.

---

## Sources

- Direct codebase analysis: `scanner.py`, `sentiment_cache.py`, `state.py`, `dashboard.py`, `bot.py`, `config.py`, `server.py`, `agents/coordinator.py`, `agents/news_analyst.py`, `strategies/__init__.py`
- `.planning/PROJECT.md` — milestone goals and constraints
- `.planning/ROADMAP.md` — phase history and dependencies
- `.planning/STATE.md` — accumulated decisions (D-01 through D-20)
- `.planning/research/ARCHITECTURE.md` (2026-03-27) — original architecture research
