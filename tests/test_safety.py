"""
test_safety.py
--------------
Tests for SAFE-01 (state persistence) and SAFE-02 (OCC symbol detection).
"""

from __future__ import annotations


def test_state_persistence_roundtrip(clean_safety_globals, tmp_state_file):
    # TODO: implement after Task 2
    pass


def test_state_corrupt_file_fallback(clean_safety_globals, tmp_state_file):
    pass


def test_state_new_day_discards(clean_safety_globals, tmp_state_file):
    pass


def test_state_missing_file(clean_safety_globals, tmp_state_file):
    pass


def test_pdt_occ_symbol_detected(clean_safety_globals):
    pass


def test_pdt_plain_symbol_not_occ(clean_safety_globals):
    pass


def test_pdt_occ_counted_in_positions_opened(clean_safety_globals):
    pass
