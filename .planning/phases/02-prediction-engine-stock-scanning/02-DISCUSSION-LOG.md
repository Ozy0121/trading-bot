# Phase 2: Prediction Engine + Stock Scanning - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-28
**Phase:** 02-prediction-engine-stock-scanning
**Areas discussed:** Strategy registry formality, Conviction score composition, News sentiment source, Earnings date source
**Mode:** --auto (all decisions auto-selected)

---

## Strategy Registry Formality

| Option | Description | Selected |
|--------|-------------|----------|
| Lightweight functions | One module per strategy exporting scan() function, registry dict | ✓ |
| ABC class hierarchy | BaseStrategy ABC with formal scan/score interface | |
| Plugin system | Dynamic strategy loading with entry points | |

**User's choice:** [auto] Lightweight functions (recommended — matches existing functional codebase pattern)
**Notes:** Codebase has no OOP patterns; all modules export plain functions. ABC would be inconsistent.

---

## Conviction Score Composition

| Option | Description | Selected |
|--------|-------------|----------|
| Weighted average | Configurable weights per dimension (tech 40%, vol 20%, sent 20%, sector 20%) | ✓ |
| Binary gates | All dimensions must pass threshold, no weighting | |
| ML ensemble | Train a model on historical signals | |

**User's choice:** [auto] Weighted average with configurable weights (recommended — tunable, transparent)
**Notes:** Weights in config env vars for easy tuning. Each sub-score 0-10 independently.

---

## News Sentiment Source

| Option | Description | Selected |
|--------|-------------|----------|
| Alpaca news + Yahoo RSS | Use existing API keys and RSS feed already in sentiment.py | ✓ |
| External NLP API | Use a paid sentiment API (e.g., FinBERT, Alpha Vantage) | |
| StockTwits only | Expand existing StockTwits integration | |

**User's choice:** [auto] Alpaca news API + Yahoo RSS (recommended — no new dependencies, API keys already configured)
**Notes:** Simple keyword scoring, not ML-based. 30-minute cache TTL.

---

## Earnings Date Source

| Option | Description | Selected |
|--------|-------------|----------|
| yfinance | Already a dependency, Ticker.calendar has earnings dates | ✓ |
| Alpaca corporate actions API | More reliable but may need additional API access | |
| Financial Modeling Prep | Free tier available, dedicated earnings API | |

**User's choice:** [auto] yfinance (recommended — already installed, no new dependency)
**Notes:** Earnings within 3 days reduces conviction (risk factor), not a hard block.

---

## Claude's Discretion

- Exact sub-score formulas (RSI→0-10 mapping, volume ratio→0-10 mapping)
- Earnings proximity penalty magnitude
- ThreadPoolExecutor worker count
- Module organization (single file vs directory)
- Error handling for failed symbol fetches

## Deferred Ideas

None — auto mode stayed within phase scope.
