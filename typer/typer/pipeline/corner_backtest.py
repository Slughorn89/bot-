"""Walk forward modelu rożnych (modul 3): wersja z efektem stanu gry i bez.

Dla kazdej ligi z danymi o rożnych i kazdego odciecia (pt/wt, jak w module 2):
  1. model goli modulu 2 (wariant i parametry z config/model.yaml: goal_models) z meczow sprzed odciecia,
  2. warianty modelu rożnych na tych samych meczach:
       baseline  tylko srednie ligi (bez druzyn), frailty dominacji; to musi pobic kazdy model,
       A0        NB per druzyna z korekta na rywala, rozne gospodarza i goscia niezalezne,
       A         A0 + frailty dominacji (ujemna zaleznosc rożnych w meczu), bez stanu gry,
       B         A + efekt stanu gry: 20 000 symulacji przebiegu z macierzy wynikow modulu 2,
  3. dla meczow do nastepnego odciecia: log loss na kilku rynkach z tego samego rozkladu lacznego.
Porownanie, o ktore chodzi: B - A (sam efekt stanu gry, przy tej samej strukturze zaleznosci).
Metryka glowna (ustalona przed uruchomieniem): log loss rozkladu lacznego (rozne_dom, rozne_gosc).
"""
from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from typer import config
from typer.features.asof import prediction_cutoff
from typer.features.corners_style import style_features
from typer.models.corners.fit import fit_corners
from typer.models.corners.markets import diff_pmf, total_pmf
from typer.models.corners.simulate import N_SIMS, corner_distribution
from typer.models.goals.distributions import fit_extra, matrix
from typer.models.goals.fit import fit_strengths
from typer.pipeline.goal_backtest import _promoted

log = logging.getLogger("typer.corners")
EPS = 1e-12
VARIANTS = {
    "baseline": dict(ridge=1e6, frailty=True, state=False, style=False),
    "A0": dict(frailty=False, state=False),
    "A": dict(frailty=True, state=False),
    "B": dict(frailty=True, state=True),
}
METRICS = ["ll_joint", "ll_total", "ll_ou95", "ll_home45", "ll_away45", "ll_hcp15", "ll_most"]


def _bin(p: float, y: bool) -> float:
    p = min(max(p, EPS), 1 - EPS)
    return -np.log(p if y else 1 - p)


def match_losses(P: np.ndarray, hc: int, ac: int) -> dict:
    """Log loss obserwowanego wyniku na rynkach liczonych z jednego rozkladu lacznego P."""
    C = P.shape[0] - 1
    hc_, ac_ = min(int(hc), C), min(int(ac), C)
    tot = total_pmf(P)
    ph, pa = P.sum(axis=1), P.sum(axis=0)
    d, pdf = diff_pmf(P)
    k = np.arange(len(tot))
    most = [np.tril(P, -1).sum(), np.trace(P), np.triu(P, 1).sum()]
    y_most = 0 if hc > ac else 1 if hc == ac else 2
    return dict(
        ll_joint=-np.log(max(P[hc_, ac_], EPS)),
        ll_total=-np.log(max(tot[hc_ + ac_], EPS)),
        ll_ou95=_bin(float(tot[k > 9.5].sum()), hc + ac > 9.5),
        ll_home45=_bin(float(ph[np.arange(C + 1) > 4.5].sum()), hc > 4.5),
        ll_away45=_bin(float(pa[np.arange(C + 1) > 4.5].sum()), ac > 4.5),
        ll_hcp15=_bin(float(pdf[d - 1.5 > 0].sum()), hc - 1.5 > ac),
        ll_most=-np.log(max(most[y_most], EPS)),
    )


def run_league(df: pd.DataFrame, start, end, half_life: float = 365.0, ridge: float = 3.0,
               use_style: bool = False, variants: dict | None = None, window_days: int = 1095,
               n_sims: int = N_SIMS, cutoff_mode: str = "fduk") -> pd.DataFrame:
    variants = variants or VARIANTS
    gcfg = config.model_params().get("goal_models", {})
    lg = df["league"].iloc[0]
    g_var = (gcfg.get("variant_per_league") or {}).get(lg, "bivariate")
    g_hl, g_wx, g_ridge = gcfg.get("half_life", 240), gcfg.get("w_xg", 0.2), gcfg.get("ridge", 3.0)
    df = df.sort_values("kickoff_utc", kind="stable").reset_index(drop=True)
    if df["hc"].notna().sum() < 300:
        return pd.DataFrame()
    d = pd.to_datetime(df["date"])
    played = df["fthg"].notna() & df["ftag"].notna()
    has_c = played & df["hc"].notna() & df["ac"].notna()
    sh, sa = style_features(df, cutoff_mode) if use_style else (np.zeros((len(df), 0)),) * 2
    cut = pd.Series([pd.Timestamp(prediction_cutoff(x, cutoff_mode)) for x in d], index=df.index)
    tgt = df.index[(d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end)) & has_c]
    rows, warm_g, warm = [], None, {}
    for c, idx in pd.Series(tgt, index=tgt).groupby(cut.loc[tgt]):
        win = (d < c) & (d >= c - pd.Timedelta(days=window_days))
        trg, trc = played & win, has_c & win
        if trc.sum() < 300:
            continue
        season = df.at[idx.iloc[0], "season"]
        G, GD = fit_strengths(df[trg], c, g_hl, g_wx, g_ridge, promoted=_promoted(df, season), warm=warm_g)
        warm_g = G
        g_extra = fit_extra(g_var, GD["gh"], GD["ga"], GD["mh"], GD["ma"], GD["w"])
        fits = {}
        for name, v in variants.items():
            st = use_style and v.get("style", True)
            m = trc.to_numpy()
            S, _ = fit_corners(df[trc], c, half_life, v.get("ridge", ridge), state=v["state"],
                               frailty=v["frailty"], cov_h=sh[m] if st else None, cov_a=sa[m] if st else None,
                               warm=warm.get(name))
            warm[name] = fits[name] = S
        for i in idx:
            r = df.loc[i]
            mh, ma = G.rates(r["home"], r["away"])
            gm = matrix(g_var, mh, ma, g_extra)
            for name, S in fits.items():
                st = use_style and variants[name].get("style", True)
                out = corner_distribution(S, r["home"], r["away"], gm, sh[i] if st else None,
                                          sa[i] if st else None, n_sims=n_sims, seed=int(i))
                rows.append(dict(event_id=r["event_id"], league=lg, season=r["season"], date=r["date"],
                                 variant=name, hc=r["hc"], ac=r["ac"], mu_h=out["mu_h"], mu_a=out["mu_a"],
                                 g_trail=S.g_trail, g_lead=S.g_lead, r=S.r, sigma=S.sigma,
                                 **match_losses(out["joint"], r["hc"], r["ac"])))
    return pd.DataFrame(rows)


def _job(args):
    g, start, end, kw = args
    return run_league(g, start, end, **kw)


def run(matches: pd.DataFrame, start, end, workers: int = 4, **kw) -> pd.DataFrame:
    jobs = [(g, start, end, kw) for _, g in matches.groupby("league")]
    if workers <= 1:
        parts = [_job(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            parts = list(ex.map(_job, jobs))
    parts = [p for p in parts if len(p)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def paired_ci(diff: np.ndarray, n_boot: int = 4000, seed: int = 7) -> dict:
    """Srednia roznica i przedzialy CI90 / CI95 ze sparowanego bootstrapu (losowanie meczow)."""
    diff = np.asarray(diff, float)
    rng = np.random.default_rng(seed)
    m = diff[rng.integers(0, len(diff), (n_boot, len(diff)))].mean(axis=1)
    q = np.percentile(m, [2.5, 5, 95, 97.5])
    return dict(mean=float(diff.mean()), ci90=(float(q[1]), float(q[2])), ci95=(float(q[0]), float(q[3])),
                n=int(len(diff)))


def compare(res: pd.DataFrame, a: str, b: str, metrics=METRICS, by_league: bool = True) -> pd.DataFrame:
    """Roznica log loss b - a (ujemna = b lepszy) per rynek, lacznie i per liga."""
    wide = {v: g.set_index("event_id") for v, g in res.groupby("variant")}
    common = wide[a].index.intersection(wide[b].index)
    A, B = wide[a].loc[common], wide[b].loc[common]
    out = []
    groups = [("razem", common)]
    if by_league:
        groups += [(lg, A.index[A["league"] == lg]) for lg in sorted(A["league"].unique())]
    for name, ix in groups:
        for m in metrics:
            ci = paired_ci(B.loc[ix, m].to_numpy() - A.loc[ix, m].to_numpy())
            out.append(dict(porownanie=f"{b}-{a}", liga=name, rynek=m, n=ci["n"],
                            ll_a=round(float(A.loc[ix, m].mean()), 5), ll_b=round(float(B.loc[ix, m].mean()), 5),
                            roznica=round(ci["mean"], 5), ci90=tuple(round(x, 5) for x in ci["ci90"]),
                            ci95=tuple(round(x, 5) for x in ci["ci95"])))
    return pd.DataFrame(out)


def calibration_total(res: pd.DataFrame, variant: str) -> pd.DataFrame:
    """Kontrola srednich: przewidziana vs obserwowana liczba rożnych w decylach przewidywanej sumy."""
    g = res[res["variant"] == variant].copy()
    g["pred"] = g["mu_h"] + g["mu_a"]
    g["obs"] = g["hc"] + g["ac"]
    g["bin"] = pd.qcut(g["pred"], 10, labels=False, duplicates="drop")
    return g.groupby("bin")[["pred", "obs"]].mean().round(3)
