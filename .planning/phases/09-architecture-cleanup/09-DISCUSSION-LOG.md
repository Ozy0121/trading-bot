# Phase 9: Architecture Cleanup - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-13
**Phase:** 09-architecture-cleanup
**Areas discussed:** Dashboard split strategy, Prediction data unification, State validation strictness, Server startup isolation

---

## Dashboard Split Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Flask Blueprints (Recommended) | Use Flask Blueprints for trading, scanner, and core. Standard Flask pattern. | |
| Plain Python modules | Move route handler functions to separate files, import and register them in dashboard.py. | |
| You decide | Claude picks the best approach based on codebase patterns. | Y |

**User's choice:** You decide
**Notes:** User confirmed the three-way route grouping (trading, scanner/predictions, core/data) in a follow-up question.

---

## Prediction Data Unification

| Option | Description | Selected |
|--------|-------------|----------|
| shared_state (in-memory) | All prediction consumers read from shared_state. Disk is only for persistence/history. | |
| Disk (prediction_history.json) | All consumers read from disk via get_latest_predictions(). shared_state just caches for SSE. | |
| You decide | Claude picks based on how the data flows work today. | Y |

**User's choice:** You decide
**Notes:** None

---

## State Validation Strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Raise ValueError immediately | Unknown keys crash hard. Matches success criteria exactly. | |
| Warn then raise after testing | Start with warnings, add strict mode flag. Flip to ValueError after verifying callers. | |
| You decide | Claude picks the safest migration path. | Y |

**User's choice:** You decide
**Notes:** None

---

## Server Startup Isolation

| Option | Description | Selected |
|--------|-------------|----------|
| Try/except per service | Wrap each service start in try/except. Failed services log error but dashboard still launches. | |
| Service registry pattern | Register services with priorities. Critical failures halt startup. Optional degrade gracefully. | |
| You decide | Claude picks the right isolation level based on which services are truly critical. | Y |

**User's choice:** You decide
**Notes:** None

---

## Claude's Discretion

All four areas were deferred to Claude's judgment. Additionally, safety.py locking and bot.py function extraction were identified as straightforward (no gray areas).

## Deferred Ideas

None — discussion stayed within phase scope.
