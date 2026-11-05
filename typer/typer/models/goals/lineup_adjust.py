"""Korekta skladu (modul 2): wklad xG/xA dostepnych zawodnikow wzgledem pelnego skladu.

  wklad_i     = (xG + xA) na 90 min zawodnika * udzial minut w ostatnich meczach (liczone "as of")
  mnoznik_atk = sum(wklad dostepnych) / sum(wklad pelnego skladu)          -> mnozy lambda wlasna
  mnoznik_obr = udzial minut dostepnych bramkarzy i obroncow / pelny udzial -> dzieli lambda rywala

Elastycznosci (kappa) beda strojone, gdy uzbiera sie historia skladow i xG zawodnikow (modul 1, API-Football).
Do tego czasu mechanizm jest sprawdzony tylko na danych syntetycznych, a w backteście nie jest uzywany.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DEFENSIVE = {"G", "D"}


@dataclass
class LineupEffect:
    atk_mult: float
    obr_mult: float
    missing_share_atk: float
    missing_share_obr: float


def contributions(player_stats: pd.DataFrame, as_of, lookback_matches: int = 10) -> pd.DataFrame:
    """player_stats: wiersze PlayerMatchStats (team, player, position, minutes, xg, xa, kickoff_utc, available_at).
    Zwraca wklad zawodnika z ostatnich meczow druzyny, wylacznie z rekordow dostepnych przed as_of."""
    ps = player_stats[pd.to_datetime(player_stats["available_at"], utc=True) <= pd.Timestamp(as_of)].copy()
    if ps.empty:
        return pd.DataFrame(columns=["team", "player", "position", "atk", "minutes_share"])
    ps["kickoff_utc"] = pd.to_datetime(ps["kickoff_utc"], utc=True)
    out = []
    for team, g in ps.groupby("team"):
        recent = sorted(g["kickoff_utc"].unique())[-lookback_matches:]
        g = g[g["kickoff_utc"].isin(recent)]
        team_min = 90.0 * len(recent)
        for (player, pos), p in g.groupby(["player", g["position"].fillna("?")]):
            mins = p["minutes"].fillna(0).sum()
            xgxa = (p["xg"].fillna(0) + p["xa"].fillna(0)).sum()
            per90 = 90 * xgxa / mins if mins > 0 else 0.0
            share = mins / team_min if team_min else 0.0
            out.append(dict(team=team, player=player, position=pos, atk=per90 * share, minutes_share=share))
    return pd.DataFrame(out)


def lineup_effect(contrib: pd.DataFrame, team: str, available: set[str], floor: float = 0.6) -> LineupEffect:
    c = contrib[contrib["team"] == team]
    if c.empty:
        return LineupEffect(1.0, 1.0, 0.0, 0.0)
    full_atk = c["atk"].sum()
    av = c["player"].isin(available)
    atk = c.loc[av, "atk"].sum() / full_atk if full_atk > 0 else 1.0
    d = c[c["position"].isin(DEFENSIVE)]
    full_def = d["minutes_share"].sum()
    obr = d.loc[d["player"].isin(available), "minutes_share"].sum() / full_def if full_def > 0 else 1.0
    return LineupEffect(max(atk, floor), max(obr, floor), 1 - atk, 1 - obr)


def apply_lineups(mh: float, ma: float, home: LineupEffect, away: LineupEffect,
                  kappa_atk: float = 1.0, kappa_obr: float = 0.5) -> tuple[float, float]:
    """Brak wlasnych strzelcow obniza wlasna lambda; brak wlasnych obroncow podnosi lambda rywala."""
    mh2 = mh * home.atk_mult ** kappa_atk * away.obr_mult ** (-kappa_obr)
    ma2 = ma * away.atk_mult ** kappa_atk * home.obr_mult ** (-kappa_obr)
    return mh2, ma2
