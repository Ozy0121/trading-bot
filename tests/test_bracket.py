"""
test_bracket.py
---------------
Tests for bracket order safety functions (BRACKET-01 through BRACKET-03 and SAFE-03).

Covers:
  - poll_order_fill: fill, timeout, rejection, partial fill
  - get_active_stop_loss_symbols: with and without orders, correct API call
  - place_oco_exit: correct order parameters
  - check_shutdown_stop_losses: all protected, missing
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch
import pytest

from alpaca.trading.enums import OrderStatus, QueryOrderStatus, OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import GetOrdersRequest


# ── poll_order_fill tests ─────────────────────────────────────────────────────

def test_poll_order_fill_filled(mock_trading_client):
    """Poll returns Order with FILLED status on first call."""
    from safety import poll_order_fill

    order = MagicMock()
    order.id = "order-123"
    order.status = OrderStatus.FILLED
    order.filled_qty = "10"
    order.filled_avg_price = "10.50"
    mock_trading_client.get_order_by_id.return_value = order

    result = poll_order_fill(mock_trading_client, "order-123", timeout=1.0)

    assert result.status == OrderStatus.FILLED
    assert result.filled_qty == "10"
    assert result.filled_avg_price == "10.50"


def test_poll_order_fill_timeout(mock_trading_client):
    """Poll returns last Order with NEW status after timeout expires."""
    from safety import poll_order_fill

    order = MagicMock()
    order.id = "order-123"
    order.status = OrderStatus.NEW
    mock_trading_client.get_order_by_id.return_value = order

    result = poll_order_fill(mock_trading_client, "order-123", timeout=0.2, poll_interval=0.1)

    assert result.status == OrderStatus.NEW
    assert mock_trading_client.get_order_by_id.call_count >= 1


def test_poll_order_fill_rejected(mock_trading_client):
    """Poll returns Order with REJECTED status immediately on rejection."""
    from safety import poll_order_fill

    order = MagicMock()
    order.id = "order-456"
    order.status = OrderStatus.REJECTED
    mock_trading_client.get_order_by_id.return_value = order

    result = poll_order_fill(mock_trading_client, "order-456", timeout=1.0)

    assert result.status == OrderStatus.REJECTED


def test_poll_order_fill_partial(mock_trading_client):
    """Poll returns Order with PARTIALLY_FILLED status and correct filled_qty."""
    from safety import poll_order_fill

    order = MagicMock()
    order.id = "order-789"
    order.status = OrderStatus.PARTIALLY_FILLED
    order.filled_qty = "6"
    mock_trading_client.get_order_by_id.return_value = order

    result = poll_order_fill(mock_trading_client, "order-789", timeout=1.0)

    assert result.status == OrderStatus.PARTIALLY_FILLED
    assert result.filled_qty == "6"


# ── get_active_stop_loss_symbols tests ────────────────────────────────────────

def test_get_active_stop_loss_symbols(mock_trading_client):
    """Returns {'SOFI'} when there is a HELD stop-loss leg for SOFI."""
    from safety import get_active_stop_loss_symbols

    leg = MagicMock()
    leg.stop_price = 9.70
    leg.status = OrderStatus.HELD

    parent = MagicMock()
    parent.symbol = "SOFI"
    parent.legs = [leg]

    mock_trading_client.get_orders.return_value = [parent]

    result = get_active_stop_loss_symbols(mock_trading_client)

    assert result == {"SOFI"}


def test_get_active_stop_loss_symbols_empty(mock_trading_client):
    """Returns empty set when there are no orders."""
    from safety import get_active_stop_loss_symbols

    mock_trading_client.get_orders.return_value = []

    result = get_active_stop_loss_symbols(mock_trading_client)

    assert result == set()


def test_get_active_stop_loss_symbols_uses_all_status(mock_trading_client):
    """Verifies get_orders is called with QueryOrderStatus.ALL and nested=True."""
    from safety import get_active_stop_loss_symbols

    mock_trading_client.get_orders.return_value = []

    get_active_stop_loss_symbols(mock_trading_client)

    assert mock_trading_client.get_orders.called
    call_args = mock_trading_client.get_orders.call_args
    filter_arg = call_args.kwargs.get("filter") or (call_args.args[0] if call_args.args else None)
    assert filter_arg is not None
    assert filter_arg.status == QueryOrderStatus.ALL
    assert filter_arg.nested is True


# ── place_oco_exit tests ──────────────────────────────────────────────────────

def test_place_oco_exit(mock_trading_client):
    """place_oco_exit submits an OCO order with correct stop and limit prices."""
    from safety import place_oco_exit
    from alpaca.trading.requests import LimitOrderRequest, StopLossRequest, TakeProfitRequest

    place_oco_exit(mock_trading_client, "SOFI", 10, 10.0, 0.03, 0.06)

    assert mock_trading_client.submit_order.called
    submitted = mock_trading_client.submit_order.call_args.args[0]

    assert submitted.order_class == OrderClass.OCO
    assert submitted.side == OrderSide.SELL
    assert submitted.time_in_force == TimeInForce.GTC
    assert submitted.stop_loss.stop_price == 9.70
    assert submitted.take_profit.limit_price == 10.60


# ── check_shutdown_stop_losses tests ─────────────────────────────────────────

def test_check_shutdown_stop_losses_all_protected(mock_trading_client):
    """Returns all_protected=True when all positions have active stop-loss orders."""
    from safety import check_shutdown_stop_losses

    leg = MagicMock()
    leg.stop_price = 9.70
    leg.status = OrderStatus.HELD

    parent = MagicMock()
    parent.symbol = "SOFI"
    parent.legs = [leg]

    mock_trading_client.get_orders.return_value = [parent]

    pos = MagicMock()
    pos.symbol = "SOFI"
    pos.qty = "10"
    mock_trading_client.get_all_positions.return_value = [pos]

    result = check_shutdown_stop_losses(mock_trading_client)

    assert result["all_protected"] is True
    assert result["unprotected"] == []


def test_check_shutdown_stop_losses_missing(mock_trading_client):
    """Returns all_protected=False and lists unprotected symbols."""
    from safety import check_shutdown_stop_losses

    # SOFI has a stop-loss, AMD does not
    leg = MagicMock()
    leg.stop_price = 9.70
    leg.status = OrderStatus.HELD

    sofi_order = MagicMock()
    sofi_order.symbol = "SOFI"
    sofi_order.legs = [leg]

    mock_trading_client.get_orders.return_value = [sofi_order]

    sofi_pos = MagicMock()
    sofi_pos.symbol = "SOFI"
    sofi_pos.qty = "10"

    amd_pos = MagicMock()
    amd_pos.symbol = "AMD"
    amd_pos.qty = "5"

    mock_trading_client.get_all_positions.return_value = [sofi_pos, amd_pos]

    result = check_shutdown_stop_losses(mock_trading_client)

    assert result["all_protected"] is False
    assert "AMD" in result["unprotected"]
    assert "SOFI" not in result["unprotected"]


# ── place_buy bracket order tests ─────────────────────────────────────────────

def test_place_buy_uses_bracket_order(mock_trading_client):
    """place_buy submits a bracket order with correct stop-loss and take-profit."""
    import config
    import state as shared_state
    from bot import place_buy

    # Setup filled order for poll_order_fill
    filled = MagicMock()
    filled.id = "test-order-123"
    filled.status = OrderStatus.FILLED
    filled.filled_qty = "10"
    filled.filled_avg_price = "10.00"
    mock_trading_client.submit_order.return_value = filled
    mock_trading_client.get_order_by_id.return_value = filled

    result = place_buy(mock_trading_client, equity=500.0, price=10.0,
                       symbol="SOFI", consecutive_losses=0)

    assert result is True
    assert mock_trading_client.submit_order.called
    submitted = mock_trading_client.submit_order.call_args.args[0]
    assert submitted.order_class == OrderClass.BRACKET
    expected_stop = round(10.0 * (1 - config.TRAILING_STOP_PCT), 2)
    expected_profit = round(10.0 * (1 + config.TAKE_PROFIT_PCT), 2)
    assert submitted.stop_loss.stop_price == expected_stop
    assert submitted.take_profit.limit_price == expected_profit


def test_place_buy_polls_for_fill(mock_trading_client):
    """place_buy calls get_order_by_id to confirm fill after submission."""
    from bot import place_buy

    filled = MagicMock()
    filled.id = "test-order-123"
    filled.status = OrderStatus.FILLED
    filled.filled_qty = "10"
    filled.filled_avg_price = "10.00"
    mock_trading_client.submit_order.return_value = filled
    mock_trading_client.get_order_by_id.return_value = filled

    place_buy(mock_trading_client, equity=500.0, price=10.0,
              symbol="SOFI", consecutive_losses=0)

    assert mock_trading_client.get_order_by_id.call_count >= 1


def test_place_buy_handles_rejection(mock_trading_client):
    """place_buy returns False when order is REJECTED."""
    from bot import place_buy

    submitted = MagicMock()
    submitted.id = "test-order-rej"
    submitted.status = OrderStatus.NEW

    rejected = MagicMock()
    rejected.id = "test-order-rej"
    rejected.status = OrderStatus.REJECTED

    mock_trading_client.submit_order.return_value = submitted
    mock_trading_client.get_order_by_id.return_value = rejected

    result = place_buy(mock_trading_client, equity=500.0, price=10.0,
                       symbol="SOFI", consecutive_losses=0)

    assert result is False
