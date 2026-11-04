"""Strojenie ocen online na WALIDACJI (nigdy na holdoucie). Przeszukiwanie po wspolrzednych.

Cel: log loss 1X2 + 0.5 * (log loss O/U 2.5 + log loss BTTS) na meczach walidacji.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import replace

import pandas as pd

from typer.pipeline.engine import Engine
from typer.pipeline.layers import metrics
from typer.models.scores.online_poisson import Params

log = logging.getLogger("typer.tune")

SEARCH = {  # parametr: (krok, min, max, tryb) ; tryb 'mul' = mnozenie, 'add' = dodawanie
    "lr_team": (0.25, 0.005, 0.2, "mul"),
    "lr_home": (0.5, 0.0, 0.05, "mul"),
    "lr_mu": (0.5, 0.0, 0.02, "mul"),
    "w_xg": (0.15, 0.0, 1.0, "add"),
    "season_regress": (0.1, 0.0, 0.8, "add"),
    "promoted_atk": (0.06, -0.6, 0.2, "add"),
    "promoted_obr": (0.06, -0.6, 0.2, "add"),
    "new_team_boost": (0.5, 0.0, 6.0, "add"),
    "rho": (0.03, -0.2, 0.1, "add"),
}


def objective(df: pd.DataFrame, params: Params, start, end) -> tuple[float, dict]:
    res = Engine(params, collect_features=False).run(df, predict_from=start)
    v = res[pd.to_datetime(res["date"]) <= pd.Timestamp(end)]
    m = metrics(v)
    return m["ll_1x2"] + 0.5 * (m["ll_ou"] + m["ll_btts"]), m


def coordinate_search(df: pd.DataFrame, start, end, base: Params | None = None, rounds: int = 3,
                      log_path=None) -> tuple[Params, float, list]:
    best = base or Params()
    best_j, best_m = objective(df, best, start, end)
    history = [dict(params=best.to_dict(), J=best_j, **best_m)]
    log.info("start J=%.5f", best_j)
    steps = {k: v[0] for k, v in SEARCH.items()}
    for rnd in range(rounds):
        improved = False
        for name, (_, lo, hi, mode) in SEARCH.items():
            for direction in (+1, -1):
                cur = getattr(best, name)
                if mode == "mul":
                    new = cur * (1 + steps[name]) if direction > 0 else cur / (1 + steps[name])
                    if cur == 0:
                        new = 0.001 if direction > 0 else 0.0
                else:
                    new = cur + direction * steps[name]
                new = min(max(new, lo), hi)
                if abs(new - cur) < 1e-12:
                    continue
                cand = replace(best, **{name: new})
                t = time.time()
                j, m = objective(df, cand, start, end)
                history.append(dict(params=cand.to_dict(), J=j, **m))
                log.info("r%d %s=%.4f J=%.5f (best %.5f) %.0fs", rnd, name, new, j, best_j, time.time() - t)
                if j < best_j - 1e-6:
                    best, best_j, improved = cand, j, True
                    break
        if log_path:
            with open(log_path, "w") as f:
                json.dump(history, f, indent=1, default=float)
        if not improved:
            steps = {k: v / 2 for k, v in steps.items()}
    return best, best_j, history
