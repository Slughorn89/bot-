"""Stan gry w czasie: jaka czesc meczu druzyna prowadzi, remisuje, przegrywa (modul 3).

Rozne zaleza od stanu gry: przegrywajacy atakuje, prowadzacy sie broni. Intensywnosc rożnych druzyny
w minucie t to mu/90 * exp(gamma_stanu(t)), wiec oczekiwana liczba rożnych w meczu:

    E[rozne] = mu * M,   M = f_remis + f_przegrywa * e^{gamma_T} + f_prowadzi * e^{gamma_L}

M jest liniowe w udzialach czasu f, dlatego do dopasowania wystarczaja OCZEKIWANE udzialy.

Dwa zrodla osi czasu:
  * mecze historyczne: znamy wynik do przerwy i koncowy, nie znamy minut goli. Gole w polowie
    rozkladamy jednostajnie, kolejnosc goli w polowie losowa (expected_fractions),
  * symulacja meczu do typowania: wynik koncowy z macierzy modulu 2, podzial goli na polowy
    dwumianowo z udzialem p1 (as of), minuty jednostajnie w polowie (timeline_library).
Ograniczenia: brak doliczonego czasu, brak empirycznych minut goli (beda, gdy API-Football odda zdarzenia).
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

HALF = 45.0
FULL = 90.0
MAX_GOALS = 10


def _fractions(times: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """times, labels: K x n (minuty i +1 gol gospodarza / -1 gosc). Zwraca udzialy (prowadzi, przegrywa)
    gospodarza w czasie meczu dla kazdego z K przebiegow."""
    K, n = times.shape
    if n == 0:
        return np.zeros(K), np.zeros(K)
    order = np.argsort(times, axis=1, kind="stable")
    t = np.take_along_axis(times, order, axis=1)
    lab = np.take_along_axis(labels, order, axis=1)
    diff = np.cumsum(lab, axis=1)                                  # roznica bramek po k-tym golu
    dur = np.diff(np.concatenate([t, np.full((K, 1), FULL)], axis=1), axis=1)  # czas do nastepnego gola
    lead = (dur * (diff > 0)).sum(axis=1) / FULL
    trail = (dur * (diff < 0)).sum(axis=1) / FULL
    return lead, trail


def _labels(rng, K: int, n_home: int, n_away: int) -> np.ndarray:
    base = np.array([1] * n_home + [-1] * n_away, dtype=np.int8)
    if len(base) == 0:
        return np.zeros((K, 0), dtype=np.int8)
    keys = rng.random((K, len(base)))
    return base[np.argsort(keys, axis=1)]


@lru_cache(maxsize=4096)
def expected_fractions(ht_h: int, ht_a: int, ft_h: int, ft_a: int, draws: int = 1000,
                       seed: int = 11) -> tuple[float, float]:
    """Oczekiwane (f_prowadzi, f_przegrywa) gospodarza przy znanym wyniku do przerwy i koncowym."""
    ht_h, ht_a = min(ht_h, ft_h), min(ht_a, ft_a)    # bledy zrodla (HT > FT) nie psuja liczenia
    rng = np.random.default_rng(seed)
    n1, n2 = ht_h + ht_a, (ft_h - ht_h) + (ft_a - ht_a)
    t1 = rng.uniform(0, HALF, (draws, n1))
    t2 = rng.uniform(HALF, FULL, (draws, n2))
    l1 = _labels(rng, draws, ht_h, ht_a)
    l2 = _labels(rng, draws, ft_h - ht_h, ft_a - ht_a)
    lead, trail = _fractions(np.concatenate([t1, t2], axis=1), np.concatenate([l1, l2], axis=1))
    return float(lead.mean()), float(trail.mean())


def match_fractions(hthg, htag, fthg, ftag) -> tuple[np.ndarray, np.ndarray]:
    """Wektorowo dla meczow historycznych; brak wyniku do przerwy = gole rozlozone na caly mecz."""
    out_l, out_t = np.zeros(len(fthg)), np.zeros(len(fthg))
    for k, (a, b, i, j) in enumerate(zip(hthg, htag, fthg, ftag)):
        if not (np.isfinite(i) and np.isfinite(j)):
            continue
        if not (np.isfinite(a) and np.isfinite(b)):
            a, b = round(i * 0.45), round(j * 0.45)
        out_l[k], out_t[k] = expected_fractions(int(a), int(b), int(i), int(j))
    return out_l, out_t


@lru_cache(maxsize=16)
def timeline_library(p1: float, k: int = 4096, seed: int = 5, max_goals: int = MAX_GOALS
                     ) -> tuple[np.ndarray, np.ndarray]:
    """Biblioteka przebiegow dla kazdego wyniku koncowego (i, j), i, j <= max_goals.
    Zwraca dwie tablice (max_goals+1) x (max_goals+1) x k: udzial czasu, gdy gospodarz prowadzi / przegrywa.
    p1: prawdopodobienstwo, ze gol pada w pierwszej polowie (z danych treningowych)."""
    rng = np.random.default_rng(seed)
    G = max_goals + 1
    lead = np.zeros((G, G, k), dtype=np.float32)
    trail = np.zeros((G, G, k), dtype=np.float32)
    for i in range(G):
        for j in range(G):
            n = i + j
            if n == 0:
                continue
            first = rng.random((k, n)) < p1
            t = np.where(first, rng.uniform(0, HALF, (k, n)), rng.uniform(HALF, FULL, (k, n)))
            lab = _labels(rng, k, i, j)
            lead[i, j], trail[i, j] = _fractions(t, lab)
    return lead, trail


def multipliers(lead, trail, g_trail: float, g_lead: float) -> tuple[np.ndarray, np.ndarray]:
    """Mnozniki oczekiwanych rożnych (gospodarz, gosc) dla danych udzialow czasu gospodarza.
    Gosc przegrywa wtedy, gdy gospodarz prowadzi, i odwrotnie."""
    lead, trail = np.asarray(lead, float), np.asarray(trail, float)
    level = 1.0 - lead - trail
    eT, eL = np.exp(g_trail), np.exp(g_lead)
    return level + trail * eT + lead * eL, level + lead * eT + trail * eL


def simulate_states(score_matrix: np.ndarray, p1: float, n_sims: int = 20000, rng=None,
                    resolution: int = 90) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Monte Carlo przebiegu meczu: wynik koncowy z macierzy (modul 2), potem przebieg z biblioteki.
    Zwraca unikalne pary udzialow (prowadzi, przegrywa) z wagami (czestosc / n_sims) oraz wyniki symulacji.
    Udzialy zaokraglone do 1/resolution meczu (minuta), co nie zmienia wynikow, a skraca liczenie rozkladu."""
    rng = rng if rng is not None else np.random.default_rng(0)
    m = np.asarray(score_matrix, float)
    G = min(m.shape[0], MAX_GOALS + 1)
    m = m[:G, :G] / m[:G, :G].sum()
    lead_lib, trail_lib = timeline_library(round(float(p1), 2))
    k = lead_lib.shape[2]
    cdf = np.cumsum(m.ravel())
    cell = np.minimum(np.searchsorted(cdf, rng.random(n_sims) * cdf[-1], side="right"), G * G - 1)
    hi, ai = np.divmod(cell, G)
    pick = rng.integers(0, k, n_sims)
    lead = lead_lib[hi, ai, pick]
    trail = trail_lib[hi, ai, pick]
    key = np.round(lead * resolution).astype(np.int32) * (resolution + 1) + np.round(trail * resolution).astype(np.int32)
    uniq, counts = np.unique(key, return_counts=True)
    ul, ut = np.divmod(uniq, resolution + 1)
    return ul / resolution, ut / resolution, counts / n_sims, np.stack([hi, ai], axis=1)
