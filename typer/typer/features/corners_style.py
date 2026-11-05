"""Cechy stylu gry pod rozne (modul 3), liczone "as of" odciecia typu.

Dosrodkowan ani posiadania w tercji rywala nie mamy w zadnym legalnym, dostepnym zrodle, wiec styl
przyblizamy tym, co jest w danych meczowych: rozne i strzaly oddane / dopuszczone oraz rozne na strzal
(druzyny grajace skrzydlami i dosrodkowaniami maja ich wiecej przy tej samej liczbie strzalow).

Dla kazdej druzyny srednia wykladnicza po meczach (half-life 8 meczow), sciagana do sredniej ligi
(as of) wagą 4 meczow. Cechy dla rożnych gospodarza (dla goscia symetrycznie):
  corners_for      log(rozne oddane gospodarza / srednia ligi)
  corners_against  log(rozne dopuszczane przez goscia / srednia ligi)
  shots_for        log(strzaly gospodarza / srednia ligi)
  shots_against    log(strzaly dopuszczane przez goscia / srednia ligi)
  corners_per_shot log((rozne / strzaly) gospodarza / to samo dla ligi)
  precip, wind     pogoda z prognozy dostepnej przed meczem (kolumny precip_mm, wind_kmh), brak = 0
Uzywane sa tylko mecze rozegrane przed odcieciem meczu (prediction_cutoff), wiec wynik i statystyki meczu i
ani zadnego pozniejszego nie zmieniaja jego cech (test podrozy w czasie w tests/test_corners.py).
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from typer.features.asof import prediction_cutoff

STYLE_NAMES = ["corners_for", "corners_against", "shots_for", "shots_against", "corners_per_shot",
               "precip", "wind"]
DECAY = 0.5 ** (1 / 8)
PRIOR_MATCHES = 4.0


class _Ewma:
    def __init__(self):
        self.s = defaultdict(float)
        self.n = defaultdict(float)

    def add(self, key, x):
        if np.isfinite(x):
            self.s[key] = DECAY * self.s[key] + x
            self.n[key] = DECAY * self.n[key] + 1.0

    def get(self, key, prior):
        return (self.s[key] + PRIOR_MATCHES * prior) / (self.n[key] + PRIOR_MATCHES)


def style_features(df: pd.DataFrame, cutoff_mode: str = "fduk") -> tuple[np.ndarray, np.ndarray]:
    """df: mecze JEDNEJ ligi. Zwraca (cov_h, cov_a): n x len(STYLE_NAMES), wiersze w kolejnosci df."""
    df = df.reset_index(drop=True)
    n = len(df)
    ch, ca = np.zeros((n, len(STYLE_NAMES))), np.zeros((n, len(STYLE_NAMES)))
    if n == 0:
        return ch, ca
    col = lambda c: df[c].to_numpy(float) if c in df.columns else np.full(n, np.nan)
    hc, ac, hs, as_ = col("hc"), col("ac"), col("hs"), col("as_")
    dates = pd.to_datetime(df["date"])
    order = np.argsort(dates.to_numpy(), kind="stable")
    played = [j for j in order if np.isfinite(hc[j]) and np.isfinite(ac[j])]
    ew = _Ewma()
    lg_c = lg_s = lg_n = lg_ns = 0.0
    ptr = 0
    for i in order:
        cut = pd.Timestamp(prediction_cutoff(dates.iloc[i], cutoff_mode))
        while ptr < len(played) and dates.iloc[played[ptr]] < cut:
            j = played[ptr]
            h, a = df.at[j, "home"], df.at[j, "away"]
            ew.add((h, "cf"), hc[j]); ew.add((h, "ca"), ac[j])
            ew.add((a, "cf"), ac[j]); ew.add((a, "ca"), hc[j])
            ew.add((h, "sf"), hs[j]); ew.add((h, "sa"), as_[j])
            ew.add((a, "sf"), as_[j]); ew.add((a, "sa"), hs[j])
            lg_c += hc[j] + ac[j]
            lg_n += 2
            if np.isfinite(hs[j]) and np.isfinite(as_[j]):
                lg_s += hs[j] + as_[j]
                lg_ns += 2
            ptr += 1
        if lg_n < 20:                      # za malo historii ligi: cechy neutralne
            continue
        mc = lg_c / lg_n
        ms = lg_s / lg_ns if lg_ns >= 20 else np.nan
        h, a = df.at[i, "home"], df.at[i, "away"]
        for arr, me, op in ((ch, h, a), (ca, a, h)):
            arr[i, 0] = np.log(ew.get((me, "cf"), mc) / mc)
            arr[i, 1] = np.log(ew.get((op, "ca"), mc) / mc)
            if np.isfinite(ms):
                sf, sa = ew.get((me, "sf"), ms), ew.get((op, "sa"), ms)
                arr[i, 2] = np.log(sf / ms)
                arr[i, 3] = np.log(sa / ms)
                arr[i, 4] = np.log((ew.get((me, "cf"), mc) / sf) / (mc / ms))
    precip = np.nan_to_num(np.clip(col("precip_mm"), 0, 10) / 5, nan=0.0)
    wind = np.nan_to_num(np.clip((col("wind_kmh") - 15) / 15, -1, 3), nan=0.0)
    ch[:, 5] = ca[:, 5] = precip
    ch[:, 6] = ca[:, 6] = wind
    return ch, ca
