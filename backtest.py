"""Long-only backtest engine with fees, slippage, ATR stops and risk-based sizing.

Execution model (conservative):
  * signal on bar i-1 close -> entry/exit at bar i OPEN (+/- slippage)
  * intrabar: if stop and take-profit are both touched in one bar, the STOP wins
  * gaps through the stop fill at the open (worse than the stop price)
  * position size = equity * risk / (entry - stop), capped at equity * max_alloc
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np
import pandas as pd

TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600,
              "2h": 7200, "4h": 14400, "1d": 86400}


@dataclass
class Result:
    equity: np.ndarray
    trades: List[dict] = field(default_factory=list)

    def metrics(self, bars_per_year: float, init: float) -> Dict[str, float]:
        eq = self.equity
        ret = eq[-1] / init - 1
        peak = np.maximum.accumulate(eq)
        mdd = float(np.max((peak - eq) / peak)) if len(eq) else 0.0
        r = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([0.0])
        sd = r.std()
        sharpe = float(r.mean() / sd * math.sqrt(bars_per_year)) if sd > 0 else 0.0
        pnls = np.array([t["pnl"] for t in self.trades]) if self.trades else np.array([])
        gains, losses = pnls[pnls > 0].sum(), -pnls[pnls < 0].sum()
        pf = float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else 0.0)
        return {"return": float(ret), "max_dd": mdd, "sharpe": sharpe,
                "profit_factor": pf, "trades": len(self.trades),
                "win_rate": float((pnls > 0).mean()) if len(pnls) else 0.0}


def run_backtest(o, h, l, c, atr, entry, exit_, sl_atr: float, tp_atr: float,
                 risk: float = 0.02, fee: float = 0.001, slip: float = 0.0002,
                 init: float = 10_000.0, max_alloc: float = 0.5) -> Result:
    """All inputs are equal-length 1-D sequences (lists/arrays)."""
    n = len(c)
    cash, qty = init, 0.0
    stop = tp = entry_px = 0.0
    entry_i = 0
    equity = np.empty(n)
    equity[0] = init
    trades: List[dict] = []

    def close_pos(i, px, why):
        nonlocal cash, qty
        proceeds = qty * px * (1 - fee)
        cost_basis = qty * entry_px * (1 + fee)
        trades.append({"entry_i": entry_i, "exit_i": i, "entry": entry_px, "exit": px,
                       "pnl": proceeds - cost_basis, "why": why})
        cash += proceeds
        qty = 0.0

    for j in range(1, n):
        was_flat = qty == 0.0
        if qty > 0 and exit_[j - 1]:
            close_pos(j, o[j] * (1 - slip), "signal")
        if was_flat and entry[j - 1] and atr[j - 1] == atr[j - 1] and atr[j - 1] > 0:
            px = o[j] * (1 + slip)
            st = px - sl_atr * atr[j - 1]
            if 0 < st < px:
                eq_now = cash
                q = min(eq_now * risk / (px - st), eq_now * max_alloc / (px * (1 + fee)))
                if q > 0:
                    cash -= q * px * (1 + fee)
                    qty, entry_px, entry_i, stop = q, px, j, st
                    tp = px + tp_atr * atr[j - 1] if tp_atr else 0.0
        if qty > 0:
            if o[j] <= stop:
                close_pos(j, o[j] * (1 - slip), "gap_stop")
            elif l[j] <= stop:
                close_pos(j, stop * (1 - slip), "stop")
            elif tp and h[j] >= tp:
                close_pos(j, tp * (1 - slip), "tp")
        equity[j] = cash + qty * c[j]
    if qty > 0:  # mark-to-market close so the last trade is counted
        close_pos(n - 1, c[-1] * (1 - slip), "end")
        equity[-1] = cash
    return Result(equity, trades)


def buy_and_hold(df: pd.DataFrame, fee: float = 0.001) -> float:
    return float(df["close"].iloc[-1] / df["open"].iloc[1] * (1 - fee) ** 2 - 1)
