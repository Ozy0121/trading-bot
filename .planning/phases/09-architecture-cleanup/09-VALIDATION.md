---
phase: 9
slug: architecture-cleanup
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-13
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | None (no pytest, unittest, or test directory in project) |
| **Config file** | None — project has no test framework |
| **Quick run command** | `py server.py paper` (manual smoke test — server starts, routes respond) |
| **Full suite command** | Manual: start server, exercise each route group, confirm no import errors |
| **Estimated runtime** | ~15 seconds (server startup + route check) |

---

## Sampling Rate

- **After every task commit:** Run `py server.py paper` — verify server starts without errors
- **After every plan wave:** Manual smoke test — hit each modified route group via browser
- **Before `/gsd-verify-work`:** Full manual verification of all 6 success criteria
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 1 | D-04 state validation | — | N/A | smoke | `py -c "from state import shared_state; shared_state.update(bogus_key=1)"` | N/A | ⬜ pending |
| 09-01-02 | 01 | 1 | Issue #2 safety lock | — | N/A | manual | Check safety.py has `_globals_lock` wrapping all 3 globals | N/A | ⬜ pending |
| 09-02-01 | 02 | 1 | D-01 dashboard split | — | N/A | smoke | `py server.py paper` + verify all routes respond | N/A | ⬜ pending |
| 09-02-02 | 02 | 1 | D-03 prediction unify | — | N/A | manual | Run prediction scan, check `/api/predictions` matches bot source | N/A | ⬜ pending |
| 09-03-01 | 03 | 2 | bot.py extraction | — | N/A | smoke | `py server.py paper` + start bot + watch logs for all 14 phases | N/A | ⬜ pending |
| 09-03-02 | 03 | 2 | D-05 server isolation | — | N/A | smoke | Comment out sentiment import, `py server.py paper` still starts | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. No test framework to install — project uses manual smoke testing per CLAUDE.md conventions.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| All 35 routes respond after split | D-01 | No test framework; routes need HTTP client | Start server, hit each route group in browser |
| Thread safety of safety.py globals | Issue #2 | Race conditions require concurrent test harness | Inspect code for Lock usage around all 3 globals |
| Prediction data consistency | D-03 | Requires running prediction scan + comparing outputs | Run scan, compare `/api/predictions` vs `shared_state` |
| Server starts with disabled services | D-05 | Requires manual service disabling | Comment out optional service, verify startup |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
