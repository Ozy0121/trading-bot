"""
state.py
--------
Thread-safe shared in-memory state for the bot, dashboard, and all threads.
"""

import threading
from collections import deque
from datetime import datetime

_lock = threading.Lock()
HISTORY_LIMIT = 200

_state = {
    # ── Account ──────────────────────────────────────────────────────────────
    "equity":       0.0,
    "cash":         0.0,
    "buying_power": 0.0,

    # ── Position ─────────────────────────────────────────────────────────────
    "symbol":       "—",
    "shares_held":  0.0,
    "avg_cost":     0.0,
    "position_pnl": 0.0,

    # ── Trailing stop info ────────────────────────────────────────────────────
    "peak_price":          None,   # highest price since entry
    "trailing_stop_price": None,   # level that triggers the stop

    # ── Latest signal ─────────────────────────────────────────────────────────
    "signal":    "—",
    "price":     0.0,
    "short_sma": 0.0,
    "long_sma":  0.0,

    # ── Technical indicators ──────────────────────────────────────────────────
    "rsi":        None,
    "macd":       None,
    "macd_signal":None,
    "macd_hist":  None,
    "bb_upper":   None,
    "bb_lower":   None,

    # ── Indicator chart series [{time, value}, ...] ───────────────────────────
    "_rsi_series":       [],
    "_macd_series":      [],
    "_macd_sig_series":  [],
    "_macd_hist_series": [],
    "_bb_upper_series":  [],
    "_bb_lower_series":  [],

    # ── Catalyst flags for current candidate ─────────────────────────────────
    "catalyst_ark":     False,
    "catalyst_upgrade": False,
    "volume_ratio":     1.0,

    # ── Sentiment (Fear & Greed) ──────────────────────────────────────────────
    "sentiment_bull":  50,
    "sentiment_bear":  50,
    "sentiment_total": 0,
    "sentiment_label": "—",

    # ── Watchlist scan results ────────────────────────────────────────────────
    "watchlist":      [],
    "use_top_movers": True,

    # ── News headlines ────────────────────────────────────────────────────────
    "news": [],

    # ── PDT status ───────────────────────────────────────────────────────────
    "pdt_applies":   False,
    "pdt_used":      0,
    "pdt_remaining": 3,

    # ── Open positions list ───────────────────────────────────────────────────
    "positions": [],

    # ── Bracket order info (per symbol) ──────────────────────────────────────
    "bracket_info": {},  # {symbol: {stop_loss_price, take_profit_price, status}}

    # ── Protection monitor status (from safety.py) ──────────────────────────
    "protection_status": {},  # {all_protected, unprotected, renewed, checked_at}

    # ── Bot status ────────────────────────────────────────────────────────────
    "status":               "idle",
    "paper_trading":        True,
    "session_start_equity": 0.0,
    "daily_pnl":            0.0,

    # ── Growth tracking ───────────────────────────────────────────────────────
    "account_goal":        1000.0,
    "account_start_equity": 0.0,   # set once at first start
    "total_trades":        0,
    "winning_trades":      0,
    "total_pnl":           0.0,
    "consecutive_losses":  0,
    "pnl_calendar":        {},      # {"YYYY-MM-DD": float}
    "trade_history":       [],      # [{date, symbol, pnl, entry, exit, win}]

    # ── Chart history ─────────────────────────────────────────────────────────
    "history":   deque(maxlen=HISTORY_LIMIT),

    # ── Trade log ─────────────────────────────────────────────────────────────
    "trade_log": deque(maxlen=100),

    # ── Scan results (Phase 2) ────────────────────────────────────────────────
    "scan_results":           [],    # list of candidate dicts (df stripped)
    "last_scan_time":         None,  # ISO timestamp of last scan completion
    "scan_conviction_scores": {},    # {symbol: composite_score} quick lookup
    "conviction_threshold":   0.0,  # grade cutoff from config (set on bot start)

    # ── Agent system (Phase 3) ───────────────────────────────────────────
    "agent_quant_count":  0,     # symbols analyzed by quant last cycle
    "agent_news_count":   0,     # symbols analyzed by news last cycle

    # ── Prediction engine (Phase 7) ──────────────────────────────────────
    "predictions":               [],     # list of prediction dicts (pre-spike picks)
    "prediction_count":          0,      # total predictions this cycle
    "overnight_predictions":     None,   # last overnight scan result dict
    "overnight_accuracy":        None,   # cumulative accuracy stats
    "scan_universe_size":        0,      # total stocks in expanded universe
    "scan_summary":              "",     # "Scanned 2,400 → 200 passed → Top 30"
    "heatmap_data":              [],     # market heatmap data [{symbol, price, change_pct, market_cap}]

    # ── Expanded scanner (Phase 7) ──────────────────────────────────────
    "expanded_scan_results":  [],     # list of quant-scored survivor dicts
    "expanded_scan_time":     None,   # ISO timestamp of last expanded scan
    "expanded_scan_status":   "idle", # idle | running | complete | error
    "expanded_scan_funnel":   {},     # {universe: N, t1: N, t2: N, t3: N, survivors: N}
}


def update(**kwargs) -> None:
    with _lock:
        for k, v in kwargs.items():
            if k in _state:
                _state[k] = v
            else:
                import logging
                logging.getLogger(__name__).warning("[state] Unknown key ignored: %s", k)


def push_history(time: str, price: float, short_sma: float, long_sma: float,
                 bb_upper: float = None, bb_lower: float = None,
                 open_: float = None, high: float = None, low: float = None,
                 volume: float = None) -> None:
    with _lock:
        _state["history"].append({
            "time":      time,
            "open":      round(open_,  4) if open_  is not None else round(price, 4),
            "high":      round(high,   4) if high   is not None else round(price, 4),
            "low":       round(low,    4) if low    is not None else round(price, 4),
            "price":     round(price,  4),
            "short_sma": round(short_sma, 4) if short_sma is not None else None,
            "long_sma":  round(long_sma,  4) if long_sma  is not None else None,
            "bb_upper":  round(bb_upper,  4) if bb_upper  is not None else None,
            "bb_lower":  round(bb_lower,  4) if bb_lower  is not None else None,
            "volume":    int(volume)          if volume    is not None else None,
        })


def push_trade(time: str, event: str, detail: str) -> None:
    with _lock:
        _state["trade_log"].appendleft({"time": time, "event": event, "detail": detail})


def record_trade(symbol: str, pnl: float, entry: float,
                 exit_price: float, is_win: bool) -> None:
    """Record a completed trade. Updates streaks, P&L calendar, and history."""
    today = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        _state["total_trades"] += 1
        if is_win:
            _state["winning_trades"]     += 1
            _state["consecutive_losses"]  = 0
        else:
            _state["consecutive_losses"] += 1
        _state["total_pnl"] = round(_state["total_pnl"] + pnl, 2)

        # P&L calendar
        cal = _state["pnl_calendar"]
        cal[today] = round(cal.get(today, 0.0) + pnl, 2)

        # Trade history (capped at 100)
        _state["trade_history"].append({
            "date":   today,
            "symbol": symbol,
            "pnl":    round(pnl, 2),
            "entry":  round(entry, 4),
            "exit":   round(exit_price, 4),
            "win":    is_win,
        })
        if len(_state["trade_history"]) > 100:
            _state["trade_history"] = _state["trade_history"][-100:]


def snapshot() -> dict:
    """Return a JSON-serializable copy of current state."""
    with _lock:
        s = dict(_state)
        s["history"]   = list(s["history"])
        s["trade_log"] = list(s["trade_log"])
    return s
