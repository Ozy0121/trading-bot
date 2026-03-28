"""
conftest.py
-----------
Shared pytest fixtures for all trading-bot tests.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderStatus


@pytest.fixture
def mock_trading_client():
    """MagicMock TradingClient with sensible paper-account defaults."""
    client = MagicMock(spec=TradingClient)

    # Account mock
    account = MagicMock()
    account.equity = "500.00"
    account.cash = "300.00"
    account.buying_power = "300.00"
    account.daytrade_count = 0
    account.options_approved_level = 2
    client.get_account.return_value = account

    # Positions and orders
    client.get_all_positions.return_value = []
    client.get_orders.return_value = []

    # Order submission
    order = MagicMock()
    order.id = "test-order-123"
    order.status = OrderStatus.FILLED
    order.filled_qty = "10"
    order.filled_avg_price = "10.00"
    order.legs = []
    order.symbol = "SOFI"
    client.submit_order.return_value = order

    return client


@pytest.fixture
def tmp_state_file(tmp_path):
    """Return a path inside a per-test temp directory for the bot state file."""
    state_dir = tmp_path / "data"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "bot_state.json"


@pytest.fixture(autouse=False)
def clean_safety_globals(tmp_state_file):
    """
    Reset safety module globals before each test and restore STATE_FILE afterwards.
    Monkeypatches safety.STATE_FILE to the tmp path so tests never touch real disk.
    """
    import safety

    # Save originals
    original_state_file = safety.STATE_FILE
    original_peak_prices = dict(safety._peak_prices)
    original_positions_opened_today = set(safety._positions_opened_today)
    original_session_start_equity = safety._session_start_equity

    # Point state file at temp location
    safety.STATE_FILE = str(tmp_state_file)

    # Reset globals to clean slate
    safety._peak_prices.clear()
    safety._positions_opened_today.clear()
    safety._session_start_equity = None

    yield

    # Restore originals
    safety._peak_prices.clear()
    safety._peak_prices.update(original_peak_prices)
    safety._positions_opened_today.clear()
    safety._positions_opened_today.update(original_positions_opened_today)
    safety._session_start_equity = original_session_start_equity
    safety.STATE_FILE = original_state_file
