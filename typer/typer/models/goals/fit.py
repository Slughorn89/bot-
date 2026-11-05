"""Dopasowanie sily druzyn dla modelu goli (modul 2), na jednej lidze, na danych sprzed odciecia.

log mh = mu + h + atk[dom] - obr[gosc] + Xh . beta
log ma = mu       + atk[gosc] - obr[dom] + Xa . beta

  * wagi czasowe: w = 0.5 ** (wiek_dni / half_life),
  * cel: y = (1 - w_xg) * gole + w_xg * xG (xG ze zrodla, a gdy go brak: proxy ze strzalow),
    quasi-wiarygodnosc Poissona dziala dla y niecalkowitych,
  * regularyzacja: atk/obr sciagane do priorytetu (0 dla znanych druzyn, prior beniaminka dla nowych),
  * start z parametrow poprzedniego dopasowania (szybkie cotygodniowe przeliczanie).
Rozklad wyniku (dc / bivariate / negbin) dostaje te same srednie, a jego wlasny parametr jest
profilowany na prawdziwych golach (distributions.fit_extra).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize

XG_SOT, XG_OFF = 0.27, 0.006  # proxy xG ze strzalow (MNK na rozgrzewce, experiments.md wpis 1)


@dataclass
class Strengths:
    mu: float
    home: float
    atk: dict
    obr: dict
    beta: np.ndarray
    prior: dict = field(default_factory=dict)   # druzyna -> (atk, obr) dla nieznanych
    promoted_prior: tuple = (-0.2, -0.2)

    def team(self, t: str) -> tuple[float, float]:
        if t in self.atk:
            return self.atk[t], self.obr[t]
        return self.prior.get(t, self.promoted_prior)

    def rates(self, home: str, away: str, xh=None, xa=None) -> tuple[float, float]:
        ah, oh = self.team(home)
        aa, oa = self.team(away)
        bh = float(np.dot(self.beta, xh)) if xh is not None and len(self.beta) else 0.0
        ba = float(np.dot(self.beta, xa)) if xa is not None and len(self.beta) else 0.0
        return float(np.exp(self.mu + self.home + ah - oa + bh)), float(np.exp(self.mu + aa - oh + ba))


def target(df: pd.DataFrame, w_xg: float) -> tuple[np.ndarray, np.ndarray]:
    gh, ga = df["fthg"].to_numpy(float), df["ftag"].to_numpy(float)
    if w_xg <= 0:
        return gh, ga

    def xg(goals, real, shots, sot):
        prox = XG_SOT * sot + XG_OFF * np.clip(shots - sot, 0, None)
        x = np.where(np.isfinite(real), real, prox)
        return np.where(np.isfinite(x), x, goals)  # brak strzalow i xG = same gole

    col = lambda c: df[c].to_numpy(float) if c in df.columns else np.full(len(df), np.nan)
    xh = xg(gh, col("xg_h"), col("hs"), col("hst"))
    xa = xg(ga, col("xg_a"), col("as_"), col("ast"))
    return (1 - w_xg) * gh + w_xg * xh, (1 - w_xg) * ga + w_xg * xa


def time_weights(dates, cutoff, half_life: float) -> np.ndarray:
    """Zanik wykladniczy: mecz sprzed half_life dni ma wage 0.5, sprzed 2*half_life 0.25."""
    age = (pd.Timestamp(cutoff) - pd.to_datetime(pd.Series(dates))).dt.days.to_numpy(float)
    return 0.5 ** (np.clip(age, 0, None) / half_life)


def make_objective(hi, ai, n, w, yh, ya, Xh, Xa, pa, po, ridge, ridge_beta):
    """Funkcja celu (ujemna wazona quasi-wiarygodnosc Poissona + regularyzacja) z gradientem analitycznym."""
    def f(th):
        mu, h, atk, obr, beta = th[0], th[1], th[2:2 + n], th[2 + n:2 + 2 * n], th[2 + 2 * n:]
        lh = mu + h + atk[hi] - obr[ai] + Xh @ beta
        la = mu + atk[ai] - obr[hi] + Xa @ beta
        eh, ea = np.exp(lh), np.exp(la)
        loss = np.sum(w * (eh - yh * lh)) + np.sum(w * (ea - ya * la))
        loss += ridge * (np.sum((atk - pa) ** 2) + np.sum((obr - po) ** 2)) + ridge_beta * np.sum(beta ** 2)
        rh, ra = w * (eh - yh), w * (ea - ya)
        g = np.empty_like(th)
        g[0] = rh.sum() + ra.sum()
        g[1] = rh.sum()
        g[2:2 + n] = np.bincount(hi, rh, n) + np.bincount(ai, ra, n) + 2 * ridge * (atk - pa)
        g[2 + n:2 + 2 * n] = -np.bincount(ai, rh, n) - np.bincount(hi, ra, n) + 2 * ridge * (obr - po)
        g[2 + 2 * n:] = Xh.T @ rh + Xa.T @ ra + 2 * ridge_beta * beta
        return loss, g
    return f


def fit_strengths(train: pd.DataFrame, cutoff, half_life: float, w_xg: float, ridge: float = 3.0,
                  ridge_beta: float = 10.0, cov_h: np.ndarray | None = None, cov_a: np.ndarray | None = None,
                  promoted: set | None = None, promoted_prior=(-0.2, -0.2), warm: Strengths | None = None
                  ) -> tuple[Strengths, dict]:
    """Zwraca (sily, dane treningowe do profilowania parametru rozkladu)."""
    teams = sorted(set(train["home"]) | set(train["away"]))
    ix = {t: i for i, t in enumerate(teams)}
    n, k = len(teams), (0 if cov_h is None else cov_h.shape[1])
    hi = train["home"].map(ix).to_numpy()
    ai = train["away"].map(ix).to_numpy()
    w = time_weights(train["date"], cutoff, half_life)
    yh, ya = target(train, w_xg)
    promoted = promoted or set()
    pa = np.array([promoted_prior[0] if t in promoted else 0.0 for t in teams])
    po = np.array([promoted_prior[1] if t in promoted else 0.0 for t in teams])
    Xh = cov_h if k else np.zeros((len(train), 0))
    Xa = cov_a if k else np.zeros((len(train), 0))

    f = make_objective(hi, ai, n, w, yh, ya, Xh, Xa, pa, po, ridge, ridge_beta)

    def unpack(th):
        return th[0], th[1], th[2:2 + n], th[2 + n:2 + 2 * n], th[2 + 2 * n:]

    th0 = np.zeros(2 + 2 * n + k)
    th0[0], th0[1] = np.log(max(np.average(ya, weights=w), 0.1)), 0.25
    th0[2:2 + n], th0[2 + n:2 + 2 * n] = pa, po
    if warm is not None:  # start z poprzedniego tygodnia
        th0[0], th0[1] = warm.mu, warm.home
        for t, i in ix.items():
            if t in warm.atk:
                th0[2 + i], th0[2 + n + i] = warm.atk[t], warm.obr[t]
        if len(warm.beta) == k:
            th0[2 + 2 * n:] = warm.beta
    res = minimize(f, th0, jac=True, method="L-BFGS-B", options=dict(maxiter=500))
    mu, h, atk, obr, beta = unpack(res.x)
    s = Strengths(mu=float(mu), home=float(h), atk=dict(zip(teams, atk)), obr=dict(zip(teams, obr)),
                  beta=np.asarray(beta), promoted_prior=tuple(promoted_prior))
    mh = np.exp(mu + h + atk[hi] - obr[ai] + Xh @ beta)
    ma = np.exp(mu + atk[ai] - obr[hi] + Xa @ beta)
    data = dict(gh=train["fthg"].to_numpy(float), ga=train["ftag"].to_numpy(float), mh=mh, ma=ma, w=w,
                converged=bool(res.success), n=len(train))
    return s, data
