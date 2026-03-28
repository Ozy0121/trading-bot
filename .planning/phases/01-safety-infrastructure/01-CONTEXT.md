# Phase 1: Safety Infrastructure + Bracket Orders - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Harden the bot's foundation and add server-side position protection. This phase delivers: state persistence across restarts, options-aware PDT tracking, order fill confirmation with intelligent partial fill handling, options-capable emergency liquidation, startup validation, AND — critically — bracket orders on Alpaca's servers (stop-loss + take-profit) for every position so the user is protected when offline.

The bracket orders are the highest priority item in this phase. The user cannot monitor the bot 24/7 and needs Alpaca's servers to enforce stop-losses and take-profits automatically.

</domain>

<decisions>
## Implementation Decisions

### State Persistence (SAFE-01)
- **D-01:** Claude's Discretion on storage format — JSON file vs SQLite. Data volume is tiny (peak prices, entry dates, PDT history for 1-3 positions), so simplicity is preferred.
- **D-02:** Claude's Discretion on flush frequency — write-on-change vs periodic. Consider that crash safety matters more than I/O performance at this data volume.
- **D-03:** Claude's Discretion on file location — project root vs data/ subdirectory. Consider existing project structure (logs/ exists, no data/ dir currently).
- **D-04:** On corrupted state files, log a warning and start with fresh/empty state. Do not crash or block startup. Worst case is losing trailing stop history for one session — acceptable for a $500 account.

### Order Fill Handling (SAFE-03)
- **D-05:** 10-second timeout for order fill polling. Market orders on liquid stocks fill in <1s; 10s covers edge cases like trading halts.
- **D-06:** Smart partial fill handling — analyze the context (fill ratio, time elapsed, position significance) to decide whether to accept the partial fill and cancel remainder, or retry for the full quantity. Not a one-size-fits-all rule — the bot should reason about the circumstance.
- **D-07:** Claude's Discretion on order rejection handling — decide based on Alpaca rejection types whether to retry or skip.

### Options Liquidation (SAFE-04)
- **D-08:** Claude's Discretion on options exit pricing strategy — LIMIT at mid-price vs bid price, with fallback behavior if no fill within timeout.
- **D-09:** Claude's Discretion on liquidation architecture — unified function with type detection vs separate stock/options paths. Should fit naturally with existing `liquidate_all()` structure.

### Startup Validation (SAFE-05)
- **D-10:** Claude's Discretion on behavior when options trading is not enabled — REQUIREMENTS say "fails loudly if not" (SAFE-05), but practical use may favor graceful degradation. Claude should weigh the requirement against usability.
- **D-11:** Claude's Discretion on whether to add a buying power check at startup — consider that `calculate_safe_qty()` already handles insufficient funds at trade time.

### PDT Options Awareness (SAFE-02)
- **D-12:** Straightforward implementation — PDT tracker must recognize OCC-format options symbols (e.g., `AAPL240119C00150000`) and count them toward the 3-trade limit. No user decision needed — the OCC format is standardized.

### Bracket Orders (BRACKET-01 through BRACKET-05)
- **D-13:** Every stock buy MUST immediately place a bracket order on Alpaca with stop-loss (3% below entry) and take-profit (6-8% above entry). These orders live on Alpaca's servers and execute even if the bot/laptop is off. This is the #1 priority in the phase.
- **D-14:** On startup, bot must check all existing positions for active stop-loss orders on Alpaca. If any position is missing a stop-loss, recreate it automatically.
- **D-15:** On shutdown, bot must confirm all positions have active server-side stop-losses. If any are missing, WARN the user and offer to place them before exiting.
- **D-16:** Dashboard must show stop-loss and take-profit prices for each open position.
- **D-17:** Stop-loss and take-profit percentages must be adjustable from the dashboard (API endpoint + UI controls).
- **D-18:** The existing local trailing stop system (`_peak_prices`, `trailing_stop_triggered()`) becomes redundant for stocks with bracket orders. Claude's Discretion on whether to keep it as a backup or remove it — bracket orders on Alpaca's servers are now the primary protection mechanism.

### Claude's Discretion
Areas where Claude has flexibility:
- Storage format and location for state persistence (D-01, D-02, D-03)
- Order rejection handling strategy (D-07)
- Options liquidation pricing and architecture (D-08, D-09)
- Startup validation behavior and scope (D-10, D-11)
- Whether to keep local trailing stops as backup alongside bracket orders (D-18)

Claude should make pragmatic choices favoring simplicity, debuggability, and safety — appropriate for a small-account bot with limited complexity.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Safety Module
- `safety.py` — Current safety guardrails: daily loss tracking, trailing stops, PDT protection, position sizing, market hours, kill switch, liquidate_all. All state is in-memory globals that reset on restart.
- `state.py` — Thread-safe shared state with Lock. No persistence. Contains peak_price, PDT fields, trade_history.

### Configuration
- `config.py` — All config loading from .env. Relevant: TRAILING_STOP_PCT, DAILY_LOSS_LIMIT, MAX_POSITION_VALUE, PAPER_TRADING.

### Trading Core
- `bot.py` — Core trading loop. Imports all safety functions. Submits MarketOrderRequest and assumes instant fill. Lines 33-51 show all safety imports.

### Codebase Analysis
- `.planning/codebase/CONCERNS.md` — Documents all known issues this phase addresses: no state persistence (Tech Debt #2), no order-to-fill confirmation (Missing Critical Features #1), no partial fill handling (#3), trailing stop peak not persisted (Known Bug #3), PDT race conditions (Fragile Areas #2).

### Requirements
- `.planning/REQUIREMENTS.md` — SAFE-01 through SAFE-05 and BRACKET-01 through BRACKET-05 definitions with acceptance criteria.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `safety.py` global dicts (`_peak_prices`, `_positions_opened_today`, `_session_start_equity`) — these are the exact state that needs persistence. Wrapping them with a persistence layer is the core task.
- `state.py` Lock pattern — established thread-safe read/write pattern that persistence should follow.
- `logger_setup.py` `log_trade_event()` — structured logging for all new safety events (fill polling, state load/save, options validation).
- `config.py` `_require()`, `_float()`, `_int()` helpers — pattern for adding any new config parameters.

### Established Patterns
- Module-level constants loaded at import time via config.py
- Broad `except Exception` catching with logging (existing pattern, not ideal but consistent)
- `MarketOrderRequest` for stock orders — options will need `OptionOrderRequest` or similar from alpaca-py
- All safety functions take `trading_client: TradingClient` as first param

### Integration Points
- `bot.py` lines 33-51: imports all safety functions — new functions plug in here
- `bot.py` main loop: order submission happens via `place_buy()` / `place_sell()` — fill polling wraps around these
- `liquidate_all()` in safety.py: needs to detect and handle options positions
- `server.py`: startup sequence where options validation check should run
- `config.py`: any new config params (state file path, fill timeout) go here

</code_context>

<specifics>
## Specific Ideas

- Partial fill handling should be intelligent — analyze fill ratio, time elapsed, and context to decide whether to accept partial or retry. User explicitly wants the bot to "think about it" rather than follow a rigid rule.
- The bot serves a $500 account — complexity should match the stakes. Simple, debuggable solutions preferred over enterprise-grade infrastructure.
- Bracket orders are the user's #1 priority — they cannot be at their computer 24/7 and need server-side protection. Every dollar of profit is at risk when the laptop is closed without bracket orders.
- The local trailing stop system becomes secondary once bracket orders exist. Alpaca's servers handle stop-losses even when the bot is offline — this is the whole point.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-safety-infrastructure*
*Context gathered: 2026-03-27*
