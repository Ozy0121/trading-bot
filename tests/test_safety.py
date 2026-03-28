"""
test_safety.py
--------------
Tests for SAFE-01 (state persistence) and SAFE-02 (OCC symbol detection).
"""

from __future__ import annotations

import json
from datetime import date


def test_state_persistence_roundtrip(clean_safety_globals, tmp_state_file):
    """State written on mutation must be fully loadable from disk."""
    import safety

    safety.record_peak_price("SOFI", 10.5)
    safety.record_buy_date("SOFI")
    safety.record_session_start_equity(500.0)

    # Reset in-memory state so load_state_from_file actually restores values
    safety._peak_prices.clear()
    safety._positions_opened_today.clear()
    safety._session_start_equity = None

    safety.load_state_from_file()

    assert safety._peak_prices == {"SOFI": 10.5}
    assert "SOFI" in safety._positions_opened_today
    assert safety._session_start_equity == 500.0


def test_state_corrupt_file_fallback(clean_safety_globals, tmp_state_file):
    """Corrupt state file must log a warning and leave globals at defaults."""
    import safety

    tmp_state_file.write_text("not valid json{{{{")

    safety.load_state_from_file()

    assert safety._peak_prices == {}
    assert safety._positions_opened_today == set()


def test_state_new_day_discards(clean_safety_globals, tmp_state_file):
    """State from a previous day must be discarded (date mismatch)."""
    import safety

    stale = {
        "date": "2020-01-01",
        "peak_prices": {"AAPL": 150.0},
        "positions_opened_today": ["AAPL"],
        "session_start_equity": 400.0,
    }
    tmp_state_file.write_text(json.dumps(stale))

    safety.load_state_from_file()

    assert safety._peak_prices == {}
    assert safety._positions_opened_today == set()


def test_state_missing_file(clean_safety_globals, tmp_state_file):
    """Missing state file must not raise — globals stay at defaults."""
    import safety

    assert not tmp_state_file.exists()
    safety.load_state_from_file()

    assert safety._peak_prices == {}
    assert safety._positions_opened_today == set()
    assert safety._session_start_equity is None


def test_pdt_occ_symbol_detected(clean_safety_globals):
    """OCC-format options symbols must be identified correctly."""
    from safety import is_options_symbol

    assert is_options_symbol("AAPL240119C00150000") is True
    assert is_options_symbol("TSLA250321P00200000") is True


def test_pdt_plain_symbol_not_occ(clean_safety_globals):
    """Plain stock symbols must not match OCC pattern."""
    from safety import is_options_symbol

    assert is_options_symbol("SOFI") is False
    assert is_options_symbol("NVDA") is False
    assert is_options_symbol("") is False


def test_pdt_occ_counted_in_positions_opened(clean_safety_globals):
    """OCC options symbols must work with PDT tracking (record_buy_date)."""
    import safety

    safety.record_buy_date("AAPL240119C00150000")

    assert "AAPL240119C00150000" in safety._positions_opened_today
    assert safety.is_options_symbol("AAPL240119C00150000") is True
