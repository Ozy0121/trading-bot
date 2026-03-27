# Architecture Research: Multi-Strategy Bot with Options

**Researched:** 2026-03-27
**Confidence:** MEDIUM — derived from codebase analysis + established trading system design patterns

---

## 1. Strategy Registry Pattern

The existing single-strategy flow in `strategy.py` should be replaced with a `strategies/` package. Each strategy implements a `BaseStrategy` ABC with a single `scan(symbol, df) -> Candidate` method. `scanner.py` becomes the aggregator — it fans out to all active strategies and returns a unified ranked list. The bot loop sees only `Candidate` objects and has no knowledge of which strategy fired.

Three strategies needed:
- **MomentumStrategy** — price breakout + volume surge (price breaks N-day high on >2x avg volume)
- **MeanReversionStrategy** — RSI < 35 + lower Bollinger Band touch
- **CatalystStrategy** — wraps existing `catalysts.py` scoring (ARK buys, analyst upgrades)

```python
# strategies/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class Candidate:
    symbol: str
    score: float          # 0-100
    strategy: str         # "momentum" | "reversion" | "catalyst"
    signal: str           # "BUY" | "SELL" | "HOLD"
    hold_days: int        # expected hold duration
    metadata: dict        # strategy-specific details

class BaseStrategy(ABC):
    @abstractmethod
    def scan(self, symbol: str, df: pd.DataFrame) -> Candidate | None:
        ...
```

---

## 2. Options Chain Data Flow

Options chain fetching only happens when a stock candidate scores above threshold AND options budget is available.

```
Stock Candidate (score >= 70)
    │
    ├─ Check options budget available ($250 bucket)
    │
    ├─ Fetch chain via yfinance (free, no tier limits)
    │    └─ Filter: DTE 7-21 days, premium <= $150, OI > 100, bid-ask spread < 15%
    │
    ├─ Select best contract (closest OTM strike, highest volume)
    │
    ├─ Build OCC symbol
    │
    └─ Submit LIMIT order via Alpaca TradingClient
```

At $500 account, only one options position is viable at a time.

---

## 3. Mixed Portfolio Risk: Two Separate Buckets

Hard capital segregation:
- **$250 stock bucket** — managed by existing position sizing logic
- **$250 options bucket** — managed by new `options_risk.py` module

Options-specific guards:
- Max premium spend per contract: $150
- Min DTE: 3 days (avoid theta crush)
- Max DTE: 21 days (avoid tying up capital)
- Earnings date avoidance
- Max IV rank: 80% (avoid overpaying for premium)

Stop-loss equivalents for options:
- Close at -50% of premium paid
- Close at DTE <= 3
- Close at +75% profit

PDT counter remains **unified** — options day trades count against the same 3-trade limit.

---

## 4. Scanner Architecture

Three scanning methods feed one unified scorer:

### Technical Scan
Run all strategies against full watchlist using `ThreadPoolExecutor` (6 workers). Each strategy returns 0 or 1 Candidate per symbol.

### Sector Scan
Track ETF momentum (XLK, XLE, XLF, XLY, XBI, etc.):
1. Rank sectors by 5-day return
2. Top 2-3 sectors → get top holdings
3. Add sector leaders to scan list

### Curated Watchlist
Always included in scan. User-manageable 20-30 stocks.

### Unified Scoring
```
final_score = base_technical_score + catalyst_bonus + sector_bonus + source_bonus
```

Parallel bar fetching (6 workers) keeps scan time under 10s for 35-40 symbols.

---

## 5. State Management Changes

**Critical decision:** Keep `state.position` (stock) and `state.options_positions` (options) as separate fields. Merging them creates conditional logic throughout every consumer.

```python
# New state fields
shared_state.update(
    options_positions=[],        # list of options position dicts
    options_pnl=0.0,             # realized P&L from options
    stock_budget=250.0,          # allocated to stocks
    options_budget=250.0,        # allocated to options
    active_strategy="",          # which strategy triggered current position
    scan_results=[],             # full ranked candidate list
)
```

---

## 6. Suggested Build Order

| Order | Component | Dependencies | New APIs? |
|-------|-----------|-------------|-----------|
| 1 | Strategy registry (`strategies/` package) | Pure logic, no new APIs | No |
| 2 | Multi-symbol parallel scanning + sector detection | Strategy registry | ETF data (yfinance) |
| 3 | Options chain fetching + contract selection | Scanner, yfinance | yfinance options chain |
| 4 | Options execution + position management | Chain selection, Alpaca | Alpaca options orders |
| 5 | Risk management updates (dual buckets, options stops) | Options execution | No |
| 6 | Dashboard updates for options P&L and strategy scores | All above | No |

---

## 7. Component Boundaries

```
┌─────────────────────────────────────────────────────┐
│                    server.py (entry)                 │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────┐    ┌──────────────┐    ┌──────────┐  │
│  │ scanner  │───→│  strategies/ │    │ options  │  │
│  │   .py    │    │  momentum    │    │ _chain   │  │
│  │(aggreg.) │    │  reversion   │    │   .py    │  │
│  │          │    │  catalyst    │    │          │  │
│  └────┬─────┘    └──────────────┘    └────┬─────┘  │
│       │                                    │        │
│       └──────────┬─────────────────────────┘        │
│                  ▼                                   │
│           ┌──────────┐                              │
│           │  bot.py  │ (trade decisions)             │
│           └────┬─────┘                              │
│                │                                     │
│    ┌───────────┼───────────┐                        │
│    ▼           ▼           ▼                        │
│ ┌──────┐ ┌─────────┐ ┌──────────┐                  │
│ │safety│ │options   │ │  state   │                  │
│ │ .py  │ │_risk.py  │ │   .py    │                  │
│ └──────┘ └─────────┘ └────┬─────┘                  │
│                            │                        │
│                            ▼                        │
│                     ┌──────────┐                    │
│                     │dashboard │ (Flask + SSE)       │
│                     │   .py    │                    │
│                     └──────────┘                    │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## Sources

- `.planning/codebase/ARCHITECTURE.md` — existing bot architecture
- `.planning/codebase/STRUCTURE.md` — current file layout
- `.planning/PROJECT.md` — project goals and constraints
