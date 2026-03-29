"""
strategies/catalyst.py
----------------------
Catalyst-driven strategy — scores stocks based on ARK buys and analyst upgrades.

STRAT-04: Use high-signal catalyst flags to boost conviction.
"""

from __future__ import annotations

import pandas as pd

from catalysts import get_catalysts
from logger_setup import get_logger

log = get_logger()

SCORE_ARK     = 5.0
SCORE_UPGRADE = 5.0


def scan(symbol: str, df: pd.DataFrame,
         catalysts: dict | None = None) -> dict:
    """
    Scan a symbol for catalyst-driven entry signal.

    Scoring:
      - ARK buying:       +5.0
      - Analyst upgrade:  +5.0
      - Both:             10.0
      - Neither:           0.0

    The `catalysts` dict can be pre-fetched to avoid redundant API calls
    when scanning a full watchlist.

    Returns dict with keys: strategy, fired, technical_score, volume_ratio, details.
    """
    _empty = {
        "strategy": "catalyst",
        "fired": False,
        "technical_score": 0.0,
        "volume_ratio": 1.0,
        "details": {},
    }

    try:
        if catalysts is None:
            catalysts = get_catalysts([symbol])

        sym_cats = catalysts.get(symbol, {})
        ark_buying       = bool(sym_cats.get("ark_buying",      False))
        analyst_upgrade  = bool(sym_cats.get("analyst_upgrade", False))
        catalyst_count   = int(sym_cats.get("catalyst_count",   0))

        tech_score = (SCORE_ARK if ark_buying else 0.0) + \
                     (SCORE_UPGRADE if analyst_upgrade else 0.0)
        fired = catalyst_count > 0

        if fired:
            log.info("[catalyst] %s: ARK=%s Upgrade=%s score=%.1f",
                     symbol, ark_buying, analyst_upgrade, tech_score)

        return {
            "strategy":        "catalyst",
            "fired":           fired,
            "technical_score": round(tech_score, 2),
            "volume_ratio":    1.0,
            "details": {
                "ark_buying":      ark_buying,
                "analyst_upgrade": analyst_upgrade,
                "catalyst_count":  catalyst_count,
            },
        }

    except Exception as exc:
        log.warning("[catalyst] %s scan error: %s", symbol, exc)
        return _empty
