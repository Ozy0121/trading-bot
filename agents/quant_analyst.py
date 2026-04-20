"""
Agent 1 — The Quant Analyst.

Crunches all the numbers. Wraps indicators.py and scanner.py, adds new
indicators (Stochastic RSI, ATR, Beta, ROC, MFI, OBV, VWAP, %B) and
analytics (volatility, probability estimates, EV, Sharpe, Sortino).

Input: {"symbols": list[str]}
Output: {"outputs": list[QuantOutput]} sorted by composite_score descending
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from agents.base import BaseAgent, QuantOutput
from agents.event_bus import EventBus
from indicators import rsi as calc_rsi, macd as calc_macd, bollinger_bands
from scanner import fetch_bars_yf, scan
from sentiment_cache import get_sentiment_score
from logger_setup import get_logger

log = get_logger()


class QuantAnalyst(BaseAgent):
    name = "quant_analyst"

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__(event_bus)

    def _execute(self, input_data: dict) -> dict:
        symbols = input_data.get("symbols", [])
        if not symbols:
            return {"outputs": []}

        bars_by_symbol = self._fetch_bars(symbols)
        spy_bars = self._fetch_spy_bars()

        outputs = []
        for symbol in symbols:
            bars = bars_by_symbol.get(symbol)
            if bars is None or len(bars) < 30:
                continue
            try:
                q = self._analyze_symbol(symbol, bars, spy_bars)
                outputs.append(q)
            except Exception as exc:
                log.warning("[quant_analyst] Error analyzing %s: %s", symbol, exc)

        outputs.sort(key=lambda o: o.composite_score, reverse=True)
        return {"outputs": outputs}

    def _summarize_output(self) -> str:
        outputs = self.last_output.get("outputs", [])
        if not outputs:
            return "No data yet"
        top = outputs[0]
        return f"Analyzed {len(outputs)} symbols — top: {top.symbol} ({top.composite_score:.0f})"

    def _fetch_bars(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV bars for all symbols. Uses yfinance via scanner."""
        result = {}
        for sym in symbols:
            try:
                df = fetch_bars_yf(sym)
                if df is not None and len(df) > 0:
                    result[sym] = df
            except Exception as exc:
                log.warning("[quant_analyst] Failed to fetch bars for %s: %s", sym, exc)
        return result

    def _fetch_spy_bars(self) -> pd.DataFrame | None:
        """Fetch SPY bars for beta calculation."""
        try:
            return fetch_bars_yf("SPY")
        except Exception:
            return None

    def _analyze_symbol(self, symbol: str, bars: pd.DataFrame,
                        spy_bars: pd.DataFrame | None) -> QuantOutput:
        """Compute all indicators and score for one symbol."""
        closes = bars["close"]
        highs = bars["high"]
        lows = bars["low"]
        volumes = bars["volume"]

        # ── Existing indicators ─────────────────────────────────────────
        rsi_series = calc_rsi(closes)
        rsi_val = float(rsi_series.dropna().iloc[-1]) if len(rsi_series.dropna()) > 0 else 50.0
        macd_line, sig_line, hist = calc_macd(closes)
        macd_val = float(macd_line.dropna().iloc[-1]) if len(macd_line.dropna()) > 0 else 0.0
        macd_hist_val = float(hist.dropna().iloc[-1]) if len(hist.dropna()) > 0 else 0.0
        macd_sig = "bullish" if macd_hist_val > 0 else "bearish" if macd_hist_val < 0 else "neutral"
        bb_upper, bb_mid, bb_lower = bollinger_bands(closes)
        bb_u = float(bb_upper.dropna().iloc[-1]) if len(bb_upper.dropna()) > 0 else closes.iloc[-1]
        bb_l = float(bb_lower.dropna().iloc[-1]) if len(bb_lower.dropna()) > 0 else closes.iloc[-1]

        short_sma = float(closes.rolling(9).mean().iloc[-1])
        long_sma = float(closes.rolling(21).mean().iloc[-1])

        # Volume ratio
        avg_vol = float(volumes.rolling(20).mean().iloc[-1]) if len(volumes) >= 20 else float(volumes.mean())
        vol_ratio = float(volumes.iloc[-1]) / avg_vol if avg_vol > 0 else 1.0

        # ── New indicators ──────────────────────────────────────────────
        atr = self._calc_atr(highs, lows, closes)
        stoch_rsi = self._calc_stochastic_rsi(rsi_series)
        beta = self._calc_beta(closes, spy_bars)
        roc = self._calc_rate_of_change(closes)
        mfi = self._calc_mfi(highs, lows, closes, volumes)
        obv = self._calc_obv(closes, volumes)
        vwap = self._calc_vwap(highs, lows, closes, volumes)
        pct_b = self._calc_bollinger_pct_b(closes, bb_upper, bb_lower)
        vol_20d = self._calc_volatility(closes, 20)
        vol_60d = self._calc_volatility(closes, 60)
        prob_3pct_3d = self._calc_move_probability(closes, pct=3.0, days=3)
        ev = self._calc_expected_value(closes, atr)
        sharpe = self._calc_sharpe(closes)
        sortino = self._calc_sortino(closes)

        # ── Scoring ─────────────────────────────────────────────────────
        tech_score = self._compute_technical_score(rsi_val, macd_hist_val, short_sma, long_sma, stoch_rsi, pct_b)
        vol_score = min(vol_ratio / 2.0, 1.0) * 10.0
        sent_score = get_sentiment_score(symbol)
        sector_score = 5.0  # default; coordinator can override from sector scan

        composite = (tech_score * 0.40 + vol_score * 0.20 +
                     sent_score * 0.20 + sector_score * 0.20)

        return QuantOutput(
            symbol=symbol, composite_score=round(composite, 2),
            rsi=round(rsi_val, 2), macd_signal=macd_sig,
            atr=round(atr, 4), beta=round(beta, 2),
            volatility_20d=round(vol_20d, 4), volatility_60d=round(vol_60d, 4),
            stochastic_rsi=round(stoch_rsi, 4), rate_of_change=round(roc, 4),
            money_flow_index=round(mfi, 2), on_balance_volume=round(obv, 0),
            vwap=round(vwap, 4), bollinger_pct_b=round(pct_b, 4),
            probability_3pct_3d=round(prob_3pct_3d, 4),
            expected_value=round(ev, 4),
            sharpe_ratio=round(sharpe, 4), sortino_ratio=round(sortino, 4),
            short_sma=round(short_sma, 4), long_sma=round(long_sma, 4),
            bb_upper=round(bb_u, 4), bb_lower=round(bb_l, 4),
            macd_value=round(macd_val, 4), macd_hist=round(macd_hist_val, 4),
            volume_ratio=round(vol_ratio, 2),
            sector_score=round(sector_score, 2),
            sentiment_score=round(sent_score, 2),
            technical_score=round(tech_score, 2),
        )

    # ── New indicator calculations ──────────────────────────────────────────

    def _calc_atr(self, highs: pd.Series, lows: pd.Series,
                  closes: pd.Series, period: int = 14) -> float:
        """Average True Range."""
        prev_close = closes.shift(1)
        tr = pd.concat([
            highs - lows,
            (highs - prev_close).abs(),
            (lows - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        val = atr.dropna()
        return float(val.iloc[-1]) if len(val) > 0 else 0.0

    def _calc_stochastic_rsi(self, rsi_series: pd.Series, period: int = 14) -> float:
        """Stochastic RSI: (RSI - min) / (max - min) over period."""
        rsi_clean = rsi_series.dropna()
        if len(rsi_clean) < period:
            return 0.5
        rsi_min = rsi_clean.rolling(period).min()
        rsi_max = rsi_clean.rolling(period).max()
        denom = rsi_max - rsi_min
        stoch = (rsi_clean - rsi_min) / denom.replace(0, np.nan)
        val = stoch.dropna()
        return float(val.iloc[-1]) if len(val) > 0 else 0.5

    def _calc_beta(self, closes: pd.Series,
                   spy_bars: pd.DataFrame | None, period: int = 60) -> float:
        """Beta relative to SPY."""
        if spy_bars is None or len(spy_bars) < period:
            return 1.0
        stock_ret = closes.pct_change().dropna().tail(period)
        spy_ret = spy_bars["close"].pct_change().dropna().tail(period)
        if len(stock_ret) < 20 or len(spy_ret) < 20:
            return 1.0
        min_len = min(len(stock_ret), len(spy_ret))
        stock_ret = stock_ret.iloc[-min_len:]
        spy_ret = spy_ret.iloc[-min_len:]
        cov = np.cov(stock_ret.values, spy_ret.values)
        if cov[1, 1] == 0:
            return 1.0
        return float(cov[0, 1] / cov[1, 1])

    def _calc_rate_of_change(self, closes: pd.Series, period: int = 12) -> float:
        """Rate of Change: (close - close_n_ago) / close_n_ago * 100."""
        if len(closes) < period + 1:
            return 0.0
        current = float(closes.iloc[-1])
        past = float(closes.iloc[-period - 1])
        return ((current - past) / past * 100) if past != 0 else 0.0

    def _calc_mfi(self, highs: pd.Series, lows: pd.Series,
                  closes: pd.Series, volumes: pd.Series, period: int = 14) -> float:
        """Money Flow Index."""
        typical = (highs + lows + closes) / 3
        money_flow = typical * volumes
        delta = typical.diff()
        pos_flow = (money_flow * (delta > 0)).rolling(period).sum()
        neg_flow = (money_flow * (delta < 0)).rolling(period).sum().abs()
        ratio = pos_flow / neg_flow.replace(0, np.nan)
        mfi = 100 - (100 / (1 + ratio))
        val = mfi.dropna()
        return float(val.iloc[-1]) if len(val) > 0 else 50.0

    def _calc_obv(self, closes: pd.Series, volumes: pd.Series) -> float:
        """On-Balance Volume."""
        direction = np.sign(closes.diff()).fillna(0)
        obv = (direction * volumes).cumsum()
        return float(obv.iloc[-1]) if len(obv) > 0 else 0.0

    def _calc_vwap(self, highs: pd.Series, lows: pd.Series,
                   closes: pd.Series, volumes: pd.Series) -> float:
        """Volume Weighted Average Price (intraday approximation)."""
        typical = (highs + lows + closes) / 3
        cum_tp_vol = (typical * volumes).cumsum()
        cum_vol = volumes.cumsum()
        vwap = cum_tp_vol / cum_vol.replace(0, np.nan)
        val = vwap.dropna()
        return float(val.iloc[-1]) if len(val) > 0 else float(closes.iloc[-1])

    def _calc_bollinger_pct_b(self, closes: pd.Series,
                              bb_upper: pd.Series, bb_lower: pd.Series) -> float:
        """%B = (close - lower) / (upper - lower)."""
        width = bb_upper - bb_lower
        pct_b = (closes - bb_lower) / width.replace(0, np.nan)
        val = pct_b.dropna()
        return float(val.iloc[-1]) if len(val) > 0 else 0.5

    def _calc_volatility(self, closes: pd.Series, window: int) -> float:
        """Annualized historical volatility over window days."""
        if len(closes) < window + 1:
            return 0.0
        returns = closes.pct_change().dropna().tail(window)
        return float(returns.std() * np.sqrt(252))

    def _calc_move_probability(self, closes: pd.Series,
                               pct: float = 3.0, days: int = 3) -> float:
        """Historical probability of >= pct% move in next N days."""
        if len(closes) < days + 30:
            return 0.0
        returns = closes.pct_change(periods=days).dropna() * 100
        big_moves = (returns.abs() >= pct).sum()
        return float(big_moves / len(returns))

    def _calc_expected_value(self, closes: pd.Series, atr: float) -> float:
        """Simple EV estimate: avg_win * P(win) - avg_loss * P(loss) based on recent bars."""
        if len(closes) < 20 or atr == 0:
            return 0.0
        returns = closes.pct_change().dropna().tail(60)
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        if len(wins) == 0 or len(losses) == 0:
            return 0.0
        p_win = len(wins) / len(returns)
        avg_win = float(wins.mean())
        avg_loss = float(losses.mean())
        return avg_win * p_win + avg_loss * (1 - p_win)

    def _calc_sharpe(self, closes: pd.Series, window: int = 60) -> float:
        """Sharpe ratio over window (assumes risk-free rate 0 for simplicity)."""
        if len(closes) < window + 1:
            return 0.0
        returns = closes.pct_change().dropna().tail(window)
        mean_ret = float(returns.mean())
        std_ret = float(returns.std())
        if std_ret == 0:
            return 0.0
        return (mean_ret / std_ret) * np.sqrt(252)

    def _calc_sortino(self, closes: pd.Series, window: int = 60) -> float:
        """Sortino ratio (downside deviation only)."""
        if len(closes) < window + 1:
            return 0.0
        returns = closes.pct_change().dropna().tail(window)
        mean_ret = float(returns.mean())
        downside = returns[returns < 0]
        if len(downside) == 0:
            return 0.0
        down_std = float(downside.std())
        if down_std == 0:
            return 0.0
        return (mean_ret / down_std) * np.sqrt(252)

    def _compute_technical_score(self, rsi: float, macd_hist: float,
                                 short_sma: float, long_sma: float,
                                 stoch_rsi: float, pct_b: float) -> float:
        """Compute a 0-10 technical score from multiple indicators."""
        score = 0.0

        # RSI in buy zone (30-50) = best, (20-30 or 50-65) = ok
        if 30 <= rsi <= 50:
            score += 3.0
        elif 20 <= rsi < 30 or 50 < rsi <= 65:
            score += 1.5

        # MACD histogram positive = bullish
        if macd_hist > 0:
            score += 2.0
        elif macd_hist > -0.1:
            score += 0.5

        # SMA crossover (short above long = bullish)
        if short_sma > long_sma:
            score += 2.0

        # Stochastic RSI in oversold zone (< 0.2) = potential bounce
        if stoch_rsi < 0.2:
            score += 1.5
        elif stoch_rsi < 0.4:
            score += 0.5

        # Bollinger %B near lower band = potential bounce
        if pct_b < 0.2:
            score += 1.5
        elif pct_b < 0.4:
            score += 0.5

        return min(score, 10.0)
