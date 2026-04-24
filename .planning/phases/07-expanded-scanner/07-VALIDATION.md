---
phase: 7
slug: expanded-scanner
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-17
completed: 2026-04-21
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | none — pytest auto-discovers `tests/` |
| **Quick run command** | `py -3 -m pytest tests/test_expanded_scanner.py -x -q` |
| **Full suite command** | `py -3 -m pytest tests/ -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `py -3 -m pytest tests/test_expanded_scanner.py -x -q`
- **After every plan wave:** Run `py -3 -m pytest tests/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 0 | UNIV-01 | — | N/A | unit | `py -3 -m pytest tests/test_expanded_scanner.py::test_universe_includes_indices -x` | ❌ W0 | ⬜ pending |
| 07-01-02 | 01 | 0 | UNIV-02 | — | N/A | unit | `py -3 -m pytest tests/test_expanded_scanner.py::test_unusual_volume_passes_t3 -x` | ❌ W0 | ⬜ pending |
| 07-01-03 | 01 | 0 | UNIV-03 | T-07-01 | Symbol strings validated with regex | unit | `py -3 -m pytest tests/test_expanded_scanner.py::test_tier1_filters -x` | ❌ W0 | ⬜ pending |
| 07-01-04 | 01 | 0 | UNIV-04 | — | N/A | integration | `py -3 -m pytest tests/test_expanded_scanner.py::test_pipeline_produces_survivors -x` | ❌ W0 | ⬜ pending |
| 07-01-05 | 01 | 0 | UNIV-05 | — | N/A | unit | `py -3 -m pytest tests/test_expanded_scanner.py::test_pipeline_isolation -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_expanded_scanner.py` — stubs for UNIV-01 through UNIV-05
- [ ] `tests/test_smc_factors.py` — covers SMC score computation with mocked OHLCV data
- [ ] `tests/test_quant_factors.py` — covers momentum/quality/volatility factor computation

*Existing `tests/test_scanner.py` tests the live scanner only — no overlap needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Dashboard manual trigger button | D-07 | Requires browser interaction | Click "Run Expanded Scan" button on dashboard, verify scan starts and results appear |
| Overnight timing fires at close+15min | D-05 | Requires market close event | Run bot during market hours, verify scan triggers ~15 min after close in logs |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
