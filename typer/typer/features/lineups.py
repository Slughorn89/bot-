"""Cecha skladu: jaka czesc "pewniakow" druzyny nie gra dzis (liczone "as of" chwili typu).

pewniak = zawodnik, ktory w ostatnich `okno` meczach druzyny z zapisanym skladem wyszedl
w podstawowej jedenastce w co najmniej `prog` z nich. Waga pewniaka = jego udzial startow.

  braki = suma wag pewniakow nieobecnych w dzisiejszym skladzie / suma wag wszystkich pewniakow

Gdy dzisiejszego skladu jeszcze nie ma, nieobecni = pewniacy z tabeli absences (kontuzje, zawieszenia).
Gdy druzyna ma mniej niz `min_meczow` zapisanych skladow: NaN (model nie zmienia predykcji).
Wszystko liczymy wylacznie z rekordow opublikowanych PRZED startem meczu (test podrozy w czasie).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import sqlalchemy as sa

from typer.store import db

OKNO, PROG, MIN_MECZOW = 8, 0.5, 3


def load(engine: sa.Engine) -> tuple[pd.DataFrame, pd.DataFrame]:
    lu = db.read_df(engine, "SELECT l.event_id, l.team, l.player, l.is_starter, l.published_utc, e.kickoff_utc "
                            "FROM lineups l JOIN events e ON e.event_id = l.event_id")
    ab = db.read_df(engine, "SELECT a.event_id, a.team, a.player, a.published_utc, e.kickoff_utc "
                            "FROM absences a JOIN events e ON e.event_id = a.event_id")
    for d in (lu, ab):
        for c in ("published_utc", "kickoff_utc"):
            d[c] = pd.to_datetime(d[c], utc=True)
    return lu, ab


def missing_share(lu: pd.DataFrame, ab: pd.DataFrame, event_id: str, team: str, kickoff_utc,
                  okno: int = OKNO, prog: float = PROG, min_meczow: int = MIN_MECZOW) -> float:
    ko = pd.Timestamp(kickoff_utc)
    ko = ko.tz_localize("UTC") if ko.tzinfo is None else ko.tz_convert("UTC")
    known = lu[(lu["team"] == team) & (lu["published_utc"] < ko)]
    past = known[(known["kickoff_utc"] < ko) & (known["event_id"] != event_id)]
    games = past[["event_id", "kickoff_utc"]].drop_duplicates().sort_values("kickoff_utc").tail(okno)
    if len(games) < min_meczow:
        return np.nan
    st = past[past["event_id"].isin(games["event_id"]) & past["is_starter"].astype(bool)]
    share = st.groupby("player")["event_id"].nunique() / len(games)
    regulars = share[share >= prog]
    if regulars.empty:
        return np.nan
    today = known[(known["event_id"] == event_id) & known["is_starter"].astype(bool)]
    if len(today) >= 11:
        absent = set(regulars.index) - set(today["player"])
    else:
        a = ab[(ab["event_id"] == event_id) & (ab["team"] == team) & (ab["published_utc"] < ko)]
        absent = set(regulars.index) & set(a["player"])
    return float(regulars[list(absent)].sum() / regulars.sum()) if absent else 0.0
