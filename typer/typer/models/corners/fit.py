"""Model rzutow roznych (modul 3): ujemny dwumianowy per druzyna z korekta na rywala.

Srednia (jedna liga, mecze sprzed odciecia, wagi 0.5^(wiek/half_life)):
    log mu_dom  = c + h + atk[dom]  - obr[gosc] + x_dom  . beta + log M_dom(gamma)
    log mu_gosc = c     + atk[gosc] - obr[dom]  + x_gosc . beta + log M_gosc(gamma)
  atk = ile rożnych druzyna wypracowuje, obr = ile rożnych nie dopuszcza (wyzsze = mniej rożnych rywala),
  M(gamma) = mnoznik stanu gry (state.py), w wersji bez stanu M = 1.
  Srednia z quasi-wiarygodnosci Poissona (zgodna takze przy nadrozproszeniu), gradient analityczny.

Rozklad laczny (rozne gospodarza i goscia w jednym meczu):
    y_dom  | u ~ NB(mu_dom  * e^{+u - sigma^2/2}, r)
    y_gosc | u ~ NB(mu_gosc * e^{-u - sigma^2/2}, r),     u ~ N(0, sigma^2)
  (poprawka -sigma^2/2 zachowuje srednie: E[e^{u - sigma^2/2}] = 1, bez niej frailty zawyza rozne o ok. 1.5%)
  u to "dominacja" w danym meczu: kto ma pilke, ten ma rozne, a rywal ich nie ma. Bez u dwa niezalezne NB
  daja za szeroki rozklad sumy (w danych korelacja reszt -0.19, suma prawie poissonowska).
  r i sigma profilowane metoda najwiekszej wiarygodnosci przy ustalonych srednich (kwadratura Gaussa-Hermite'a).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln, logsumexp

from typer.models.corners.state import match_fractions
from typer.models.goals.fit import time_weights

GH_NODES = 15
R_BOUNDS = (np.log(3.0), np.log(2000.0))   # zakres pokryty testem zachowania srednich (dopasowania: r ok. 45)
SIGMA_BOUNDS = (0.0, 0.5)                  # dopasowania: sigma ok. 0.17
_X, _W = np.polynomial.hermite.hermgauss(GH_NODES)
GH_U = np.sqrt(2.0) * _X                 # wezly dla N(0, 1)
GH_W = _W / np.sqrt(np.pi)


def nb_logpmf(y, m, r):
    y, m = np.asarray(y, float), np.maximum(np.asarray(m, float), 1e-9)
    return gammaln(y + r) - gammaln(r) - gammaln(y + 1) + r * np.log(r / (r + m)) + y * np.log(m / (r + m))


def joint_loglik(yh, ya, mh, ma, r: float, sigma: float) -> np.ndarray:
    """log P(y_dom, y_gosc) dla kazdego meczu przy srednich mh, ma (z mnoznikiem stanu, jesli jest)."""
    u = sigma * GH_U[None, :]
    adj = -0.5 * sigma ** 2
    lh = nb_logpmf(np.asarray(yh, float)[:, None], np.asarray(mh, float)[:, None] * np.exp(u + adj), r)
    la = nb_logpmf(np.asarray(ya, float)[:, None], np.asarray(ma, float)[:, None] * np.exp(-u + adj), r)
    return logsumexp(lh + la + np.log(GH_W)[None, :], axis=1)


def fit_dispersion(yh, ya, mh, ma, w, frailty: bool = True) -> tuple[float, float]:
    """(r, sigma) z najwiekszej wazonej wiarygodnosci; frailty=False: sigma = 0 (niezalezne NB)."""
    w = np.asarray(w, float)

    def nll(p):
        r = np.exp(p[0])
        s = p[1] if frailty else 0.0
        return -np.sum(w * joint_loglik(yh, ya, mh, ma, r, s))

    x0 = [np.log(15.0), 0.15 if frailty else 0.0]
    bounds = [R_BOUNDS, SIGMA_BOUNDS if frailty else (0.0, 0.0)]
    res = minimize(nll, x0, method="L-BFGS-B", bounds=bounds)
    return float(np.exp(res.x[0])), float(res.x[1] if frailty else 0.0)


@dataclass
class CornerStrengths:
    c: float
    home: float
    atk: dict
    obr: dict
    beta: np.ndarray
    g_trail: float = 0.0
    g_lead: float = 0.0
    r: float = 15.0
    sigma: float = 0.0
    p1: float = 0.45                  # udzial goli w pierwszej polowie (do symulacji przebiegu)
    state: bool = False
    info: dict = field(default_factory=dict)

    def team(self, t: str) -> tuple[float, float]:
        return self.atk.get(t, 0.0), self.obr.get(t, 0.0)   # nieznana druzyna = srednia ligi

    def base_rates(self, home: str, away: str, xh=None, xa=None) -> tuple[float, float]:
        """Srednie rożnych bez mnoznika stanu (dla wersji bez stanu sa to srednie ostateczne)."""
        ah, oh = self.team(home)
        aa, oa = self.team(away)
        bh = float(np.dot(self.beta, xh)) if xh is not None and len(self.beta) else 0.0
        ba = float(np.dot(self.beta, xa)) if xa is not None and len(self.beta) else 0.0
        return float(np.exp(self.c + self.home + ah - oa + bh)), float(np.exp(self.c + aa - oh + ba))


def make_objective(hi, ai, n, w, yh, ya, Xh, Xa, lead, trail, ridge, ridge_beta, ridge_gamma, state):
    """Ujemna wazona quasi-wiarygodnosc Poissona + regularyzacja, z gradientem analitycznym.
    Wektor parametrow: c, h, atk[n], obr[n], beta[k], (g_trail, g_lead gdy state)."""
    k = Xh.shape[1]
    lvl = 1.0 - lead - trail

    def f(th):
        c, h = th[0], th[1]
        atk, obr, beta = th[2:2 + n], th[2 + n:2 + 2 * n], th[2 + 2 * n:2 + 2 * n + k]
        eh_lin = c + h + atk[hi] - obr[ai] + Xh @ beta
        ea_lin = c + atk[ai] - obr[hi] + Xa @ beta
        if state:
            gT, gL = th[-2], th[-1]
            eT, eL = np.exp(gT), np.exp(gL)
            Mh = lvl + trail * eT + lead * eL
            Ma = lvl + lead * eT + trail * eL
            eh_lin = eh_lin + np.log(Mh)
            ea_lin = ea_lin + np.log(Ma)
        eh, ea = np.exp(eh_lin), np.exp(ea_lin)
        loss = np.sum(w * (eh - yh * eh_lin)) + np.sum(w * (ea - ya * ea_lin))
        loss += ridge * (np.sum(atk ** 2) + np.sum(obr ** 2)) + ridge_beta * np.sum(beta ** 2)
        rh, ra = w * (eh - yh), w * (ea - ya)
        g = np.zeros_like(th)
        g[0] = rh.sum() + ra.sum()
        g[1] = rh.sum()
        g[2:2 + n] = np.bincount(hi, rh, n) + np.bincount(ai, ra, n) + 2 * ridge * atk
        g[2 + n:2 + 2 * n] = -np.bincount(ai, rh, n) - np.bincount(hi, ra, n) + 2 * ridge * obr
        g[2 + 2 * n:2 + 2 * n + k] = Xh.T @ rh + Xa.T @ ra + 2 * ridge_beta * beta
        if state:
            loss += ridge_gamma * (gT ** 2 + gL ** 2)
            g[-2] = np.sum(rh * trail * eT / Mh) + np.sum(ra * lead * eT / Ma) + 2 * ridge_gamma * gT
            g[-1] = np.sum(rh * lead * eL / Mh) + np.sum(ra * trail * eL / Ma) + 2 * ridge_gamma * gL
        return loss, g
    return f


def fit_corners(train: pd.DataFrame, cutoff, half_life: float = 365.0, ridge: float = 3.0,
                ridge_beta: float = 10.0, ridge_gamma: float = 1.0, state: bool = False, frailty: bool = True,
                cov_h: np.ndarray | None = None, cov_a: np.ndarray | None = None,
                warm: CornerStrengths | None = None) -> tuple[CornerStrengths, dict]:
    """train: rozegrane mecze JEDNEJ ligi sprzed odciecia, z kolumnami hc, ac (i hthg, htag dla stanu)."""
    train = train[train["hc"].notna() & train["ac"].notna()]
    teams = sorted(set(train["home"]) | set(train["away"]))
    ix = {t: i for i, t in enumerate(teams)}
    n, k = len(teams), (0 if cov_h is None else cov_h.shape[1])
    hi = train["home"].map(ix).to_numpy()
    ai = train["away"].map(ix).to_numpy()
    w = time_weights(train["date"], cutoff, half_life)
    yh, ya = train["hc"].to_numpy(float), train["ac"].to_numpy(float)
    Xh = cov_h if k else np.zeros((len(train), 0))
    Xa = cov_a if k else np.zeros((len(train), 0))
    if state:
        lead, trail = match_fractions(train["hthg"].to_numpy(float), train["htag"].to_numpy(float),
                                      train["fthg"].to_numpy(float), train["ftag"].to_numpy(float))
    else:
        lead = trail = np.zeros(len(train))
    f = make_objective(hi, ai, n, w, yh, ya, Xh, Xa, lead, trail, ridge, ridge_beta, ridge_gamma, state)
    th0 = np.zeros(2 + 2 * n + k + (2 if state else 0))
    th0[0], th0[1] = np.log(max(np.average(ya, weights=w), 0.5)), 0.15
    if warm is not None:
        th0[0], th0[1] = warm.c, warm.home
        for t, i in ix.items():
            if t in warm.atk:
                th0[2 + i], th0[2 + n + i] = warm.atk[t], warm.obr[t]
        if len(warm.beta) == k:
            th0[2 + 2 * n:2 + 2 * n + k] = warm.beta
        if state and warm.state:
            th0[-2], th0[-1] = warm.g_trail, warm.g_lead
    res = minimize(f, th0, jac=True, method="L-BFGS-B", options=dict(maxiter=500))
    th = res.x
    c, h = th[0], th[1]
    atk, obr, beta = th[2:2 + n], th[2 + n:2 + 2 * n], th[2 + 2 * n:2 + 2 * n + k]
    gT, gL = (th[-2], th[-1]) if state else (0.0, 0.0)
    lvl = 1 - lead - trail
    Mh = lvl + trail * np.exp(gT) + lead * np.exp(gL)
    Ma = lvl + lead * np.exp(gT) + trail * np.exp(gL)
    mh = np.exp(c + h + atk[hi] - obr[ai] + Xh @ beta) * Mh
    ma = np.exp(c + atk[ai] - obr[hi] + Xa @ beta) * Ma
    r, sigma = fit_dispersion(yh, ya, mh, ma, w, frailty=frailty)
    goals = train["fthg"].to_numpy(float) + train["ftag"].to_numpy(float)
    ht = train["hthg"].to_numpy(float) + train["htag"].to_numpy(float) if "hthg" in train else np.full(len(train), np.nan)
    ok = np.isfinite(ht) & np.isfinite(goals)
    p1 = float(np.sum(w[ok] * ht[ok]) / max(np.sum(w[ok] * goals[ok]), 1e-9)) if ok.any() else 0.45
    s = CornerStrengths(c=float(c), home=float(h), atk=dict(zip(teams, atk)), obr=dict(zip(teams, obr)),
                        beta=np.asarray(beta), g_trail=float(gT), g_lead=float(gL), r=r, sigma=sigma,
                        p1=min(max(p1, 0.3), 0.6), state=state,
                        info=dict(n=len(train), converged=bool(res.success)))
    return s, dict(yh=yh, ya=ya, mh=mh, ma=ma, w=w)
