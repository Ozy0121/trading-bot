"""
tests/test_score_grades.py
--------------------------
Unit tests for conviction score grade computation (SCORE-01)
and conviction_threshold state plumbing (SCORE-02).

The score_to_grade() function is a Python reference implementation
of the JS grade logic (Plan 02). Grade cutoffs are anchored to
CONVICTION_THRESHOLD per D-06/D-07.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Reference implementation (mirrors JS grade logic) ────────────────────────

def score_to_grade(score: float, threshold: float) -> str:
    """Return letter grade for a conviction score given a threshold.

    Grade boundaries (per D-06):
        A: score >= threshold + 2.2
        B: score >= threshold
        C: score >= threshold - 1.8
        D: score >= threshold - 3.3
        F: below D cutoff
    """
    if score >= threshold + 2.2:
        return "A"
    if score >= threshold:
        return "B"
    if score >= threshold - 1.8:
        return "C"
    if score >= threshold - 3.3:
        return "D"
    return "F"


# ── SCORE-01: Grade threshold computation ────────────────────────────────────

def test_grade_thresholds():
    """With default threshold=5.8, verify grade boundaries."""
    t = 5.8
    assert score_to_grade(8.0, t) == "A"   # 5.8 + 2.2 = 8.0 -> A
    assert score_to_grade(5.8, t) == "B"    # exactly threshold -> B
    assert score_to_grade(4.0, t) == "C"    # 5.8 - 1.8 = 4.0 -> C
    assert score_to_grade(2.5, t) == "D"    # 5.8 - 3.3 = 2.5 -> D
    assert score_to_grade(2.4, t) == "F"    # below D cutoff -> F


def test_grade_auto_adjusts():
    """With threshold=7.0, grade boundaries shift accordingly (D-07)."""
    t = 7.0
    assert score_to_grade(9.2, t) == "A"    # 7.0 + 2.2 = 9.2 -> A
    assert score_to_grade(7.0, t) == "B"    # exactly threshold -> B
    assert score_to_grade(5.2, t) == "C"    # 7.0 - 1.8 = 5.2 -> C
    assert score_to_grade(3.7, t) == "D"    # 7.0 - 3.3 = 3.7 -> D
    assert score_to_grade(3.6, t) == "F"    # below D cutoff -> F


def test_grade_boundary_exact():
    """Exact boundary values get the higher grade (>= comparison)."""
    t = 5.8
    # Each boundary value should return the higher grade, not the lower
    assert score_to_grade(8.0, t) == "A"    # exactly A cutoff -> A
    assert score_to_grade(5.8, t) == "B"    # exactly B cutoff -> B
    assert score_to_grade(4.0, t) == "C"    # exactly C cutoff -> C
    assert score_to_grade(2.5, t) == "D"    # exactly D cutoff -> D

    # Just below each boundary should get the next lower grade
    assert score_to_grade(7.99, t) == "B"
    assert score_to_grade(5.79, t) == "C"
    assert score_to_grade(3.99, t) == "D"
    assert score_to_grade(2.49, t) == "F"


# ── SCORE-02: conviction_threshold in shared state ───────────────────────────

def test_conviction_threshold_in_state():
    """conviction_threshold key exists in state and flows through update/snapshot."""
    import state

    # Key exists in _state dict with default 0.0
    assert "conviction_threshold" in state._state
    assert state._state["conviction_threshold"] == 0.0

    # update() sets the value, snapshot() returns it
    state.update(conviction_threshold=5.8)
    snap = state.snapshot()
    assert snap["conviction_threshold"] == 5.8

    # Reset for test isolation
    state.update(conviction_threshold=0.0)
