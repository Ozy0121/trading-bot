# Phase 7: Expanded Scanner - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-16
**Phase:** 07-expanded-scanner
**Areas discussed:** Pre-filter strategy, Overnight timing, Universe composition, Scanner integration

---

## Pre-filter Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Volume + price gate | Bulk yf.download() 5d bars, keep price $5-$200, vol >500K, one day >1.5x avg | |
| Technical signal gate | Same + require bullish technical signal (RSI <40, near 20d SMA, vol spike >2x) | |
| Momentum + volume gate | Price/vol gate + positive 5d momentum or >2x avg volume | |

**User's choice:** Custom — 4-tier cascading pipeline: price → volume → momentum → heavy quant strategies. User specifically asked about using quant strategies to filter, researching premade strategies from GitHub, and whether open-source implementations exist.

**Notes:** User wants maximum sophistication in the pre-filter. Research phase should evaluate quant libraries and GitHub repos.

### Quant Filter Depth

| Option | Description | Selected |
|--------|-------------|----------|
| Light quant | Use existing indicators as pass/fail filters | |
| Medium quant | Existing + 2-3 factor scores (relative strength, earnings momentum) | |
| Heavy quant | Full multi-factor model: momentum, value, quality, volatility | ✓ |

**User's choice:** Heavy quant
**Notes:** None

### Survivor Count

| Option | Description | Selected |
|--------|-------------|----------|
| ~50 stocks | Matches UNIV-04, ~30s scoring | ✓ |
| ~100 stocks | Wider net, ~60s scoring | |
| ~25 stocks | Very selective, near-instant | |

**User's choice:** ~50 stocks (recommended)
**Notes:** None

### Scanner Impact Clarification

**User asked:** "Will this affect my scanner?"
**Answer:** No — expanded scanner runs overnight only, separate from the 60s live loop. Both share conviction scoring engine but expanded adds 4-tier pre-filter. Two scanners coexist independently.

---

## Overnight Timing

| Option | Description | Selected |
|--------|-------------|----------|
| Alpaca calendar | Query API for close time, trigger 15min after. DST-safe, handles holidays | ✓ |
| Fixed clock time | 4:30 PM ET daily. Breaks on early closes/holidays/DST | |
| Manual trigger only | Dashboard button, no automation | |

**User's choice:** Alpaca calendar (recommended)
**Notes:** None

### Timeout Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Hard timeout | 2-hour max, save partial results, stop | ✓ |
| Let it finish | Run to completion even past pre-market | |
| Kill and discard | Kill 30min before open, no partial results | |

**User's choice:** Hard timeout (recommended)
**Notes:** None

### Manual Dashboard Trigger

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, add button | On-demand trigger for testing/weekends/off-hours | ✓ |
| No, overnight only | Automated only | |

**User's choice:** Yes, add dashboard button (recommended)
**Notes:** None

---

## Universe Composition

### ETF Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Filter ETFs in pre-filter | Keep in universe, pre-filter removes them (UNIV-03) | ✓ |
| Exempt leveraged ETFs | Filter index/sector ETFs, keep TQQQ/SOXL/USO/GLD | |
| Remove all ETFs | Strictly no ETFs in expanded scanner | |

**User's choice:** Filter ETFs in pre-filter (recommended)
**Notes:** None

### Universe Size

| Option | Description | Selected |
|--------|-------------|----------|
| Keep 2,500+ | Full universe, 4-tier pipeline handles volume | ✓ |
| Trim to ~1,000 | Drop Russell 2000, keep major indices + discovery | |
| Trim to ~500 | S&P 500 + NASDAQ 100 only | |

**User's choice:** Keep 2,500+ (recommended)
**Notes:** None

---

## Scanner Integration

### Scoring Method

| Option | Description | Selected |
|--------|-------------|----------|
| Same conviction scoring | Reuse existing tech/vol/sentiment/sector scoring | |
| Enhanced overnight scoring | Base scoring + daily bar patterns, relative strength | |
| Quant-only ranking | Rank by multi-factor quant scores only, skip conviction | ✓ |

**User's choice:** Quant-only ranking
**Notes:** Intentionally different from conviction scoring — overnight results are a separate "discovery" system

### Results Storage

| Option | Description | Selected |
|--------|-------------|----------|
| State + JSON file | shared_state for display + JSON for persistence | ✓ |
| State only | In-memory only, lost on restart | |
| JSON file only | File persistence, slower reads | |

**User's choice:** State + JSON file (recommended)
**Notes:** None

---

## Claude's Discretion

- Batch size for bulk yf.download() calls
- Specific quant factor weights and thresholds
- JSON file location and format
- Thread pool worker count for overnight scan

## Deferred Ideas

None — discussion stayed within phase scope
