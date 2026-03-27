# Codebase Concerns

**Analysis Date:** 2026-03-27

## Tech Debt

**Broad exception handling in trading operations:**
- Issue: Many try-except blocks catch all exceptions with `except Exception:` without distinguishing between transient network errors, API rate limits, invalid credentials, and actual trading failures.
- Files: `bot.py` (lines 86-90, 95-99, 103-128, 442-443), `dashboard.py` (lines 125-148, 159-268, 281-295), `safety.py` (lines 121-133, 137-149, 153-161, 223-245, 260-293)
- Impact: Silent failures in critical trading paths. An order might fail for reasons other than position size, but the exception is treated identically. Makes debugging production issues difficult.
- Fix approach: Implement specific exception handling for `APIError`, `InsufficientFundsError`, `SymbolError` and log them distinctly. Retry logic for network errors should be separate from error logging for invalid orders.

**Global state variables for position tracking:**
- Issue: Position peak prices, PDT history, and session equity are tracked in global module-level dictionaries (`_peak_prices`, `_positions_opened_today`, `_session_start_equity`) in `safety.py`. No persistence across restarts.
- Files: `safety.py` (lines 33-38, 60-99, 103-115)
- Impact: If the bot crashes and restarts, all trailing stop history is lost, and PDT tracking resets. Could lead to hitting PDT limits in real trading if tracking is corrupted.
- Fix approach: Persist position metadata (peak prices, buy dates) to a local SQLite database or JSON file with daily cleanup. Initialize from file on startup.

**Unvalidated external API responses:**
- Issue: Yahoo Finance ticker data (scanner.py), ARK API (catalysts.py), and news APIs return complex nested JSON/XML without schema validation. Missing keys default to sensible values, but malformed responses could silently create garbage signals.
- Files: `scanner.py` (lines 72-112, 158-143), `catalysts.py` (lines 71-96, 119-140), `sentiment.py` (lines 35-67, 70-102)
- Impact: If Yahoo Finance changes response format or API returns partial data, the scanner could produce nonsensical scores. ARK API downtime falls back to config.WATCHLIST without alerting user.
- Fix approach: Add schema validation using `pydantic` or `marshmallow`. Wrap external API calls with retry logic + exponential backoff. Log all API failures with timestamps so user sees when data sources are degraded.

**Tight coupling between bot trading logic and shared state:**
- Issue: `bot.py` directly updates `shared_state` module across 20+ call sites, and the state dict has no schema validation. Dashboard reads raw state without type safety.
- Files: `bot.py` (lines 158-162, 196-200, 222-225, 318-339, 343-352), `state.py` (lines 102-170)
- Impact: Changing state structure requires updating bot.py AND all dashboard endpoints. Hard to refactor safely. Race conditions possible if state is mutated while being serialized for HTTP response.
- Fix approach: Create a `StateManager` class with typed properties and a change log. Use property decorators to validate assignments. Add a state schema validation on every update.

## Known Bugs

**Watchlist size explosion with top movers:**
- Symptoms: When `USE_TOP_MOVERS=true`, the scanner can return 50+ symbols on volatile days, creating massive API load scanning Yahoo Finance OHLCV for each one. No scanning timeout.
- Files: `scanner.py` (lines 115-118, 258-275), `bot.py` (lines 260-269)
- Trigger: Market opens on day with broad rally or fear event → top gainers list grows. Each symbol takes 1-3 seconds to fetch bars → entire scan cycle can exceed 60 seconds.
- Workaround: Set `USE_TOP_MOVERS=false` and use fixed WATCHLIST. Reduce `POLL_INTERVAL` if you want faster scans.
- Fix approach: Implement a scanner timeout (e.g., 30 seconds total scan time). Early-exit scanning if N candidates already found with high conviction. Add a dynamic watchlist limit based on previous cycle time.

**Dashboard SSE stream never closes gracefully:**
- Symptoms: Browser tab left open will eventually accumulate hundreds of stale SSE connections. Reconnect logic on frontend is missing.
- Files: `dashboard.py` (lines 71-86)
- Trigger: Open /api/stream in browser, close tab, reopen. Browser keeps old connection alive.
- Workaround: Browser reload forces reconnection. Manual cleanup not available.
- Fix approach: Add a max connection lifetime (e.g., 5 minutes) in the generator. Implement client-side reconnect with exponential backoff in the frontend JavaScript.

**Trailing stop peak price not persisted across restart:**
- Symptoms: Bot closes position near trailing stop level, crashes. Restarts and opens same position → peak price resets to entry, trailing stop protection is lost until price rises above entry.
- Files: `safety.py` (lines 60-99), `bot.py` (lines 294-299)
- Trigger: Bot crash while holding position. Restart with same position still open.
- Workaround: Manually close position and reopen after restart, or accept temporary loss of stop protection.
- Fix approach: Serialize peak prices to a file whenever they're updated. Load on startup. Keyed by symbol + session date.

## Security Considerations

**Credentials in .env files in git (checked but not read):**
- Risk: `.env`, `.env.paper`, `.env.live` files are present. If accidentally committed, API keys leak.
- Files: `.env`, `.env.paper`, `.env.live` (confirmed in git history)
- Current mitigation: `.gitignore` lists `*.env` files. However, if any .env file was committed before the gitignore rule was added, it remains in git history.
- Recommendations:
  1. Run `git log --all -- "*.env"` to check if any env files are in history
  2. If found, use `git-filter-branch` or `git-filter-repo` to purge from history
  3. Rotate API keys immediately
  4. Use GitHub Secrets or a secrets manager for production deployment

**No request signing for outbound API calls:**
- Risk: Outbound requests to catalyst APIs, sentiment APIs, and news APIs are unauthenticated. If Alpaca API keys are exposed, an attacker can't make orders (Alpaca validates), but they can replay your auth to these free APIs.
- Files: `catalysts.py` (lines 71-96, 119-140), `sentiment.py` (lines 35-102)
- Current mitigation: Free APIs don't require auth anyway. Attack surface is low.
- Recommendations: Monitor for unusual API usage patterns (spike in lookups for single symbol). Consider rate-limiting requests internally.

**No HTTPS certificate pinning for Alpaca API:**
- Risk: Alpaca SDK uses standard SSL/TLS. If attacker compromises the machine, they can intercept all Alpaca API calls.
- Files: `server.py` (lines 55-64), `bot.py` (trading client calls throughout)
- Current mitigation: Runs on user's local machine. Network is assumed trusted.
- Recommendations: Use VPN if running on untrusted network. Consider firewall rules limiting outbound HTTPS to Alpaca IPs only.

**No order confirmation step before execution:**
- Risk: Manual order POST endpoint (`/api/order`) in dashboard has no approval workflow. Single click = order executes immediately.
- Files: `dashboard.py` (lines 419-423)
- Current mitigation: User can only access dashboard if they have network access to localhost:5000. Only they can place orders.
- Recommendations: Add a 5-second confirmation delay before order executes. Implement a "dry-run" mode for testing. Log all manual orders with user IP + timestamp.

## Performance Bottlenecks

**Watchlist scan cycle time grows with watchlist size:**
- Problem: Scanner fetches OHLCV data for each symbol sequentially. Yahoo Finance request = 1-3 seconds per symbol. With 20 symbols = 20-60 seconds per cycle. If POLL_INTERVAL=60, scan + indicators can consume the entire window.
- Files: `scanner.py` (lines 123-143, 258-275), `bot.py` (lines 260-269)
- Cause: `yfinance` is wrapped in a for-loop without parallelization. Catalyst fetch is serial. Each request waits for response.
- Improvement path:
  1. Parallelize bar fetches using `ThreadPoolExecutor` with max_workers=5
  2. Cache yesterday's OHLCV locally and only fetch today's bars (delta fetch)
  3. Implement a scan timeout: if cycle exceeds 40 seconds, skip remaining symbols
  4. Pre-warm cache during market-closed hours

**Indicator computation on every scan cycle:**
- Problem: `compute_all()` in indicators.py recalculates RSI, MACD, Bollinger Bands for 50+ bars even though only the last bar changed. EWM operations are O(n) per indicator.
- Files: `indicators.py` (lines 41-100), `bot.py` (lines 312-315), `scanner.py` (lines 147-253)
- Cause: No incremental/streaming indicator updates. Entire series recomputed from scratch.
- Improvement path: Cache previous bar's indicator state + only update with new close. Use talib library (C extension) for faster computation if indicator performance becomes critical.

**SSE state serialization on every second:**
- Problem: Every second, the entire bot state (including deques, lists, nested dicts) is serialized to JSON and streamed to all browsers. With 10 clients = 10 JSON serializations/second.
- Files: `dashboard.py` (lines 71-86), `state.py` (lines 163-169)
- Cause: No delta compression. No filtering of fields that actually changed.
- Improvement path:
  1. Only send fields that changed since last push (delta protocol)
  2. Compress state fields that don't need real-time updates (history, trade_log) into summaries
  3. Reduce push frequency from 1s to 3-5s for non-critical metrics
  4. Move large series (indicator charts) to dedicated endpoints with caching

## Fragile Areas

**Catalyst confirmation logic is opaque:**
- Files: `scanner.py` (lines 201-234), `catalysts.py` (lines 145-172)
- Why fragile: ARK buying + analyst upgrade are scored additively (+40, +30) but high-conviction filter requires ALL FOUR technical conditions. If ARK buys a stock but RSI is 72, it still gets a BUY signal. Logic is: `score >= 100` = BUY, but score includes catalyst bonuses. Not clear from code.
- Safe modification: Add explicit comments explaining the order of operations. Create a `ConvictionScore` namedtuple with separate fields for tech score vs. catalyst bonus. Add unit tests covering edge cases (all tech conditions fail but ARK buys).
- Test coverage: No unit tests for `_score_symbol()`. Edge cases: RSI=NaN, volume=0, MACD missing, multiple catalysts.

**PDT limit enforcement has race conditions:**
- Files: `safety.py` (lines 101-149), `bot.py` (lines 404-410)
- Why fragile: `check_pdt_allows_buy/sell` calls `get_account()` to fetch day trade count, but there's a delay between the check and the actual order submission. If two bot instances run simultaneously, both could see 2/3 day trades, both place buy orders, both breach the limit.
- Safe modification: Use Alpaca's order submission dry-run feature to validate PDT before placing. Or add a local counter that gets incremented before submitting, blocking further buys.
- Test coverage: No test for concurrent PDT scenarios. No test for equity < $25k boundary.

**Position PnL calculation depends on avg_cost being set correctly:**
- Files: `bot.py` (lines 85-99, 166-201), `state.py` (lines 133-161)
- Why fragile: If a position is opened by a previous bot instance or manually, `avg_cost` might be stale or wrong. PnL is calculated as `(price - avg_cost) * qty`. If avg_cost is off by $0.01, the trade record will have incorrect P&L.
- Safe modification: Always fetch fresh position data from Alpaca API before calculating PnL. Verify avg_cost from `trading_client.get_open_position()` before using it.
- Test coverage: No test for positions opened externally. No test for partial fills.

**Exception handlers swallow networking errors:**
- Files: `catalysts.py` (lines 73-86, 119-132), `sentiment.py` (lines 43-67, 79-102)
- Why fragile: `requests.get()` + `except Exception` catches timeout, DNS failure, SSL error identically. If API is down, user gets no alert. If network is unstable, failures are silent.
- Safe modification: Catch `requests.RequestException` specifically. Log timeout vs. connection error differently. Implement retry with exponential backoff for transient failures.
- Test coverage: No tests for network failures. No tests for malformed JSON/XML responses.

## Scaling Limits

**Memory usage of history deques:**
- Current capacity: `HISTORY_LIMIT = 200` and `trade_log maxlen = 100`. Each history entry is ~500 bytes (OHLCV + indicators + timestamps).
- Limit: At 200 entries * 500 bytes = 100 KB per deque. With 10 concurrent dashboard clients streaming state every 1s, memory is negligible. But if you store 30 days of intraday bars (43,200 bars), memory will spike.
- Scaling path: Move long-term history to SQLite database. Keep only today's bars in memory. Query historical data on demand for charts.

**Watchlist size for scanning:**
- Current: Tested with 15-50 symbols. With 100+ symbols, scan cycle becomes 5+ minutes.
- Limit: Market open at 9:30 AM ET, need to complete first scan by 10:00 AM. If scan takes 5+ minutes with current serial fetching, you miss the opening momentum.
- Scaling path: Parallelize bar fetches. Implement priority queue (large-cap mega-movers scanned first, penny stocks scanned last if time permits). Drop symbols that haven't moved in 2+ days.

**Dashboard concurrent connections:**
- Current: Flask development server (single-threaded). Each SSE connection blocks one thread.
- Limit: Flask default is 1 worker. With 5 simultaneous dashboard clients, you can't accept new HTTP requests (POST /api/order blocked).
- Scaling path: Run Flask with Gunicorn + multiple workers. Move SSE to a separate async server (Quart, FastAPI). Implement a pub-sub message queue for state updates.

**Alpaca API rate limits:**
- Current: Bot makes ~5 API calls per POLL_INTERVAL (get_account, get_all_positions, get_orders, get_clock, place_order). Dashboard makes dozens more.
- Limit: Alpaca free tier throttles to ~200 requests/minute. With slow poll cycles, you're safe. But with scanner hammering Yahoo Finance + sentiment APIs, you're not hitting Alpaca limits yet.
- Scaling path: Implement local caching with TTLs for frequently accessed data (account, positions, clock). Batch requests where possible.

## Dependencies at Risk

**yfinance library maintenance:**
- Risk: yfinance is community-maintained, not officially supported by Yahoo Finance. Yahoo frequently changes web scraping targets, breaking yfinance without warning.
- Impact: Scanner stops fetching bar data. All entry signals collapse. No buys can be placed.
- Migration plan: Primary: Use Alpaca's native historical data API (already have `StockHistoricalDataClient` in imports). Secondary: Switch to Polygon.io (free tier available). Tertiary: Finnhub or IEX Cloud.

**requests library SSL context:**
- Risk: requests library version < 2.28 had known SSL certificate verification bypass bugs. Current code uses requests but doesn't pin version tightly.
- Impact: If older requests is installed, SSL/TLS for Alpaca API could be bypassed.
- Migration plan: Pin `requests>=2.31.0` in requirements.txt. Add a startup check `requests.__version__` and warn if < 2.28.

**pandas and numpy version compatibility:**
- Risk: Code uses `.iloc[]` indexing, EWM calculations, and rolling operations which changed behavior between pandas 1.x and 2.x.
- Impact: If user installs pandas 3.0 (future release), indicators might break or produce different values.
- Migration plan: Pin `pandas>=2.0.0,<3.0.0` and `numpy>=1.24.0,<2.0.0` in requirements.txt.

## Missing Critical Features

**No order-to-fill confirmation:**
- Problem: Bot submits a market order and immediately assumes it filled. If order is rejected by Alpaca (e.g., trading halted), the bot thinks it has a position when it doesn't.
- Blocks: Can't track accurate P&L. Can't implement stop-loss if position doesn't exist. Can't sell when you think you own shares.
- Impact: HIGH. Silent position tracking failure could lead to overleveraging.
- Fix: Implement order status polling. After submitting an order, poll `trading_client.get_order()` until status is FILLED or REJECTED. Only record trade if FILLED.

**No slippage/fill price tracking:**
- Problem: Bot uses last bar close for entry/exit prices in logs. Actual fill price could be $0.50 worse.
- Blocks: P&L tracking is approximate. Performance metrics are misleading.
- Impact: MEDIUM. Affects profitability analysis and strategy tuning.
- Fix: Fetch filled order's `filled_avg_price` from Alpaca API and use that for P&L calculations.

**No partial fill handling:**
- Problem: If market order fills 50 shares out of 100 requested, bot records full position but only 50 shares are owned.
- Blocks: Position size tracking is wrong. Trailing stops and take-profits are off.
- Impact: HIGH. Position management is corrupted.
- Fix: Poll order status until order is fully filled or rejected. If partially filled, place another order for the remainder or cancel and alert user.

**No intraday position averaging:**
- Problem: If bot buys TSLA at 10:00 AM and gets another BUY signal at 11:00 AM, it skips (only one position allowed). Missing potential to average in on strong moves.
- Blocks: Can't implement pyramid strategy.
- Impact: LOW. Design decision, not a bug. But limits strategy flexibility.

**No correlation/pair trading:**
- Problem: Bot trades single symbols independently. Can't correlate entries across the watchlist (e.g., avoid buying both AMD and NVDA on same day).
- Blocks: Can't implement sector hedging or volatility strategies.
- Impact: LOW. Outside current scope, but noted for future expansion.

## Test Coverage Gaps

**Untested: High-conviction filter edge cases**
- What's not tested: What happens when `rsi_val` is NaN (few bars available)? What if volume_ratio is infinity (avg_vol = 0)? What if MACD histogram is exactly 0?
- Files: `scanner.py` (lines 147-253)
- Risk: Dividing by zero, NaN comparisons, missing exception handling could cause silent failures.
- Priority: HIGH — affects entry signals daily.
- Fix: Add unit tests for each conviction condition with edge case values. Add defensive checks: `if pd.isna(rsi_val): return None`, etc.

**Untested: PDT boundary at $25,000 equity**
- What's not tested: Does the bot correctly enable/disable PDT checks when crossing $25k equity? What if equity fluctuates around $25k intraday?
- Files: `safety.py` (lines 118-149)
- Risk: User might get PDT blocked when they shouldn't, or bypass when they should.
- Priority: HIGH — affects trading in margin accounts.
- Fix: Unit tests for PDT logic with equity = $24,999 and $25,001. Integration test crossing the boundary.

**Untested: Trailing stop with gap-down opens**
- What's not tested: If market opens with a 10% gap down (pre-market event), does trailing stop trigger correctly?
- Files: `safety.py` (lines 76-89), `bot.py` (lines 355-369)
- Risk: Bot might liquidate the position at gap-down price, only to see reversal 2 minutes later.
- Priority: MEDIUM — rare but impactful.
- Fix: Test with historical data including gap-down days. Consider adding a "wait for open cross" check before triggering stop on first bar of the day.

**Untested: Concurrent dashboard + bot state mutations**
- What's not tested: If dashboard is reading state while bot is writing (trade execution), can you get torn reads (partial state)?
- Files: `state.py` (lines 102-170), `bot.py` (lines 318-339)
- Risk: Dashboard shows stale/inconsistent state. User sees qty=100 but avg_cost=0 (mismatch).
- Priority: MEDIUM — data consistency.
- Fix: Add read-write lock to state module. Add unit tests that spawn concurrent threads updating state while querying it.

**Untested: External API failures (ARK, sentiment, news)**
- What's not tested: What happens if arkfunds.io is down for an hour? Does the scanner still work? Does the bot keep running?
- Files: `catalysts.py` (lines 55-172), `sentiment.py` (lines 35-125)
- Risk: If catalyst APIs are down, bot might avoid high-conviction entries it should make. Or sentiment becomes stale.
- Priority: LOW — graceful degradation is implemented (fallback to watchlist, silent API failures). But no alerting to user.
- Fix: Add a "data freshness" metric in state. Track last successful fetch time for each external API. Alert user if any data is > 1 hour old.

---

*Concerns audit: 2026-03-27*
