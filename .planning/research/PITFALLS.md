# Pitfalls Research: Swing Trading Bot with Options

**Researched:** 2026-03-27
**Domain:** Adding options trading + multi-strategy swing to existing stock-only bot, $500 account, PDT-constrained

---

## Critical Pitfalls

### 1. Options Count as Day Trades — PDT Tracker Will Miss Them
- **Risk:** Existing PDT tracker in `safety.py` uses stock ticker symbols. Options use OCC format (`TSLA250117C00250000`). The tracker will not recognize options round-trips as day trades, allowing accidental PDT violations.
- **Warning signs:** Bot opens and closes an options position same day without incrementing PDT counter
- **Prevention:** Extend PDT tracking to recognize OCC symbols and map them back to round-trip detection. Both stock AND options trades must share the same 3-trade counter.
- **Phase:** Must be solved before any options execution

### 2. 100x Contract Multiplier Missing from Position Sizing
- **Risk:** `calculate_safe_qty()` in `safety.py` sizes positions by share price. Options contracts represent 100 shares. A $1.50 premium = $150 actual cost, not $1.50. Without the multiplier, the bot will either buy 100x too many contracts or size 100x too small.
- **Warning signs:** Position value doesn't match expected allocation
- **Prevention:** Create separate options position sizing that multiplies premium by 100. Never reuse stock sizing logic for options.
- **Phase:** Options execution phase

### 3. Theta Decay Makes Short-Hold Options Structurally Unprofitable
- **Risk:** 1-3 day holds on options lose value to theta decay every day, especially near expiry. A $1.50 call can lose $0.10-0.30/day in time value alone, requiring a large underlying move just to break even.
- **Warning signs:** Options positions consistently lose money even when the underlying moves in the right direction
- **Prevention:** Target DTE 7-21 days (slower theta decay). Never buy options with <5 DTE. Set minimum expected move threshold that accounts for theta cost.
- **Phase:** Options chain selection phase

### 4. Bid-Ask Spread Destroys Small Account Returns
- **Risk:** Illiquid options have 10-40% bid-ask spreads. Buying at $1.50 ask when bid is $1.20 means you're immediately down 20%. On a $500 account with $150 contracts, that's $30 gone instantly.
- **Warning signs:** Options positions show immediate unrealized loss after fill
- **Prevention:** Filter options by: open interest > 100, daily volume > 50, bid-ask spread < 15% of mid price. Hard reject anything wider.
- **Phase:** Options chain selection phase

### 5. Options PDT "Loophole" Does Not Exist
- **Risk:** Common misconception that options don't count toward PDT. They absolutely do. Opening and closing the same options contract in the same day = 1 day trade.
- **Warning signs:** PDT violation flagged by Alpaca
- **Prevention:** Unified PDT counter for all instrument types. Document clearly in code comments.
- **Phase:** Risk management phase

### 6. Alpaca Options Require Account Approval
- **Risk:** Alpaca requires explicit options trading approval, separate from stock trading. Paper mode may work without approval, but live mode will fail. Bot could test perfectly in paper and break on go-live.
- **Warning signs:** Options orders rejected in live mode but work in paper
- **Prevention:** Document the approval requirement. Add a startup check that verifies options trading is enabled on the account. Fail loudly if not.
- **Phase:** Options execution phase — add startup validation

### 7. OCC Symbol Format Breaks Existing Code
- **Risk:** Every function in `safety.py`, `bot.py`, and `state.py` that looks up positions by ticker symbol will fail for options. OCC format (`AAPL240119C00185000`) doesn't match any existing symbol comparison logic.
- **Warning signs:** Options positions invisible to trailing stop, kill switch, and liquidation logic
- **Prevention:** Separate stock and options position tracking. Never mix OCC symbols into stock-oriented lookups. Use `state.options_positions` as a distinct field.
- **Phase:** State management refactor — before options execution

---

## Moderate Pitfalls

### 8. Greeks-Blind Entry
- **Risk:** Buying options without checking IV rank, delta, or gamma exposure. High IV = overpaying for premium. Wrong delta = wrong risk/reward profile. Near-earnings IV crush can lose 30-50% of premium overnight.
- **Prevention:** Check earnings dates (exclude 5 days before earnings). Target delta 0.30-0.50 for directional plays. Prefer IV rank < 50th percentile.
- **Phase:** Options chain selection

### 9. Over-Trading the 3-Trade Budget
- **Risk:** With stocks AND options, it's easy to burn all 3 PDT trades in one day. Two asset types competing for 3 weekly trades creates allocation conflicts.
- **Prevention:** Pre-allocate trades: e.g., max 2 stock trades + 1 options trade per week. Or let the scoring system decide but enforce a hard 3-trade gate regardless.
- **Phase:** Risk management phase

### 10. Trailing Stop Logic Doesn't Work for Options
- **Risk:** Existing trailing stop in `safety.py` tracks peak price as a percentage of underlying. Options prices don't move linearly with underlying — delta, gamma, and theta all affect the relationship. A 3% trailing stop on the underlying doesn't translate to a meaningful options stop.
- **Prevention:** Options exits should use premium-based stops (e.g., close at -50% of premium paid, close at +75% profit) rather than underlying price movement.
- **Phase:** Options risk management

### 11. No Order Fill Confirmation (Existing Bug, Now Critical)
- **Risk:** Already flagged in CONCERNS.md as MEDIUM. With options, this becomes CRITICAL. Options LIMIT orders may not fill immediately. The bot could assume a fill happened and move on, leaving phantom positions or double-ordering.
- **Prevention:** Implement order status polling. After submitting an options order, poll for fill status with timeout. Handle partial fills and rejections explicitly.
- **Phase:** Options execution — must solve before live trading

### 12. `liquidate_all()` Uses MarketOrderRequest — Breaks for Options
- **Risk:** The emergency liquidation function uses `MarketOrderRequest` which won't work for OCC symbols. In a panic liquidation scenario, options positions would be left open.
- **Prevention:** `liquidate_all()` must handle both stock and options positions. Use `OptionOrderRequest` with aggressive LIMIT price (e.g., bid price - 5%) for options liquidation.
- **Phase:** Safety/risk management refactor

---

## Minor Pitfalls

### 13. yfinance Options Chain Data Can Be Stale
- **Risk:** yfinance chain data is delayed and sometimes missing for low-volume options. Good for discovery, risky for execution decisions.
- **Prevention:** Use yfinance for chain discovery and filtering. Before executing, verify current bid/ask via Alpaca's options data API if available. Accept some staleness for paper trading.
- **Phase:** Options chain selection

### 14. Dashboard P&L Math Breaks for Options
- **Risk:** Current dashboard calculates P&L as `(current_price - entry_price) * qty`. For options, notional value is `premium * 100 * qty`. Displaying raw premium without the multiplier will show misleading P&L.
- **Prevention:** Options P&L calculation must use: `(current_premium - entry_premium) * 100 * qty`. Display separately from stock P&L.
- **Phase:** Dashboard updates

### 15. Scoring System Gives Options Unfair Advantage
- **Risk:** A 5% move on a 0.40 delta call = ~12.5% return on premium. The combined scoring system might always prefer options over stocks due to leverage, without accounting for lower probability of profit.
- **Prevention:** Score stocks and options independently, then allocate based on budget buckets rather than raw score comparison.
- **Phase:** Scoring/allocation phase

---

## Cross-Cutting Finding

Three existing issues from CONCERNS.md escalate from MEDIUM to **CRITICAL** when options are added:

1. **No order-fill confirmation** → options LIMIT orders may not fill, causing phantom positions
2. **No state persistence across restarts** → options positions with expiry dates MUST survive restarts
3. **`liquidate_all()` not handling multiple asset types** → emergency exit leaves options open

These must be addressed BEFORE or DURING the options integration phases, not after.
