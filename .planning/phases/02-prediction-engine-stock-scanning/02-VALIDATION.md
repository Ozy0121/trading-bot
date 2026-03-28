---
phase: 02
slug: prediction-engine-stock-scanning
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-28
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | none — Wave 0 installs |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | STRAT-01 | unit | `python -m pytest tests/test_strategies.py -k registry` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | STRAT-02 | unit | `python -m pytest tests/test_strategies.py -k momentum` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 1 | STRAT-03 | unit | `python -m pytest tests/test_strategies.py -k reversion` | ❌ W0 | ⬜ pending |
| 02-01-04 | 01 | 1 | STRAT-04 | unit | `python -m pytest tests/test_strategies.py -k catalyst` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 1 | STRAT-05,STRAT-06 | unit | `python -m pytest tests/test_scoring.py` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 1 | PRED-01 | unit | `python -m pytest tests/test_sentiment.py` | ❌ W0 | ⬜ pending |
| 02-02-03 | 02 | 1 | PRED-02 | unit | `python -m pytest tests/test_scoring.py -k volume` | ❌ W0 | ⬜ pending |
| 02-02-04 | 02 | 1 | PRED-03 | unit | `python -m pytest tests/test_scoring.py -k earnings` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 2 | SCAN-01,SCAN-05 | integration | `python -m pytest tests/test_scanner.py -k parallel` | ❌ W0 | ⬜ pending |
| 02-03-02 | 03 | 2 | SCAN-02 | unit | `python -m pytest tests/test_scanner.py -k sector` | ❌ W0 | ⬜ pending |
| 02-03-03 | 03 | 2 | SCAN-03,SCAN-04 | unit | `python -m pytest tests/test_scanner.py -k watchlist` | ❌ W0 | ⬜ pending |
| 02-04-01 | 04 | 2 | PRED-04,PRED-05 | integration | `python -m pytest tests/test_scanner.py -k conviction` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_strategies.py` — stubs for STRAT-01 through STRAT-04
- [ ] `tests/test_scoring.py` — stubs for STRAT-05, STRAT-06, PRED-01, PRED-02, PRED-03
- [ ] `tests/test_scanner.py` — stubs for SCAN-01 through SCAN-05, PRED-04, PRED-05
- [ ] `tests/conftest.py` — shared fixtures (mock bar data, mock news responses)
- [ ] `pytest` install — if not in requirements.txt

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full scan < 15s for 35-40 symbols | SCAN-05 | Requires live API calls | Run `python -c "from scanner import scan; scan(watchlist)"` and time it |
| Alpaca news API authentication | PRED-01 | Requires valid API credentials | Check logs for "[sentiment] Alpaca news: N headlines" |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
