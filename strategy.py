import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

from signals import ATR_LEN, atr, compute_signals


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class StrategyResult:
    signal: Signal
    reason: str
    confidence: float = 0.0
    stop_distance: Optional[float] = None    # price distance below the fill (ATR based)
    target_distance: Optional[float] = None  # price distance above the fill, None = no target


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


class MACrossoverStrategy:
    """Golden/Death Cross using fast and slow moving averages."""

    def __init__(self, fast: int = 20, slow: int = 50):
        self.fast = fast
        self.slow = slow

    def analyze(self, df: pd.DataFrame) -> StrategyResult:
        if len(df) < self.slow + 1:
            return StrategyResult(Signal.HOLD, "Not enough data")

        close = df["close"]
        fast_ma = _ema(close, self.fast)
        slow_ma = _ema(close, self.slow)

        prev_fast, curr_fast = fast_ma.iloc[-2], fast_ma.iloc[-1]
        prev_slow, curr_slow = slow_ma.iloc[-2], slow_ma.iloc[-1]

        if prev_fast <= prev_slow and curr_fast > curr_slow:
            gap = (curr_fast - curr_slow) / curr_slow
            return StrategyResult(Signal.BUY, f"Golden cross (EMA{self.fast}/EMA{self.slow})", min(gap * 100, 1.0))

        if prev_fast >= prev_slow and curr_fast < curr_slow:
            gap = (curr_slow - curr_fast) / curr_slow
            return StrategyResult(Signal.SELL, f"Death cross (EMA{self.fast}/EMA{self.slow})", min(gap * 100, 1.0))

        return StrategyResult(Signal.HOLD, "No crossover detected")


class RSIStrategy:
    """RSI overbought/oversold strategy."""

    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def analyze(self, df: pd.DataFrame) -> StrategyResult:
        if len(df) < self.period + 1:
            return StrategyResult(Signal.HOLD, "Not enough data")

        rsi = _rsi(df["close"], self.period)
        curr_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-2]

        if prev_rsi <= self.oversold and curr_rsi > self.oversold:
            confidence = (self.oversold - prev_rsi) / self.oversold
            return StrategyResult(Signal.BUY, f"RSI recovery from oversold ({curr_rsi:.1f})", confidence)

        if prev_rsi >= self.overbought and curr_rsi < self.overbought:
            confidence = (prev_rsi - self.overbought) / (100 - self.overbought)
            return StrategyResult(Signal.SELL, f"RSI drop from overbought ({curr_rsi:.1f})", confidence)

        return StrategyResult(Signal.HOLD, f"RSI neutral ({curr_rsi:.1f})")


class MACDStrategy:
    """MACD histogram crossover strategy."""

    def analyze(self, df: pd.DataFrame) -> StrategyResult:
        if len(df) < 35:
            return StrategyResult(Signal.HOLD, "Not enough data")

        _, _, histogram = _macd(df["close"])
        prev_hist = histogram.iloc[-2]
        curr_hist = histogram.iloc[-1]

        if prev_hist < 0 and curr_hist >= 0:
            return StrategyResult(Signal.BUY, f"MACD histogram turned positive ({curr_hist:.6f})", abs(curr_hist))

        if prev_hist > 0 and curr_hist <= 0:
            return StrategyResult(Signal.SELL, f"MACD histogram turned negative ({curr_hist:.6f})", abs(curr_hist))

        return StrategyResult(Signal.HOLD, f"MACD histogram unchanged ({curr_hist:.6f})")


class OptimizedStrategy:
    """Runs the strategy + parameters selected by optimize.py (walk-forward validated).

    If no strategy passed the out-of-sample quality gates, best_params.json says so
    and this strategy always returns HOLD - i.e. the bot stays out of the market.
    """

    def __init__(self, path: str):
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"{path} not found. Run `python optimize.py` first (needs exchange data).")
        cfg = json.load(open(path))
        self.name = cfg.get("strategy")
        self.params = cfg.get("params", {})
        self.note = cfg.get("note", "no optimized strategy")

    def analyze(self, df: pd.DataFrame) -> StrategyResult:
        if not self.name:
            return StrategyResult(Signal.HOLD, self.note)
        entry, exit_ = compute_signals(self.name, df, self.params)
        a = atr(df, ATR_LEN).iloc[-1]
        if entry.iloc[-1] and a == a and a > 0:
            tp = self.params.get("tp_atr") or 0
            return StrategyResult(Signal.BUY, f"{self.name} entry {self.params}",
                                  stop_distance=self.params["sl_atr"] * a,
                                  target_distance=tp * a if tp else None)
        if exit_.iloc[-1]:
            return StrategyResult(Signal.SELL, f"{self.name} exit signal")
        return StrategyResult(Signal.HOLD, f"{self.name}: no signal")


def get_strategy(name: str, params_file: str = "best_params.json"):
    if name == "OPTIMIZED":
        return OptimizedStrategy(params_file)
    strategies = {
        "MA_CROSSOVER": MACrossoverStrategy(),
        "RSI": RSIStrategy(),
        "MACD": MACDStrategy(),
    }
    if name not in strategies:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(strategies) + ['OPTIMIZED']}")
    return strategies[name]
