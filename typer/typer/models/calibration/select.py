"""Kalibracja per rynek i liga z wyborem metody po ECE (modul 6).

Kandydaci (zakres "L" = osobno dla ligi z >= min_rows meczow historii, inaczej globalnie; "G" = globalnie):
  1X2:     none, vector_L, vector_G (Platt wieloklasowy), temperature_L, temperature_G, isotonic_L, isotonic_G
  binarne: none, platt_L, platt_G, isotonic_L, isotonic_G
Kazdy kandydat dopasowywany KROCZACO (sezon S: tylko mecze sprzed 1 lipca roku startu S).
Wybor per (rynek, liga) na sezonach walidacji:
  1. bezpiecznik log loss: guard="mean" (domyslnie) - kandydat odpada, jesli SREDNIO pogarsza log loss wzgledem
     none; guard="ci95" (pierwsza wersja, za luzna: przepuszczala izotoniczna per liga z +0.011, experiments.md
     wpis 25) - odpada tylko, gdy CI95 roznicy lezy w calosci powyzej zera,
  2. z pozostalych najnizszy ECE (10 przedzialow rownej licznosci, dla 1X2 srednia po klasach),
  3. kontrola stabilnosci: ten sam wybor przy 15 i 20 przedzialach oraz przy przedzialach rownej szerokosci;
     zgodnosc raportowana, a gdy wybor w lidze jest niestabilny (mniej niz 3 z 4 schematow), liga dostaje
     metode wybrana globalnie dla rynku.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from typer.metrics.scores import ece, paired_diff_ci, per_event_log_loss
from typer.models.calibration.calibrate import Binary, Multiclass
from typer.pipeline.layers import P1X2, outcomes

MARKETS = {"1X2": P1X2, "OU2.5": "p_over", "BTTS": "p_btts"}
YKEY = {"1X2": "1x2", "OU2.5": "over", "BTTS": "btts"}
CANDIDATES = {
    "1X2": ["none", "vector_L", "vector_G", "temperature_L", "temperature_G", "isotonic_L", "isotonic_G"],
    "binary": ["none", "platt_L", "platt_G", "isotonic_L", "isotonic_G"],
}
SCHEMES = [(10, "quantile"), (15, "quantile"), (20, "quantile"), (10, "uniform")]


def candidates(market: str) -> list[str]:
    return CANDIDATES["1X2" if market == "1X2" else "binary"]


def _split(c: str) -> tuple[str, str]:
    return (c, "G") if c == "none" else tuple(c.rsplit("_", 1))


def _fit_apply(market, method, tr, tg):
    y = outcomes(tr)[YKEY[market]]
    if market == "1X2":
        c = Multiclass(method).fit(tr[P1X2].to_numpy(float), y)
        return c.transform(tg[P1X2].to_numpy(float))
    col = MARKETS[market]
    b = Binary(method).fit(tr[col].to_numpy(float), y)
    return np.clip(b.transform(tg[col].to_numpy(float)), 0.001, 0.999)


def calibrate_select_fn(choice: dict, min_rows: int = 1500):
    """Warstwa do layers.chain: choice = {rynek: {liga: kandydat, "_global": kandydat}}."""
    def fp(tr: pd.DataFrame, tg: pd.DataFrame) -> pd.DataFrame:
        tg = tg.copy()
        for market, cols in MARKETS.items():
            ch = choice.get(market, {})
            for lg, idx in tg.groupby("league").groups.items():
                cand = ch.get(lg, ch.get("_global", "none"))
                method, scope = _split(cand)
                if method == "none":
                    continue
                t = tr[tr["league"] == lg] if scope == "L" else tr
                if scope == "L" and len(t) < min_rows:
                    t = tr
                out = _fit_apply(market, method, t, tg.loc[idx])
                tg.loc[idx, cols] = out
        return tg
    return fp


def uniform_choice(c1x2: str, cbin: str) -> dict:
    return {"1X2": {"_global": c1x2}, "OU2.5": {"_global": cbin}, "BTTS": {"_global": cbin}}


def market_arrays(df: pd.DataFrame, market: str) -> tuple[np.ndarray, np.ndarray]:
    y = outcomes(df)[YKEY[market]]
    if market == "1X2":
        P = df[P1X2].to_numpy(float)
        return P / P.sum(axis=1, keepdims=True), y
    return df[MARKETS[market]].to_numpy(float), y


def _paired_ci95(d: np.ndarray, n_boot: int = 2000, seed: int = 7) -> tuple[float, float]:
    return paired_diff_ci(d, n_boot, seed)["ci95"]


def ece_noise_floor(P, n_sim: int = 30, seed: int = 11) -> float:
    """ECE idealnie skalibrowanego modelu przy tym samym n i tych samych p (wyniki losowane z p):
    ponizej tej wartosci roznice ECE to szum."""
    rng = np.random.default_rng(seed)
    P = np.asarray(P, float)
    vals = []
    for _ in range(n_sim):
        if P.ndim == 2:
            c = P.cumsum(axis=1)
            y = (rng.random((len(P), 1)) > c).sum(axis=1)
            vals.append(ece(P, np.minimum(y, P.shape[1] - 1)))
        else:
            vals.append(ece(P, (rng.random(len(P)) < P).astype(float)))
    return float(np.mean(vals))


def select(oof: dict[str, pd.DataFrame], leagues: list[str] | None = None, guard: str = "mean"
           ) -> tuple[dict, pd.DataFrame]:
    """oof: kandydat -> ramka OOF z sezonow walidacji (te same mecze, ta sama kolejnosc event_id).
    Zwraca (choice dla calibrate_select_fn, tabela z ECE i log loss kazdego kandydata)."""
    ref = next(iter(oof.values()))
    leagues = leagues or sorted(ref["league"].unique())
    rows, choice = [], {}
    for market in MARKETS:
        cands = [c for c in candidates(market) if c in oof]
        choice[market] = {}
        scopes = [("_global", None)] + [(lg, lg) for lg in leagues]
        for name, lg in scopes:
            ll, ec = {}, {s: {} for s in SCHEMES}
            for c in cands:
                d = oof[c] if lg is None else oof[c][oof[c]["league"] == lg]
                P, y = market_arrays(d, market)
                ll[c] = per_event_log_loss(P, y)
                for b, strat in SCHEMES:
                    ec[(b, strat)][c] = ece(P, y, b, strat)
            ok = []
            d0 = oof["none"] if lg is None else oof["none"][oof["none"]["league"] == lg]
            floor = ece_noise_floor(market_arrays(d0, market)[0])
            for c in cands:
                lo, hi = (0.0, 0.0) if c == "none" else _paired_ci95(ll[c] - ll["none"])
                d = float((ll[c] - ll["none"]).mean())
                elig = c == "none" or (d <= 0 if guard == "mean" else lo <= 0)
                if elig:
                    ok.append(c)
                rows.append(dict(rynek=market, liga=name, kandydat=c, n=len(ll[c]), log_loss=float(ll[c].mean()),
                                 d_ll_vs_none=float((ll[c] - ll["none"]).mean()), ci95_lo=lo, ci95_hi=hi,
                                 dopuszczony=elig, ece_podloga_szumu=floor, **{f"ece_{b}{s[0]}": ec[(b, s)][c] for b, s in SCHEMES}))
            picks = [min(ok, key=lambda c: ec[s][c]) for s in SCHEMES]
            main = picks[0]
            stable = sum(p == main for p in picks) >= 3
            choice[market][name] = main if (stable or name == "_global") else None
            for r in rows[-len(cands):]:
                r.update(wybrany=r["kandydat"] == main, stabilny=stable)
        g = choice[market]["_global"]
        for lg in leagues:
            if choice[market].get(lg) is None:
                choice[market][lg] = g
    return choice, pd.DataFrame(rows)
