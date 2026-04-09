# Domain Pitfalls: Intelligence Suite (v2.0)

**Domain:** Adding 6 major features to an existing Python/Flask trading bot
**Researched:** 2026-04-02
**Scope:** Score recalibration, overnight scanner, expanded stock scanner (500+ stocks), multi-source news, Intelligence tab, PDF report
**Confidence:** HIGH for rate-limiting and threading pitfalls (well-documented). MEDIUM for PDF memory and overnight timing specifics (depends on implementation choices).

---

## Critical Pitfalls

### 1. yfinance Throttling at 500+ Stock Scale

**What goes wrong:** The current scanner uses `ThreadPoolExecutor(max_workers=15)` to fetch bars for ~60 stocks. Expanding to S&P 500 + NASDAQ 100 + volume lists puts 500-600 concurrent yfinance calls through Yahoo Finance's undocumented rate limiter. Yahoo Finance silently begins returning empty DataFrames, 429s, or stale data after roughly 50-100 rapid requests per IP within a short window. The scanner already discards `None` results gracefully (`return None`), so throttled symbols will silently disappear from scan results with no alert.

**Why it happens:** yfinance is a scraping wrapper over Yahoo Finance private APIs. There is no published rate limit and no API key. Yahoo can and does change throttling behavior without notice. Running 15 workers simultaneously, each fetching 5-day 5-minute bars, creates a burst spike that triggers IP-level throttling.

**Consequences:** The expanded scanner will appear to work but produce degraded scan results. You'll see far fewer than 500 symbols evaluated per cycle, with no error logged — just missing candidates. The bot may miss the best setup of the day because that stock was in the throttled batch.

**Prevention:**
- Reduce `max_workers` to 5-8 for the large-scale scan. Slower but reliable.
- Add jitter between requests: `time.sleep(random.uniform(0.1, 0.3))` inside `fetch_bars_yf`.
- Track and log how many symbols return `None` per scan cycle. If >20% return None, emit a `log.warning` about possible throttling.
- Run the expanded scanner in off-peak time slots (e.g., the overnight scanner runs post-market when Yahoo load is lower).
- Consider using Alpaca's own bar data API for the core 60-stock watchlist during market hours, falling back to yfinance only for the extended discovery scan.

**Detection:** Log `scan_null_count` to state. Alert if null rate > 20%.

**Phase:** Expanded scanner phase — must address before deploying the 500-stock scan.

---

### 2. SEC EDGAR Requests Without User-Agent Block All Traffic

**What goes wrong:** EDGAR's API (both the REST endpoint `https://data.sec.gov/` and the RSS feed `https://www.sec.gov/cgi-bin/browse-edgar`) requires a proper `User-Agent` header that identifies your application and contact email. Requests without it, or with a generic browser `User-Agent`, receive HTTP 403 responses. The SEC enforces a strict 10 requests/second rate limit per IP with automated blocking for violations.

**Why it happens:** The SEC published explicit requirements in 2022 requiring applications identify themselves. The existing `sentiment.py` and `scanner.py` already use `headers={"User-Agent": "Mozilla/5.0"}` — this is exactly the wrong pattern for EDGAR. A browser user-agent on EDGAR tells the SEC you're scraping without identifying yourself and is treated as abuse.

**Consequences:** All SEC EDGAR RSS feeds (Form 8-K, 10-Q, insider filings) will return 403. If the code treats a 403 as an empty feed, EDGAR-based catalysts will silently provide zero signals.

**Prevention:**
```python
EDGAR_HEADERS = {
    "User-Agent": "TradingBot/2.0 your@email.com",  # REQUIRED by SEC
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov",
}
```
- Use a dedicated `_edgar_fetch()` function that enforces this header pattern.
- Add a 0.15-second sleep between sequential EDGAR requests to stay under the 10/s limit.
- Cache EDGAR results for at least 15 minutes. Do NOT poll EDGAR more frequently than this.
- Never fire EDGAR requests from a ThreadPoolExecutor alongside other HTTP sources — keep it on a single serial background thread.

**Detection:** Log HTTP status codes from EDGAR. A 403 on startup should raise a `log.error`, not be silently swallowed.

**Phase:** Multi-source news phase — must be solved before any EDGAR integration.

---

### 3. State Dict Grows Unbounded with Intelligence Tab Data

**What goes wrong:** The current `_state` dict in `state.py` uses `deque(maxlen=200)` for chart history and `deque(maxlen=100)` for trade log — both bounded. The Intelligence tab will add SPY/QQQ/DIA/IWM chart series, VIX time-series, sector heatmap data (11 sectors × N data points), breadth data, and AI brief text. If these are stored as plain Python lists and updated every scan cycle without bounds, the process memory will grow without limit over a long running session.

**Why it happens:** The existing `state.update()` function accepts any dict — it does no size enforcement. New fields added as plain lists will keep growing unless they use `deque(maxlen=N)`.

**Consequences:** On a development machine with limited RAM, the bot will silently degrade as memory pressure increases. The Flask dashboard SSE stream sends the full state snapshot every 1 second — a large state dict creates significant per-second serialization overhead that compounds over hours.

**Prevention:**
- All new time-series state fields must use `deque(maxlen=N)` initialized in `_state`. Never use plain `[]` for anything that gets appended over time.
- The AI brief is a single string that gets replaced, not appended — that's fine as-is.
- Sector heatmap is a snapshot (11 values), not a series — store as a plain dict, not a list.
- VIX history: `deque(maxlen=100)` is sufficient.
- Run the `snapshot()` function timing check: if the snapshot serialization takes >50ms, the SSE stream will stutter.

**Detection:** Log `len(state_snapshot_bytes)` periodically. Warn if snapshot JSON exceeds 50 KB.

**Phase:** Intelligence tab phase — design state fields before implementation.

---

### 4. PDF Generation Blocks the Flask Thread

**What goes wrong:** PDF generation libraries (ReportLab, WeasyPrint, pdfkit) are synchronous and CPU-intensive. Generating a report with embedded charts — account summary, P&L chart, positions table, trade history — can take 2-10 seconds. If the `/api/report/download` endpoint generates the PDF inline on the Flask request thread, every other dashboard request (including the 1-second SSE stream) will block for that duration.

**Why it happens:** Flask runs with its built-in single-threaded development server. Even if `threaded=True` is used, Python's GIL limits true parallelism for CPU-intensive work. Chart generation (matplotlib figure rendering to bytes) is the main bottleneck.

**Consequences:** The dashboard freezes for the user during PDF generation. The SSE stream gaps out, the user sees the dashboard go stale, and bot monitoring is interrupted.

**Prevention:**
- Generate the PDF in a background thread (`threading.Thread`). Return a task ID immediately from the POST endpoint. Add a GET endpoint that checks if the PDF is ready and returns it when done.
- OR: Generate the PDF on demand but use `io.BytesIO` in-memory (never write to disk) and avoid matplotlib entirely. Use ReportLab's native drawing primitives for charts instead of rendering matplotlib figures — ReportLab chart generation is 5-10x faster than matplotlib-to-PNG embedding.
- Keep charts simple (line charts for P&L, not complex multi-axis plots) to minimize generation time.
- Limit the report to the last 30 days of trade data — not full history.

**Detection:** Add response time logging on the PDF endpoint. Flag if generation exceeds 3 seconds.

**Phase:** PDF report phase.

---

### 5. Finnhub Free Tier Rate Limit is 60 Calls/Minute

**What goes wrong:** The Finnhub free tier enforces 60 API calls per minute. The expanded scanner plans to fetch news for 500+ stocks. If news is fetched per-symbol during the scan (as the current sentiment approach does for a single symbol), 500 symbols × 1 news call = 500 calls, which hits the rate limit in 30 seconds and starts returning 429 errors.

**Why it happens:** Per-symbol API calls that work fine at 60-stock scale break at 500-stock scale without a rate-aware batching layer.

**Consequences:** After the first 60 news calls, all subsequent calls return 429. The scanner silently assigns neutral sentiment scores to 440 stocks. The Intelligence tab news feed will intermittently fail.

**Prevention:**
- Use Finnhub's **company news** endpoint which returns multiple articles in a single call. Batch the 500 symbols but fetch news for only the top N candidates (the ones that passed technical filters first). Do NOT fetch news for all 500 — only the 20-30 finalists.
- Maintain a news cache keyed by symbol with a 15-minute TTL. Never refetch news for a symbol that was recently updated.
- Add a `_finnhub_calls_this_minute` counter with a reset timer. If approaching 55 calls, pause and wait for the minute window to reset.
- For the Intelligence tab's market news feed, use a single Finnhub market news call (not per-symbol), which counts as 1 call.

**Detection:** Log all 429 responses from Finnhub explicitly. A single 429 should emit `log.warning("[news] Finnhub rate limit hit — throttling for 60s")`.

**Phase:** Multi-source news phase.

---

### 6. RSS Feed XML Parsing Is Fragile Against Malformed Feeds

**What goes wrong:** MarketWatch, Reuters, and Google News RSS feeds are structurally inconsistent. Google News RSS returns Atom-format feeds (not RSS 2.0), which use `<entry>` elements instead of `<item>`. MarketWatch sometimes includes CDATA-wrapped content that confuses `xml.etree.ElementTree`. Reuters RSS periodically changes its feed structure. The current `sentiment.py` uses `ET.fromstring(resp.content)` and `.findall(".//item")` — this will silently return zero results for Atom feeds.

**Why it happens:** The existing code was written for Yahoo Finance RSS which is standard RSS 2.0. Other feed sources don't follow the same schema.

**Consequences:** Google News RSS (likely the highest-volume news source) returns zero articles permanently. The news feed on the Intelligence tab appears empty. No errors are logged because `findall(".//item")` on an Atom feed simply returns an empty list.

**Prevention:**
- Use the `feedparser` library (pure Python, no C dependencies) instead of raw `xml.etree.ElementTree`. Feedparser handles RSS 2.0, RSS 1.0, Atom, and most malformed variants transparently.
- `feedparser.parse(url)` returns a normalized dict regardless of underlying feed format.
- Add a feed health check: if a feed returns 0 entries for 3+ consecutive cycles, log a warning.
- Validate that `feedparser` is added to `requirements.txt` — it's not currently present.

**Detection:** Log entry count per feed source per cycle. Zero entries for any known-active feed should emit `log.warning`.

**Phase:** Multi-source news phase.

---

### 7. Overnight Scanner Timing Breaks at DST Boundaries and Holidays

**What goes wrong:** The overnight scanner needs to run "post-market" (after 4:00 PM ET) but before the user goes to sleep. The current bot already has market-hours logic in `safety.py` using Eastern time. But DST transitions (March and November) shift the UTC offset by 1 hour. A hardcoded "run after 16:00 UTC-5" check will run 1 hour early during EDT (UTC-4) and miss the post-market window. Additionally, the overnight scanner should not run on market holidays — but there's no holiday calendar in the existing code.

**Why it happens:** The existing `assert_market_open()` in `safety.py` likely uses the Alpaca market calendar (which IS holiday-aware), but the overnight scanner may use a simpler time check if implemented naively.

**Consequences:** The scanner triggers at 3 PM on DST changeover days (market still open, data incomplete). On holidays, it triggers but fetches data for a session that didn't exist.

**Prevention:**
- Use Alpaca's market calendar API (`trading_client.get_calendar()`) to determine if a given day was a trading day and what the close time was. This is already available via `alpaca-py`.
- Always use `pytz` or `zoneinfo` (Python 3.9+) with the `America/New_York` timezone — never use UTC offsets directly for market time calculations.
- Trigger the overnight scanner on market close event (from the Alpaca WebSocket stream) rather than a fixed clock time. This is DST-immune.
- Add an explicit check: `if today is not a trading day: skip overnight scan`.

**Detection:** Log the computed "post-market trigger time" at startup each day. If it differs from expected by >30 minutes, emit a warning.

**Phase:** Overnight scanner phase.

---

### 8. Approve/Reject UI State Not Persisted Across Bot Restarts

**What goes wrong:** The "Tomorrow's Game Plan" approve/reject UI stores user decisions in shared state (in-memory dict). If the bot process restarts overnight — due to a crash, Windows update, or manual restart — all pending approvals are lost. The bot has no persisted state (Phase 1 added state persistence, but the overnight plan decisions were not part of that design).

**Why it happens:** `state.py` is entirely in-memory. The overnight plan is a new data structure that will be added to `_state` but won't automatically persist unless explicitly written to disk.

**Consequences:** User approves 3 setups at 9 PM, bot restarts at 11 PM, market opens with no pending approvals — the bot either does nothing or falls back to the live scan. The "Tonight's Game Plan" feature provides no value if it can't survive restarts.

**Prevention:**
- Persist overnight plan decisions to a JSON file: `.planning_state.json` (not inside `.planning/` which is tracked by git).
- Write the file on every approve/reject action, not just at shutdown.
- On bot startup, load this file and restore pending overnight decisions to state.
- Include an expiry: decisions older than 18 hours are discarded on load (they're from yesterday).

**Detection:** On startup, log whether a persisted overnight plan was found and restored.

**Phase:** Overnight scanner phase — must be part of the initial design, not a followup fix.

---

## Moderate Pitfalls

### 9. FRED API Economic Calendar Has an Undocumented Key Requirement

**What goes wrong:** The FRED API (Federal Reserve Economic Data) requires a free API key for all endpoints, including the release calendar. The API key is free but requires registration. The key must be passed as a query parameter (`api_key=YOUR_KEY`) or in a header. Requests without a key return a descriptive error JSON (not a 403), which the code may silently discard as "empty calendar."

**Prevention:**
- Register for a free FRED API key at `api.stlouisfed.org`. Add it to `.env` as `FRED_API_KEY`.
- Make `FRED_API_KEY` an optional config field (not required) with a clear startup log message if missing: `"[news] FRED_API_KEY not set — economic calendar disabled"`.
- Cache FRED release schedules for 24 hours. The FRED calendar does not change intraday.

**Phase:** Multi-source news phase.

---

### 10. ThreadPoolExecutor for 500-Stock Scan Creates 500 yfinance Objects

**What goes wrong:** The current scan creates one `yf.Ticker(symbol)` object per thread per scan cycle. At 500 stocks, 500 Ticker objects are created and garbage-collected each scan. Each Ticker object maintains an internal session cache. On Windows, Python's garbage collector does not immediately reclaim these objects, and the OS file handle count can spike during the scan burst.

**Why it happens:** yfinance's `Ticker` class opens HTTP sessions internally. Creating 500 in rapid succession without explicit session management creates resource churn.

**Prevention:**
- Prefer `yf.download(symbols_list, ...)` for bulk bar fetching (single HTTP request for multiple tickers) over individual `yf.Ticker(sym).history()` calls where the yfinance API allows it.
- Limit `max_workers` to 5 for the extended scan. The bottleneck is network/Yahoo's rate limit, not CPU — more workers don't help and make throttling worse.
- Run the 500-stock discovery scan during the overnight window only (not on the live 60-second polling loop).

**Phase:** Expanded scanner phase.

---

### 11. VIX Data from yfinance Has Different Column Schema

**What goes wrong:** VIX (`^VIX`) is an index, not a stock. yfinance returns VIX history with `Close` as the current volatility reading. However, VIX has no `Volume` column (indices don't trade), and the `Open`/`High`/`Low` columns behave differently than for equities. Code that applies standard `df.columns = [c.lower() for c in df.columns]` and then accesses `df["volume"]` will raise `KeyError` for VIX.

**Prevention:**
- Write a `fetch_vix()` function that specifically handles the VIX ticker's schema: access only `Close`, skip volume entirely.
- Do not pass VIX data through the existing `fetch_bars_yf()` function in `scanner.py` — it assumes `["open", "high", "low", "close", "volume"]` all exist.

**Phase:** Intelligence tab phase.

---

### 12. Sector Heatmap Double-Fetches What Scanner Already Computed

**What goes wrong:** The Intelligence tab's sector heatmap needs sector ETF performance data (XLK, XLE, XLF, etc.). The scanner already fetches this via `_fetch_sector_scores()` every scan cycle. If the heatmap fetches this data independently via its own yfinance call, the same 11 ETF downloads happen twice per cycle — doubling unnecessary API load.

**Prevention:**
- Expose `_fetch_sector_scores()` (or its result) through `state.py`. After each scan, write the sector scores dict to `state.update(sector_etf_scores=etf_scores)`.
- The Intelligence tab reads `sector_etf_scores` from state rather than fetching independently.
- The sector heatmap should also store the raw 5-day return (not just the 0-10 normalized score) so the UI can display actual percentage changes.

**Phase:** Intelligence tab phase.

---

### 13. Concurrent News Fetching Races Against Shared `news` State Key

**What goes wrong:** The current `state.py` has a single `"news": []` key. Multi-source news (Finnhub, Yahoo RSS, MarketWatch RSS, Google News RSS, EDGAR RSS) will each write to state on different threads and at different intervals. If each source calls `shared_state.update(news=[...])`, the last writer wins and overwrites results from all other sources.

**Why it happens:** `state.update(**kwargs)` does a simple key replacement — it's not a list-append or merge operation. Multiple sources all writing to the same key will race.

**Consequences:** The news feed shows only the output from whichever source last wrote, discarding all others.

**Prevention:**
- Use separate state keys per source: `"news_finnhub"`, `"news_yahoo_rss"`, `"news_google"`, `"news_edgar"`, `"news_fred_events"`.
- The dashboard aggregates and deduplicates them client-side (or a single `get_aggregated_news()` function in `dashboard.py` merges them on read).
- Add a `state.append_news(source, items)` helper that merges into a unified deque while preserving source attribution.

**Phase:** Multi-source news phase — the state schema must be designed before implementing any news source.

---

### 14. Letter Grade Display Logic Tied to Hardcoded Score Ranges

**What goes wrong:** Score recalibration changed the conviction threshold from 7.0 to 5.8. If the letter grade cutoffs (A/B/C/D/F) are hardcoded as absolute numbers (e.g., `>= 8.0 = A`, `>= 6.5 = B`) rather than percentile-relative, recalibrating the scoring weights in the future will break the grade display without an obvious error. The grades will persist showing "C" for setups that are now considered strong.

**Prevention:**
- Define grade cutoffs relative to the configured conviction threshold, not as absolute numbers.
- Example: `A >= threshold * 1.4`, `B >= threshold * 1.2`, `C >= threshold`, `D >= threshold * 0.7`, `F < threshold * 0.7`.
- Store grade thresholds in `config.py`, not in frontend JavaScript. The frontend should receive letter grade from the API, not compute it.

**Phase:** Score recalibration phase.

---

### 15. matplotlib Not in requirements.txt but Required for PDF Charts

**What goes wrong:** PDF report generation will need chart images (P&L equity curve, trade frequency histogram). matplotlib is the obvious choice, but it is not in `requirements.txt` and is not currently imported anywhere in the codebase. On a fresh install, `import matplotlib` will fail silently if imported in a try/except block, producing a PDF with blank chart placeholders and no error message.

**Prevention:**
- Add `matplotlib>=3.7.0` and `reportlab>=4.0.0` (or `weasyprint>=60.0`) to `requirements.txt` explicitly.
- Add an import check at bot startup: if PDF generation libraries are missing, log a clear `log.warning("[report] PDF generation disabled — install reportlab")` and disable the `/api/report/download` endpoint rather than returning a broken PDF.

**Phase:** PDF report phase.

---

## Minor Pitfalls

### 16. Google News RSS Returns Encoded Redirect URLs, Not Direct Article Links

**What goes wrong:** Google News RSS `<link>` tags contain Google redirect URLs (`https://news.google.com/rss/articles/CBMi...`), not the actual article URLs. If the dashboard displays these as clickable links, clicking opens a Google redirect page, not the article. This makes the news tab appear broken.

**Prevention:** Accept Google News redirect URLs as-is — they do redirect correctly in a browser. Document this behavior in code comments. Do not attempt to resolve the final URL at fetch time (that doubles HTTP requests and is fragile).

**Phase:** Multi-source news phase.

---

### 17. Pre-market Data in the Overnight Scanner Has Very Different Characteristics

**What goes wrong:** The overnight scanner runs post-close and may fetch "pre-market" or "extended hours" bar data from yfinance (`prepost=True`). Extended hours bars have extremely low volume, wide bid-ask spreads, and high price volatility that does not represent the regular session. If the scanner applies the same volume ratio and momentum indicators to extended-hours bars, it will generate false high-conviction signals from tiny pre-market moves.

**Prevention:**
- The overnight scanner should only use regular-session close data from the current day and prior days. Never use extended-hours bars as input to conviction scoring.
- yfinance: pass `prepost=False` (the default) explicitly in all overnight scanner fetches to make intent clear.

**Phase:** Overnight scanner phase.

---

### 18. PDF File Left on Disk if Download Fails Midway

**What goes wrong:** If the PDF is written to a temp file on disk (`tempfile.NamedTemporaryFile`) and the download request is cancelled or errors, the temp file is never deleted. On Windows, temp files in `%TEMP%` accumulate over time. For a long-running bot, this becomes a disk space leak.

**Prevention:**
- Use `io.BytesIO` (in-memory buffer) for PDF generation. Never write to disk. The Flask response streams directly from the BytesIO buffer.
- If disk files are unavoidable, use `tempfile.TemporaryFile()` with a context manager, or register a cleanup callback on the response.

**Phase:** PDF report phase.

---

## Phase-Specific Warnings

| Phase | Topic | Likely Pitfall | Mitigation |
|-------|-------|---------------|------------|
| Score recalibration | Letter grade thresholds | Hardcoded cutoffs break on future recalibration | Express grades relative to `CONVICTION_THRESHOLD` |
| Score recalibration | Hover breakdown UI | Score components change names/weights — UI desync | Drive breakdown labels from API response, not hardcoded JS |
| Overnight scanner | Timing trigger | DST transitions shift trigger time by 1 hour | Use Alpaca market calendar for close time, not fixed clock |
| Overnight scanner | State persistence | Approved setups lost on restart | Write approve/reject to JSON file on every action |
| Overnight scanner | Extended hours data | Pre/post-market bars inflate signals | Always fetch with `prepost=False` |
| Expanded scanner | yfinance throttling | Silent data loss above ~100 concurrent requests | Reduce workers to 5-8, add jitter, log null rate |
| Expanded scanner | Resource churn | 500 Ticker objects per cycle | Use `yf.download()` for batch fetches |
| Expanded scanner | Scan duration | 500 stocks at 5 workers = slow | Only run extended scan during overnight window, not live loop |
| Multi-source news | EDGAR User-Agent | 403 from SEC blocks all EDGAR data | Use `"TradingBot/2.0 email"` header, never browser UA |
| Multi-source news | RSS Atom format | Google News uses Atom, not RSS — `findall("item")` returns [] | Use `feedparser` library |
| Multi-source news | Finnhub rate limit | 60 calls/min exceeded if per-symbol | Only fetch news for finalists, not all 500 |
| Multi-source news | State key collision | Multiple sources overwrite `state["news"]` | Separate state keys per source |
| Multi-source news | FRED API key | Missing key = silent empty calendar | Make optional with explicit warning on missing |
| Intelligence tab | Shared sector data | Heatmap re-fetches data scanner already computed | Write ETF scores to state after scan, read from state |
| Intelligence tab | VIX schema | `df["volume"]` KeyError on VIX ticker | Write dedicated `fetch_vix()` function |
| Intelligence tab | Unbounded state growth | Intelligence time-series data grows forever | Initialize all new series as `deque(maxlen=N)` |
| PDF report | Flask thread blocking | Synchronous PDF generation blocks dashboard | Generate in background thread, return task ID |
| PDF report | Missing dependencies | `matplotlib` not in requirements.txt | Add to requirements.txt with startup import check |
| PDF report | Temp file leak | Disk accumulates temp PDFs on Windows | Use `io.BytesIO` in-memory, never write to disk |

---

## Integration Pitfalls (Cross-Feature)

### A. The Scan Loop Is Not Designed to Scale From 60 to 500 Stocks

The current scan is designed as a per-cycle live scan: every 60 seconds, score all watchlist symbols, return the best buy. This model works at 60 stocks (60s / 15 workers ≈ 4s per cycle). At 500 stocks with 5 workers, a single scan cycle takes 40-100 seconds depending on network latency. That's longer than the 60-second polling interval.

**Resolution:** The extended 500-stock scan must be a separate, infrequent process (run once at market open + once post-close) that writes its top-50 candidates to state. The live 60-second loop scans only those 50 candidates using the existing logic. Two-tier scanning: discovery (slow, broad) and monitoring (fast, narrow).

### B. Multiple Background Threads Competing for yfinance

After this milestone, the bot will have: (1) the 60-second scan loop (yfinance bars), (2) the sentiment polling thread (yfinance might be added for per-symbol news), (3) the overnight scanner (yfinance bars), and (4) the Intelligence tab refresh (yfinance for SPY/QQQ/VIX). All of these hitting yfinance simultaneously from different threads increases the throttling risk multiplicatively.

**Resolution:** Centralize all yfinance calls through a single rate-aware fetch queue. A `_yf_fetch_queue` with a semaphore limiting concurrent yfinance calls to 5 globally (not per-module) prevents different threads from inadvertently combining into a traffic spike.

### C. The `state.update()` Guard Silently Drops New Keys

`state.update()` in `state.py` only updates keys that already exist in `_state`:
```python
for k, v in kwargs.items():
    if k in _state:     # <-- new keys are silently dropped
        _state[k] = v
```
Every new state key added by the Intelligence Suite (sector_etf_scores, vix_history, overnight_plan, news_finnhub, etc.) must be explicitly initialized in `_state` at the bottom of `state.py`. If a developer adds a `state.update(overnight_plan=data)` call without adding `"overnight_plan": None` to the initial `_state` dict, the data is silently discarded with no error.

**Resolution:** Add a `state.set_new_key()` function for initialization, or change the guard to raise on unknown keys during development (and log a warning in production). At minimum, the code review checklist for every state-writing feature should include "verify key initialized in `_state`."

---

## Sources

All findings based on:
- Direct inspection of the existing codebase (`scanner.py`, `sentiment.py`, `state.py`, `dashboard.py`)
- SEC EDGAR documented rate limit policy and User-Agent requirement (published 2022, enforced ongoing) — MEDIUM confidence
- yfinance throttling behavior at scale — documented in community reports and library issues — MEDIUM confidence
- Finnhub free tier documented rate limits (60 calls/minute) — from Finnhub official docs — HIGH confidence
- Python threading and Flask development server limitations — well-established — HIGH confidence
- feedparser vs xml.etree.ElementTree for multi-format RSS — documented behavior — HIGH confidence
- DST/market calendar timing issues — well-documented in financial software engineering — HIGH confidence
- All state.py architectural findings — direct code inspection — HIGH confidence
