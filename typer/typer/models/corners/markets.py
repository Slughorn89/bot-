"""Rynki rożnych z rozkladu lacznego (modul 3): O/U lacznie, O/U per druzyna, handicap.

Wszystko liczone z jednej macierzy P[i, j] = P(rozne_dom = i, rozne_gosc = j), wiec rynki sa ze soba spojne
(np. O/U lacznie zgadza sie z suma po przekatnych, a handicap z rozkladem roznicy).
Linie polowkowe (9.5) nie maja zwrotu; linie calkowite (10, handicap -1) maja zwrot przy rownej liczbie (push).
"""
from __future__ import annotations

import numpy as np

TOTAL_LINES = [6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5, 13.5]
TEAM_LINES = [2.5, 3.5, 4.5, 5.5, 6.5, 7.5]
HANDICAP_LINES = [x / 2 for x in range(-10, 11)]        # -5.0 .. +5.0 co 0.5, dla gospodarza


def total_pmf(P: np.ndarray) -> np.ndarray:
    C = P.shape[0] - 1
    out = np.zeros(2 * C + 1)
    for i in range(C + 1):
        out[i:i + C + 1] += P[i]
    return out


def diff_pmf(P: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rozklad roznicy dom - gosc: (wartosci, prawdopodobienstwa)."""
    C = P.shape[0] - 1
    d = np.arange(-C, C + 1)
    out = np.zeros(2 * C + 1)
    for i in range(C + 1):
        out[i - np.arange(C + 1) + C] += P[i]
    return d, out


def _ou(pmf: np.ndarray, line: float) -> dict:
    k = np.arange(len(pmf))
    over = float(pmf[k > line].sum())
    push = float(pmf[k == line].sum())
    return dict(over=over, under=1.0 - over - push, push=push)


def handicap(P: np.ndarray, line: float) -> dict:
    """Handicap gospodarza: wygrywa, gdy (rozne_dom + line) > rozne_gosc."""
    d, pd_ = diff_pmf(P)
    adj = d + line
    return dict(home=float(pd_[adj > 0].sum()), away=float(pd_[adj < 0].sum()), push=float(pd_[adj == 0].sum()))


def corner_markets(P: np.ndarray) -> dict:
    P = np.asarray(P, float) / np.sum(P)
    tot = total_pmf(P)
    ph, pa = P.sum(axis=1), P.sum(axis=0)
    k = np.arange(len(tot))
    return {
        "mean_total": float(np.dot(k, tot)),
        "mean_home": float(np.dot(np.arange(len(ph)), ph)),
        "mean_away": float(np.dot(np.arange(len(pa)), pa)),
        "total": {line: _ou(tot, line) for line in TOTAL_LINES},
        "home": {line: _ou(ph, line) for line in TEAM_LINES},
        "away": {line: _ou(pa, line) for line in TEAM_LINES},
        "handicap": {line: handicap(P, line) for line in HANDICAP_LINES},
        "most_corners": dict(home=float(np.tril(P, -1).sum()), draw=float(np.trace(P)),
                             away=float(np.triu(P, 1).sum())),
    }
