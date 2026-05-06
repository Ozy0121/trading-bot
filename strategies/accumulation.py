"""
strategies/accumulation.py
--------------------------
Pre-spike accumulation strategy — fires when Volume Profile, Order Flow,
and AMT signals indicate a stock is being quietly accumulated before a move.

Uses the same VP/CVD/AMT signal generators as prediction.py but with
a simpler threshold (any 2 of 3 signals active = fire).
"""

from __future__ import annotations

import pandas as pd

from volume_profile import score_volume_profile
from order_flow import score_order_flow
from amt_engine import score_amt
from prediction import STAGE_LABELS
from logger_setup import get_logger

log = get_logger()

MIN_SIGNALS = 2
VP_THRESHOLD = 5.0
CVD_THRESHOLD = 5.5
AMT_THRESHOLD = 5.0


def scan(symbol: str, df: pd.DataFrame) -> dict:
    """Scan a symbol for pre-spike accumulation setup.

    Fires when at least 2 of 3 signals (VP, CVD, AMT) are active.
    """
    _empty = {
        "strategy": "accumulation",
        "fired": False,
        "technical_score": 0.0,
        "volume_ratio": 1.0,
        "details": {},
    }

    if df is None or len(df) < 35:
        return _empty

    vp = score_volume_profile(df)
    of = score_order_flow(df)
    amt = score_amt(df)

    active = []
    if vp["score"] >= VP_THRESHOLD:
        active.append(("volume_profile", vp["score"]))
    if of["score"] >= CVD_THRESHOLD:
        active.append(("order_flow", of["score"]))
    if amt["score"] >= AMT_THRESHOLD:
        active.append(("amt_state", amt["score"]))

    fired = len(active) >= MIN_SIGNALS

    if not fired:
        return {
            **_empty,
            "details": {
                "signals_detected": len(active),
                "signals_needed": MIN_SIGNALS,
                "active_signals": [a[0] for a in active],
            },
        }

    avg_score = sum(s for _, s in active) / len(active)
    confirmation_bonus = min(2.0, (len(active) - MIN_SIGNALS) * 1.0)
    tech_score = min(10.0, avg_score + confirmation_bonus)

    # Derive stage from AMT state
    amt_state = amt.get("state", "balanced")
    if amt_state == "imbalanced_up" and len(active) == 3:
        stage = "launch_zone"
    elif amt_state in ("imbalanced_up", "testing_low") and len(active) >= 2:
        stage = "pre_breakout"
    elif len(active) >= 2:
        stage = "accumulation"
    else:
        stage = "early_accumulation"

    log.info(
        "[accumulation] %s PRE-SPIKE: %d signals active (%s), stage=%s, score=%.1f",
        symbol,
        len(active),
        "+".join(a[0] for a in active),
        stage,
        tech_score,
    )

    return {
        "strategy": "accumulation",
        "fired": True,
        "technical_score": round(tech_score, 2),
        "volume_ratio": 1.0,
        "details": {
            "signals_detected": len(active),
            "active_signals": [a[0] for a in active],
            "signal_scores": {a[0]: a[1] for a in active},
            "stage": stage,
            "stage_label": STAGE_LABELS.get(stage, ""),
            "vp_position": vp.get("position", "unknown"),
            "cvd_trend": of.get("cvd_trend", "neutral"),
            "amt_state": amt_state,
        },
    }
