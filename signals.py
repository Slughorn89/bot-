"""Shared, causal signal logic used by BOTH the backtester and the live bot.

Every function only looks at past/current bars (no look-ahead). A signal on bar
`i` is computed from the close of bar `i`; the trade executes at the open of
bar `i+1`.
"""
from itertools import product
from typing import Callable, Dict, List, Tuple

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    out = 100 - 100 / (1 + au / ad.replace(0, np.nan))
    out[(ad == 0) & au.notna()] = 100.0
    return out


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def _trend_ok(df: pd.DataFrame, trend: int) -> pd.Series:
    if not trend:
        return pd.Series(True, index=df.index)
    return df["close"] > ema(df["close"], trend)


def ema_trend(df: pd.DataFrame, fast: int, slow: int, trend: int) -> Tuple[pd.Series, pd.Series]:
    f, s = ema(df["close"], fast), ema(df["close"], slow)
    cross_up = (f > s) & (f.shift(1) <= s.shift(1))
    cross_dn = (f < s) & (f.shift(1) >= s.shift(1))
    return cross_up & _trend_ok(df, trend), cross_dn


def rsi_revert(df: pd.DataFrame, rsi_len: int, buy_below: float,
               exit_above: float, trend: int) -> Tuple[pd.Series, pd.Series]:
    r = rsi(df["close"], rsi_len)
    entry = (r < buy_below) & (r.shift(1) >= buy_below)
    return entry & _trend_ok(df, trend), r > exit_above


def donchian(df: pd.DataFrame, entry_n: int, exit_n: int) -> Tuple[pd.Series, pd.Series]:
    hi = df["high"].rolling(entry_n).max().shift(1)
    lo = df["low"].rolling(exit_n).min().shift(1)
    return df["close"] > hi, df["close"] < lo


# name -> (function, parameter grid). Exit-management params (sl_atr, tp_atr,
# atr_len) are handled by the engine, not by the signal function.
STRATEGIES: Dict[str, Tuple[Callable, Dict[str, list]]] = {
    "ema_trend": (ema_trend, {"fast": [8, 12, 20, 30], "slow": [40, 50, 80, 120],
                              "trend": [0, 200], "sl_atr": [1.5, 2.5, 3.5],
                              "tp_atr": [0, 3, 6]}),
    "rsi_revert": (rsi_revert, {"rsi_len": [7, 14], "buy_below": [20, 30, 35],
                                "exit_above": [50, 60, 70], "trend": [0, 200],
                                "sl_atr": [2, 3], "tp_atr": [0, 3]}),
    "donchian": (donchian, {"entry_n": [20, 40, 55, 100], "exit_n": [10, 20, 30],
                            "sl_atr": [2, 3, 4], "tp_atr": [0]}),
}
EXIT_KEYS = ("sl_atr", "tp_atr")
ATR_LEN = 14


def expand_grid(name: str) -> List[Dict[str, float]]:
    _, grid = STRATEGIES[name]
    keys = list(grid)
    combos = [dict(zip(keys, v)) for v in product(*grid.values())]
    if "fast" in grid:
        combos = [c for c in combos if c["fast"] < c["slow"]]
    return combos


def compute_signals(name: str, df: pd.DataFrame, params: Dict[str, float]):
    fn, _ = STRATEGIES[name]
    sig_params = {k: v for k, v in params.items() if k not in EXIT_KEYS}
    entry, exit_ = fn(df, **sig_params)
    return entry.fillna(False).astype(bool), exit_.fillna(False).astype(bool)
