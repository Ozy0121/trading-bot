"""Quick diagnostic: where are predictions being filtered out?"""
import sys, os
os.environ.setdefault("PYTHONUTF8", "1")
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(".env.paper")

from prediction import predict, _detect_rsi2, _detect_ibs, _detect_consec_down, _detect_bb_touch, _passes_regime_filter
from data_provider import fetch_bulk_bars

symbols = [
    "AAPL","MSFT","NVDA","TSLA","AMD","META","AMZN","GOOG","NFLX","SOFI",
    "PLTR","RIVN","NIO","BABA","JD","SNAP","COIN","HOOD","MARA","RIOT",
    "SQ","PYPL","DIS","BA","F","GM","AAL","DAL","UAL","CCL",
    "INTC","MU","QCOM","AVGO","CRM","ORCL","NOW","SNOW","DDOG","NET",
    "SHOP","SE","MELI","GRAB","NU","ROKU","PINS","SPOT","UBER","LYFT"
]

print(f"Fetching bars for {len(symbols)} symbols...")
bars = fetch_bulk_bars(symbols, period="60d", interval="1d")
print(f"Got bars for {len(bars)} symbols\n")

spy_bars = bars.get("SPY")

stats = {"no_data": 0, "0_signals": 0, "1_signal": 0, "2+_signals": 0, "regime_fail": 0, "passed_regime": 0}
details = []

for sym in symbols:
    df = bars.get(sym)
    if df is None or len(df) < 35:
        stats["no_data"] += 1
        continue

    rsi2 = _detect_rsi2(df)
    ibs = _detect_ibs(df)
    consec = _detect_consec_down(df)
    bb = _detect_bb_touch(df)

    active = [p for p in [rsi2, ibs, consec, bb] if p.detected]
    count = len(active)
    names = [p.name for p in active]

    if count == 0:
        stats["0_signals"] += 1
    elif count == 1:
        stats["1_signal"] += 1
        details.append(f"  {sym}: 1 signal ({names[0]})")
    else:
        stats["2+_signals"] += 1
        passes, reason, mult = _passes_regime_filter(df, spy_bars)
        if passes:
            stats["passed_regime"] += 1
            details.append(f"  {sym}: {count} signals ({', '.join(names)}) -> PASSED REGIME")
        else:
            stats["regime_fail"] += 1
            details.append(f"  {sym}: {count} signals ({', '.join(names)}) -> regime FAIL: {reason}")

print("=== FILTER BREAKDOWN ===")
print(f"No data:     {stats['no_data']}")
print(f"0 signals:   {stats['0_signals']}")
print(f"1 signal:    {stats['1_signal']}")
print(f"2+ signals:  {stats['2+_signals']}")
print(f"  Regime OK: {stats['passed_regime']}")
print(f"  Regime fail: {stats['regime_fail']}")
print()
print("=== DETAILS ===")
for d in details:
    print(d)
