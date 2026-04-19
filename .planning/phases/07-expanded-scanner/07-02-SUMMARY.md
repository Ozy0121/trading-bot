---
phase: 07-expanded-scanner
plan: 02
subsystem: expanded-scanner-pipeline
tags: [pipeline, overnight-daemon, four-tier-filter, json-persistence, dashboard-integration]
dependency_graph:
  requires: [quant_factors.py, smc_factors.py, stock_universe.py, openbb_data.py]
  provides: [expanded_scanner.py, tests/test_expanded_scanner.py]
  affects: [state.py, config.py, server.py, dashboard.py]
tech_stack:
  added: []
  patterns: [cascading-pipeline, daemon-thread, json-persistence, tdd]
key_files:
  created:
    - expanded_scanner.py
    - tests/test_expanded_scanner.py
  modified:
    - state.py
    - config.py
    - server.py
    - dashboard.py
decisions:
  - "Four-tier pipeline: price/ETF -> volume -> momentum -> quant scoring"
  - "ETF detection at T1 (symbol heuristic) and T4 (quoteType from ticker info)"
  - "Overnight daemon uses Alpaca calendar API for market close timing"
  - "JSON persistence with 18-hour TTL in data/overnight_results.json"
  - "Pipeline fully isolated from scanner.py (zero imports)"
metrics:
  duration: "~8m"
  completed: "2026-04-18T05:30:00Z"
  tasks_completed: 2
  tasks_total: 2
  tests_added: 8
  tests_passing: 8
---

# Phase 07 Plan 02: Expanded Scanner Pipeline Summary

Four-tier cascading pipeline for overnight expanded stock scanning with daemon thread, JSON persistence, and dashboard integration.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create expanded_scanner.py with four-tier pipeline + tests (TDD) | b781278 | expanded_scanner.py, tests/test_expanded_scanner.py |
| 2 | Integration hooks (state/config/server/dashboard) + overnight daemon | 09c4537 | state.py, config.py, server.py, dashboard.py, expanded_scanner.py |

## What Was Built

### expanded_scanner.py (499 lines)
- `_is_etf_or_preferred(symbol, info)` — ETF/preferred share detection via symbol heuristics and quoteType
- `_valid_symbol(sym)` — regex validation (1-5 uppercase letters, T-07 threat mitigation)
- `_filter_price_mcap(symbols, bars_dict)` — T1: price gate $5-$200, ETF rejection
- `_filter_volume(symbols, bars_dict)` — T2: avg volume >= 500K gate
- `_filter_momentum(symbols, bars_5d, bars_20d)` — T3: positive 5d return OR unusual volume >1.5x
- `_score_quant_multifactor(symbols, bars_dict, deadline)` — T4: multi-factor scoring, top 50 survivors
- `run_expanded_pipeline(timeout_seconds)` — main pipeline orchestrator
- `save_overnight_results(results, scan_meta)` — JSON persistence with 18h TTL
- `load_overnight_results()` — load cached results with TTL enforcement
- `trigger_manual_scan()` — manual scan trigger for dashboard
- `_get_market_close_today(trading_client)` — Alpaca calendar-based close time
- `_overnight_daemon_loop(trading_client)` — daemon thread loop
- `start_overnight_daemon(trading_client)` — daemon startup with cached results restore

### tests/test_expanded_scanner.py (226 lines, 8 tests)
- `test_tier1_filters` — price gate and ETF rejection
- `test_tier2_volume_filter` — volume threshold filtering
- `test_tier3_momentum_gate` — momentum and return filtering
- `test_unusual_volume_passes_t3` — unusual volume bypass (UNIV-02)
- `test_pipeline_produces_survivors` — end-to-end pipeline with mocks
- `test_pipeline_isolation` — zero imports from scanner.py (D-04)
- `test_save_load_overnight_results` — JSON round-trip + TTL expiry
- `test_etf_detection` — ETF keyword and quoteType detection

### Integration Changes
- **state.py**: 4 new keys (expanded_scan_results, expanded_scan_time, expanded_scan_status, expanded_scan_funnel)
- **config.py**: 4 new constants (EXPANDED_SCAN_BATCH_SIZE, EXPANDED_SCAN_WORKERS, EXPANDED_SCAN_TIMEOUT, EXPANDED_SCAN_DELAY_MINUTES)
- **server.py**: Overnight daemon startup call
- **dashboard.py**: GET /api/expanded-scan + POST /api/expanded-scan/run routes

## Deviations from Plan

None — all acceptance criteria met as specified.

## Verification Results

All 8 tests pass. Plan 01 regression tests (8 tests) also pass. Key checks:
- `grep -c "from scanner import" expanded_scanner.py` returns 0 (isolation confirmed)
- `expanded_scan_results` key found in state.py
- `EXPANDED_SCAN_TIMEOUT` constant found in config.py
- `start_overnight_daemon` call found in server.py
- Both `/api/expanded-scan` routes found in dashboard.py

## Self-Check: PASSED

All 2 created files and 4 modified files verified. Both commits present in git log.
