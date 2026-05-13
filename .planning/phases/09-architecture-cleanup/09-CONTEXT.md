# Phase 9: Architecture Cleanup - Context

**Gathered:** 2026-05-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Reduce the risk of silent bugs and thread-safety issues by splitting the monolithic dashboard, adding state schema validation, protecting shared mutable globals, unifying prediction data sources, extracting bot phases into functions, and isolating server startup failures. Six specific issues from the architecture review.

</domain>

<decisions>
## Implementation Decisions

### Dashboard Split (Issue #1)
- **D-01:** Split dashboard.py (1,086 lines, 35+ routes) into 3 route modules:
  - **Trading routes:** `/api/order`, `/api/start`, `/api/stop`, `/api/kill`, `/api/sell_all`, `/api/config/exits`, `/api/positions`, `/api/orders`, `/api/orders/history`, `/api/account`, `/api/performance`, `/api/backtest/*`, `/api/predictions/auto-trade`
  - **Scanner/prediction routes:** `/api/predictions`, `/api/predictions/run`, `/api/overnight/*`, `/api/expanded-scan/*`, `/api/scan`, `/api/intelligence`, `/api/heatmap/*`, `/api/scan-logs`, `/api/prediction-log/*`
  - **Core/data routes:** `/`, `/api/state`, `/api/stream`, `/api/health`, `/api/quote/<symbol>`, `/api/bars/<symbol>`, `/api/agents/status`
- **D-02:** User confirmed the three-way grouping (trading, scanner/predictions, core/data)

### Prediction Data Unification (Issue #4)
- **D-03:** Unify the two prediction data sources (shared_state in-memory vs prediction_scanner.get_latest_predictions() from disk) into a single source of truth

### State Validation (Issue #3)
- **D-04:** state.py update() must raise ValueError on unknown keys (matching success criteria). Currently logs a warning and ignores on line 140.

### Server Startup Isolation (Issue #6)
- **D-05:** Isolate server.py startup so that failure in optional services (scanner, office bridge, sentiment) does not block the dashboard from launching

### Claude's Discretion
- Dashboard split implementation approach (Flask Blueprints vs plain modules) — user deferred
- Which prediction data source becomes canonical (shared_state vs disk) — user deferred
- State validation migration path (immediate ValueError vs staged rollout) — user deferred
- Server startup isolation pattern (try/except per service vs service registry with priorities) — user deferred
- safety.py locking strategy for `_session_start_equity`, `_peak_prices`, `_positions_opened_today` — no ambiguity, just add Lock protection
- bot.py run_bot function extraction — no ambiguity, just extract 14 phases into named functions

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

No external specs — requirements fully captured in decisions above and ROADMAP.md Phase 9 section.

### Source Files (read before modifying)
- `dashboard.py` — 1,086 lines, 35+ routes to split into modules
- `safety.py` — Module globals on lines 323, 351, 397 need Lock protection
- `state.py` — update() on line 133, unknown-key handling on line 140
- `bot.py` — run_bot() starting at line 435, 314 lines to extract
- `server.py` — Startup sequence lines 50-189, no error isolation
- `prediction_scanner.py` — get_latest_predictions() disk-based source
- `prediction.py` — predict_batch() in-memory prediction source

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `state.py` already has `_lock = threading.Lock()` — pattern to replicate in safety.py
- `dashboard.py` already uses `set_dependencies()` injection pattern (line 93 in server.py) — useful for keeping split modules testable
- Flask `app` object created in dashboard.py — Blueprints or module imports would register against this

### Established Patterns
- Thread safety: state.py uses `with _lock:` context manager consistently
- Module globals: safety.py has `_state_lock` (line 82) but it doesn't cover `_peak_prices`, `_positions_opened_today`, `_session_start_equity`
- Dependency injection: dashboard uses `set_dependencies()` and `set_coordinator()` to receive clients

### Integration Points
- `server.py` imports and wires everything — split modules need to maintain the same injection interface
- SSE stream (`/api/stream`) reads shared_state.snapshot() — prediction unification must ensure this stays consistent
- `bot.py:run_bot_from_server()` (line 749) is the entry point called by server — extracted functions are internal to run_bot()

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 09-architecture-cleanup*
*Context gathered: 2026-05-13*
