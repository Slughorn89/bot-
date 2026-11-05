"""Usuwanie marzy z kursow (modul 6): proporcjonalna, Shina, potegowa.

Wejscie: kursy dziesietne jednego rynku, ksztalt (..., k), k = liczba wynikow (3 dla 1X2, 2 dla O/U).
Wszystkie metody zwracaja prawdopodobienstwa sumujace sie do 1 w kazdym wierszu.

  proportional  p_i = pi_i / sum(pi),  pi_i = 1 / o_i. Marza rozlozona proporcjonalnie do p.
  shin          model Shina (1993): czesc obrotu to gracze z informacja poufna (udzial z).
                p_i(z) = (sqrt(z^2 + 4 (1 - z) pi_i^2 / sum(pi)) - z) / (2 (1 - z)), z z warunku sum p = 1.
                Wiecej marzy zdejmuje z outsiderow (efekt faworyt-outsider).
  power         p_i = pi_i^k, k z warunku sum p = 1 (k > 1, gdy jest marza). Tez wiecej z outsiderow.
Gdy suma pi <= 1 (brak marzy albo arbitraz), Shin wraca do proporcjonalnej (z = 0 nie istnieje w modelu).
Pierwiastek liczymy bisekcja wektorowo: 80 krokow daje dokladnosc ponizej 1e-15 na przedziale.
"""
from __future__ import annotations

import numpy as np

METHODS = ("proportional", "shin", "power")


def _inv(odds) -> np.ndarray:
    o = np.asarray(odds, dtype=float)
    if np.any(o <= 1.0):
        raise ValueError("kurs dziesietny musi byc > 1")
    return 1.0 / o


def proportional(odds) -> np.ndarray:
    pi = _inv(odds)
    return pi / pi.sum(axis=-1, keepdims=True)


def _shin_p(pi, S, z):
    return (np.sqrt(z ** 2 + 4 * (1 - z) * pi ** 2 / S) - z) / (2 * (1 - z))


def shin(odds, return_param: bool = False):
    pi = _inv(odds)
    S = pi.sum(axis=-1, keepdims=True)
    lo, hi = np.zeros_like(S), np.full_like(S, 0.999)
    for _ in range(80):              # suma p(z) maleje w z; szukamy sumy = 1
        mid = (lo + hi) / 2
        big = _shin_p(pi, S, mid).sum(axis=-1, keepdims=True) > 1
        lo, hi = np.where(big, mid, lo), np.where(big, hi, mid)
    z = (lo + hi) / 2
    p = _shin_p(pi, S, z)
    p = p / p.sum(axis=-1, keepdims=True)
    nomargin = S <= 1.0
    p = np.where(nomargin, pi / S, p)
    z = np.where(nomargin, 0.0, z)
    return (p, z[..., 0]) if return_param else p


def power(odds, return_param: bool = False):
    pi = _inv(odds)
    lo, hi = np.full(pi.shape[:-1] + (1,), np.log(0.2)), np.full(pi.shape[:-1] + (1,), np.log(20.0))
    for _ in range(80):              # suma pi^k maleje w k
        mid = (lo + hi) / 2
        big = (pi ** np.exp(mid)).sum(axis=-1, keepdims=True) > 1
        lo, hi = np.where(big, mid, lo), np.where(big, hi, mid)
    k = np.exp((lo + hi) / 2)
    p = pi ** k
    p = p / p.sum(axis=-1, keepdims=True)
    return (p, k[..., 0]) if return_param else p


def devig(odds, method: str = "proportional") -> np.ndarray:
    if method == "proportional":
        return proportional(odds)
    if method == "shin":
        return shin(odds)
    if method == "power":
        return power(odds)
    raise ValueError(f"nieznana metoda {method}; dostepne: {METHODS}")


def devig_rows(odds: np.ndarray, method: str) -> np.ndarray:
    """Jak devig, ale wiersze z brakujacym kursem daja NaN zamiast bledu."""
    odds = np.asarray(odds, dtype=float)
    out = np.full(odds.shape, np.nan)
    ok = np.isfinite(odds).all(axis=-1) & (odds > 1).all(axis=-1)
    if ok.any():
        out[ok] = devig(odds[ok], method)
    return out
