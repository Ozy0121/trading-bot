---
phase: 6
slug: score-recalibration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-07
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 |
| **Config file** | none — pytest discovers from `tests/` |
| **Quick run command** | `py -m pytest tests/test_score_grades.py -x -q` |
| **Full suite command** | `py -m pytest tests/ -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `py -m pytest tests/test_score_grades.py -x -q`
- **After every plan wave:** Run `py -m pytest tests/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | SCORE-01 | — | N/A | unit | `py -m pytest tests/test_score_grades.py::test_grade_thresholds -x -q` | Wave 0 | pending |
| 06-01-02 | 01 | 1 | SCORE-01 | — | N/A | unit | `py -m pytest tests/test_score_grades.py::test_grade_auto_adjusts -x -q` | Wave 0 | pending |
| 06-01-03 | 01 | 1 | SCORE-02 | — | N/A | unit | `py -m pytest tests/test_score_grades.py::test_conviction_threshold_in_state -x -q` | Wave 0 | pending |
| 06-01-04 | 01 | 1 | SCORE-02 | — | N/A | manual | Browser: hover score cell, verify tooltip | N/A | pending |

*Status: pending*

---

## Wave 0 Requirements

- [ ] `tests/test_score_grades.py` — stubs for SCORE-01 (grade threshold computation) and SCORE-02 (conviction_threshold in state)

*Existing pytest infrastructure covers test discovery and fixtures.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Grade badge renders with correct color | SCORE-01 | CSS visual rendering | Open dashboard, verify grade pills show A=green, B=yellow-green, C=yellow, D=orange, F=red |
| Tooltip appears on hover with sub-score bars | SCORE-02 | CSS hover interaction | Hover over any score cell in watchlist, verify tooltip shows Technical/Volume/Sentiment/Sector bars with values |
| Tooltip footer shows strategy labels | SCORE-02 | CSS hover + JS rendering | Hover score cell, verify "Strategy: Momentum + Catalyst" format |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
