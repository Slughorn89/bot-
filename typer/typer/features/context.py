"""Cechy kontekstu meczu dla modelu goli (modul 2), liczone "as of" odciecia typu.

Kolumny (dla gospodarza i goscia osobno, wchodza do log lambda z jednym wspolnym beta):
  rest         odpoczynek: (min(dni od poprzedniego meczu ligowego, 14) - 7) / 7
  congestion   mecze ligowe druzyny w ostatnich 7 dniach / 2 (pucharow w danych nie ma: ograniczenie)
  dead_rubber  "mecz o nic": po 70% sezonu druzyna ani nie dogoni miejsca europejskiego, ani nie spadnie,
               liczone z tabeli z wynikow sprzed odciecia (nie z tabeli "na dzis")
  derby        para z config/derbies.yaml
  precip, wind pogoda (kolumny precip_mm, wind_kmh z prognozy dostepnej przed meczem), brak = 0
  referee_pen  karne na mecz sedziego "as of" minus srednia ligi (kolumna ref_pen_rate), brak = 0
  travel       podroz goscia w tys. km (kolumna travel_km, wymaga wspolrzednych stadionow), brak = 0
Brak danych = 0, a regularyzacja beta sciaga wtedy wplyw do zera.
"""
from __future__ import annotations

from collections import defaultdict, deque

import numpy as np
import pandas as pd

from typer import config
from typer.features.asof import prediction_cutoff

COV_NAMES = ["rest", "congestion", "dead_rubber", "derby", "precip", "wind", "referee_pen", "travel"]
EUROPE_PLACES, RELEGATION_PLACES, DEAD_FROM = 4, 3, 0.7


def _derbies(league: str) -> set[frozenset]:
    pairs = (config.load_yaml("derbies.yaml") or {}).get(league) or []
    return {frozenset(p) for p in pairs}


def _table_dead(points: dict, played: dict, total: dict) -> set[str]:
    """Druzyny, dla ktorych mecz nic nie zmienia (wg tabeli w chwili odciecia)."""
    if not points:
        return set()
    order = sorted(points, key=lambda t: -points[t])
    n = len(order)
    if n < EUROPE_PLACES + RELEGATION_PLACES + 2:
        return set()
    p_top = points[order[EUROPE_PLACES - 1]]
    rel_team = order[n - RELEGATION_PLACES]          # pierwsze miejsce spadkowe
    p_rel = points[rel_team]
    rem_rel = max(total.get(rel_team, 0) - played.get(rel_team, 0), 0)
    dead = set()
    for t in order:
        rem = max(total.get(t, 0) - played.get(t, 0), 0)
        if total.get(t, 0) == 0 or played.get(t, 0) / total[t] < DEAD_FROM:
            continue
        cannot_top = points[t] + 3 * rem < p_top
        safe = points[t] > p_rel + 3 * rem_rel
        if cannot_top and safe and t not in order[:EUROPE_PLACES]:
            dead.add(t)
    return dead


def context_features(df: pd.DataFrame, cutoff_mode: str = "fduk") -> tuple[np.ndarray, np.ndarray]:
    """df: mecze JEDNEJ ligi posortowane po starcie (wspolny schemat). Zwraca (cov_h, cov_a): n x len(COV_NAMES).
    Wynik meczu i, ani zadnego meczu po odcieciu meczu i, nie wplywa na jego cechy (test podrozy w czasie)."""
    df = df.reset_index(drop=True)
    n, k = len(df), len(COV_NAMES)
    ch, ca = np.zeros((n, k)), np.zeros((n, k))
    if n == 0:
        return ch, ca
    lg = df["league"].iloc[0]
    derby = _derbies(lg)
    dates = pd.to_datetime(df["date"])
    # terminarz (znany z gory): odpoczynek i natezenie meczow
    last: dict[str, pd.Timestamp] = {}
    history: dict[str, deque] = defaultdict(lambda: deque(maxlen=6))
    for i, r in enumerate(df.itertuples(index=False)):
        d = dates.iloc[i]
        for side, team, arr in ((0, r.home, ch), (1, r.away, ca)):
            prev = last.get(team)
            rest = 14 if prev is None else min((d - prev).days, 14)
            arr[i, 0] = (rest - 7) / 7
            arr[i, 1] = sum(1 for x in history[team] if 0 < (d - x).days <= 7) / 2
        last[r.home] = last[r.away] = d
        history[r.home].append(d)
        history[r.away].append(d)
        if frozenset((r.home, r.away)) in derby:
            ch[i, 3] = ca[i, 3] = 1.0
    # tabela "as of" odciecia: punkty tylko z meczow rozegranych przed odcieciem
    total = defaultdict(int)
    for (season, team), c in pd.concat([df[["season", "home"]].set_axis(["season", "team"], axis=1),
                                         df[["season", "away"]].set_axis(["season", "team"], axis=1)]
                                        ).value_counts().items():
        total[(season, team)] = c
    pts, pld = defaultdict(int), defaultdict(int)
    order = np.argsort(dates.to_numpy(), kind="stable")
    ptr = 0
    played_rows = [j for j in order if pd.notna(df.at[j, "fthg"]) and pd.notna(df.at[j, "ftag"])]
    for i in order:
        cut = pd.Timestamp(prediction_cutoff(dates.iloc[i], cutoff_mode))
        while ptr < len(played_rows) and dates.iloc[played_rows[ptr]] < cut:
            j = played_rows[ptr]
            s, gh, ga = df.at[j, "season"], df.at[j, "fthg"], df.at[j, "ftag"]
            h, a = df.at[j, "home"], df.at[j, "away"]
            pts[(s, h)] += 3 if gh > ga else 1 if gh == ga else 0
            pts[(s, a)] += 3 if ga > gh else 1 if gh == ga else 0
            pld[(s, h)] += 1
            pld[(s, a)] += 1
            ptr += 1
        s = df.at[i, "season"]
        teams = {t for (ss, t) in total if ss == s}
        dead = _table_dead({t: pts[(s, t)] for t in teams}, {t: pld[(s, t)] for t in teams},
                           {t: total[(s, t)] for t in teams})
        ch[i, 2] = float(df.at[i, "home"] in dead)
        ca[i, 2] = float(df.at[i, "away"] in dead)
    col = lambda c: df[c].to_numpy(float) if c in df.columns else np.full(n, np.nan)
    # brak danych = 0 (wplyw neutralny), nigdy wartosc udajaca konkretne warunki
    precip = np.nan_to_num(np.clip(col("precip_mm"), 0, 10) / 5, nan=0.0)
    wind = np.nan_to_num(np.clip((col("wind_kmh") - 15) / 15, -1, 3), nan=0.0)
    pen = np.nan_to_num(col("ref_pen_rate") - 0.3, nan=0.0)
    ch[:, 4] = ca[:, 4] = precip
    ch[:, 5] = ca[:, 5] = wind
    ch[:, 6] = ca[:, 6] = pen
    ca[:, 7] = np.nan_to_num(col("travel_km") / 1000, nan=0.0)
    return ch, ca
