"""
strategies/accumulation.py
--------------------------
Pre-spike accumulation strategy — fires when multiple prediction patterns
indicate a stock is being quietly accumulated before a move.

Unlike momentum (waits for breakout) or mean reversion (waits for oversold),
this strategy fires BEFORE the move happens, during the setup phase.

STRAT-05: Detect pre-spike accumulation setups for early entry.
"""

from __future__ import annotations

import pandas as pd

from prediction import (
    detect_keltner_squeeze,
    detect_obv_divergence,
    detect_volume_accumulation,
    detect_higher_lows,
    detect_macd_launch_zone,
    _classify_stage,
    STAGE_LABELS,
)
from logger_setup import get_logger

log = get_logger()

MIN_PATTERNS = 2  # need at least 2 patterns to fire


def scan(symbol: str, df: pd.DataFrame) -> dict:
    """
    Scan a symbol for pre-spike accumulation setup.

    Fires when at least 2 prediction patterns are active simultaneously.
    Technical score based on pattern quality and count.

    Returns dict with keys: strategy, fired, technical_score, volume_ratio, details.
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

    # Run the prediction pattern detectors (skip relative_strength — too slow for scanning)
    patterns = [
        detect_keltner_squeeze(df),
        detect_obv_divergence(df),
        detect_volume_accumulation(df),
        detect_higher_lows(df),
        detect_macd_launch_zone(df),
    ]

    active = [p for p in patterns if p.detected]
    fired = len(active) >= MIN_PATTERNS

    if not fired:
        return {
            **_empty,
            "details": {
                "patterns_detected": len(active),
                "patterns_needed": MIN_PATTERNS,
                "active_patterns": [p.name for p in active],
            },
        }

    # Technical score: average of active pattern scores + confirmation bonus
    avg_score = sum(p.score for p in active) / len(active)
    confirmation_bonus = min(2.0, (len(active) - MIN_PATTERNS) * 1.0)
    tech_score = min(10.0, avg_score + confirmation_bonus)

    # Volume ratio from the most relevant source
    vol_pattern = next((p for p in active if p.name == "volume_accumulation"), None)
    volume_ratio = vol_pattern.details.get("vol_increase_ratio", 1.0) if vol_pattern else 1.0

    stage = _classify_stage(patterns)

    log.info(
        "[accumulation] %s PRE-SPIKE: %d patterns active (%s), stage=%s, score=%.1f",
        symbol,
        len(active),
        "+".join(p.name for p in active),
        stage,
        tech_score,
    )

    return {
        "strategy": "accumulation",
        "fired": True,
        "technical_score": round(tech_score, 2),
        "volume_ratio": round(volume_ratio, 2),
        "details": {
            "patterns_detected": len(active),
            "active_patterns": [p.name for p in active],
            "pattern_scores": {p.name: p.score for p in active},
            "stage": stage,
            "stage_label": STAGE_LABELS.get(stage, ""),
        },
    }
