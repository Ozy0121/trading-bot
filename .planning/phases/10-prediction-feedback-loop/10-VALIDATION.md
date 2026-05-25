---
phase: 10
slug: prediction-feedback-loop
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-25
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Python unittest / manual verification |
| **Config file** | none — no formal test runner configured |
| **Quick run command** | `python -m pytest tests/test_signal_calibration.py -v` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_signal_calibration.py -v`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 1 | active_signals field | unit | `python -m pytest tests/test_signal_calibration.py::test_active_signals_stored` | ❌ W0 | ⬜ pending |
| 10-01-02 | 01 | 1 | outcome resolution | manual | Check `/api/prediction-log/accuracy` pending count | ❌ W0 | ⬜ pending |
| 10-02-01 | 02 | 2 | weight clamp [1.0, 6.0] | unit | `python -m pytest tests/test_signal_calibration.py::test_weight_clamp` | ❌ W0 | ⬜ pending |
| 10-02-02 | 02 | 2 | skip if < 20 resolved | unit | `python -m pytest tests/test_signal_calibration.py::test_skip_threshold` | ❌ W0 | ⬜ pending |
| 10-02-03 | 02 | 2 | config file load/fallback | integration | Delete signal_weights.json, restart, verify defaults | N/A | ⬜ pending |
| 10-03-01 | 03 | 3 | accuracy banner renders | manual | Open dashboard, verify banner text | N/A | ⬜ pending |
| 10-03-02 | 03 | 3 | per-signal stats display | manual | Open dashboard, verify stats section | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_signal_calibration.py` — unit tests for recalibration logic (clamp, skip threshold, formula)
- No framework install needed — project uses standard Python and manual testing

*Existing infrastructure covers remaining phase requirements via manual verification.*

---

## Manual-Only Verifications

| Behavior | Why Manual | Test Instructions |
|----------|------------|-------------------|
| Outcome resolution of pending records | Requires real prediction data in prediction_history.json | Call POST `/api/prediction-log/accuracy`, confirm pending count drops |
| Accuracy banner renders correctly | Visual UI verification | Open dashboard, verify "Last 50 predictions: X correct (Y%)" banner |
| Sunday scheduler triggers recalibration | Time-dependent scheduling | Trigger manually via POST `/api/prediction-log/recalibrate`, verify log output |
| Config file fallback on missing weights | Requires restart cycle | Delete `data/signal_weights.json`, restart server, confirm defaults used |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
