# Technology Stack — Options & Multi-Strategy Swing Trading

**Project:** Trading Bot v2 (milestone addition)
**Researched:** 2026-03-27
**Scope:** Libraries and patterns needed to ADD options trading and multi-strategy swing scanning to the existing Python/Alpaca bot.

---

## Summary Recommendation

No new major framework is needed. The additions are:

1. Use alpaca-py's already-available options classes (`OptionHistoricalDataClient`, `OptionOrderRequest`, `OptionDataStream`) — no additional SDK required
2. Add `pandas-ta` for extra indicators swing strategies need (ATR, ADX, Stochastic, EMA). Do NOT add TA-Lib (C compile dependency, brittle on Windows)
3. Keep yfinance for options chain data — returns full chain with IV/OI for free, no account tier requirement. Use Alpaca for execution only
4. Optionally add `scipy` later for Black-Scholes delta approximation in strike selection

---

## Core Framework — No Changes

The existing alpaca-py SDK already contains the options trading surface. `OptionHistoricalDataClient`, `OptionDataStream`, and options order requests are available in the installed version (>=0.13.0).

**Confidence: HIGH**

---

## Additions to requirements.txt

### 1. pandas-ta

| Property | Value |
|----------|-------|
| Package | `pandas-ta` |
| Version | `>=0.3.14b` |
| Purpose | ATR, ADX, Stochastic %K/%D, EMA, OBV for swing strategy scoring |
| Why | Existing `indicators.py` only has RSI, MACD, Bollinger Bands. Multi-strategy swing scanning requires ATR (volatility filter), ADX (trend strength), Stochastic (oversold signal). pandas-ta covers them with one import and uses the same pd.DataFrame interface |
| Why NOT TA-Lib | Requires compiled C extension. Windows install routinely fails without pre-built wheels |

**Confidence: HIGH**

**Usage pattern (extend existing indicators.py):**
```python
import pandas_ta as ta

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return ta.atr(df["high"], df["low"], df["close"], length=period)

def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return ta.adx(df["high"], df["low"], df["close"], length=period)["ADX_14"]

def stochastic(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    stoch = ta.stoch(df["high"], df["low"], df["close"])
    return stoch["STOCHk_14_3_3"], stoch["STOCHd_14_3_3"]
```

### 2. scipy (deferred)

| Property | Value |
|----------|-------|
| Package | `scipy` |
| Version | `>=1.11.0` |
| Purpose | Normal CDF for Black-Scholes delta approximation in strike selection |
| Deferral | First-pass strike selection should use simple OTM heuristic (5% OTM closest strike). Add scipy only when delta-based selection is needed |

**Confidence: MEDIUM**

---

## alpaca-py Options Classes — Already Available

### Options Data Client
```python
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest

option_data_client = OptionHistoricalDataClient(api_key, secret_key)
request = OptionChainRequest(
    underlying_symbol="AAPL",
    expiration_date_gte=date.today() + timedelta(days=3),
    expiration_date_lte=date.today() + timedelta(days=10),
    type="call",
)
chain = option_data_client.get_option_chain(request)
```

### Options Orders
```python
from alpaca.trading.requests import OptionOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType

order = trading_client.submit_order(
    OptionOrderRequest(
        symbol="AAPL240119C00185000",   # OCC format
        qty=1,
        side=OrderSide.BUY,
        type=OrderType.LIMIT,           # MUST use LIMIT, not MARKET
        time_in_force=TimeInForce.DAY,
        limit_price=1.50,
    )
)
```

**Safety requirement:** Always use `OrderType.LIMIT` for options orders. `OrderType.MARKET` on illiquid options can fill at extreme prices — catastrophic on a $500 account.

### OCC Symbol Construction
```python
def build_occ_symbol(underlying: str, expiry: date, call_put: str, strike: float) -> str:
    sym        = underlying.ljust(6)
    exp        = expiry.strftime("%y%m%d")
    cp         = "C" if call_put.upper() == "CALL" else "P"
    strike_int = int(round(strike * 1000))
    return f"{sym}{exp}{cp}{strike_int:08d}"
```

---

## yfinance — Options Chain Lookup (Existing Dependency, New Use)

```python
import yfinance as yf

ticker      = yf.Ticker("AAPL")
expirations = ticker.options          # tuple of "YYYY-MM-DD" strings
chain       = ticker.option_chain("2024-01-19")
calls       = chain.calls             # DataFrame: strike, bid, ask, volume, openInterest, impliedVolatility
puts        = chain.puts
```

**Why yfinance for chains, Alpaca for execution:** yfinance returns the full chain including OI, volume, and IV for free. Alpaca's chain data API may require a paid tier. Use yfinance to discover the right strike/expiry, build the OCC symbol, then submit through Alpaca.

---

## What NOT to Use

| Library | Why Not |
|---------|---------|
| TA-Lib | C extension, Windows install fragile. pandas-ta is the clean alternative |
| mibian | Unmaintained since 2016 |
| py_vollib | C extension. Overkill for simple delta approximation |
| backtrader | Full backtesting framework. Conflicts with existing polling loop architecture |
| zipline-reloaded | Too heavyweight, different execution model |
| vectorbt | Backtesting library. Fine offline, not for the live loop |
| alpaca-trade-api | OLD Alpaca SDK (v1). Deprecated. Project correctly uses alpaca-py |

---

## Updated requirements.txt (Proposed)

```
# Existing (unchanged)
alpaca-py>=0.13.0
python-dotenv>=1.0.0
numpy>=1.24.0
pandas>=2.0.0

# Implicit dependencies (already used — make explicit)
flask>=3.0.0
requests>=2.31.0
yfinance>=0.2.40
beautifulsoup4>=4.12.0

# New: swing strategy indicators
pandas-ta>=0.3.14b

# New: options strike selection (add only if delta-based selection is implemented)
# scipy>=1.11.0
```

---

## Open Questions

- **Alpaca paper account chain access:** Does the paper account return usable chain data from `OptionHistoricalDataClient`, or is yfinance the only viable source in paper mode?
- **pandas-ta maintenance status:** Verify latest version on PyPI and check for pandas 2.x compatibility issues
- **PDT and options:** Do options trades count against the PDT day-trade counter on Alpaca paper accounts? Verify before building allocation logic
