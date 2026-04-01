"""
config.py
---------
Loads all configuration from the .env file and validates it.
"""

import os
from dotenv import load_dotenv

load_dotenv(override=False)   # fallback; server.py loads the correct .env first


def _require(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val or val.startswith("YOUR_"):
        raise ValueError(
            f"[config] '{key}' is not set in your .env file. "
            "Please add your real Alpaca credentials before running the bot."
        )
    return val


def _float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        raise ValueError(f"[config] '{key}' must be a number.")


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        raise ValueError(f"[config] '{key}' must be an integer.")


# ── Alpaca credentials ───────────────────────────────────────────────────────
API_KEY    = _require("ALPACA_API_KEY")
SECRET_KEY = _require("ALPACA_SECRET_KEY")

# ── Paper vs live trading ────────────────────────────────────────────────────
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").strip().lower() == "true"

# ── Trading parameters ───────────────────────────────────────────────────────
SYMBOL = os.getenv("SYMBOL", "SOFI").upper().strip()

# Mixed watchlist: large-cap momentum + high-vol smaller stocks
_watchlist_raw = os.getenv(
    "WATCHLIST",
    "NVDA,AMD,TSLA,META,MSFT,PLTR,COIN,SOFI,HOOD,RIVN,SNAP,MARA,NIO,F"
)
WATCHLIST     = [s.strip().upper() for s in _watchlist_raw.split(",") if s.strip()]
SHORT_WINDOW  = _int("SHORT_WINDOW", 9)
LONG_WINDOW   = _int("LONG_WINDOW", 21)
BAR_TIMEFRAME = os.getenv("BAR_TIMEFRAME", "5Min").strip()
LOOKBACK_BARS = _int("LOOKBACK_BARS", 50)
POLL_INTERVAL = _int("POLL_INTERVAL_SECONDS", 60)

# ── Safety limits ────────────────────────────────────────────────────────────
MAX_POSITION_VALUE    = _float("MAX_POSITION_VALUE",    200.0)  # $200 max per trade
MAX_POSITION_FRACTION = _float("MAX_POSITION_FRACTION",  0.05)  # 5% of equity
DAILY_LOSS_LIMIT      = _float("DAILY_LOSS_LIMIT",       50.0)

# ── Per-trade exit rules ──────────────────────────────────────────────────────
# Trailing stop: exit when price falls this % from its peak since entry
TRAILING_STOP_PCT = _float("TRAILING_STOP_PCT", 0.03)   # 3% trailing stop

# Take profit: exit at this gain % (0 = disabled, let trailing stop run)
TAKE_PROFIT_PCT   = _float("TAKE_PROFIT_PCT",   0.06)   # 6% take profit

# Legacy fixed stop-loss (kept for kill-switch fallback, trailing stop is primary)
STOP_LOSS_PCT = _float("STOP_LOSS_PCT", 0.0)

# ── High-conviction entry filters ────────────────────────────────────────────
# ALL FOUR must be true before entering a trade:
#   1. SMA crossover (BUY signal)
#   2. RSI < MAX_RSI_BUY
#   3. Volume ratio >= MIN_VOLUME_RATIO (vs 20-bar average)
#   4. MACD histogram > 0
MAX_RSI_BUY       = _float("MAX_RSI_BUY",       65.0)   # RSI must be under this to buy
MIN_VOLUME_RATIO  = _float("MIN_VOLUME_RATIO",   2.0)    # volume must be 2x avg

# ── Top movers / watchlist mode ──────────────────────────────────────────────
USE_TOP_MOVERS   = os.getenv("USE_TOP_MOVERS", "true").strip().lower() == "true"
TOP_MOVERS_COUNT = _int("TOP_MOVERS_COUNT", 15)

# Price and volume filters for top-movers screener
# No upper price cap — allow NVDA ($130+), AMD ($160+), etc.
MIN_PRICE  = _float("MIN_PRICE",    5.00)       # skip sub-$5 stocks (too risky)
MAX_PRICE  = _float("MAX_PRICE",  500.00)       # allow large-caps
MIN_VOLUME = _int("MIN_VOLUME", 1_000_000)      # minimum daily volume for liquidity

# ── Account growth goal ───────────────────────────────────────────────────────
ACCOUNT_GOAL = _float("ACCOUNT_GOAL", 1000.0)

# ── Losing streak protection ──────────────────────────────────────────────────
# After this many consecutive losses, cut position size in half
LOSING_STREAK_THRESHOLD  = _int("LOSING_STREAK_THRESHOLD",   3)
LOSING_STREAK_SIZE_FACTOR = _float("LOSING_STREAK_SIZE_FACTOR", 0.5)

# ── Dashboard ────────────────────────────────────────────────────────────────
DASHBOARD_PORT = _int("DASHBOARD_PORT", 5000)

# ── State persistence ────────────────────────────────────────────────────────
STATE_FILE_PATH = os.getenv("STATE_FILE_PATH",
    os.path.join(os.path.dirname(__file__), "data", "bot_state.json"))

# ── Order fill polling ───────────────────────────────────────────────────────
ORDER_FILL_TIMEOUT       = _float("ORDER_FILL_TIMEOUT",       10.0)   # seconds
ORDER_FILL_POLL_INTERVAL = _float("ORDER_FILL_POLL_INTERVAL",  0.5)   # seconds

if SHORT_WINDOW >= LONG_WINDOW:
    raise ValueError(
        f"[config] SHORT_WINDOW ({SHORT_WINDOW}) must be less than "
        f"LONG_WINDOW ({LONG_WINDOW})."
    )

# ── Multi-strategy conviction scoring (D-03, D-04) ───────────────────────────
CONVICTION_THRESHOLD        = _float("CONVICTION_THRESHOLD",        5.8)
CONVICTION_WEIGHT_TECHNICAL = _float("CONVICTION_WEIGHT_TECHNICAL", 0.40)
CONVICTION_WEIGHT_VOLUME    = _float("CONVICTION_WEIGHT_VOLUME",    0.20)
CONVICTION_WEIGHT_SENTIMENT = _float("CONVICTION_WEIGHT_SENTIMENT", 0.20)
CONVICTION_WEIGHT_SECTOR    = _float("CONVICTION_WEIGHT_SECTOR",    0.20)

_weight_sum = (CONVICTION_WEIGHT_TECHNICAL + CONVICTION_WEIGHT_VOLUME +
               CONVICTION_WEIGHT_SENTIMENT + CONVICTION_WEIGHT_SECTOR)
if abs(_weight_sum - 1.0) > 0.001:
    raise ValueError(f"[config] Conviction weights must sum to 1.0, got {_weight_sum:.3f}")

# ── Market regime filter (D-19) ───────────────────────────────────────────────
MARKET_REGIME_ETF          = os.getenv("MARKET_REGIME_ETF", "SPY").strip().upper()
MARKET_REGIME_BEARISH_MULT = _float("MARKET_REGIME_BEARISH_MULT", 0.7)

# ── Swing watchlist (D-15 updated: 50-75 stocks, all GICS sectors) ───────────
_swing_raw = os.getenv(
    "SWING_WATCHLIST",
    # Technology (12)
    "NVDA,AMD,MSFT,AAPL,GOOGL,META,AVGO,CRM,ADBE,ORCL,PLTR,CRWD,"
    # Consumer Discretionary (8)
    "TSLA,AMZN,NFLX,SHOP,UBER,DKNG,RBLX,NKE,"
    # Communication Services (4)
    "DIS,SNAP,PINS,ROKU,"
    # Financials (6)
    "COIN,SOFI,HOOD,JPM,GS,V,"
    # Healthcare (5)
    "UNH,JNJ,PFE,MRNA,ABBV,"
    # Energy (4)
    "XOM,CVX,OXY,FSLR,"
    # Industrials (5)
    "CAT,DE,BA,LMT,GE,"
    # Consumer Staples (3)
    "COST,WMT,PG,"
    # Materials (3)
    "FCX,NEM,LIN,"
    # Real Estate (3)
    "AMT,PLD,O,"
    # Utilities (2)
    "NEE,DUK,"
    # High-momentum mid-caps (5)
    "MARA,RIVN,NIO,F,LYFT"
)
SWING_WATCHLIST = [s.strip().upper() for s in _swing_raw.split(",") if s.strip()]

# ── Anthropic API (for Strategist and Auditor agents) ───────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
STRATEGIST_MODEL  = os.getenv("STRATEGIST_MODEL", "claude-sonnet-4-6")
AUDITOR_MODEL     = os.getenv("AUDITOR_MODEL", "claude-opus-4-6")
