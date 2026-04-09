# Feature Landscape: Intelligence Suite (v2.0 Milestone)

**Domain:** Trading bot intelligence layer — overnight planning, expanded scanning, news aggregation, market overview, PDF reporting
**Researched:** 2026-04-02
**Milestone context:** Adding 6 major features to an existing Python/Flask swing-trading bot that already has multi-strategy scanning, conviction scoring, bracket orders, and a 60-stock watchlist

---

## Table Stakes

Features users expect in any serious trading dashboard. Missing = product feels incomplete or amateurish.

### Score Display with Letter Grades and Hover Breakdowns

| Attribute | Value |
|-----------|-------|
| Feature | Show conviction score as letter grade (A/B/C/D/F) alongside raw numeric, with tooltip showing sub-score breakdown |
| Why expected | Every trading platform that shows a composite score (Finviz, TradingView screener, Schwab StreetSmart) renders the score AND its components. Raw 5.8/10 is meaningless to a user who doesn't know the weighting formula. |
| Complexity | Low — purely frontend. Score data already exists in `conviction` dict; grades are a mapping function. Hover tooltip via CSS/JS. |
| Dependencies | Existing conviction dict (`technical`, `volume`, `sentiment`, `sector`, `composite`) — already in state.scan_results |
| Note | Grade cutoffs need deliberate calibration: 8.0+ = A, 6.5-7.9 = B, 5.8-6.4 = C, 4.0-5.7 = D, <4.0 = F. These thresholds should match the 5.8 conviction threshold so anything below C is already below trade threshold. |

### Expanded Stock Scanner Universe

| Attribute | Value |
|-----------|-------|
| Feature | Scan S&P 500 + NASDAQ 100 + daily top-volume + unusual-volume stocks with hard filters (price, volume, market cap minimums) |
| Why expected | A 60-stock fixed watchlist misses too many opportunities. Professional scanners (Trade Ideas, Finviz) scan 3,000-8,000 symbols. For a swing-trading bot with 3 PDT trades/week, quality of the candidate universe directly determines outcome quality. |
| Complexity | Medium — need index constituent fetching (S&P 500 ~503 symbols, NASDAQ 100 ~102 symbols), deduplication, hard filter pass, then run existing conviction scoring on the filtered subset. The existing parallel scanner handles 60 symbols in <30s; 600+ symbols requires pre-filtering to a manageable subset before deep scoring. |
| Dependencies | S&P 500 constituents (Wikipedia table via `pandas.read_html` or static file), NASDAQ 100 constituents (same), top-volume screen via Yahoo Finance screener API (existing pattern in `fetch_top_movers()`), existing `scan()` orchestrator |
| Note | The hard filter pass is the key architectural decision: price $5-$500, volume >500K daily, market cap >$500M, no OTC/pink sheets, no symbols with ".". Run hard filters on all ~600 symbols first, then run deep scoring only on the top 80-100 that pass. This keeps scan time under 60 seconds. |

### Multi-Source News Aggregation

| Attribute | Value |
|-----------|-------|
| Feature | Aggregate news from Finnhub API, MarketWatch/Reuters/Google News RSS, SEC EDGAR RSS filings feed, and FRED economic calendar, deduplicated by title similarity |
| Why expected | Single-source news (currently Alpaca + Yahoo RSS) misses SEC filings, macro events (Fed rate decisions, CPI), and analyst calls from MarketWatch/Reuters. Professional platforms (Bloomberg Terminal, Refinitiv) aggregate 40+ sources. A swing bot that misses a Fed rate decision the day before a trade is materially disadvantaged. |
| Complexity | Medium — each source is a separate fetch, but all return headline strings that feed into the existing `_score_headlines()` function. Deduplication requires title normalization (lowercase, strip punctuation, first 40 chars as key). FRED calendar is economic events (dates + descriptions), not headlines — needs separate handling as a conviction penalty similar to earnings. |
| Dependencies | Existing `sentiment_cache.py` (extend, don't replace), Finnhub API (free tier: 60 calls/minute, requires `FINNHUB_API_KEY` env var), RSS parsing (existing `xml.etree.ElementTree` pattern), SEC EDGAR RSS (`https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&dateb=&owner=include&count=40&output=atom`), FRED API (`https://api.stlouisfed.org/fred/releases/dates?release_id=X&api_key=...`) |
| Note | Finnhub company news endpoint: `GET https://finnhub.io/api/v1/company-news?symbol={symbol}&from={date}&to={date}&token={key}`. Returns JSON with `headline` field. EDGAR RSS is for market-wide 8-K filings, not per-symbol — use as a market event feed, not sentiment input. FRED requires an API key (free) but is optional — economic calendar dates can be hardcoded for key releases (FOMC, CPI, NFP) rather than requiring a live API call. |

### Intelligence Tab (Market Overview)

| Attribute | Value |
|-----------|-------|
| Feature | Dedicated dashboard tab showing SPY/QQQ/DIA/IWM mini-charts, VIX gauge, sector performance heatmap, market breadth (advance/decline), and an AI brief |
| Why expected | Swing trading requires understanding macro context before picking individual stocks. Every professional terminal (Bloomberg, TD Ameritrade thinkorswim) has a market overview view. Users making 3 trades/week with $500 need this context to avoid buying into a market crash. |
| Complexity | Medium-High — four distinct sub-components with different data sources. Mini-charts reuse existing `/api/bars/<symbol>` endpoint. VIX gauge requires fetching `^VIX` via yfinance. Sector heatmap reuses `_fetch_sector_scores()` from scanner.py. Breadth requires NYSE advancing/declining issues (available via yfinance or Alpha Vantage). AI brief is the highest-complexity piece. |
| Dependencies | Existing Chart.js setup, existing sector ETF scoring in `scanner.py`, yfinance for VIX/index data, Anthropic API (`claude-sonnet-4-20250514`) for AI brief, existing SSE stream infrastructure |
| Note | The AI brief is the differentiator (see Differentiators section). VIX can be fetched via `yf.Ticker("^VIX").history(period="5d")`. Market breadth via `yf.Ticker("^ADVN")` and `"^DECL"` — these are not always reliable from yfinance; a fallback to a fixed "N/A" is acceptable. Sector heatmap is a visual rendering of data already computed in `scanner.py:_fetch_sector_scores()` — expose via a new `/api/intelligence/sectors` endpoint. |

---

## Differentiators

Features that set this bot apart. Not strictly expected, but highly valued for a serious personal trading tool.

### Overnight Scanner with Tomorrow's Game Plan

| Attribute | Value |
|-----------|-------|
| Feature | Post-market analysis run that identifies the best swing setups for the next trading day, presents them as a ranked "Tomorrow's Game Plan" with approve/reject UI, and pre-queues approved candidates for execution at open |
| Why valuable | PDT constraints make the 3 weekly trade slots extremely precious. Making the decision calmly at 7pm with full analysis is far better than making reactive decisions during market hours. No retail scanner (Finviz, Webull) offers a structured approve/reject queue — they just show screener results. This is a genuine differentiator. |
| Complexity | High — requires a scheduled job (post-market trigger at 4:15 PM ET), a new state container for "pending overnight candidates," a UI panel separate from the live scan view, and a `/api/overnight/approve` and `/api/overnight/reject` endpoint. The underlying scoring is the same existing `scan()` logic but run post-market on daily bars instead of intraday bars. |
| Dependencies | Existing `scan()` orchestrator, existing conviction scoring, scheduler (Python `sched` or `threading.Timer` — no new dependency needed), new state fields `overnight_candidates`, `overnight_approved`, new Flask endpoints, new UI panel |
| Note | Post-market bar interval: switch from `BAR_TIMEFRAME` (5Min) to `1Day` for the overnight scan to use full-day context. The approve/reject UI should show: symbol, score, strategy triggered, key indicators (RSI, volume ratio), and the top 2 headlines. "Approve" moves the candidate to a pre-queue; the bot checks pre-queue first before running a live scan at open. "Reject" removes it from consideration for the session. |

### PDF Trade Report Download

| Attribute | Value |
|-----------|-------|
| Feature | Downloadable PDF with account summary, open positions, recent trade history (last 20), performance metrics (win rate, avg gain/loss, PDT usage), and mini price charts |
| Why valuable | No open-source retail trading bot generates a professional PDF report. This enables the user to review session performance offline, share results, and keep records. Adds perceived legitimacy to a personal project. |
| Complexity | Medium — `reportlab` or `weasyprint` for PDF generation. reportlab is the standard choice (pure Python, no system dependencies). Chart images require rendering Chart.js charts server-side or using matplotlib for simple candlestick/line charts. Trade history and metrics are already in `state.trade_log` and `state.growth`. |
| Dependencies | `reportlab>=4.0` (new dependency, pip-installable, no C extension), or `weasyprint` (requires Pango/GTK on Windows — avoid), existing state fields (`trade_log`, `growth`, `performance`), new `/api/report/pdf` endpoint, matplotlib for embedded charts (already available or add as dependency) |
| Note | Use `reportlab` not `weasyprint` — weasyprint has system library dependencies that fail on Windows. Chart rendering: use matplotlib to generate a 5-day price line chart as a PNG in memory (BytesIO), embed in PDF via reportlab's `Image` element. Don't attempt to render Chart.js charts server-side (requires headless browser). Report sections: (1) Account snapshot, (2) Open positions with entry price / current P&L, (3) Last 20 trades with outcome, (4) Win rate / avg gain / avg loss / best trade / worst trade, (5) PDT usage this week, (6) Price charts for any currently held symbols. |

---

## Near-Differentiators (Table Stakes in Richer Context)

These feel like differentiators for a personal bot but are table stakes for commercial platforms. Include them.

### Conviction Score Letter Grades (Extended)

Already listed under Table Stakes — but the hover breakdown tooltip that shows "Technical: 7.2/10 (momentum breakout)" is closer to differentiator territory for a personal project. Include the verbose breakdown, not just the grade.

### AI Market Brief (Intelligence Tab Sub-Feature)

| Attribute | Value |
|-----------|-------|
| Feature | 2-4 sentence plain-English market summary generated by Claude, updated every 15 minutes, covering: overall market trend (SPY/QQQ direction), dominant sector, VIX risk level, and 1-2 notable macro events |
| Why valuable | Novice trader context (per `user_trading_experience.md`): user needs plain-English interpretation, not raw numbers. "Market is in a cautious uptrend, tech leading, VIX elevated at 22 suggesting uncertainty — consider tighter stops" is more actionable than raw data. |
| Complexity | Medium — single Anthropic API call per update cycle with a structured prompt. Input: SPY 5-day change, QQQ 5-day change, VIX current level, top/bottom sector from heatmap, any FRED macro events today. Output: 2-4 sentences. Cost: ~$0.001/call at claude-sonnet-4 pricing, negligible. |
| Dependencies | Anthropic API (`claude-sonnet-4-20250514`), existing market data (sector scores, already fetched by scanner), `^VIX` yfinance fetch, new background thread or cached on Intelligence tab load |
| Note | This overlaps with Phase 5's AI Chart Analyst requirement (already in `PROJECT.md` Active requirements). The AI brief for the Intelligence tab is broader (market-level) vs the Chart Analyst (symbol-level). Build them as two separate calls with separate prompts. Rate limit risk: 15-minute cadence is safe for Anthropic API. |

---

## Anti-Features

Features to explicitly NOT build for this milestone.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Real-time SEC EDGAR filing parsing | 8-K filings are full documents (legal language, tables, attachments). Parsing them for trading signals requires NLP at a level far beyond keyword matching and risks false signals. | Use EDGAR RSS as a timing signal only: "8-K filed for {company}" as a neutral news item, not a scored signal. |
| FRED live API dependency | FRED requires an API key and the free tier has rate limits. Economic calendar data is largely predictable (FOMC meets 8x/year, CPI monthly). | Hardcode the key economic release schedule as a static calendar. Refresh quarterly via manual update, not live API. |
| Full candlestick charts in PDF | Candlestick charts require per-bar OHLCV rendering — complex to implement in reportlab and large file sizes. | Use simple line charts (close price over 5 days) via matplotlib. Clean, fast, sufficient. |
| Sector heatmap with drill-down (clicking a sector shows its stocks) | Interactive drill-down requires significant frontend state management and additional API endpoints. Disproportionate complexity for a personal bot. | Static colored grid showing sector name + 5-day % change + color gradient. Read-only. |
| Push notifications (email, SMS, Slack) for overnight plan | Notification infrastructure (SMTP, Twilio, Slack webhooks) adds external service dependencies. User monitors via dashboard. | Dashboard badge/count indicator showing "3 candidates pending review" is sufficient. |
| Historical backtesting in PDF | Backtesting requires a separate historical data pipeline and execution simulation. Completely different scope. | Show actual live trade history only. |
| Unusual options activity scanning | Options volume/OI screening requires a paid data feed (Unusual Whales, Market Chameleon). Free APIs don't surface this data reliably. | Add unusual_volume flag for stocks (already partially doable via volume ratio), not options activity. |
| Per-symbol RSS subscriptions stored in database | A database is not in the current stack (all state is in-memory dict). Persisting user RSS subscriptions requires either file storage or SQLite — scope creep. | Use hardcoded source list in config. Sources can be toggled via env vars if customization is needed. |

---

## Feature Dependencies

```
Existing Conviction Scoring (Phase 2)
    │
    ├──→ Score Recalibration + Letter Grades   [LOW complexity, no new deps]
    │         └──→ Hover Breakdown Tooltip     [LOW complexity, frontend only]
    │
    ├──→ Expanded Scanner Universe             [MEDIUM complexity]
    │         ├── Requires: S&P 500 / NASDAQ 100 constituent fetch
    │         └── Requires: Hard filter pre-pass before deep scoring
    │
    ├──→ Multi-Source News                     [MEDIUM complexity]
    │         ├── Requires: Finnhub API key
    │         ├── Requires: extend sentiment_cache.py (not replace)
    │         └── Feeds into: existing _score_headlines()
    │
    ├──→ Overnight Scanner                     [HIGH complexity]
    │         ├── Requires: Expanded Scanner (better candidate pool)
    │         ├── Requires: Post-market scheduler trigger
    │         └── Requires: New state fields + UI panel + endpoints
    │
    ├──→ Intelligence Tab                      [MEDIUM-HIGH complexity]
    │         ├── Requires: existing sector scores (already computed)
    │         ├── Requires: Anthropic API (for AI brief)
    │         └── Requires: VIX data (yfinance ^VIX)
    │
    └──→ PDF Report                            [MEDIUM complexity]
              ├── Requires: reportlab (new pip dependency)
              └── Requires: trade_log, growth, performance in state (already exist)

Multi-Source News ──→ improves Overnight Scanner candidate quality
Expanded Scanner ──→ improves Overnight Scanner candidate pool
Intelligence Tab AI Brief ──→ informs Overnight Scanner "market context" section
```

### Dependency-Driven Build Order

1. **Score Recalibration + Letter Grades** — Zero deps, immediate visual improvement, validates scoring logic before it drives bigger features
2. **Multi-Source News** — Extends `sentiment_cache.py` which feeds all subsequent scanning. Better news = better overnight candidates.
3. **Expanded Scanner** — Larger candidate pool before the overnight scanner needs it
4. **Overnight Scanner** — Depends on scanner quality (2+3 above). Highest-value feature.
5. **Intelligence Tab** — Can be built in parallel with overnight scanner; no cross-dependency
6. **PDF Report** — All data it needs exists in state after other features are built; purely additive

---

## MVP Recommendation

For a minimal-but-working Intelligence Suite delivery, prioritize in this order:

**Must ship (core value of milestone):**
1. Overnight scanner with approve/reject UI — the #1 PDT-optimizer
2. Expanded scanner universe (S&P 500 + NASDAQ 100) — wider candidate pool directly improves trade quality
3. Score letter grades + hover breakdown — makes existing scores interpretable

**Should ship (strong supporting features):**
4. Multi-source news (Finnhub + RSS feeds) — improves conviction quality
5. Intelligence tab (sector heatmap + VIX + AI brief) — market context

**Can defer:**
6. PDF report — useful but lowest urgency; no other feature depends on it

**Rationale for order:** The overnight scanner is the killer feature — it converts the bot from reactive (trade during market hours) to deliberate (plan the night before, use all 3 PDT slots wisely). Everything else improves the quality of what feeds into it.

---

## Phase-Specific Complexity Notes

| Feature | Complexity | Main Risk | Mitigation |
|---------|------------|-----------|------------|
| Score letter grades + hover | Low | None — purely frontend | — |
| Expanded scanner (S&P 500 + NASDAQ) | Medium | Scan time explosion with 600+ symbols | Hard filter pre-pass to <100 before deep scoring |
| Multi-source news | Medium | Finnhub rate limits (60/min free tier) | Cache per symbol with existing 30-min TTL; batch requests |
| Overnight scanner | High | Post-market scheduling + new state management | Use `threading.Timer`, not a new scheduler library; store overnight state in existing `state.py` dict |
| Intelligence tab | Medium-High | AI brief latency (Anthropic API call) | Cache brief for 15 min; show stale data with timestamp |
| PDF report | Medium | Chart rendering without headless browser | Use matplotlib line charts (BytesIO) embedded in reportlab; avoid candlesticks |

---

## Sources

**Confidence: MEDIUM** — Based on domain knowledge of trading platform conventions (Bloomberg Terminal, thinkorswim, Finviz, Trade Ideas, Webull), existing codebase analysis (scanner.py, sentiment_cache.py, dashboard.py, state.py), and project context documents. Web search was unavailable during this research session; API specifics (Finnhub endpoints, FRED structure) are from training-data knowledge (knowledge cutoff August 2025) and should be verified against official docs during implementation.

**HIGH confidence findings (codebase-verified):**
- Existing conviction dict fields: confirmed in `scanner.py:457-466`
- Existing sector ETF scoring: confirmed in `scanner.py:83-135`
- Existing sentiment cache with Alpaca + Yahoo RSS: confirmed in `sentiment_cache.py`
- Existing state fields (trade_log, growth): confirmed in `.planning/codebase/ARCHITECTURE.md`
- Post-market scheduling pattern: threading.Timer is consistent with existing daemon thread architecture

**MEDIUM confidence findings (training knowledge, verify during planning):**
- Finnhub company-news endpoint structure: verify at `https://finnhub.io/api/v1/company-news` docs
- reportlab vs weasyprint Windows compatibility: verify via pip install test on Windows 11
- yfinance `^VIX` and `^ADVN`/`^DECL` ticker availability: verify with a live yfinance call before relying on it

**LOW confidence findings (verify before building):**
- FRED API free tier rate limits: check `https://fred.stlouisfed.org/docs/api/fred/` — consider skipping and using hardcoded FOMC/CPI calendar instead
- S&P 500 constituents via `pandas.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")`: Wikipedia table format changes occasionally; have a static fallback list

---
*Research completed: 2026-04-02*
*Scope: Intelligence Suite milestone (v2.0) — 6 new features*
*Prerequisite phases complete: Phase 1 (Safety + Brackets), Phase 2 (Prediction Engine + Scanning)*
