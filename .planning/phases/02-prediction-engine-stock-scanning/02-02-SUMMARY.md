---
phase: 02-prediction-engine-stock-scanning
plan: "02"
subsystem: sentiment-cache
tags: [sentiment, news, scoring, caching, earnings, yfinance, alpaca-news]
dependency_graph:
  requires: [config.py, logger_setup.py]
  provides: [sentiment_cache.py]
  affects: [scanner orchestrator (plan 03)]
tech_stack:
  added: [alpaca.data.historical.news.NewsClient, yfinance.Ticker.calendar]
  patterns: [TTL cache with threading.Lock, keyword scoring, TDD]
key_files:
  created: [sentiment_cache.py, tests/test_sentiment_cache.py]
  modified: []
decisions:
  - "Thread-safe cache uses per-cache Lock; fetch happens outside lock to allow parallel symbol fetches"
  - "Both caches (sentiment + earnings) use module-level dicts — no external storage needed"
  - "Earnings penalty formula: (3 - days_until) * 0.5 + 0.5 for days_until <= 3"
  - "yfinance calendar may return datetime objects or date objects — both handled"
metrics:
  duration: "~10 minutes"
  completed: "2026-03-28"
  tasks_completed: 2
  files_created: 2
---

# Phase 02 Plan 02: Sentiment Cache Module Summary

**One-liner:** Per-symbol news sentiment scoring (Alpaca+Yahoo RSS fallback) with 30-min TTL cache and yfinance earnings proximity penalty (0-2.0).

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Sentiment cache module (TDD RED + GREEN) | e8bd456 / 13f7450 | sentiment_cache.py, tests/test_sentiment_cache.py |
| 2 | Unit tests (10 tests, all passing) | 13f7450 | tests/test_sentiment_cache.py |

## What Was Built

**sentiment_cache.py** — New top-level module exporting:

- `get_sentiment_score(symbol) -> float` — Fetches headlines from Alpaca NewsClient (primary) or Yahoo Finance RSS (fallback). Scores via keyword counting: bullish terms push score toward 10.0, bearish terms toward 0.0, no headlines returns neutral 5.0. Cached per-symbol for 30 minutes with `threading.Lock`.

- `get_earnings_penalty(symbol) -> float` — Returns 0.0-2.0 penalty based on days until next earnings (via yfinance calendar). Penalty: 0 days=2.0, 1=1.5, 2=1.0, 3=0.5, >3=0.0. Cached per calendar day.

**tests/test_sentiment_cache.py** — 10 unit tests with full mock coverage (no real API calls):
- Score range validation
- TTL cache hit (mock called only once on second call)
- All-bullish headlines → score > 7.0
- All-bearish headlines → score < 3.0
- No headlines → score == 5.0
- Alpaca failure → Yahoo RSS fallback used
- Earnings penalty at 3 days, today, >3 days, missing data

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all functions are fully implemented. `get_earnings_penalty` requires yfinance to be installed (gracefully returns 0.0 if not available).

## Self-Check: PASSED

- `sentiment_cache.py` exists and imports cleanly
- `get_sentiment_score` and `get_earnings_penalty` exported
- `SENTIMENT_TTL = 1800` confirmed
- `_BULLISH_KEYWORDS`, `_BEARISH_KEYWORDS`, `_earnings_cache`, `threading.Lock` all present
- `NewsClient` and `yahoo.com/rss` URL present
- All 10 tests pass: `python -m pytest tests/test_sentiment_cache.py -x -q` → 10 passed
- Both commits verified: 13f7450 (tests), e8bd456 (implementation)
