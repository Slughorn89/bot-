"""Rozklad laczny rożnych meczu (modul 3): z efektem stanu gry (Monte Carlo) albo bez.

Wersja B (ze stanem): 20 000 symulacji przebiegu meczu. Kazda symulacja losuje wynik koncowy z macierzy
modulu 2, potem minuty goli (state.simulate_states). Przebieg daje mnozniki M_dom, M_gosc, a rozne przy danym
przebiegu maja rozklad z fit.py (NB z frailty dominacji). Zamiast losowac rozne w kazdej symulacji,
usredniamy WARUNKOWE rozklady po symulacjach (Rao-Blackwell): ten sam wynik, mniejszy szum Monte Carlo.
Wersja A (bez stanu): jeden "przebieg" z M = 1.
Ta sama macierz i to samo ziarno w obu wersjach (wspolne liczby losowe), wiec gdy gamma = 0, B == A.
"""
from __future__ import annotations

import numpy as np
from scipy.special import gammaln

from typer.models.corners.fit import GH_U, GH_W, CornerStrengths
from typer.models.corners.state import multipliers, simulate_states

MAX_CORNERS = 50          # ostatnia komorka zbiera ogon; w danych maks. 26 rożnych druzyny, przy 30 skrajne
                          # parametry (r = 3, sigma = 0.5) zanizaly srednia o 1.7%, przy 50 o < 0.5%
N_SIMS = 20000


def _nb_pmf_grid(m: np.ndarray, r: float, C: int = MAX_CORNERS) -> np.ndarray:
    """m: dowolny ksztalt; zwraca m.shape + (C+1,), ogon >= C dodany do ostatniej komorki."""
    y = np.arange(C + 1, dtype=float)
    m = np.maximum(m, 1e-9)[..., None]
    lp = gammaln(y + r) - gammaln(r) - gammaln(y + 1) + r * np.log(r / (r + m)) + y * np.log(m / (r + m))
    p = np.exp(lp)
    p[..., -1] += np.clip(1.0 - p.sum(axis=-1), 0, None)
    return p


def joint_pmf(mu_h: float, mu_a: float, r: float, sigma: float, Mh=None, Ma=None, wts=None,
              C: int = MAX_CORNERS) -> np.ndarray:
    """P(rozne_dom = i, rozne_gosc = j), macierz (C+1) x (C+1), suma 1.
    Mh, Ma, wts: mnozniki stanu z wagami (z symulacji); brak = jeden przebieg z M = 1."""
    Mh = np.ones(1) if Mh is None else np.asarray(Mh, float)
    Ma = np.ones(1) if Ma is None else np.asarray(Ma, float)
    wts = np.ones(len(Mh)) / len(Mh) if wts is None else np.asarray(wts, float)
    eh = np.exp(sigma * GH_U - 0.5 * sigma ** 2)                  # Q wezlow frailty, srednia 1
    ea = np.exp(-sigma * GH_U - 0.5 * sigma ** 2)
    ph = _nb_pmf_grid(mu_h * Mh[:, None] * eh[None, :], r, C)     # K x Q x (C+1)
    pa = _nb_pmf_grid(mu_a * Ma[:, None] * ea[None, :], r, C)
    W = wts[:, None] * GH_W[None, :]
    P = np.einsum("kq,kqi,kqj->ij", W, ph, pa)
    return P / P.sum()


def corner_distribution(s: CornerStrengths, home: str, away: str, score_matrix: np.ndarray | None = None,
                        xh=None, xa=None, n_sims: int = N_SIMS, seed: int = 0, use_state: bool | None = None
                        ) -> dict:
    """Pelny rozklad rożnych meczu. use_state=None: wedlug modelu (s.state); B wymaga macierzy wynikow."""
    use_state = s.state if use_state is None else use_state
    mu_h, mu_a = s.base_rates(home, away, xh, xa)
    if not use_state:
        return dict(joint=joint_pmf(mu_h, mu_a, s.r, s.sigma), mu_h=mu_h, mu_a=mu_a, n_sims=0)
    if score_matrix is None:
        raise ValueError("wersja ze stanem gry wymaga macierzy wynikow z modulu 2")
    rng = np.random.default_rng(seed)
    lead, trail, wts, scores = simulate_states(score_matrix, s.p1, n_sims, rng)
    Mh, Ma = multipliers(lead, trail, s.g_trail, s.g_lead)
    P = joint_pmf(mu_h, mu_a, s.r, s.sigma, Mh, Ma, wts)
    return dict(joint=P, mu_h=mu_h * float(np.dot(wts, Mh)), mu_a=mu_a * float(np.dot(wts, Ma)),
                n_sims=n_sims, sim_scores=scores)
