"""
kill_switch.py
--------------
Standalone emergency script. Run this any time — even while bot.py is running —
to immediately:
  1. Cancel ALL open orders for the configured symbol.
  2. Market-sell the entire position.

Usage:
    python kill_switch.py

You will be asked to confirm before anything executes.
This script uses the same credentials and symbol from your .env file.
"""

import sys

from alpaca.trading.client import TradingClient

import config
from logger_setup import get_logger
from safety import kill_switch

log = get_logger()


def main():
    print()
    print("=" * 60)
    print("  !! KILL SWITCH — EMERGENCY LIQUIDATION !!")
    print("=" * 60)
    print(f"  Symbol : {config.SYMBOL}")
    print(f"  This will CANCEL all open orders and SELL all shares.")
    print("=" * 60)
    print()
    print("Type  YES  (all caps) to proceed, anything else to abort.")
    print()

    answer = input("> ").strip()
    if answer != "YES":
        print("Aborted. No changes made.")
        sys.exit(0)

    trading_client = TradingClient(
        api_key=config.API_KEY,
        secret_key=config.SECRET_KEY,
        paper=False,  # LIVE
    )

    kill_switch(trading_client)
    print()
    print("Kill switch executed. Check the logs/ folder for details.")


if __name__ == "__main__":
    main()
