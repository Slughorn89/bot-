"""Warstwy nad ocenami online, dopasowywane KROCZACO: dla sezonu S uczymy sie tylko na meczach
sprzed 1 lipca roku startu S. Zadna warstwa nie widzi sezonu, ktory typuje.

  calibrate  kalibracja per rynek (1X2: vector/temperature/isotonic, binarne: platt/isotonic)
  gbm        LightGBM na cechach + wyjsciach ocen (cel: prawdopodobienstwo, strata log loss)
  blend      mieszanka log-liniowa z rynkiem w chwili typu (kurs "wziety" bez marzy)
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

from typer.betting.core import devig
from typer.models.calibration.calibrate import Binary, Multiclass

log = logging.getLogger("typer.layers")
EPS = 1e-9
P1X2 = ["p_h", "p_d", "p_a"]

FEATURES = ["lam_h", "lam_a", "p_h", "p_d", "p_a", "p_over", "p_btts", "atk_h", "obr_h", "atk_a",
            "obr_a", "n_h", "n_a", "home_adv", "mu", "elo_h", "elo_a", "elo_diff", "rest_h", "rest_a",
            "month", "season_progress", "h_gf_ewm", "h_ga_ewm", "h_xgf_ewm", "h_xga_ewm", "h_pts5",
            "a_gf_ewm", "a_ga_ewm", "a_xgf_ewm", "a_xga_ewm", "a_pts5", "base_h", "base_d", "base_a",
            "base_over", "base_btts"]


def outcomes(df: pd.DataFrame) -> dict[str, np.ndarray]:
    gh, ga = df["fthg"].to_numpy(float), df["ftag"].to_numpy(float)
    return {"1x2": np.select([gh > ga, gh == ga], [0, 1], 2),
            "over": (gh + ga > 2.5).astype(int), "btts": ((gh > 0) & (ga > 0)).astype(int)}


def season_cut(season: str) -> pd.Timestamp:
    return pd.Timestamp(f"{season[:4]}-07-01")


def walk_forward(df: pd.DataFrame, seasons: list[str], fit_predict, train_from: str = "2008-07-01"
                 ) -> pd.DataFrame:
    """fit_predict(train_df, target_df) -> target_df z nowymi kolumnami."""
    parts = []
    d = pd.to_datetime(df["date"])
    for s in seasons:
        tgt = df[df["season"] == s]
        if tgt.empty:
            continue
        tr = df[(d < season_cut(s)) & (d >= pd.Timestamp(train_from))]
        parts.append(fit_predict(tr, tgt))
    return pd.concat(parts) if parts else df.iloc[0:0]


# ---------------- kalibracja ----------------
def calibrate_fn(method_1x2: str = "vector", method_bin: str = "platt"):
    def fp(tr: pd.DataFrame, tg: pd.DataFrame) -> pd.DataFrame:
        tg = tg.copy()
        y = outcomes(tr)
        c = Multiclass(method_1x2).fit(tr[P1X2].to_numpy(), y["1x2"])
        tg[P1X2] = c.transform(tg[P1X2].to_numpy())
        for col, key in (("p_over", "over"), ("p_btts", "btts")):
            b = Binary(method_bin).fit(tr[col].to_numpy(), y[key])
            tg[col] = np.clip(b.transform(tg[col].to_numpy()), 0.001, 0.999)
        return tg
    return fp


# ---------------- LightGBM ----------------
GBM_PARAMS = dict(num_leaves=15, learning_rate=0.03, min_child_samples=200, subsample=0.8,
                  subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, verbose=-1)


def _gbm_fit(X, y, Xv, yv, objective, num_class=None):
    import lightgbm as lgb
    params = dict(GBM_PARAMS, objective=objective)
    if num_class:
        params["num_class"] = num_class
    ds, dv = lgb.Dataset(X, y), lgb.Dataset(Xv, yv)
    m = lgb.train(params, ds, 1500, valid_sets=[dv], callbacks=[lgb.early_stopping(50, verbose=False)])
    best = max(m.best_iteration, 20)
    # finalny model na calosci danych treningowych z wybrana liczba drzew
    return lgb.train(params, lgb.Dataset(np.vstack([X, Xv]), np.r_[y, yv]), best)


def gbm_fn(features: list[str] = FEATURES):
    def fp(tr: pd.DataFrame, tg: pd.DataFrame) -> pd.DataFrame:
        tg = tg.copy()
        dtr = pd.to_datetime(tr["date"])
        inner = dtr >= dtr.max() - pd.Timedelta(days=365)  # ostatni rok = wczesne zatrzymanie
        a, b = tr[~inner], tr[inner]
        ya, yb = outcomes(a), outcomes(b)
        X, Xv, Xt = a[features].to_numpy(float), b[features].to_numpy(float), tg[features].to_numpy(float)
        m = _gbm_fit(X, ya["1x2"], Xv, yb["1x2"], "multiclass", 3)
        tg[P1X2] = m.predict(Xt)
        for col, key in (("p_over", "over"), ("p_btts", "btts")):
            m = _gbm_fit(X, ya[key], Xv, yb[key], "binary")
            tg[col] = np.clip(m.predict(Xt), 0.001, 0.999)
        return tg
    return fp


# ---------------- mieszanka z rynkiem ----------------
def market_probs(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Rynek w chwili typu bez marzy: (P1X2, maska1X2, p_over, maskaOU)."""
    o1 = df[["odds_h", "odds_d", "odds_a"]].to_numpy(float)
    m1 = np.isfinite(o1).all(axis=1)
    P = np.full_like(o1, np.nan)
    P[m1] = devig(o1[m1])
    o2 = df[["odds_o25", "odds_u25"]].to_numpy(float)
    m2 = np.isfinite(o2).all(axis=1)
    po = np.full(len(df), np.nan)
    po[m2] = devig(o2[m2])[:, 0]
    return P, m1, po, m2


def _pool(Pm, Pk, w):
    L = w * np.log(np.clip(Pm, EPS, 1)) + (1 - w) * np.log(np.clip(Pk, EPS, 1))
    E = np.exp(L - L.max(axis=1, keepdims=True))
    return E / E.sum(axis=1, keepdims=True)


def _fit_w(Pm, Pk, y):
    f = lambda w: -np.mean(np.log(np.clip(_pool(Pm, Pk, w)[np.arange(len(y)), y], EPS, 1)))
    return minimize_scalar(f, bounds=(0.0, 1.0), method="bounded").x


def blend_fn(fixed_w: tuple[float, float] | None = None):
    def fp(tr: pd.DataFrame, tg: pd.DataFrame) -> pd.DataFrame:
        tg = tg.copy()
        y = outcomes(tr)
        Pk, m1, po, m2 = market_probs(tr)
        if fixed_w:
            w1, w2 = fixed_w
        else:
            w1 = _fit_w(tr.loc[m1, P1X2].to_numpy(), Pk[m1], y["1x2"][m1]) if m1.sum() > 500 else 1.0
            Po = np.c_[po[m2], 1 - po[m2]]
            Pmo = np.c_[tr.loc[m2, "p_over"], 1 - tr.loc[m2, "p_over"]]
            w2 = _fit_w(Pmo, Po, 1 - y["over"][m2]) if m2.sum() > 500 else 1.0
        Pk, m1, po, m2 = market_probs(tg)
        tg.loc[m1, P1X2] = _pool(tg.loc[m1, P1X2].to_numpy(), Pk[m1], w1)
        if m2.any():
            Pmo = np.c_[tg.loc[m2, "p_over"], 1 - tg.loc[m2, "p_over"]]
            tg.loc[m2, "p_over"] = _pool(Pmo, np.c_[po[m2], 1 - po[m2]], w2)[:, 0]
        tg["w_model_1x2"], tg["w_model_ou"] = w1, w2
        return tg
    return fp


def chain(*fns):
    def fp(tr, tg):
        # kazda kolejna warstwa uczy sie na wyjsciu poprzednich (out-of-fold z wczesniejszych sezonow)
        for f in fns:
            tg = f(tr, tg)
        return tg
    return fp


def chain_oof(df: pd.DataFrame, seasons: list[str], fns: list, train_from: str = "2008-07-01"
              ) -> pd.DataFrame:
    """Uczciwe skladanie warstw: warstwa k+1 uczy sie na out-of-fold wyjsciach warstwy k.
    Najpierw warstwa k liczona kroczaco dla WSZYSTKICH sezonow (takze treningowych),
    potem kolejna warstwa na tym wyniku."""
    all_seasons = sorted(df["season"].unique())
    cur = df
    for i, f in enumerate(fns):
        last = i == len(fns) - 1
        target_seasons = seasons if last else [s for s in all_seasons if season_cut(s) >
                                               pd.Timestamp(train_from) + pd.Timedelta(days=730)]
        out = walk_forward(cur, target_seasons, f, train_from=train_from)
        if last:
            return out
        cur = out
    return cur


def metrics(df: pd.DataFrame) -> dict:
    """Szybkie metryki do strojenia: log loss 1X2, O/U 2.5, BTTS, takze tam, gdzie jest rynek."""
    y = outcomes(df)
    P = np.clip(df[P1X2].to_numpy(float), EPS, 1)
    P = P / P.sum(axis=1, keepdims=True)
    ll1 = -np.log(P[np.arange(len(df)), y["1x2"]])
    po = np.clip(df["p_over"].to_numpy(float), EPS, 1 - EPS)
    llo = -(y["over"] * np.log(po) + (1 - y["over"]) * np.log(1 - po))
    pb = np.clip(df["p_btts"].to_numpy(float), EPS, 1 - EPS)
    llb = -(y["btts"] * np.log(pb) + (1 - y["btts"]) * np.log(1 - pb))
    Pk, m1, pk, m2 = market_probs(df)
    out = dict(n=len(df), ll_1x2=ll1.mean(), ll_ou=llo.mean(), ll_btts=llb.mean())
    if m1.any():
        out["ll_1x2_m"] = ll1[m1].mean()
        out["mkt_1x2"] = -np.log(Pk[m1][np.arange(m1.sum()), y["1x2"][m1]]).mean()
    if m2.any():
        yo = y["over"][m2]
        out["ll_ou_m"] = llo[m2].mean()
        out["mkt_ou"] = -(yo * np.log(pk[m2]) + (1 - yo) * np.log(1 - pk[m2])).mean()
    return out


def live_apply(past: pd.DataFrame, target: pd.DataFrame, fns: list, train_from: str = "2008-07-01"
               ) -> pd.DataFrame:
    """Cykl dzienny: warstwy uczone na calej historii przed dzisiaj, nakladane na terminarz.
    Warstwa k+1 uczy sie na out-of-fold wyjsciach warstwy k (jak w backteście)."""
    cur = past[pd.to_datetime(past["date"]) >= pd.Timestamp(train_from)]
    tg = target.copy()
    for i, f in enumerate(fns):
        tg = f(cur, tg)
        if i < len(fns) - 1:
            seasons = [s for s in sorted(cur["season"].unique())
                       if season_cut(s) > pd.Timestamp(train_from) + pd.Timedelta(days=730)]
            cur = walk_forward(cur, seasons, f, train_from=train_from)
    return tg
