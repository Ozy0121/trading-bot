---
phase: 1
slug: safety-infrastructure
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-27
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (not yet installed — Wave 0) |
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
| 01-01-01 | 01 | 1 | SAFE-01 | unit | `python -m pytest tests/test_safety.py::test_state_persistence -x` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | SAFE-01 | unit | `python -m pytest tests/test_safety.py::test_state_new_day -x` | ❌ W0 | ⬜ pending |
| 01-01-03 | 01 | 1 | SAFE-02 | unit | `python -m pytest tests/test_safety.py::test_pdt_occ_symbols -x` | ❌ W0 | ⬜ pending |
| 01-01-04 | 01 | 1 | SAFE-03 | unit (mock) | `python -m pytest tests/test_safety.py::test_fill_polling -x` | ❌ W0 | ⬜ pending |
| 01-01-05 | 01 | 1 | SAFE-03 | unit (mock) | `python -m pytest tests/test_safety.py::test_partial_fill_handling -x` | ❌ W0 | ⬜ pending |
| 01-01-06 | 01 | 1 | SAFE-04 | unit (mock) | `python -m pytest tests/test_safety.py::test_liquidate_all_options -x` | ❌ W0 | ⬜ pending |
| 01-01-07 | 01 | 1 | SAFE-05 | unit (mock) | `python -m pytest tests/test_safety.py::test_options_validation -x` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 1 | BRACKET-01 | unit (mock) | `python -m pytest tests/test_bracket.py::test_bracket_on_buy -x` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 1 | BRACKET-02 | unit (mock) | `python -m pytest tests/test_bracket.py::test_startup_stop_loss_recovery -x` | ❌ W0 | ⬜ pending |
| 01-02-03 | 02 | 1 | BRACKET-02 | unit (mock) | `python -m pytest tests/test_bracket.py::test_startup_stop_loss_present -x` | ❌ W0 | ⬜ pending |
| 01-02-04 | 02 | 1 | BRACKET-03 | unit (mock) | `python -m pytest tests/test_bracket.py::test_shutdown_stop_loss_warning -x` | ❌ W0 | ⬜ pending |
| 01-02-05 | 02 | 1 | BRACKET-04 | unit | `python -m pytest tests/test_bracket.py::test_positions_api_includes_sl_tp -x` | ❌ W0 | ⬜ pending |
| 01-02-06 | 02 | 1 | BRACKET-05 | unit | `python -m pytest tests/test_bracket.py::test_config_exits_endpoint -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pip install pytest` — install test framework
- [ ] `tests/conftest.py` — shared fixtures: mock TradingClient, mock Order, mock Account
- [ ] `tests/test_safety.py` — stubs for SAFE-01 through SAFE-05
- [ ] `tests/test_bracket.py` — stubs for BRACKET-01 through BRACKET-05
- [ ] `data/` directory — created lazily at first state save

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Dashboard shows SL/TP prices | BRACKET-04 | Browser rendering | Open dashboard, verify position cards show stop-loss and take-profit prices |
| Dashboard config exits form | BRACKET-05 | Browser interaction | Submit new SL/TP %, verify config updates |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
