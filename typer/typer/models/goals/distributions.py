"""Trzy rozklady wyniku meczu przy tych samych srednich goli (mh, ma). Roznia sie zaleznoscia i dyspersja:

  dc         Poisson x Poisson z korekta Dixona-Colesa niskich wynikow (rho)
  bivariate  dwuwymiarowy Poisson (Karlis-Ntzoufras): X = X1 + X3, Y = X2 + X3, wspolna skladowa
             lambda3 = phi * min(mh, ma), wiec srednie brzegowe zostaja rowne mh i ma
  negbin     ujemny dwumianowy dla kazdej druzyny (srednia m, rozmiar r: var = m + m^2/r), niezalezne

Kazda macierz ma wymiar 11x11 (0..10 goli) i jest normalizowana do sumy 1. Parametr zaleznosci/dyspersji
dopasowujemy profilowanym MLE na prawdziwych golach przy srednich z modelu sily (fit.py).
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import gammaln

from typer.models.scores.matrix import MAX_GOALS, score_matrix

G = np.arange(MAX_GOALS + 1)
VARIANTS = ("dc", "bivariate", "negbin")
EPS = 1e-12


# ---------------- macierze ----------------
def dc_matrix(mh: float, ma: float, rho: float) -> np.ndarray:
    return score_matrix(mh, ma, rho)


def bp_matrix(mh: float, ma: float, phi: float) -> np.ndarray:
    l3 = phi * min(mh, ma)
    l1, l2 = max(mh - l3, 1e-9), max(ma - l3, 1e-9)
    x = G[:, None]
    y = G[None, :]
    m = np.zeros((MAX_GOALS + 1, MAX_GOALS + 1))
    base = -(l1 + l2 + l3) + x * np.log(l1) - gammaln(x + 1) + y * np.log(l2) - gammaln(y + 1)
    for k in range(MAX_GOALS + 1):  # suma po wspolnej skladowej X3 = k
        ok = (x >= k) & (y >= k)
        xk, yk = np.maximum(x - k, 0), np.maximum(y - k, 0)
        term = (gammaln(x + 1) - gammaln(xk + 1) - gammaln(k + 1) + gammaln(y + 1) - gammaln(yk + 1)
                + k * (np.log(l3 + EPS) - np.log(l1) - np.log(l2)))
        m += np.where(ok, np.exp(np.where(ok, base + term, -np.inf)), 0.0)
    return m / m.sum()


def nb_pmf(m: float, r: float) -> np.ndarray:
    m = max(m, 1e-9)
    p = r / (r + m)
    return np.exp(gammaln(G + r) - gammaln(r) - gammaln(G + 1) + r * np.log(p) + G * np.log1p(-p))


def nb_matrix(mh: float, ma: float, r: float) -> np.ndarray:
    m = np.outer(nb_pmf(mh, r), nb_pmf(ma, r))
    return m / m.sum()


def matrix(variant: str, mh: float, ma: float, extra: float) -> np.ndarray:
    if variant == "dc":
        return dc_matrix(mh, ma, extra)
    if variant == "bivariate":
        return bp_matrix(mh, ma, extra)
    if variant == "negbin":
        return nb_matrix(mh, ma, extra)
    raise ValueError(variant)


# ---------------- profilowane MLE parametru zaleznosci / dyspersji ----------------
def _ll_dc(rho, gh, ga, mh, ma, w):
    tau = np.ones_like(mh)
    m00, m01, m10, m11 = (gh == 0) & (ga == 0), (gh == 0) & (ga == 1), (gh == 1) & (ga == 0), (gh == 1) & (ga == 1)
    tau[m00] = 1 - mh[m00] * ma[m00] * rho
    tau[m01] = 1 + mh[m01] * rho
    tau[m10] = 1 + ma[m10] * rho
    tau[m11] = 1 - rho
    return float(np.sum(w * np.log(np.clip(tau, EPS, None))))


def _ll_bp(phi, gh, ga, mh, ma, w):
    l3 = phi * np.minimum(mh, ma)
    l1, l2 = np.maximum(mh - l3, 1e-9), np.maximum(ma - l3, 1e-9)
    base = -(l1 + l2 + l3) + gh * np.log(l1) - gammaln(gh + 1) + ga * np.log(l2) - gammaln(ga + 1)
    s = np.zeros_like(mh)
    for k in range(int(min(gh.max(), ga.max())) + 1):
        ok = (gh >= k) & (ga >= k)
        t = (gammaln(gh + 1) - gammaln(np.maximum(gh - k, 0) + 1) - gammaln(k + 1) + gammaln(ga + 1) -
             gammaln(np.maximum(ga - k, 0) + 1) + k * (np.log(l3 + EPS) - np.log(l1) - np.log(l2)))
        s += np.where(ok, np.exp(np.where(ok, t, -np.inf)), 0.0)
    return float(np.sum(w * (base + np.log(np.clip(s, EPS, None)))))


def _ll_nb(log_r, gh, ga, mh, ma, w):
    r = np.exp(log_r)
    tot = 0.0
    for y, m in ((gh, mh), (ga, ma)):
        p = r / (r + m)
        tot += np.sum(w * (gammaln(y + r) - gammaln(r) - gammaln(y + 1) + r * np.log(p) + y * np.log1p(-p)))
    return float(tot)


BOUNDS = {"dc": (-0.25, 0.25), "bivariate": (0.0, 0.6), "negbin": (np.log(0.5), np.log(5000.0))}


def fit_extra(variant: str, gh, ga, mh, ma, w) -> float:
    """Parametr zaleznosci/dyspersji z maksymalizacji wazonej wiarygodnosci przy danych srednich.
    negbin zwraca r (nie log r). r przy gornej granicy = brak nadmiernej dyspersji (praktycznie Poisson)."""
    gh, ga = np.asarray(gh, float), np.asarray(ga, float)
    mh, ma, w = np.asarray(mh, float), np.asarray(ma, float), np.asarray(w, float)
    f = {"dc": _ll_dc, "bivariate": _ll_bp, "negbin": _ll_nb}[variant]
    res = minimize_scalar(lambda x: -f(x, gh, ga, mh, ma, w), bounds=BOUNDS[variant], method="bounded",
                          options=dict(xatol=1e-4))
    return float(np.exp(res.x)) if variant == "negbin" else float(res.x)
