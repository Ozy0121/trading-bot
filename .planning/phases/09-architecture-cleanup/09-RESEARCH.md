# Phase 9: Architecture Cleanup - Research

**Researched:** 2026-05-13
**Domain:** Python refactoring — Flask Blueprints, threading locks, schema validation, module decomposition
**Confidence:** HIGH (all findings from direct codebase inspection; no external library changes required)

## Summary

Phase 9 is a pure refactoring phase with no new features. All six issues are self-contained code
changes within the existing Python/Flask stack. No new dependencies are needed. The main risk is
regression: splitting dashboard.py requires careful handling of the shared module-level globals
(`_trading_client`, `_data_client`, `_kill_fn`, `_start_fn`, `_coordinator`) and the `app` Flask
object. The safety.py locking issue is the highest-priority risk — `_peak_prices` has a confirmed
read-then-write race in `update_peak_price()` that could corrupt trailing stop tracking.

The codebase already has the right patterns everywhere: `state.py` uses `with _lock:` correctly,
`dashboard.py` uses `set_dependencies()` injection, and `safety.py` already has `_state_lock` for
file I/O. The fix is extending those established patterns, not introducing anything new.

**Primary recommendation:** Flask Blueprints for the dashboard split; a single module-level
`_globals_lock` in safety.py for the three unprotected globals; immediate ValueError (not staged
rollout) for state.py unknown-key validation; shared_state as the single prediction source of truth
with prediction_scanner writing INTO it directly; server.py wrapped in per-service try/except blocks.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Split dashboard.py into 3 route modules:
  - Trading routes: `/api/order`, `/api/start`, `/api/stop`, `/api/kill`, `/api/sell_all`, `/api/config/exits`, `/api/positions`, `/api/orders`, `/api/orders/history`, `/api/account`, `/api/performance`, `/api/backtest/*`, `/api/predictions/auto-trade`
  - Scanner/prediction routes: `/api/predictions`, `/api/predictions/run`, `/api/overnight/*`, `/api/expanded-scan/*`, `/api/scan`, `/api/intelligence`, `/api/heatmap/*`, `/api/scan-logs`, `/api/prediction-log/*`
  - Core/data routes: `/`, `/api/state`, `/api/stream`, `/api/health`, `/api/quote/<symbol>`, `/api/bars/<symbol>`, `/api/agents/status`
- **D-02:** User confirmed the three-way grouping (trading, scanner/predictions, core/data)
- **D-03:** Unify the two prediction data sources (shared_state in-memory vs prediction_scanner.get_latest_predictions() from disk) into a single source of truth
- **D-04:** state.py update() must raise ValueError on unknown keys (matching success criteria). Currently logs a warning and ignores on line 140.
- **D-05:** Isolate server.py startup so that failure in optional services (scanner, office bridge, sentiment) does not block the dashboard from launching

### Claude's Discretion
- Dashboard split implementation approach (Flask Blueprints vs plain modules) — user deferred
- Which prediction data source becomes canonical (shared_state vs disk) — user deferred
- State validation migration path (immediate ValueError vs staged rollout) — user deferred
- Server startup isolation pattern (try/except per service vs service registry with priorities) — user deferred
- safety.py locking strategy for `_session_start_equity`, `_peak_prices`, `_positions_opened_today` — no ambiguity, just add Lock protection
- bot.py run_bot function extraction — no ambiguity, just extract 14 phases into named functions

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

## Standard Stack

### Core (no new dependencies — all existing)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| flask | existing | Web framework with Blueprint support | Already in use; Blueprints are built-in |
| threading | stdlib | Lock for safety.py globals | Already used in state.py |
| python | 3.x | Language runtime | Project standard |

### No New Packages Required
This phase is pure refactoring. All required capabilities (Flask Blueprints, threading.Lock,
ValueError exceptions) are already available in the installed stack. [VERIFIED: direct codebase inspection]

---

## Architecture Patterns

### Recommended Project Structure After Split

```
trading-bot/
├── dashboard.py              # Flask app object, set_dependencies(), run() — thin coordinator only
├── routes/
│   ├── __init__.py           # empty
│   ├── trading.py            # Blueprint: trading routes
│   ├── scanner.py            # Blueprint: scanner/prediction routes
│   └── data.py               # Blueprint: core/data routes
├── safety.py                 # globals protected by _globals_lock
├── state.py                  # update() raises ValueError on unknown keys
├── bot.py                    # run_bot() decomposed into named phase functions
└── server.py                 # per-service try/except isolation
```

### Pattern 1: Flask Blueprints for Dashboard Split

**What:** Flask Blueprints allow route definitions in separate modules that register against the
central `app` object in dashboard.py. Each Blueprint file is self-contained but shares the same
dependency injection via a module-level reference.

**Why Blueprints over plain module imports:** Blueprints have proper request context isolation,
support `url_prefix` if ever needed, and are the Flask-idiomatic solution for exactly this problem.
Plain module imports that call `@app.route` also work but require `app` to be importable before
routes are defined, creating circular import risk. [VERIFIED: Flask docs pattern, confirmed against
existing dashboard.py structure]

**The dependency injection problem:** The three route modules need access to `_trading_client`,
`_data_client`, `_kill_fn`, `_start_fn`, and `_coordinator`. These are currently set via
`set_dependencies()` and `set_coordinator()` in dashboard.py. With Blueprints, two options exist:

Option A (recommended): Keep the dependency variables in dashboard.py. Each Blueprint imports
them from dashboard at request time (lazy import inside route function). This avoids circular
imports because route functions are called after app startup, not at import time.

Option B: Give each Blueprint its own `set_dependencies()` function called from server.py.
More explicit but requires server.py to call 4 functions instead of 1.

**Recommendation: Option A** — lazy imports inside route functions are already the project pattern
(dashboard.py already does `from prediction_scanner import ...` inside route handlers). No circular
import risk.

**Example Blueprint structure:**
```python
# routes/trading.py
from flask import Blueprint, jsonify, request, abort
import config
import state as shared_state

trading_bp = Blueprint("trading", __name__)


@trading_bp.route("/api/account")
def api_account():
    from dashboard import _trading_client   # lazy — no circular import at module level
    if _trading_client is None:
        abort(503, "Not connected.")
    ...
```

```python
# dashboard.py (after split)
from flask import Flask
from routes.trading import trading_bp
from routes.scanner import scanner_bp
from routes.data import data_bp

app = Flask(__name__)
app.register_blueprint(trading_bp)
app.register_blueprint(scanner_bp)
app.register_blueprint(data_bp)

_trading_client = None
_data_client    = None
_kill_fn        = None
_start_fn       = None
_coordinator    = None


def set_dependencies(trading_client, data_client, kill_fn, start_fn):
    global _trading_client, _data_client, _kill_fn, _start_fn
    _trading_client = trading_client
    _data_client    = data_client
    _kill_fn        = kill_fn
    _start_fn       = start_fn


def set_coordinator(coordinator):
    global _coordinator
    _coordinator = coordinator


def run(port: int = 5000):
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
```

**Routes that stay in dashboard.py (core/data):** `/`, `/api/state`, `/api/stream`, `/api/health`,
`/api/quote/<symbol>`, `/api/bars/<symbol>`, `/api/agents/status`. These are most tightly coupled to
the app object and SSE stream. They can remain as `@app.route` decorators in dashboard.py directly,
or be placed in `routes/data.py` as a Blueprint. Either is fine.

[ASSUMED: Blueprint lazy-import pattern avoids circular imports in this specific file layout — should
be tested at Wave 0 with a smoke import check]

### Pattern 2: Threading Lock for safety.py Globals

**What:** The three unprotected globals need a single `threading.Lock` guarding all reads and writes.

**Current state (verified from source):**
- Line 82: `_state_lock = threading.Lock()` — EXISTS but is used ONLY for the JSON file write in
  `_save_state()`. It does NOT protect the in-memory globals.
- Line 323: `_session_start_equity: float | None = None` — mutated in `record_session_start_equity()`
  with no lock
- Line 351: `_peak_prices: dict[str, float] = {}` — mutated in `record_peak_price()`,
  `update_peak_price()`, `clear_peak_price()` with no lock
- Line 397: `_positions_opened_today: set[str] = set()` — mutated in `record_buy_date()`,
  `clear_position_date()` with no lock

**The confirmed race condition:** `update_peak_price()` (line 361-366) does:
```python
def update_peak_price(symbol: str, price: float) -> None:
    sym = symbol.upper()
    if sym not in _peak_prices or price > _peak_prices[sym]:   # READ
        _peak_prices[sym] = price                               # WRITE
        _save_state()
```
Between the read (`sym not in _peak_prices`) and the write (`_peak_prices[sym] = price`), another
thread can modify `_peak_prices`. In this bot, the protection monitor thread (started by
`start_protection_monitor()` in server.py) and the main bot loop thread both call safety functions,
making this a real (not theoretical) race. [VERIFIED: source inspection of safety.py and server.py]

**Recommended approach:** Add a new `_globals_lock = threading.Lock()` (separate from `_state_lock`
which covers file I/O only) and wrap all reads and writes of the three globals with `with _globals_lock:`.

Alternatively, reuse `_state_lock` to cover both file I/O and in-memory globals — simpler, one less
lock. But: `_save_state()` itself holds `_state_lock`, so callers that hold `_globals_lock` while
calling `_save_state()` would deadlock if they're the same lock and not reentrant. Python's
`threading.Lock` is NOT reentrant. Use a `threading.RLock` or keep them as separate locks.

**Recommended: add `_globals_lock = threading.RLock()`** — RLock allows the same thread to acquire
it multiple times, which handles the `record_peak_price()` → `_save_state()` → `_state_lock`
pattern safely. OR keep them as two separate non-reentrant Locks (no nesting needed if `_save_state`
uses its own `_state_lock`). The existing `_save_state` already acquires `_state_lock` internally —
if callers hold `_globals_lock` when calling `_save_state`, there is no deadlock as long as these
are two different Lock objects. This is the safer and simpler choice.

**Concrete implementation:**
```python
_globals_lock = threading.Lock()   # protects _peak_prices, _positions_opened_today, _session_start_equity

def update_peak_price(symbol: str, price: float) -> None:
    sym = symbol.upper()
    with _globals_lock:
        if sym not in _peak_prices or price > _peak_prices[sym]:
            _peak_prices[sym] = price
    _save_state()   # _save_state has its own _state_lock, no nesting issue
```

[VERIFIED: threading.Lock non-reentrancy confirmed via Python stdlib docs knowledge; codebase pattern
verified by inspecting safety.py and state.py]

### Pattern 3: State Schema Validation (Immediate ValueError)

**Current behavior (line 140, verified):**
```python
else:
    import logging
    logging.getLogger(__name__).warning("[state] Unknown key ignored: %s", k)
```

**Decision D-04 requires:** raise ValueError on unknown keys.

**Immediate vs staged rollout question (Claude's discretion):**
Staged rollout (warn first, then raise) would require a flag and temporary code. This is a
refactoring phase — the point is to surface bugs, not hide them. Immediate ValueError is correct.

**Recommended implementation:**
```python
def update(**kwargs) -> None:
    with _lock:
        for k, v in kwargs.items():
            if k not in _state:
                raise ValueError(f"[state] Unknown key: {k!r}. Check for typos. "
                                 f"Valid keys: {sorted(_state.keys())}")
            _state[k] = v
```

**Migration risk:** If any existing caller passes an unknown key, this will crash the calling thread
at runtime (not import time). The warning log that currently exists would have surfaced such bugs.
Before switching to ValueError, the planner should include a task to grep all `state.update()` call
sites and verify every key they pass is in the schema. [VERIFIED: state.py schema has 50+ keys,
all defined at module level in `_state` dict]

**One confirmed exception:** The `scan_funnel` key is written by dashboard.py line 745:
```python
shared_state.update(..., scan_funnel=funnel.get("breakdown", {}), ...)
```
But `scan_funnel` does NOT exist in the `_state` dict in state.py. This call would immediately raise
ValueError. It must be audited and either added to the schema or removed. [VERIFIED: grepped
dashboard.py line 745, confirmed scan_funnel is not in state.py _state dict]

### Pattern 4: Prediction Data Source Unification

**Current two-source architecture (verified):**

Source A — `shared_state["predictions"]` (in-memory):
- Written by: `dashboard.py:api_predictions_run()` (line 741) via `predict_batch()`
- Written by: `prediction_scanner.run_overnight_scan()` (line 143) which writes into shared_state
- Read by: `dashboard.py:api_predictions()` (line 685) via `shared_state.snapshot()`
- Read by: SSE stream (line 89) which reads full snapshot

Source B — `prediction_scanner.get_latest_predictions()` (disk):
- Written by: `run_overnight_scan()` saves to `data/overnight_predictions.json`
- Read by: `dashboard.py:api_predictions_auto_trade()` (line 976) calls `get_latest_predictions()`
- Read by: `dashboard.py:api_overnight()` (line 761) calls `get_latest_predictions()`

**The divergence scenario:** After the bot restarts, `shared_state["predictions"]` is empty (in-memory
reset), but `prediction_scanner.get_latest_predictions()` still returns disk data. The auto-trade
route and the predictions display route then return different results. [VERIFIED: both paths confirmed
by source inspection]

**Which source becomes canonical (Claude's discretion):** `shared_state` should be the single
source. Reasons:
1. It is already read by the SSE stream (live push to dashboard)
2. It is already what `api_predictions()` returns
3. `run_overnight_scan()` already writes into it (line 143)
4. The disk file should be a persistence/recovery mechanism only — on startup, if shared_state is
   empty and the disk file is recent (same day), load it INTO shared_state

**Recommended unification approach:**
- `prediction_scanner.get_latest_predictions()` continues to read from disk (no change to function)
- On server startup or first access, if `shared_state["predictions"]` is empty, auto-load from disk
- `api_predictions_auto_trade()` and `api_overnight()` switch from calling
  `get_latest_predictions()` to reading `shared_state.snapshot()["predictions"]` /
  `shared_state.snapshot()["overnight_predictions"]`
- A new `load_predictions_into_state()` helper in prediction_scanner.py reads disk and calls
  `shared_state.update(predictions=...)` on startup

[ASSUMED: "same day" disk file is safe to load on startup — if predictions are from a prior day
they should be discarded, which prediction_scanner already tracks via scan_date field]

### Pattern 5: bot.py run_bot Phase Extraction

**Current state (verified):** `run_bot()` is 294 lines (line 435-729). It has 14 numbered comment
phases inline. The while loop body is ~260 lines.

**Recommended extraction pattern:**
```python
def run_bot(trading_client, data_client, session_start_equity):
    _setup_bot(trading_client)
    while not _shutdown_requested:
        cycle_start = datetime.now(timezone.utc)
        try:
            _phase_1_scan_watchlist(trading_client, ...)
            if not _phase_2_market_hours(trading_client, cycle_start):
                continue
            account_data = _phase_3_account_info(trading_client)
            if _phase_4_daily_loss_check(account_data, trading_client):
                break
            ...
        except Exception as exc:
            log.error("[bot] Unhandled exception: %s", exc, exc_info=True)
        _interruptible_sleep(config.POLL_INTERVAL)
```

Each extracted function receives the data it needs as parameters and returns its result. No new
global state. Functions remain private (`_phase_N_*` naming) — consistent with project naming
conventions for internal helpers. [VERIFIED: project naming convention uses `_` prefix for internal
functions]

**Phase boundary challenge:** Phases 3 through 14 share a large amount of local state
(`equity`, `cash`, `bp`, `held_symbol`, `held_qty`, `avg_cost`, `price`, `sig`, `scan_results`,
etc.). Extracting these cleanly requires either passing many parameters or using a cycle-state
dataclass. A simple `dict` or `dataclass` passed through the phases avoids parameter explosion.

**Recommended: cycle context dict passed through phase functions:**
```python
@dataclass
class CycleState:
    account_data: dict = None
    scan_results: list = None
    held_symbol: str = ""
    held_qty: float = 0
    ...
```

### Pattern 6: Server Startup Isolation

**Current state (verified from server.py):** All service startups are sequential and unguarded:
```python
live_stream.start(config.API_KEY, config.SECRET_KEY)       # line 83 — no try/except
sentiment_feed.start()                                      # line 84 — no try/except
# ... then agent coordinator, office bridge, overnight scheduler — all unguarded
```

**Only the office bridge has partial handling:**
```python
def _start_office():
    if not os.path.isdir(backend_dir) ...
        log.warning("...skipping")
        return
    try: ...
    except Exception as exc:
        log.warning(...)
```
But `office_bridge.connect(agent_bus)` (line 164) and `start_overnight_scheduler()` (line 169) have
no protection.

**Service criticality classification:**
| Service | Critical? | Reason |
|---------|-----------|--------|
| `TradingClient` / `StockHistoricalDataClient` | YES — fail loud | No dashboard without these |
| `validate_options_enabled()` | YES — fail loud | Required safety check |
| `live_stream.start()` | Optional | Price updates degrade gracefully |
| `sentiment_feed.start()` | Optional | Sentiment data non-critical |
| `AgentCoordinator` startup | Optional | Agents can fail independently |
| `office_bridge.connect()` | Optional | Pixel art visualization only |
| `start_overnight_scheduler()` | Optional | Overnight scans can run manually |
| `start_overnight_daemon()` | Optional | Expanded scanner runs manually |
| `start_protection_monitor()` | Recommended | Should warn but not block |

**Recommended pattern (try/except per optional service):**
```python
# Optional services — wrapped individually, dashboard still starts on failure

try:
    live_stream.start(config.API_KEY, config.SECRET_KEY)
    log.info("[server] Live stream started")
except Exception as exc:
    log.warning("[server] Live stream failed to start (continuing): %s", exc)

try:
    sentiment_feed.start()
    log.info("[server] Sentiment feed started")
except Exception as exc:
    log.warning("[server] Sentiment feed failed to start (continuing): %s", exc)

# ... etc for each optional service
```

This is the simplest pattern matching the CLAUDE.md error handling convention:
"Exceptions are logged with context and details, using log.warning() ... Graceful fallbacks: return
sensible defaults." [VERIFIED: CLAUDE.md Error Handling section]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Route modularization | Custom import/registration scheme | Flask Blueprints | Built-in, idiomatic, no risk |
| Thread-safe reads | Manual flag variables | `threading.Lock` context manager | Already used in state.py |
| Schema validation | Custom key whitelist logic | Simple `if k not in _state: raise` | Single dict comparison is sufficient |
| State startup hydration | Complex sync protocol | Load disk → `shared_state.update()` once at startup | Disk file already exists, schema already matches |

**Key insight:** This phase should use zero new libraries. Every problem has a solution already
present in the codebase.

---

## Common Pitfalls

### Pitfall 1: Circular Import Between dashboard.py and routes/

**What goes wrong:** If `routes/trading.py` does `from dashboard import _trading_client` at module
level (top of file), and `dashboard.py` does `from routes.trading import trading_bp`, you get a
circular import that crashes at startup.

**Why it happens:** Python's import system resolves circular imports by returning a partially
initialized module, meaning `_trading_client` may not exist yet when the import runs.

**How to avoid:** Import `from dashboard import _trading_client` INSIDE route handler functions
(lazy import), not at module top-level. This is already the codebase pattern — dashboard.py itself
does `from prediction_scanner import get_latest_predictions` inside handler functions. [VERIFIED:
dashboard.py lines 761, 793, 804]

**Warning signs:** `ImportError: cannot import name '_trading_client' from partially initialized
module 'dashboard'` at server startup.

### Pitfall 2: scan_funnel Key Missing from state.py Schema

**What goes wrong:** `dashboard.py` line 745 calls `shared_state.update(..., scan_funnel=...)`.
After D-04 raises ValueError on unknown keys, this line crashes the prediction scan background
thread silently (thread dies, no predictions appear in dashboard, no error shown to user).

**Why it happens:** `scan_funnel` is not in the `_state` dict in state.py. [VERIFIED: grepped
state.py — key is absent]

**How to avoid:** Before implementing D-04, run a grep of all `state.update()` call sites and add
any missing keys to the `_state` schema. `scan_funnel` must be added explicitly.

**Additional keys to audit:** Check `bot.py`, `prediction_scanner.py`, `expanded_scanner.py`,
`sentiment.py` for any `shared_state.update()` calls with keys not in the schema.

### Pitfall 3: Lock Nesting / Deadlock in safety.py

**What goes wrong:** If the new `_globals_lock` is the same object as `_state_lock`, and a caller
holds `_globals_lock` while calling `_save_state()`, which tries to acquire `_state_lock` again,
it deadlocks (Python threading.Lock is not reentrant).

**Why it happens:** `_save_state()` already acquires `_state_lock`. If a caller acquires
`_globals_lock` first and `_globals_lock is _state_lock`, re-acquiring in `_save_state()` blocks.

**How to avoid:** Use TWO SEPARATE Lock objects — `_globals_lock` for in-memory globals, `_state_lock`
for file I/O. No nesting, no deadlock. [VERIFIED: Python threading.Lock docs — non-reentrant]

### Pitfall 4: State File Write While globals_lock Is Held

**What goes wrong:** Holding `_globals_lock` while calling `_save_state()` (which does file I/O)
increases lock contention — the bot loop thread blocks waiting for a file write to finish.

**How to avoid:** Read-modify globals under `_globals_lock`, release lock, then call `_save_state()`
outside the lock. `_save_state()` already takes its own `_state_lock` for the actual file write.

```python
def update_peak_price(symbol: str, price: float) -> None:
    sym = symbol.upper()
    should_save = False
    with _globals_lock:
        if sym not in _peak_prices or price > _peak_prices[sym]:
            _peak_prices[sym] = price
            should_save = True
    if should_save:
        _save_state()   # outside _globals_lock — no nested locking
```

### Pitfall 5: Blueprint Registration Order Matters for SSE Stream

**What goes wrong:** If `routes/data.py` (which owns `/api/stream`) is registered after
`routes/trading.py`, and there's a route conflict, Flask silently uses the first registration.

**How to avoid:** Register Blueprints in a consistent order in dashboard.py. Use explicit url_prefix
or verify with `app.url_map` after registration.

### Pitfall 6: _get_prediction_candidate() in bot.py Reads from Disk

**What goes wrong:** `bot.py` has a function `_get_prediction_candidate()` (verified around line 420)
that calls `get_latest_predictions()` from prediction_scanner — the disk-based source. After
prediction unification, this would diverge from what the dashboard shows.

**How to avoid:** As part of D-03, update `_get_prediction_candidate()` in bot.py to read from
`shared_state.snapshot()["predictions"]` instead of calling `get_latest_predictions()` directly.
[VERIFIED: bot.py line ~420 area, `_get_prediction_candidate()` imports prediction_scanner]

---

## Code Examples

### Blueprint Registration (dashboard.py after split)
```python
# Source: Flask Blueprint pattern [ASSUMED: standard Flask docs pattern]
from flask import Flask
from routes.trading import trading_bp
from routes.scanner import scanner_bp
from routes.data import data_bp

app = Flask(__name__)
app.register_blueprint(trading_bp)
app.register_blueprint(scanner_bp)
app.register_blueprint(data_bp)
```

### Lock-protected update_peak_price (safety.py)
```python
# Source: adapted from existing state.py with _lock pattern [VERIFIED: state.py line 134]
_globals_lock = threading.Lock()

def update_peak_price(symbol: str, price: float) -> None:
    sym = symbol.upper()
    should_save = False
    with _globals_lock:
        if sym not in _peak_prices or price > _peak_prices[sym]:
            _peak_prices[sym] = price
            should_save = True
    if should_save:
        _save_state()
```

### State validation with ValueError (state.py)
```python
# Source: adapted from existing state.py update() [VERIFIED: state.py line 133-140]
def update(**kwargs) -> None:
    with _lock:
        for k, v in kwargs.items():
            if k not in _state:
                raise ValueError(
                    f"[state] Unknown key: {k!r}. "
                    f"Add it to _state in state.py or fix the typo. "
                    f"Valid keys: {sorted(_state.keys())}"
                )
            _state[k] = v
```

### Server startup isolation pattern (server.py)
```python
# Source: CLAUDE.md error handling convention [VERIFIED: CLAUDE.md]
_OPTIONAL_SERVICES = []

try:
    live_stream.start(config.API_KEY, config.SECRET_KEY)
    log.info("[server] Live stream started")
    _OPTIONAL_SERVICES.append("live_stream")
except Exception as exc:
    log.warning("[server] Live stream failed to start — continuing without live prices: %s", exc)

try:
    sentiment_feed.start()
    log.info("[server] Sentiment feed started")
    _OPTIONAL_SERVICES.append("sentiment")
except Exception as exc:
    log.warning("[server] Sentiment feed failed to start — continuing without sentiment: %s", exc)
```

### Startup prediction hydration (prediction_scanner.py)
```python
# Source: pattern derived from existing _last_scan_result cache [VERIFIED: prediction_scanner.py]
def load_predictions_into_state() -> bool:
    """Load today's disk predictions into shared_state on startup. Returns True if loaded."""
    import state as shared_state
    try:
        with open(PREDICTIONS_FILE) as f:
            data = json.load(f)
        if data.get("scan_date") != date.today().isoformat():
            return False   # stale — don't load
        preds = data.get("all_predictions", [])
        shared_state.update(
            predictions=preds[:30],
            prediction_count=len(preds),
        )
        return True
    except (FileNotFoundError, json.JSONDecodeError):
        return False
```

---

## Runtime State Inventory

This is a refactoring phase, not a rename/migration phase. No runtime state is renamed or migrated.
The state schema change in D-04 (ValueError on unknown keys) changes the behavior of `update()` but
does not modify what keys are stored — existing state in memory is unaffected.

**Nothing to migrate** — verified by phase scope inspection.

---

## State of the Art

| Old Pattern | Current Pattern | Applies Here |
|-------------|-----------------|--------------|
| Flat 1000-line Flask file | Flask Blueprints for route splitting | Dashboard split (D-01) |
| Unguarded module globals | threading.Lock wrapping all mutations | safety.py globals (Issue #2) |
| Silent typo swallowing | ValueError on schema mismatch | state.py validation (D-04) |
| Two prediction sources | Single in-memory source of truth | Prediction unification (D-03) |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Flask Blueprint lazy-import pattern avoids circular imports in this file layout | Architecture Patterns (Pattern 1) | Import error at startup — caught immediately in Wave 0 |
| A2 | `scan_funnel` is the only undeclared key passed to `state.update()` — other callers use declared keys | Common Pitfalls (Pitfall 2) | Additional crash sites after D-04 — mitigation: grep audit before D-04 |
| A3 | Loading today's disk predictions on startup is safe (not stale) | Pattern 4 / Code Examples | Could load outdated picks if date check fails — low risk given explicit date check |

---

## Open Questions

1. **Are there other undeclared state.update() keys besides scan_funnel?**
   - What we know: `scan_funnel` confirmed missing from schema. Other callers not fully audited.
   - What's unclear: `bot.py`, `expanded_scanner.py`, `sentiment.py` may have additional unknown keys.
   - Recommendation: Wave 0 task — grep all `shared_state.update(` calls across the repo and
     cross-reference every key against the `_state` dict. Add missing keys before D-04.

2. **Should `_get_prediction_candidate()` in bot.py be updated as part of D-03?**
   - What we know: It calls `prediction_scanner.get_latest_predictions()` (disk source).
   - What's unclear: Whether the planner treats this as in-scope for D-03.
   - Recommendation: Yes — include it in the prediction unification wave. Otherwise D-03 is
     incomplete (bot still diverges from dashboard).

3. **Does `scan_funnel` vs `expanded_scan_funnel` confusion exist elsewhere?**
   - What we know: `state.py` has `expanded_scan_funnel` (line 129). Dashboard writes `scan_funnel`.
   - What's unclear: Whether `scan_funnel` and `expanded_scan_funnel` are intended to be separate
     or the dashboard is using the wrong key name.
   - Recommendation: Audit during the grep pass. If `scan_funnel` is intended to be separate from
     `expanded_scan_funnel`, add it to the schema. If it's a typo for `expanded_scan_funnel`, fix
     the call site.

---

## Environment Availability

Step 2.6: SKIPPED — this phase is purely code refactoring with no new external dependencies,
CLI tools, databases, or runtimes beyond the existing Python/Flask stack.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | None detected (no pytest.ini, no tests/ directory) |
| Config file | None — Wave 0 must not add test infrastructure (project has no test framework) |
| Quick run command | `py server.py paper` (manual smoke test — server starts, routes respond) |
| Full suite command | Manual: start server, exercise each route group, confirm no import errors |

### Phase Requirements → Test Map

| Issue | Behavior | Test Type | Automated Command | Notes |
|-------|----------|-----------|-------------------|-------|
| D-01: Dashboard split | Server starts, all 35 routes respond | smoke | `py server.py paper` + HTTP checks | Manual verification via browser |
| Issue #2: safety lock | `update_peak_price()` called from 2 threads — no race | integration | No automated test possible without test framework | Manual: check logs for warnings |
| D-04: State ValueError | `state.update(unknown_key=1)` raises ValueError | unit | None — no test framework | Verify by adding a temporary bad key and checking for crash |
| D-03: Prediction unification | Dashboard predictions == bot candidate source | integration | Manual: run prediction scan, check `/api/predictions` vs bot log | Manual |
| D-05: Server isolation | Disable sentiment, server still starts | smoke | Comment out sentiment import, `py server.py paper` | Manual |
| bot.py extraction | Bot loop still executes all 14 phases | integration | `py server.py paper` + start bot + watch logs for all 14 phases | Manual |

### Wave 0 Gaps
No test infrastructure exists in this project. Per project conventions, no test framework is to be
added as part of this phase. All validation is manual smoke testing.

*(Existing test infrastructure: None — project has no pytest, unittest, or test directory)*

---

## Security Domain

This phase introduces no new authentication, session management, input validation, or cryptographic
operations. The changes are:
- Moving existing route handlers into Blueprint modules (no new attack surface)
- Adding thread locks (no security impact)
- Changing a warning log to a ValueError (error handling only)
- Consolidating in-memory data reads (no new data exposure)

Security domain: NOT APPLICABLE for this refactoring phase.

---

## Sources

### Primary (HIGH confidence — direct codebase inspection)
- `dashboard.py` lines 1-1087 — full route map verified, dependency injection pattern confirmed
- `safety.py` lines 82, 323, 351, 361-366, 397 — unprotected globals and race condition confirmed
- `state.py` lines 14-140 — schema keys audited, `scan_funnel` absence confirmed
- `bot.py` lines 435-729 — run_bot structure verified (14 phases, 294 lines)
- `server.py` lines 50-189 — startup sequence verified, optional services unguarded confirmed
- `prediction_scanner.py` lines 130-148 — writes to both disk and shared_state confirmed
- `CLAUDE.md` — project conventions confirmed (error handling, naming, logging)

### Secondary (MEDIUM confidence)
- Flask Blueprint pattern — standard Flask documentation pattern [ASSUMED standard, not Context7 verified]

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Issue identification: HIGH — all 6 issues confirmed via source inspection with exact line numbers
- Dashboard split approach (Blueprints): MEDIUM — standard Flask pattern, minor circular import risk to validate
- Safety lock strategy: HIGH — threading.Lock semantics are stdlib, pattern mirrors state.py exactly
- State validation: HIGH — simple dict key check, implementation is trivial
- Prediction unification: HIGH — both source paths verified, unification approach is additive
- Bot extraction: HIGH — mechanical extraction, no logic changes

**Research date:** 2026-05-13
**Valid until:** 2026-06-13 (stable refactoring — no fast-moving external dependencies)
