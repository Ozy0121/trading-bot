# Phase 1: Safety Infrastructure + Bracket Orders - Research

**Researched:** 2026-03-27
**Domain:** alpaca-py bracket orders, state persistence, order fill polling, options validation, PDT tracking
**Confidence:** HIGH (all key claims verified against installed library + official docs)

## Summary

This phase hardens a live trading bot's foundation by adding four capabilities that are currently absent and potentially account-breaking: state persistence across restarts, explicit order fill confirmation, options-aware PDT tracking, and — most critically — server-side bracket orders on Alpaca that protect the position even when the bot is offline.

The bracket order system is the highest-priority deliverable. The existing bot submits a `MarketOrderRequest` and immediately assumes a fill, with no server-side protection. If the laptop closes, there are no stop-losses. The alpaca-py SDK at version 0.43.2 (installed) has full support for `OrderClass.BRACKET`, `StopLossRequest`, and `TakeProfitRequest` in a single `submit_order` call. A critical gotcha: bracket order child legs appear with `OrderStatus.HELD` and are NOT visible when filtering by `QueryOrderStatus.OPEN` — you must use `QueryOrderStatus.ALL` with `nested=True` to see and verify them.

State persistence is a simple file write. The data volume is tiny (3-5 symbols worth of peak prices, buy dates, one PDT counter). JSON to a `data/` subdirectory is the right choice — matches the existing `logs/` pattern, is human-readable for debugging, and write-on-change (every mutation) is the correct flush strategy given that crash safety matters more than I/O performance at this scale. SQLite is listed as v2 scope in REQUIREMENTS.md (INFRA-V2-01) and should not be introduced here.

**Primary recommendation:** Implement bracket orders first (BRACKET-01 through BRACKET-05) as the highest-risk gap, then layer in state persistence, fill polling, and options validation.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Claude's Discretion on storage format — JSON file vs SQLite. Data volume is tiny; simplicity preferred.
- **D-02:** Claude's Discretion on flush frequency — write-on-change vs periodic. Crash safety matters more than I/O performance.
- **D-03:** Claude's Discretion on file location — project root vs data/ subdirectory.
- **D-04:** On corrupted state files, log a warning and start with fresh/empty state. Do not crash or block startup.
- **D-05:** 10-second timeout for order fill polling.
- **D-06:** Smart partial fill handling — analyze fill ratio, time elapsed, and position significance to decide accept/retry.
- **D-07:** Claude's Discretion on order rejection handling.
- **D-08:** Claude's Discretion on options exit pricing strategy.
- **D-09:** Claude's Discretion on liquidation architecture (unified vs separate paths).
- **D-10:** Claude's Discretion on options-not-enabled behavior — weigh SAFE-05 "fails loudly" requirement vs usability.
- **D-11:** Claude's Discretion on whether to add buying power check at startup.
- **D-12:** PDT tracker must recognize OCC-format options symbols and count them toward the 3-trade limit.
- **D-13:** Every stock buy MUST immediately place a bracket order on Alpaca with stop-loss (3% below entry) and take-profit (6-8% above entry). This is the #1 priority in the phase.
- **D-14:** On startup, bot must check all existing positions for active stop-loss orders on Alpaca. Recreate missing ones automatically.
- **D-15:** On shutdown, bot must confirm all positions have active server-side stop-losses. Warn and offer to place them if missing.
- **D-16:** Dashboard must show stop-loss and take-profit prices for each open position.
- **D-17:** Stop-loss and take-profit percentages must be adjustable from the dashboard.
- **D-18:** Claude's Discretion on whether to keep local trailing stops as backup or remove them alongside new bracket orders.

### Claude's Discretion

- Storage format and location for state persistence (D-01, D-02, D-03)
- Order rejection handling strategy (D-07)
- Options liquidation pricing and architecture (D-08, D-09)
- Startup validation behavior and scope (D-10, D-11)
- Whether to keep local trailing stops as backup alongside bracket orders (D-18)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SAFE-01 | Bot persists position state (peak prices, entry dates, PDT history) to local file, survives restarts | JSON file in data/ directory; write-on-change pattern; load-on-startup with corruption fallback |
| SAFE-02 | PDT tracker recognizes OCC-format options symbols and counts them toward the 3-trade limit | OCC regex `^[A-Z]{1,6}\d{6}[CP]\d{8}$` verified correct for AAPL240119C00150000 format |
| SAFE-03 | Order submission polls for fill status with timeout, handles partial fills and rejections explicitly | `trading_client.get_order_by_id(order.id)` returns Order with `filled_qty`, `filled_avg_price`, `status` fields; poll loop with 10s timeout |
| SAFE-04 | `liquidate_all()` handles both stock positions and options positions (using LimitOrderRequest) | Options positions use `LimitOrderRequest` with `PositionIntent.SELL_TO_CLOSE`; stock positions keep `MarketOrderRequest`; detect by OCC pattern |
| SAFE-05 | Bot validates options trading is enabled on the Alpaca account at startup, fails loudly if not | `account.options_approved_level` field on `TradeAccount` model; Level 2+ required for buying calls/puts |
| BRACKET-01 | Every stock buy immediately places bracket order (stop-loss 3% below, take-profit 6-8% above) | `MarketOrderRequest(order_class=OrderClass.BRACKET, stop_loss=StopLossRequest(...), take_profit=TakeProfitRequest(...))` — single call |
| BRACKET-02 | On startup, bot checks all existing positions for active stop-loss orders — recreates missing ones | Must query `QueryOrderStatus.ALL` with `nested=True`; child orders appear as `OrderStatus.HELD`; use OCO order for existing positions without bracket |
| BRACKET-03 | On shutdown, bot confirms all positions have active server-side stop-losses — warns if missing | Check before allowing exit; offer to place OCO stop-loss if missing |
| BRACKET-04 | Dashboard shows stop-loss and take-profit prices for each open position | Compute from entry price + percentages; store in shared state per position; expose via `/api/positions` |
| BRACKET-05 | Stop-loss and take-profit percentages adjustable from dashboard | New API endpoint `POST /api/config/exits`; update config values at runtime; persist to .env or separate config file |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| alpaca-py | 0.43.2 (installed) | Bracket orders, order polling, account validation | Project's mandated broker SDK |
| json (stdlib) | stdlib | State persistence | No extra dependency; human-readable for debugging |
| re (stdlib) | stdlib | OCC symbol detection | Pattern matching `^[A-Z]{1,6}\d{6}[CP]\d{8}$` |
| threading (stdlib) | stdlib | Lock for state file writes | Matches existing state.py pattern |
| pytest | 8.x latest | Test framework | Standard Python; no C extensions, works on Windows |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| unittest.mock | stdlib | Mocking TradingClient in tests | Avoids live API calls during testing |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| JSON file | SQLite | SQLite is REQUIREMENTS.md v2 scope (INFRA-V2-01). Use JSON now, migrate later. |
| Polling loop for fill status | WebSocket stream | Stream is more efficient but adds async complexity; polling is simpler for a 10s window on market orders that typically fill in <1s |
| OCO order for existing positions | Simple StopOrderRequest | Both work; OCO lets you set both stop-loss and take-profit simultaneously for startup recovery |

**Installation:**
```bash
pip install pytest
```

**Version verification:**
```bash
python -c "import alpaca; print(alpaca.__version__)"
# 0.43.2 — confirmed installed and sufficient
```

## Architecture Patterns

### Recommended Project Structure

```
trading-bot/
├── data/                    # NEW: persisted state files
│   └── bot_state.json       # peak prices, PDT history, entry dates
├── safety.py                # MODIFIED: add persistence layer, bracket order helpers
├── bot.py                   # MODIFIED: place_buy wraps bracket, startup/shutdown checks
├── config.py                # MODIFIED: add STATE_FILE_PATH, fill timeout constants
├── dashboard.py             # MODIFIED: positions with SL/TP prices, config endpoint
├── state.py                 # MODIFIED: add stop_loss_price, take_profit_price per position
└── tests/
    ├── conftest.py           # shared fixtures (mock TradingClient)
    ├── test_safety.py        # SAFE-01 through SAFE-05
    └── test_bracket.py       # BRACKET-01 through BRACKET-05
```

### Pattern 1: Bracket Order on Every Stock Buy (BRACKET-01)

**What:** Replace plain `MarketOrderRequest` in `place_buy()` with a bracket order that includes both stop-loss and take-profit legs in a single API call.

**When to use:** Every stock buy. Not used for options (options have separate exit rules).

**Example:**
```python
# Source: Verified against alpaca-py 0.43.2 installed + forum.alpaca.markets/t/bracket-order-code-example
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

def place_buy_with_bracket(
    trading_client: TradingClient,
    symbol: str,
    qty: int,
    entry_price: float,
    stop_loss_pct: float = 0.03,
    take_profit_pct: float = 0.06,
) -> Order:
    stop_price   = round(entry_price * (1 - stop_loss_pct),   2)
    profit_price = round(entry_price * (1 + take_profit_pct), 2)

    order = trading_client.submit_order(
        MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            stop_loss=StopLossRequest(stop_price=stop_price),
            take_profit=TakeProfitRequest(limit_price=profit_price),
        )
    )
    return order
```

### Pattern 2: Checking for Active Stop-Loss on Existing Positions (BRACKET-02)

**What:** On startup, scan all open positions and check whether each one has an active bracket child order (stop-loss leg with `OrderStatus.HELD`).

**Critical gotcha:** Bracket child orders are NOT visible with `QueryOrderStatus.OPEN`. You MUST use `QueryOrderStatus.ALL` with `nested=True`.

**Example:**
```python
# Source: Verified — medium.com/@trademamba (key gotcha article) + alpaca-py enums confirmed HELD status
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus, OrderStatus

def get_active_stop_loss_symbols(trading_client: TradingClient) -> set[str]:
    """Return set of symbols that already have an active stop-loss leg."""
    protected = set()
    try:
        orders = trading_client.get_orders(
            filter=GetOrdersRequest(
                status=QueryOrderStatus.ALL,
                nested=True,
            )
        )
        for order in orders:
            if order.legs:
                for leg in order.legs:
                    if (leg.stop_price is not None
                            and leg.status == OrderStatus.HELD):
                        protected.add(order.symbol.upper())
    except Exception as exc:
        log.warning("[safety] Could not fetch orders for stop-loss check: %s", exc)
    return protected
```

### Pattern 3: Add Stop-Loss to Existing Position (BRACKET-02 recovery)

**What:** When startup finds a position without a stop-loss, place an OCO order (both stop-loss and take-profit) for the existing position.

**Example:**
```python
# Source: docs.alpaca.markets/docs/orders-at-alpaca — OCO is designed for this exact use case
from alpaca.trading.requests import LimitOrderRequest, StopLossRequest, TakeProfitRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

def place_oco_exit(
    trading_client: TradingClient,
    symbol: str,
    qty: int,
    current_price: float,
    stop_loss_pct: float = 0.03,
    take_profit_pct: float = 0.06,
) -> None:
    stop_price   = round(current_price * (1 - stop_loss_pct),   2)
    profit_price = round(current_price * (1 + take_profit_pct), 2)

    trading_client.submit_order(
        LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC,
            order_class=OrderClass.OCO,
            stop_loss=StopLossRequest(stop_price=stop_price),
            take_profit=TakeProfitRequest(limit_price=profit_price),
        )
    )
```

### Pattern 4: Order Fill Polling (SAFE-03)

**What:** After submitting a market order, poll until FILLED, PARTIALLY_FILLED, or REJECTED, or until the 10-second timeout is reached.

**Example:**
```python
# Source: Verified against Order model fields — filled_qty, filled_avg_price, status confirmed present
import time
from alpaca.trading.enums import OrderStatus

def poll_order_fill(
    trading_client: TradingClient,
    order_id: str,
    timeout: float = 10.0,
    poll_interval: float = 0.5,
) -> Order:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        order = trading_client.get_order_by_id(order_id)
        if order.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED,
                             OrderStatus.REJECTED, OrderStatus.CANCELED,
                             OrderStatus.EXPIRED):
            return order
        time.sleep(poll_interval)
    return trading_client.get_order_by_id(order_id)  # final state
```

### Pattern 5: State Persistence (SAFE-01)

**What:** Persist `_peak_prices`, `_positions_opened_today`, and `_session_start_equity` from `safety.py` to `data/bot_state.json`. Write on every mutation. Load on startup with corruption fallback.

**Example:**
```python
# Source: stdlib json + threading patterns matching existing state.py conventions
import json, os, threading
from datetime import date

_state_lock = threading.Lock()
STATE_FILE  = os.path.join(os.path.dirname(__file__), "data", "bot_state.json")


def _save_state() -> None:
    """Write current safety globals to disk. Call after every mutation."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    payload = {
        "date":                     date.today().isoformat(),
        "peak_prices":              _peak_prices,
        "positions_opened_today":   list(_positions_opened_today),
        "session_start_equity":     _session_start_equity,
    }
    with _state_lock:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, STATE_FILE)  # atomic on POSIX; best-effort on Windows


def load_state_from_file() -> None:
    """Load persisted state on startup. Log and ignore if file is missing/corrupt."""
    global _peak_prices, _positions_opened_today, _session_start_equity
    if not os.path.exists(STATE_FILE):
        log.info("[safety] No state file found — starting fresh.")
        return
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        saved_date = data.get("date", "")
        if saved_date != date.today().isoformat():
            log.info("[safety] State file is from %s — starting fresh (new day).", saved_date)
            return
        _peak_prices              = data.get("peak_prices", {})
        _positions_opened_today   = set(data.get("positions_opened_today", []))
        _session_start_equity     = data.get("session_start_equity")
        log.info("[safety] State restored: %d peak prices, %d PDT entries.",
                 len(_peak_prices), len(_positions_opened_today))
    except Exception as exc:
        log.warning("[safety] State file corrupt — starting fresh: %s", exc)
```

### Pattern 6: OCC Symbol Detection (SAFE-02)

**What:** Detect OCC-format options symbols to count them against the PDT limit.

**Example:**
```python
# Source: OCC format is standardized. Regex verified against real OCC symbols.
import re

_OCC_PATTERN = re.compile(r'^[A-Z]{1,6}\d{6}[CP]\d{8}$')

def is_options_symbol(symbol: str) -> bool:
    """True if symbol matches OCC format e.g. AAPL240119C00150000."""
    return bool(_OCC_PATTERN.match(symbol.upper()))
```

### Pattern 7: Options Validation at Startup (SAFE-05)

**What:** Check `account.options_approved_level` before starting in live mode. Level 2+ is required to buy calls/puts.

**Example:**
```python
# Source: TradeAccount model verified — options_approved_level is Optional[int], Level 0=disabled, 2=buy calls/puts
def validate_options_enabled(trading_client: TradingClient, live_mode: bool) -> None:
    if not live_mode:
        log.info("[safety] Paper mode — skipping options approval check.")
        return
    try:
        account = trading_client.get_account()
        level   = getattr(account, "options_approved_level", None)
        if level is None or int(level) < 2:
            log.critical(
                "[safety] OPTIONS TRADING NOT ENABLED. "
                "Account options_approved_level=%s (need >= 2). "
                "Enable options in your Alpaca account before running live.",
                level,
            )
            raise SystemExit(1)
        log.info("[safety] Options trading enabled (level=%d).", level)
    except SystemExit:
        raise
    except Exception as exc:
        log.warning("[safety] Could not validate options level: %s. Proceeding with caution.", exc)
```

### Pattern 8: Options Liquidation (SAFE-04)

**What:** In `liquidate_all()`, detect options positions by OCC symbol and close them with `LimitOrderRequest` at mid-price (bid + ask) / 2, with fallback to market.

**Example:**
```python
# Source: REQUIREMENTS.md SAFE-04 specifies LimitOrderRequest for options.
# PositionIntent.SELL_TO_CLOSE is the correct intent for closing a long options position.
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.enums import PositionIntent, TimeInForce, OrderSide

def _close_options_position(
    trading_client: TradingClient,
    symbol: str,
    qty: int,
    mid_price: float,
) -> None:
    trading_client.submit_order(
        LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            limit_price=round(mid_price, 2),
            position_intent=PositionIntent.SELL_TO_CLOSE,
        )
    )
```

### Anti-Patterns to Avoid

- **`QueryOrderStatus.OPEN` for bracket child detection:** Child legs have status `HELD`, not `OPEN`. Always use `QueryOrderStatus.ALL` + `nested=True` when checking for active stop-losses.
- **Bracket order for options positions:** Bracket orders work for stocks. Options positions use separate exit logic (OPT-06 requirements, Phase 3 scope).
- **Storing state only in memory:** The entire motivation for SAFE-01 is that Python module globals reset on crash. Any new safety state must be persisted immediately after mutation.
- **Polling with `time.sleep(1)` in blocking loop:** Use `time.monotonic()` deadline + short interval (0.5s) to avoid overshooting the 10s timeout.
- **`os.replace()` file-write assumption on Windows:** `os.replace()` is atomic on POSIX but is best-effort on Windows (target must not be locked). Write to `.tmp` then replace — works well enough for this use case.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Server-side stop-loss/take-profit | Local trailing stop logic | `OrderClass.BRACKET` via alpaca-py | Alpaca executes even when bot is offline — that is the entire point |
| OCO exit for existing positions | Custom cancel-then-replace logic | `OrderClass.OCO` via alpaca-py | Alpaca handles the cancel-other leg atomically |
| OCC symbol parsing | Custom string parser | `re.compile(r'^[A-Z]{1,6}\d{6}[CP]\d{8}$')` | One-liner; OCC format is a fixed standard |
| Atomic file write | Custom locking scheme | `tmp + os.replace()` pattern | Best available on Windows without external libs |

**Key insight:** Alpaca's server-side order execution is the whole point of bracket orders. Any local Python implementation of stop-loss is secondary because it requires the bot to be running.

## Common Pitfalls

### Pitfall 1: Bracket Child Orders Not Visible as OPEN

**What goes wrong:** Developer calls `get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))` expecting to see the stop-loss leg. Gets empty results and concludes there is no stop-loss. Rewrites a duplicate.

**Why it happens:** Bracket child legs have `status=HELD`, not `OPEN`. Alpaca's OPEN filter excludes HELD orders.

**How to avoid:** Always use `QueryOrderStatus.ALL` with `nested=True` when checking for active bracket legs on startup or shutdown.

**Warning signs:** "No stop-loss found" on startup immediately after placing a bracket order.

### Pitfall 2: Bracket Order Entry is MarketOrder but Fill Price is Approximate

**What goes wrong:** Stop-loss is computed from `entry_price` (last bar close), but the actual fill price from the bracket's market leg might differ. The stop-loss is then slightly wrong relative to actual entry.

**Why it happens:** Market orders fill at market price, not the "estimated" price you used to compute legs.

**How to avoid:** After the bracket order fills, read `order.filled_avg_price` from the FILLED entry leg and optionally update the stop-loss/take-profit using `replace_order_by_id()` if the fill price deviated more than 0.5% from estimate. For a $500 account this may be acceptable to skip in v1 — flag as a known approximation.

**Warning signs:** Take-profit triggers at a slightly different gain percentage than configured.

### Pitfall 3: State File from Previous Day Reloaded

**What goes wrong:** Bot crashes at 4 PM. Restarts next morning. Loads yesterday's `_positions_opened_today` set — PDT count is wrong for the new day.

**Why it happens:** File restoration without date validation.

**How to avoid:** Include a `"date"` field in `bot_state.json`. On load, check if `data["date"] == date.today().isoformat()`. If not, discard and start fresh.

**Warning signs:** PDT shows 1-2 used trades at session start when the account shows 0.

### Pitfall 4: Partial Fill Accepted, Old Trailing Stop Logic Uses Wrong Qty

**What goes wrong:** Market order for 10 shares fills 6. Bot records peak price and bracket was placed for 10 shares. Mismatch between actual position and bracket order quantity.

**Why it happens:** `place_buy()` doesn't wait for fill confirmation — it records state based on the requested qty.

**How to avoid:** After fill polling, use `order.filled_qty` as the authoritative quantity for all subsequent state recording and bracket placement. If partial, cancel the remainder before placing bracket.

**Warning signs:** Dashboard shows different qty than Alpaca position page.

### Pitfall 5: Options Validation Blocks Paper Mode

**What goes wrong:** `validate_options_enabled()` calls `get_account()` and checks `options_approved_level`. Paper accounts may return `None` or `0` for options level even when the user has options enabled on live. Bot refuses to start in paper mode.

**Why it happens:** Paper account doesn't mirror live account's options approval settings.

**How to avoid:** Skip the options validation check when `PAPER_TRADING=True` (per D-10 discretion). Log a notice that options validation is paper-mode-skipped. Only enforce on live.

**Warning signs:** `SystemExit(1)` on every paper mode start.

### Pitfall 6: `os.replace()` Fails on Windows If Target Is Locked

**What goes wrong:** Another process (e.g., antivirus scanner) has `bot_state.json` open. `os.replace()` raises `PermissionError`.

**Why it happens:** Windows does not allow replacing a file that is open by another process.

**How to avoid:** Wrap `_save_state()` in try/except and log a warning on failure. Losing one state write is acceptable — the next write will succeed.

**Warning signs:** Recurring `PermissionError` in logs during startup.

## Code Examples

### Verified: Bracket Order (BRACKET-01)

```python
# Source: Verified against installed alpaca-py 0.43.2 + forum.alpaca.markets/t/bracket-order-code-example
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce

bracket = trading_client.submit_order(
    MarketOrderRequest(
        symbol="SOFI",
        qty=50,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.BRACKET,
        stop_loss=StopLossRequest(stop_price=9.70),    # 3% below $10 entry
        take_profit=TakeProfitRequest(limit_price=10.60),  # 6% above $10 entry
    )
)
# bracket.id = parent order id
# bracket.legs = [stop_loss_leg, take_profit_leg] — both status=HELD
```

### Verified: Order Model Fields (SAFE-03)

```python
# Source: Confirmed via python -c "from alpaca.trading.models import Order; print(Order.model_fields.keys())"
# Key fields: filled_qty, filled_avg_price, status, legs, stop_price, limit_price
order = trading_client.get_order_by_id(order_id)
print(order.status)            # OrderStatus.FILLED / PARTIALLY_FILLED / REJECTED
print(order.filled_qty)        # Decimal — actual shares filled
print(order.filled_avg_price)  # Decimal — actual fill price
print(order.legs)              # List[Order] — bracket child legs
```

### Verified: Account Options Fields (SAFE-05)

```python
# Source: Confirmed via python -c "from alpaca.trading.models import TradeAccount; ..."
# options_approved_level: Optional[int] — 0=none, 1=covered, 2=buying calls/puts, 3=spreads
account = trading_client.get_account()
level = getattr(account, "options_approved_level", None)
if level is None or int(level) < 2:
    raise SystemExit("Options not enabled — set options_approved_level >= 2")
```

### Verified: OrderClass and OrderStatus Enums

```python
# Source: Confirmed via python -c "from alpaca.trading.enums import OrderClass, OrderStatus; ..."
# OrderClass: SIMPLE, MLEG, BRACKET, OCO, OTO
# OrderStatus: NEW, PARTIALLY_FILLED, FILLED, DONE_FOR_DAY, CANCELED, EXPIRED,
#              REPLACED, PENDING_CANCEL, PENDING_REPLACE, PENDING_REVIEW, ACCEPTED,
#              PENDING_NEW, ACCEPTED_FOR_BIDDING, STOPPED, REJECTED, SUSPENDED,
#              CALCULATED, HELD
```

### Verified: PositionIntent for Options Close

```python
# Source: Confirmed via python -c "from alpaca.trading.enums import PositionIntent; ..."
# PositionIntent: BUY_TO_OPEN, BUY_TO_CLOSE, SELL_TO_OPEN, SELL_TO_CLOSE
from alpaca.trading.enums import PositionIntent
# For closing a long call/put: PositionIntent.SELL_TO_CLOSE
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Local trailing stop as primary protection | Bracket orders on Alpaca as primary | Phase 1 deliverable | Bot now protected even when laptop is closed |
| Assume order filled instantly | Poll for fill confirmation | Phase 1 deliverable | Silent failures become explicit log messages |
| PDT tracking for stocks only | PDT tracking includes OCC options symbols | Phase 1 deliverable | Prevents PDT violations when options trading begins |
| No startup validation | Options approval check at startup | Phase 1 deliverable | Bot fails loudly in live mode if options not enabled |
| All safety state in memory | Safety state persisted to data/bot_state.json | Phase 1 deliverable | Trailing stop peak survives restart |

**Deprecated/outdated within this phase:**
- Local trailing stop as the ONLY stop-loss mechanism: Now a secondary backup. Bracket orders are primary.
- `MarketOrderRequest` without `order_class`: Replaced by `MarketOrderRequest(order_class=OrderClass.BRACKET, ...)` for every stock buy.

## Open Questions

1. **Bracket order qty vs. partial fill**
   - What we know: If the entry leg fills partially (e.g., 6 of 10 shares), the bracket legs are placed for the originally requested quantity (10), creating a mismatch.
   - What's unclear: Alpaca's behavior when the entry partially fills — does it adjust child leg quantities automatically or keep original qty?
   - Recommendation: After fill polling, if `filled_qty < requested_qty`, cancel remainder, then check bracket child legs to confirm they reflect `filled_qty`. If Alpaca doesn't auto-adjust, cancel and replace child legs with corrected quantity.

2. **Dashboard stop-loss price update after bracket replace**
   - What we know: The dashboard will compute and display stop-loss/take-profit from entry price + config percentages.
   - What's unclear: When the user adjusts percentages from the dashboard (BRACKET-05), should existing open bracket orders be updated via `replace_order_by_id()`, or only apply to future orders?
   - Recommendation: For v1, apply new percentages to future orders only. Updating existing bracket legs requires knowing the bracket order ID per position — build that mapping if time allows, but don't block the phase.

3. **Paper account options level**
   - What we know: `options_approved_level` is `Optional[int]` on `TradeAccount`. Paper accounts may return `None`.
   - What's unclear: Whether paper accounts mirror live options approval level or always return `None`.
   - Recommendation: Skip options validation in paper mode entirely (D-10 discretion). Document as known behavior difference.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| alpaca-py | All trading operations | Yes | 0.43.2 | — |
| Python 3.x | Runtime | Yes | 3.14 (CPython) | — |
| pytest | Test suite | No | — | `pip install pytest` — Wave 0 task |
| data/ directory | State persistence | No (not yet created) | — | Create at first `_save_state()` call with `os.makedirs(..., exist_ok=True)` |

**Missing dependencies with no fallback:**
- None — all blockers have clear resolution paths.

**Missing dependencies with fallback / Wave 0 task:**
- `pytest` not installed — install before writing any tests: `pip install pytest`
- `data/` directory does not exist — create lazily in `_save_state()` using `os.makedirs(exist_ok=True)`

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (not yet installed) |
| Config file | none — see Wave 0 |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SAFE-01 | State file written on peak price update; loads correctly on restart; corrupt file falls back to fresh | unit | `python -m pytest tests/test_safety.py::test_state_persistence -x` | No — Wave 0 |
| SAFE-01 | New-day detection discards old state | unit | `python -m pytest tests/test_safety.py::test_state_new_day -x` | No — Wave 0 |
| SAFE-02 | OCC symbols counted toward PDT limit; plain stock symbols not affected | unit | `python -m pytest tests/test_safety.py::test_pdt_occ_symbols -x` | No — Wave 0 |
| SAFE-03 | Fill polling returns FILLED order; timeout returns last state; REJECTED raises/logs | unit (mock) | `python -m pytest tests/test_safety.py::test_fill_polling -x` | No — Wave 0 |
| SAFE-03 | Partial fill (6/10 shares) handled intelligently | unit (mock) | `python -m pytest tests/test_safety.py::test_partial_fill_handling -x` | No — Wave 0 |
| SAFE-04 | `liquidate_all()` submits MarketOrderRequest for stocks, LimitOrderRequest for OCC symbols | unit (mock) | `python -m pytest tests/test_safety.py::test_liquidate_all_options -x` | No — Wave 0 |
| SAFE-05 | `validate_options_enabled()` raises SystemExit if level < 2 in live mode; skips in paper | unit (mock) | `python -m pytest tests/test_safety.py::test_options_validation -x` | No — Wave 0 |
| BRACKET-01 | `place_buy()` submits MarketOrderRequest with BRACKET class, correct stop/profit prices | unit (mock) | `python -m pytest tests/test_bracket.py::test_bracket_on_buy -x` | No — Wave 0 |
| BRACKET-02 | Startup check finds position without stop-loss; places OCO recovery order | unit (mock) | `python -m pytest tests/test_bracket.py::test_startup_stop_loss_recovery -x` | No — Wave 0 |
| BRACKET-02 | Startup check finds position WITH stop-loss (HELD); skips recovery | unit (mock) | `python -m pytest tests/test_bracket.py::test_startup_stop_loss_present -x` | No — Wave 0 |
| BRACKET-03 | Shutdown check warns if position has no active stop-loss | unit (mock) | `python -m pytest tests/test_bracket.py::test_shutdown_stop_loss_warning -x` | No — Wave 0 |
| BRACKET-04 | `/api/positions` response includes `stop_loss_price` and `take_profit_price` fields | unit | `python -m pytest tests/test_bracket.py::test_positions_api_includes_sl_tp -x` | No — Wave 0 |
| BRACKET-05 | `POST /api/config/exits` updates TRAILING_STOP_PCT and TAKE_PROFIT_PCT at runtime | unit | `python -m pytest tests/test_bracket.py::test_config_exits_endpoint -x` | No — Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/ -x -q`
- **Per wave merge:** `python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/conftest.py` — shared fixtures: mock TradingClient, mock Order, mock Account
- [ ] `tests/test_safety.py` — covers SAFE-01 through SAFE-05
- [ ] `tests/test_bracket.py` — covers BRACKET-01 through BRACKET-05
- [ ] `data/` directory — created lazily at first state save
- [ ] pytest install: `pip install pytest`

## Project Constraints (from CLAUDE.md)

| Directive | Impact on This Phase |
|-----------|---------------------|
| alpaca-py SDK only for all trading | Bracket orders via `OrderClass.BRACKET`, not manual order chains |
| python-dotenv for config | Any new config params (STATE_FILE_PATH, FILL_TIMEOUT) go in config.py via `_float()`/`_int()` helpers |
| No TA-Lib (C extension, fails on Windows) | Not relevant to this phase |
| snake_case, verb-first functions | `load_state_from_file()`, `place_bracket_order()`, `validate_options_enabled()`, `check_positions_have_stop_loss()` |
| `_` prefix for private/module globals | `_peak_prices`, `_state_lock`, `_OCC_PATTERN` |
| Broad `except Exception` catching with logging | Maintain pattern; log at WARNING for recoverable, ERROR for unhandled |
| `log_trade_event()` for structured events | New events: `BRACKET_ORDER_PLACED`, `STOP_LOSS_RECREATED`, `FILL_TIMEOUT`, `PARTIAL_FILL_ACCEPTED`, `OPTIONS_VALIDATION_FAILED` |
| Module-level constants from config.py | `STATE_FILE_PATH`, `ORDER_FILL_TIMEOUT_SECONDS` added to config.py |
| All new state for dashboard stored via `state.py` | `stop_loss_price`, `take_profit_price` per position entry in `positions` list |
| No direct repo edits outside GSD workflow | N/A — research only |

## Sources

### Primary (HIGH confidence)

- Installed alpaca-py 0.43.2 — `OrderClass`, `OrderStatus`, `StopLossRequest`, `TakeProfitRequest`, `Order.model_fields`, `TradeAccount.model_fields` all directly verified via `python -c` introspection
- [Alpaca-py Requests Reference](https://alpaca.markets/sdks/python/api_reference/trading/requests.html) — `MarketOrderRequest`, `StopLossRequest`, `TakeProfitRequest` fields
- [Alpaca Orders At Alpaca](https://docs.alpaca.markets/docs/orders-at-alpaca) — OCO order structure for existing positions

### Secondary (MEDIUM confidence)

- [Bracket Order Code Example — Alpaca Forum](https://forum.alpaca.markets/t/bracket-order-code-example-with-alpaca-py-library/12110) — confirmed API pattern matches installed SDK
- [Bracket Orders Key Gotcha — Trade Mamba](https://medium.com/@trademamba/bracket-orders-with-alpaca-markets-and-a-key-gotcha-6560d47ad6f4) — `QueryOrderStatus.ALL` + `nested=True` requirement for child order visibility; cross-verified against `OrderStatus.HELD` enum value confirmed present in installed SDK
- [Alpaca Options Trading Docs](https://docs.alpaca.markets/docs/options-trading) — `options_approved_level` levels 0-3 description; cross-verified field name against installed `TradeAccount.model_fields`

### Tertiary (LOW confidence — flag for validation)

- OCO alpaca-py code example (old alpaca-trade-api syntax, not alpaca-py) — pattern translated to class-based API, needs live testing to confirm

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — library installed locally, all classes verified via introspection
- Architecture: HIGH — pattern matches existing project conventions; bracket order API confirmed
- Pitfalls: HIGH — bracket child HELD status verified against actual enum; date-validation and partial fill patterns are standard
- Test map: MEDIUM — test behaviors are well-defined, but no live API calls validated yet

**Research date:** 2026-03-27
**Valid until:** 2026-06-27 (alpaca-py stable; bracket order API unlikely to change)
