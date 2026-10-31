"""Challenger: Dixon-Coles z wagami czasowymi (penaltyblog, MIT), dopasowywany kroczaco.

Co tydzien (przy kazdym odcieciu) per liga: dopasowanie na meczach z ostatnich `window_days`
sprzed odciecia, z wagami exp(-xi * dni). Typowanie meczow do nastepnego odciecia.
Druzyny bez historii w oknie (beniaminkowie) dostaja NaN: porownanie z ocenami online robimy
na wspolnym podzbiorze.
"""
from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd

from typer.features.asof import prediction_cutoff

log = logging.getLogger("typer.dc")


def walk_forward_dc(df: pd.DataFrame, start, end, xi: float = 0.0018, window_days: int = 730,
                    cutoff_mode: str = "fduk") -> pd.DataFrame:
    from penaltyblog.models import DixonColesGoalModel, dixon_coles_weights

    df = df.copy()
    df["d"] = pd.to_datetime(df["date"])
    df["cut"] = [pd.Timestamp(prediction_cutoff(x, cutoff_mode)) for x in df["date"]]
    tgt = df[(df["d"] >= pd.Timestamp(start)) & (df["d"] <= pd.Timestamp(end))]
    out = []
    for (lg, cut), grp in tgt.groupby(["league", "cut"], sort=True):
        tr = df[(df["league"] == lg) & (df["d"] < cut) & (df["d"] >= cut - pd.Timedelta(days=window_days))]
        if len(tr) < 150:
            continue
        w = dixon_coles_weights(tr["d"], xi=xi, base_date=cut)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m = DixonColesGoalModel(tr["fthg"].astype(int), tr["ftag"].astype(int),
                                        tr["home"], tr["away"], weights=w)
                m.fit()
        except Exception as e:  # pragma: no cover - zalezy od danych
            log.warning("DC %s %s: %s", lg, cut.date(), e)
            continue
        known = set(tr["home"]) | set(tr["away"])
        for r in grp.itertuples(index=False):
            if r.home not in known or r.away not in known:
                continue
            try:
                g = m.predict(r.home, r.away, max_goals=10)
            except Exception:
                continue
            h, d_, a = g.home_draw_away
            over = g.total_goals("over", 2.5)
            out.append(dict(event_id=r.event_id, p_h=h, p_d=d_, p_a=a, p_over=over, p_btts=g.btts_yes))
    return pd.DataFrame(out)
