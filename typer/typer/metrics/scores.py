"""Log loss, Brier, ECE i tabele niezawodnosci (modul 6).

Konwencje:
  * rynek binarny: p (n,) = P(zdarzenie), y (n,) w {0, 1},
  * rynek wieloklasowy (1X2): P (n, k), y (n,) = indeks wyniku.
ECE: srednia wazona |srednie p - czestosc| po przedzialach. Domyslnie 10 przedzialow rownej licznosci
("quantile"): przy skupionych p (np. remis 0.2 do 0.3) przedzialy rownej szerokosci bylyby prawie puste.
Dla 1X2 ECE per klasa (jeden przeciw reszcie) i srednia po klasach ("classwise ECE").
ECE ma dodatnie obciazenie przy malym n (szum w przedzialach), dlatego porownujemy metody na tych samych
meczach i podajemy CI z bootstrapu.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-12


def _as2d(P):
    P = np.asarray(P, float)
    return P if P.ndim == 2 else np.c_[1 - P, P]


def log_loss(P, y) -> float:
    return float(per_event_log_loss(P, y).mean())


def per_event_log_loss(P, y) -> np.ndarray:
    P, y = np.asarray(P, float), np.asarray(y)
    if P.ndim == 1:
        p = np.clip(P, EPS, 1 - EPS)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))
    Q = np.clip(P, EPS, 1)
    Q = Q / Q.sum(axis=1, keepdims=True)
    return -np.log(Q[np.arange(len(y)), y.astype(int)])


def brier(P, y) -> float:
    """Binarny: mean (p - y)^2. Wieloklasowy: mean sum_k (P_k - 1[y = k])^2 (zakres 0..2)."""
    P, y = np.asarray(P, float), np.asarray(y)
    if P.ndim == 1:
        return float(np.mean((P - y) ** 2))
    Y = np.zeros_like(P)
    Y[np.arange(len(y)), y.astype(int)] = 1
    return float(np.mean(((P - Y) ** 2).sum(axis=1)))


def _edges(p, bins, strategy):
    if strategy == "uniform":
        return np.linspace(0, 1, bins + 1)
    if strategy == "quantile":
        e = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
        e[0], e[-1] = -np.inf, np.inf
        return e
    raise ValueError(strategy)


def reliability_table(p, y, bins: int = 10, strategy: str = "quantile") -> pd.DataFrame:
    """Przedzialy: n, srednie p, czestosc, przedzial Wilsona 95% dla czestosci."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    e = _edges(p, bins, strategy)
    idx = np.clip(np.searchsorted(e, p, side="right") - 1, 0, len(e) - 2)
    rows = []
    for b in range(len(e) - 1):
        m = idx == b
        n = int(m.sum())
        if n == 0:
            continue
        f, z = y[m].mean(), 1.96
        den = 1 + z ** 2 / n
        c = (f + z ** 2 / (2 * n)) / den
        h = z * np.sqrt(f * (1 - f) / n + z ** 2 / (4 * n ** 2)) / den
        rows.append(dict(przedzial=b, n=n, p_srednie=float(p[m].mean()), czestosc=float(f),
                         ci_lo=float(c - h), ci_hi=float(c + h)))
    return pd.DataFrame(rows)


def ece(p, y, bins: int = 10, strategy: str = "quantile") -> float:
    """Binarny ECE; dla macierzy (n, k) srednia ECE po klasach (jeden przeciw reszcie)."""
    p, y = np.asarray(p, float), np.asarray(y)
    if p.ndim == 2:
        return float(np.mean([ece(p[:, j], (y == j).astype(float), bins, strategy) for j in range(p.shape[1])]))
    t = reliability_table(p, y, bins, strategy)
    if t.empty:
        return float("nan")
    return float(np.sum(t["n"] * np.abs(t["p_srednie"] - t["czestosc"])) / t["n"].sum())


def bootstrap_ci(fn, arrays, n_boot: int = 2000, seed: int = 7, levels=(90, 95)) -> dict:
    """fn(*arrays_po_losowaniu) -> liczba. Losowanie zdarzen ze zwracaniem, te same indeksy dla wszystkich tablic."""
    arrays = [np.asarray(a) for a in arrays]
    n = len(arrays[0])
    rng = np.random.default_rng(seed)
    vals = np.array([fn(*[a[ix] for a in arrays]) for ix in rng.integers(0, n, (n_boot, n))])
    out = {"wartosc": float(fn(*arrays))}
    for lv in levels:
        a = (100 - lv) / 2
        out[f"ci{lv}"] = (float(np.nanpercentile(vals, a)), float(np.nanpercentile(vals, 100 - a)))
    return out


def summary(P, y, bins: int = 10) -> dict:
    return dict(n=int(len(y)), log_loss=log_loss(P, y), brier=brier(P, y), ece=ece(P, y, bins))
