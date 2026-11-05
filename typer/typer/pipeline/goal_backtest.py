"""Walk forward modelu goli (modul 2): Dixon-Coles, dwuwymiarowy Poisson, ujemny dwumianowy.

Dla kazdej ligi i kazdego odciecia (pt/wt, jak zbieranie kursow w football-data):
  1. sily druzyn z meczow sprzed odciecia (okno 3 lata, wagi 0.5^(wiek/half_life), cel gole+xG, cechy kontekstu),
  2. parametr kazdego rozkladu (rho / phi / r) profilowany na tych samych meczach,
  3. macierze 0..10 dla meczow do nastepnego odciecia -> 1X2, O/U 2.5, BTTS (pelny pakiet w markets.market_bundle).
Wybor wariantu per liga: najnizszy J = ll 1X2 + 0.5 (ll O/U + ll BTTS), ale zmiana wzgledem wariantu domyslnego
tylko wtedy, gdy CI90 roznicy J w sparowanym bootstrapie jest ponizej zera (6 lig x 4 kandydatow = latwo o szum).
"""
from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from typer.features.asof import prediction_cutoff
from typer.features.context import context_features
from typer.models.goals.distributions import VARIANTS, fit_extra, matrix
from typer.models.goals.fit import fit_strengths
from typer.pipeline.layers import outcomes

log = logging.getLogger("typer.goals")
EPS = 1e-12


def _promoted(df: pd.DataFrame, season: str) -> set:
    seasons = sorted(df["season"].unique())
    if season not in seasons or seasons.index(season) == 0:
        return set()
    prev = seasons[seasons.index(season) - 1]
    cur = set(df.loc[df["season"] == season, "home"]) | set(df.loc[df["season"] == season, "away"])
    old = set(df.loc[df["season"] == prev, "home"]) | set(df.loc[df["season"] == prev, "away"])
    return cur - old


def run_league(df: pd.DataFrame, start, end, half_life: float, w_xg: float, ridge: float = 3.0,
               use_context: bool = True, window_days: int = 1095, variants=VARIANTS,
               cutoff_mode: str = "fduk") -> pd.DataFrame:
    df = df.sort_values("kickoff_utc", kind="stable").reset_index(drop=True)
    d = pd.to_datetime(df["date"])
    played = df["fthg"].notna() & df["ftag"].notna()
    if use_context:
        ch, ca = context_features(df, cutoff_mode)
    else:
        ch = ca = np.zeros((len(df), 0))
    cut = pd.Series([pd.Timestamp(prediction_cutoff(x, cutoff_mode)) for x in d], index=df.index)
    tgt = df.index[(d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))]
    rows, warm = [], None
    for c, idx in pd.Series(tgt, index=tgt).groupby(cut.loc[tgt]):
        tr = played & (d < c) & (d >= c - pd.Timedelta(days=window_days))
        if tr.sum() < 150:
            continue
        season = df.at[idx.iloc[0], "season"]
        S, D = fit_strengths(df[tr], c, half_life, w_xg, ridge, cov_h=ch[tr.to_numpy()],
                             cov_a=ca[tr.to_numpy()], promoted=_promoted(df, season), warm=warm)
        warm = S
        extras = {v: fit_extra(v, D["gh"], D["ga"], D["mh"], D["ma"], D["w"]) for v in variants}
        for i in idx:
            r = df.loc[i]
            mh, ma = S.rates(r["home"], r["away"], ch[i] if ch.shape[1] else None, ca[i] if ca.shape[1] else None)
            for v in variants:
                m = matrix(v, mh, ma, extras[v])
                ph = float(np.tril(m, -1).sum())
                pdr = float(np.trace(m))
                tot = np.add.outer(np.arange(m.shape[0]), np.arange(m.shape[1]))
                rows.append(dict(event_id=r["event_id"], league=r["league"], season=r["season"], date=r["date"],
                                 variant=v, mh=mh, ma=ma, extra=extras[v], p_h=ph, p_d=pdr, p_a=1 - ph - pdr,
                                 p_over=float(m[tot > 2.5].sum()),
                                 p_btts=float(1 - m[0, :].sum() - m[:, 0].sum() + m[0, 0]),
                                 fthg=r["fthg"], ftag=r["ftag"],
                                 **{k: r[k] for k in ("odds_h", "odds_d", "odds_a", "odds_o25", "odds_u25",
                                                      "base_h") if k in r}))
    return pd.DataFrame(rows)


def _job(args):
    df, start, end, hl, wx, ridge, ctx = args
    return run_league(df, start, end, hl, wx, ridge, ctx)


def run(matches: pd.DataFrame, start, end, half_life: float, w_xg: float, ridge: float = 3.0,
        use_context: bool = True, workers: int = 4) -> pd.DataFrame:
    jobs = [(g, start, end, half_life, w_xg, ridge, use_context) for _, g in matches.groupby("league")]
    if workers <= 1:
        parts = [_job(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            parts = list(ex.map(_job, jobs))
    return pd.concat([p for p in parts if len(p)], ignore_index=True)


def per_match_j(df: pd.DataFrame) -> pd.Series:
    """J na mecz: -ln p(1X2) + 0.5 (-ln p(O/U 2.5) - ln p(BTTS))."""
    y = outcomes(df)
    P = np.clip(df[["p_h", "p_d", "p_a"]].to_numpy(float), EPS, 1)
    P = P / P.sum(axis=1, keepdims=True)
    ll1 = -np.log(P[np.arange(len(df)), y["1x2"]])
    po = np.clip(df["p_over"].to_numpy(float), EPS, 1 - EPS)
    pb = np.clip(df["p_btts"].to_numpy(float), EPS, 1 - EPS)
    llo = -(y["over"] * np.log(po) + (1 - y["over"]) * np.log(1 - po))
    llb = -(y["btts"] * np.log(pb) + (1 - y["btts"]) * np.log(1 - pb))
    return pd.Series(ll1 + 0.5 * (llo + llb), index=df["event_id"].to_numpy())


def paired_ci(diff: np.ndarray, n_boot: int = 2000, seed: int = 7) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(diff), (n_boot, len(diff)))
    m = diff[idx].mean(axis=1)
    return float(diff.mean()), float(np.percentile(m, 5)), float(np.percentile(m, 95))


def select_per_league(cands: dict[str, pd.DataFrame], default: str) -> pd.DataFrame:
    """cands: nazwa -> ramka predykcji (event_id, league, p_*, wyniki). Zwraca tabele wyboru per liga."""
    out = []
    leagues = sorted(set.intersection(*[set(c["league"]) for c in cands.values()]))
    for lg in leagues:
        js = {k: per_match_j(c[c["league"] == lg]) for k, c in cands.items()}
        common = sorted(set.intersection(*[set(j.index) for j in js.values()]))
        js = {k: j.loc[common] for k, j in js.items()}
        best = min(js, key=lambda k: js[k].mean())
        mean, lo, hi = paired_ci(js[best].to_numpy() - js[default].to_numpy()) if best != default else (0.0, 0.0, 0.0)
        chosen = best if best != default and hi < 0 else default
        out.append(dict(liga=lg, n=len(common), **{f"J_{k}": round(float(j.mean()), 5) for k, j in js.items()},
                        najlepszy=best, roznica_vs_domyslny=round(mean, 5), ci90=(round(lo, 5), round(hi, 5)),
                        wybrany=chosen))
    return pd.DataFrame(out)
