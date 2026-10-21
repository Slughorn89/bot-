#!/usr/bin/env python3
"""Walk-forward optimisation of the strategies in signals.py.

For every fold: pick the best parameters on the TRAIN window, then trade them on
the next, unseen TEST window. Only the stitched out-of-sample (OOS) results are
reported as performance. Parameters are written to best_params.json ONLY if they
pass the quality gates; otherwise the bot is told to stay out of the market.

    python optimize.py --symbol BTC/USDT --timeframe 1h --days 1095
    python optimize.py --synthetic        # code smoke test, never writes params
"""
import argparse
import json
import math
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from backtest import TF_SECONDS, buy_and_hold, run_backtest
from data import fetch_history, synthetic
from signals import ATR_LEN, STRATEGIES, atr, compute_signals, expand_grid

GATES = {"min_return": 0.0, "min_profit_factor": 1.2, "min_trades": 20,
         "max_drawdown": 0.30, "min_fold_hit_rate": 0.5}


class Evaluator:
    def __init__(self, df, name, risk, max_alloc, fee, slip):
        self.o, self.h = df["open"].to_numpy(), df["high"].to_numpy()
        self.l, self.c = df["low"].to_numpy(), df["close"].to_numpy()
        self.atr = atr(df, ATR_LEN).to_numpy()
        self.df, self.name = df, name
        self.kw = dict(risk=risk, fee=fee, slip=slip, max_alloc=max_alloc)
        self.combos = expand_grid(name)
        self.sigs = [tuple(s.to_numpy() for s in compute_signals(name, df, p)) for p in self.combos]
        self.bpy = 365 * 86_400 / TF_SECONDS[df.attrs.get("tf", "1h")]

    def run(self, k, a, b):
        p, (en, ex) = self.combos[k], self.sigs[k]
        sl = slice(a, b)
        return run_backtest(self.o[sl].tolist(), self.h[sl].tolist(), self.l[sl].tolist(),
                            self.c[sl].tolist(), self.atr[sl].tolist(), en[sl].tolist(),
                            ex[sl].tolist(), p["sl_atr"], p["tp_atr"], **self.kw)

    def best_on(self, a, b, min_trades):
        best, best_s = None, -math.inf
        for k in range(len(self.combos)):
            m = self.run(k, a, b).metrics(self.bpy, 10_000)
            s = score(m, min_trades)
            if s > best_s:
                best, best_s = k, s
        return best, best_s


def score(m, min_trades):
    if m["trades"] < min_trades or m["profit_factor"] < 1.0:
        return -math.inf
    return m["return"] / max(m["max_dd"], 0.05)


def walk_forward(ev: Evaluator, train, test, min_trades):
    n, folds, level, eq_all, trades_all = len(ev.c), [], 1.0, [], []
    start = 0
    while start + train + test <= n:
        a, b, e = start, start + train, start + train + test
        k, s = ev.best_on(a, b, min_trades)
        if k is not None:
            res = ev.run(k, b, e)
            m = res.metrics(ev.bpy, 10_000)
            eq = res.equity / res.equity[0]
            eq_all.append(eq * level)
            level *= eq[-1]
            trades_all += res.trades
            folds.append({"start": str(ev.df.index[b]), "params": ev.combos[k],
                          "train_score": round(s, 3), "oos": m})
        else:
            folds.append({"start": str(ev.df.index[b]), "params": None, "oos": None})
        start += test
    if not eq_all:
        return None
    eq = np.concatenate(eq_all)
    peak = np.maximum.accumulate(eq)
    pnls = np.array([t["pnl"] for t in trades_all])
    g, ls = pnls[pnls > 0].sum(), -pnls[pnls < 0].sum()
    traded = [f for f in folds if f["oos"]]
    return {
        "return": float(eq[-1] - 1), "max_dd": float(np.max((peak - eq) / peak)),
        "profit_factor": float(g / ls) if ls > 0 else (float("inf") if g > 0 else 0.0),
        "trades": len(trades_all),
        "fold_hit_rate": sum(f["oos"]["return"] > 0 for f in traded) / max(len(folds), 1),
        "folds": folds, "oos_start": folds[0]["start"],
    }


def passes(oos):
    g = GATES
    return bool(oos and oos["return"] > g["min_return"]
                and oos["profit_factor"] >= g["min_profit_factor"]
                and oos["trades"] >= g["min_trades"] and oos["max_dd"] <= g["max_drawdown"]
                and oos["fold_hit_rate"] >= g["min_fold_hit_rate"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="1h", choices=list(TF_SECONDS))
    ap.add_argument("--days", type=int, default=1095)
    ap.add_argument("--train-days", type=int, default=365)
    ap.add_argument("--test-days", type=int, default=90)
    ap.add_argument("--risk", type=float, default=0.02)
    ap.add_argument("--max-alloc", type=float, default=0.5)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--slippage", type=float, default=0.0002)
    ap.add_argument("--min-trades", type=int, default=15)
    ap.add_argument("--strategies", nargs="+", default=list(STRATEGIES))
    ap.add_argument("--out", default="best_params.json")
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()

    df = synthetic(a.days, a.timeframe) if a.synthetic else \
        fetch_history(a.exchange, a.symbol, a.timeframe, a.days)
    df.attrs["tf"] = a.timeframe
    per_day = 86_400 / TF_SECONDS[a.timeframe]
    train, test = int(a.train_days * per_day), int(a.test_days * per_day)
    if len(df) < train + test:
        sys.exit(f"Za malo danych: {len(df)} swiec, potrzeba >= {train + test}")
    print(f"{'SYNTHETIC ' if a.synthetic else ''}{a.symbol} {a.timeframe}: {len(df)} swiec "
          f"({df.index[0]} .. {df.index[-1]}), fee={a.fee:.2%}/strona, poslizg={a.slippage:.2%}\n")

    reports = {}
    for name in a.strategies:
        print(f"[{name}] optymalizacja walk-forward ...", flush=True)
        ev = Evaluator(df, name, a.risk, a.max_alloc, a.fee, a.slippage)
        oos = walk_forward(ev, train, test, a.min_trades)
        reports[name] = (ev, oos)

    first = next((o["oos_start"] for _, o in reports.values() if o), None)
    bh = buy_and_hold(df[df.index >= pd.Timestamp(first)]) if first else float("nan")
    print(f"\n{'strategia':<12}{'OOS zwrot':>10}{'maxDD':>8}{'PF':>7}{'trades':>8}{'folds+':>8}  gates")
    for name, (_, o) in reports.items():
        if not o:
            print(f"{name:<12}  brak wynikow (za malo transakcji w treningu)")
            continue
        print(f"{name:<12}{o['return']:>10.1%}{o['max_dd']:>8.1%}{o['profit_factor']:>7.2f}"
              f"{o['trades']:>8}{o['fold_hit_rate']:>8.0%}  {'PASS' if passes(o) else 'fail'}")
    print(f"{'buy&hold':<12}{bh:>10.1%}  (ten sam okres OOS)\n")

    winners = [(n, o) for n, (_, o) in reports.items() if passes(o)]
    summary = {"created": datetime.now(timezone.utc).isoformat(), "symbol": a.symbol,
               "timeframe": a.timeframe, "exchange": a.exchange, "gates": GATES,
               "buy_and_hold_oos": bh, "risk": a.risk, "max_alloc": a.max_alloc,
               "synthetic": a.synthetic}
    if a.synthetic:
        print("Tryb syntetyczny: test kodu. Nic nie zapisano do", a.out)
        return
    if not winners:
        summary.update(strategy=None, note="Zadna strategia nie przeszla bramek OOS - bot nie handluje.")
        print("ZADNA strategia nie przeszla bramek jakosci. Bot pozostanie poza rynkiem.")
    else:
        name, oos = max(winners, key=lambda w: w[1]["return"] / max(w[1]["max_dd"], 0.05))
        ev = reports[name][0]
        k, _ = ev.best_on(len(df) - train, len(df), a.min_trades)
        summary.update(strategy=name, params=ev.combos[k],
                       oos={k_: v for k_, v in oos.items() if k_ != "folds"})
        print(f"Wybrano: {name} {ev.combos[k]}")
    json.dump(summary, open(a.out, "w"), indent=2, default=str)
    print("Zapisano", a.out)


if __name__ == "__main__":
    main()
