# Phase 1: Safety Infrastructure - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 01-safety-infrastructure
**Areas discussed:** State persistence, Order fill handling, Options liquidation, Startup validation

---

## State Persistence

### Storage Format
| Option | Description | Selected |
|--------|-------------|----------|
| JSON file (Recommended) | Simple, human-readable, easy to debug. One file like bot_state.json in project root. | |
| SQLite database | More robust for concurrent access and complex queries. Overkill for 3-5 tracked values. | |
| You decide | Claude picks the best approach based on codebase patterns and data volume. | ✓ |

**User's choice:** You decide
**Notes:** None

### Flush Frequency
| Option | Description | Selected |
|--------|-------------|----------|
| On every state change (Recommended) | Write immediately when peak price updates, trade executes, or PDT count changes. | |
| Periodic (every 30-60s) | Buffer changes and write on interval. Risks losing up to 60s of state on crash. | |
| You decide | Claude picks based on data volume and risk profile. | ✓ |

**User's choice:** You decide
**Notes:** None

### File Path
| Option | Description | Selected |
|--------|-------------|----------|
| Project root (Recommended) | e.g. ./bot_state.json — visible, easy to inspect. Add to .gitignore. | |
| Inside data/ directory | e.g. ./data/bot_state.json — keeps root clean, groups runtime data. | |
| You decide | Claude picks the best location based on project structure. | ✓ |

**User's choice:** You decide
**Notes:** None

### Corruption Handling
| Option | Description | Selected |
|--------|-------------|----------|
| Log warning, start fresh (Recommended) | If state file is unreadable, log a warning and start with empty state. | ✓ |
| Atomic writes with backup | Write to .tmp file then rename. Keep one backup copy. More complexity. | |
| You decide | Claude picks the right tradeoff for a $500 account bot. | |

**User's choice:** Log warning, start fresh
**Notes:** None

---

## Order Fill Handling

### Fill Timeout
| Option | Description | Selected |
|--------|-------------|----------|
| 10 seconds (Recommended) | Market orders fill in <1s. 10s covers edge cases. | ✓ |
| 30 seconds | More generous timeout. Covers illiquid stocks and options. | |
| You decide | Claude picks based on Alpaca's typical fill times. | |

**User's choice:** 10 seconds
**Notes:** None

### Partial Fill Handling
| Option | Description | Selected |
|--------|-------------|----------|
| Accept partial, track actual qty (Recommended) | If 50 of 100 shares fill, treat as 50-share position. Cancel remainder. | |
| Cancel and retry full order | Cancel partial, resubmit full qty. Risk of looping. | |
| You decide | Claude picks the safest approach. | |

**User's choice:** Other (free text)
**Notes:** User wants smart/contextual handling — the bot should analyze the circumstance (fill ratio, time elapsed, position significance) and decide dynamically whether to accept partial or retry. Not a rigid rule.

### Rejection Handling
| Option | Description | Selected |
|--------|-------------|----------|
| Log and skip, continue cycle (Recommended) | Log rejection reason, skip trade, move on. Don't retry. | |
| Retry once after 5s delay | One retry for transient rejections. If still rejected, log and skip. | |
| You decide | Claude picks based on Alpaca rejection types. | ✓ |

**User's choice:** You decide
**Notes:** None

---

## Options Liquidation

### Exit Pricing
| Option | Description | Selected |
|--------|-------------|----------|
| LIMIT at mid-price (Recommended) | Use bid-ask midpoint. If no fill in 10s, retry at bid. | |
| LIMIT at bid price | Aggressive exit, fastest fill, lose the spread. | |
| You decide | Claude picks best emergency exit strategy. | ✓ |

**User's choice:** You decide
**Notes:** None

### Liquidation Architecture
| Option | Description | Selected |
|--------|-------------|----------|
| Unified with type detection (Recommended) | One liquidate_all() that detects stock vs option via OCC symbol format. | |
| Separate functions | liquidate_stocks() and liquidate_options() as distinct functions. | |
| You decide | Claude picks based on existing code structure. | ✓ |

**User's choice:** You decide
**Notes:** None

---

## Startup Validation

### Options Not Enabled Behavior
| Option | Description | Selected |
|--------|-------------|----------|
| Warn and run stocks-only (Recommended) | Log WARNING, disable options features, keep running for stocks. | |
| Refuse to start entirely | Hard stop with clear error. Forces user to enable options first. | |
| You decide | Claude picks based on requirements and practical use. | ✓ |

**User's choice:** You decide
**Notes:** None

### Capital Check at Startup
| Option | Description | Selected |
|--------|-------------|----------|
| Yes, warn if low (Recommended) | Check buying power at startup. Warn if < $50. | |
| No, just options check | Only validate options capability per SAFE-05. | |
| You decide | Claude picks based on what's practical. | ✓ |

**User's choice:** You decide
**Notes:** None

---

## Claude's Discretion

Storage format, flush frequency, file path, order rejection handling, options exit pricing, liquidation architecture, startup validation behavior, and capital check — all deferred to Claude's judgment with preference for simplicity and safety.

## Deferred Ideas

None — discussion stayed within phase scope.
