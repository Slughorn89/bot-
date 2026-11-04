"""Macierz wynikow: P(gole gospodarza = i, gole goscia = j).

Poisson z korekta Dixona-Colesa dla niskich wynikow (rho), ucieta na MAX_GOALS i ZAWSZE
normalizowana do sumy 1 (uciecie bez normalizacji to realny blad wylapany przez bramki).
"""
from __future__ import annotations

import numpy as np
from scipy.special import gammaln

MAX_GOALS = 10
_G = np.arange(MAX_GOALS + 1)
_LOGFACT = gammaln(_G + 1)


def poisson_pmf(lam: float) -> np.ndarray:
    return np.exp(-lam + _G * np.log(max(lam, 1e-9)) - _LOGFACT)


def dc_tau(lh: float, la: float, rho: float) -> np.ndarray:
    tau = np.ones((MAX_GOALS + 1, MAX_GOALS + 1))
    tau[0, 0] = 1 - lh * la * rho
    tau[0, 1] = 1 + lh * rho
    tau[1, 0] = 1 + la * rho
    tau[1, 1] = 1 - rho
    return np.clip(tau, 0.0, None)


def score_matrix(lh: float, la: float, rho: float = 0.0) -> np.ndarray:
    ph = poisson_pmf(lh)
    pa = poisson_pmf(la)
    m = np.outer(ph, pa)
    if rho:
        m *= dc_tau(lh, la, rho)
    return m / m.sum()


def fast_markets(lh: float, la: float, rho: float = 0.0) -> tuple[float, float, float, float, float]:
    """Szybka sciezka dla backtestu: (p_home, p_draw, p_away, p_over2.5, p_btts)."""
    m = score_matrix(lh, la, rho)
    ph = float(np.tril(m, -1).sum())
    pd_ = float(np.trace(m))
    tot = _total_dist(m)
    over = float(tot[3:].sum())
    btts = float(1 - m[0, :].sum() - m[:, 0].sum() + m[0, 0])
    return ph, pd_, 1 - ph - pd_, over, btts


def _total_dist(m: np.ndarray) -> np.ndarray:
    n = m.shape[0]
    out = np.zeros(2 * n - 1)
    for i in range(n):
        out[i:i + n] += m[i]
    return out
