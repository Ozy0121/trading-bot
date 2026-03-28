"""
test_safety.py
--------------
Tests for SAFE-01 (state persistence), SAFE-02 (OCC symbol detection),
SAFE-04 (options-aware liquidation), and SAFE-05 (options trading validation).
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, call

from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest


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


# ── SAFE-04: Options-aware liquidate_all ─────────────────────────────────────

def _make_position(symbol: str, qty: str, current_price: str):
    """Helper to build a mock position object."""
    pos = MagicMock()
    pos.symbol = symbol
    pos.qty = qty
    pos.current_price = current_price
    return pos


def test_liquidate_all_stock_only(mock_trading_client, clean_safety_globals):
    """Stock-only positions must use MarketOrderRequest, not LimitOrderRequest."""
    from safety import liquidate_all

    pos = _make_position("SOFI", "10", "10.50")
    mock_trading_client.get_all_positions.return_value = [pos]

    liquidate_all(mock_trading_client)

    assert mock_trading_client.submit_order.call_count == 1
    req = mock_trading_client.submit_order.call_args[0][0]
    assert isinstance(req, MarketOrderRequest), "Stock must use MarketOrderRequest"
    assert not isinstance(req, LimitOrderRequest)


def test_liquidate_all_options_position(mock_trading_client, clean_safety_globals):
    """Options positions must use LimitOrderRequest, not MarketOrderRequest."""
    from safety import liquidate_all

    pos = _make_position("AAPL240119C00150000", "2", "3.50")
    mock_trading_client.get_all_positions.return_value = [pos]

    liquidate_all(mock_trading_client)

    assert mock_trading_client.submit_order.call_count == 1
    req = mock_trading_client.submit_order.call_args[0][0]
    assert isinstance(req, LimitOrderRequest), "Options must use LimitOrderRequest"
    assert not isinstance(req, MarketOrderRequest)


def test_liquidate_all_mixed(mock_trading_client, clean_safety_globals):
    """Mixed portfolio: stock uses MarketOrderRequest, options uses LimitOrderRequest."""
    from safety import liquidate_all

    stock_pos = _make_position("SOFI", "10", "10.50")
    opts_pos = _make_position("AAPL240119C00150000", "2", "3.50")
    mock_trading_client.get_all_positions.return_value = [stock_pos, opts_pos]

    liquidate_all(mock_trading_client)

    assert mock_trading_client.submit_order.call_count == 2
    calls = mock_trading_client.submit_order.call_args_list

    # Collect request types used in calls
    req_types = [type(c[0][0]) for c in calls]
    assert MarketOrderRequest in req_types, "Stock position must use MarketOrderRequest"
    assert LimitOrderRequest in req_types, "Options position must use LimitOrderRequest"


def test_liquidate_all_options_uses_limit_price(mock_trading_client, clean_safety_globals):
    """LimitOrderRequest for options must have limit_price = round(current_price, 2)."""
    from safety import liquidate_all

    pos = _make_position("AAPL240119C00150000", "2", "3.567")
    mock_trading_client.get_all_positions.return_value = [pos]

    liquidate_all(mock_trading_client)

    req = mock_trading_client.submit_order.call_args[0][0]
    assert isinstance(req, LimitOrderRequest)
    assert req.limit_price == round(3.567, 2), (
        f"limit_price must equal round(current_price, 2). Got {req.limit_price}"
    )


# ── SAFE-05: validate_options_enabled ────────────────────────────────────────

def test_validate_options_live_level_ok(mock_trading_client):
    """Live mode with options_approved_level=2 must not raise."""
    from safety import validate_options_enabled

    mock_trading_client.get_account.return_value.options_approved_level = 2
    # Must not raise
    validate_options_enabled(mock_trading_client, live_mode=True)


def test_validate_options_live_level_too_low(mock_trading_client):
    """Live mode with options_approved_level=1 must raise SystemExit."""
    from safety import validate_options_enabled
    import pytest

    mock_trading_client.get_account.return_value.options_approved_level = 1
    with pytest.raises(SystemExit):
        validate_options_enabled(mock_trading_client, live_mode=True)


def test_validate_options_live_level_none(mock_trading_client):
    """Live mode with options_approved_level=None must raise SystemExit."""
    from safety import validate_options_enabled
    import pytest

    mock_trading_client.get_account.return_value.options_approved_level = None
    with pytest.raises(SystemExit):
        validate_options_enabled(mock_trading_client, live_mode=True)


def test_validate_options_paper_skips(mock_trading_client):
    """Paper mode must skip options validation regardless of approval level (per D-10)."""
    from safety import validate_options_enabled

    mock_trading_client.get_account.return_value.options_approved_level = None
    # Must not raise even though approval level is None
    validate_options_enabled(mock_trading_client, live_mode=False)
