"""Wspolna konwersja ramki meczow (schemat ingest/schema.py, tryb extended) na rekordy z available_at.

Reguly (plan modulu 1):
  wynik, statystyki meczu       min(start + 2h15, fetched_at)  (walidator: nie wczesniej niz start + 90 min)
  kurs sprzed meczu (football-data)  min(szacowany moment zebrania pt/wt 12:00 UTC, fetched_at), szacunek
  kurs zamkniecia               start meczu (nigdy nie wejdzie do typu przed startem)
  kurs o nieznanym momencie     'bench' z chwila startu (tylko benchmark)
  sedzia z pliku historii       min(start - 24h, fetched_at), szacunek (prawdziwej daty ogloszenia nie znamy)
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from typer.features.asof import collection_time
from typer.ingest.core.records import (POST_MATCH_LAG, MatchResult, OddsQuote, RefereeAssignment,
                                       TeamMatchStats)

REFEREE_LEAD = timedelta(hours=24)
ODDS_GROUPS = [  # (kolumny, rynek, selekcje, bukmacher, rodzaj)
    (("odds_h", "odds_d", "odds_a"), "1X2", ("1", "X", "2"), "b365", "prematch"),
    (("odds_o25", "odds_u25"), "OU2.5", ("over2.5", "under2.5"), "b365", "prematch"),
    (("max_h", "max_d", "max_a"), "1X2", ("1", "X", "2"), "market_max", "prematch"),
    (("max_o25", "max_u25"), "OU2.5", ("over2.5", "under2.5"), "market_max", "prematch"),
    (("close_h", "close_d", "close_a"), "1X2", ("1", "X", "2"), "pinnacle", "close"),
    (("close_o25", "close_u25"), "OU2.5", ("over2.5", "under2.5"), "pinnacle", "close"),
    (("bench_h", "bench_d", "bench_a"), "1X2", ("1", "X", "2"), "unknown", "bench"),
]


def _num(v):
    return None if v is None or pd.isna(v) else v


def _int(v):
    v = _num(v)
    return None if v is None else int(v)


def frame_to_records(df: pd.DataFrame, source: str, fetched_at: datetime, license: str = "") -> list:
    out: list = []
    for r in df.itertuples(index=False):
        ko = pd.Timestamp(r.kickoff_utc).to_pydatetime()
        ref = dict(league=r.league, kickoff_utc=ko, home=r.home, away=r.away, event_id=r.event_id,
                   source=source, fetched_at=fetched_at, license=license)
        played = _num(r.fthg) is not None and _num(r.ftag) is not None
        post = min(ko + POST_MATCH_LAG, fetched_at)
        if played:
            out.append(MatchResult(**ref, source_key=f"{r.event_id}:result", available_at=post,
                                   fthg=int(r.fthg), ftag=int(r.ftag), hthg=_int(r.hthg), htag=_int(r.htag)))
            for side, team, cols in (("home", r.home, ("hs", "hst", "hc", "hf", "hy", "hr")),
                                     ("away", r.away, ("as_", "ast", "ac", "af", "ay", "ar"))):
                vals = [_int(getattr(r, c, None)) for c in cols]
                if all(v is None for v in vals):
                    continue
                out.append(TeamMatchStats(**ref, source_key=f"{r.event_id}:stats:{side}", available_at=post,
                                          team=team, side=side, shots=vals[0], shots_on_target=vals[1],
                                          corners=vals[2], fouls=vals[3], yellow=vals[4], red=vals[5]))
        for cols, market, sels, book, kind in ODDS_GROUPS:
            prices = [_num(getattr(r, c, None)) for c in cols]
            if any(p is None for p in prices):
                continue
            if kind == "prematch":
                at, est = min(collection_time(r.date), fetched_at), True
            else:
                at, est = min(ko, fetched_at), False
            for sel, price in zip(sels, prices):
                out.append(OddsQuote(**ref, source_key=f"{r.event_id}:{book}:{kind}:{market}:{sel}",
                                     available_at=at, available_at_estimated=est, bookmaker=book,
                                     market=market, selection=sel, price=float(price), kind=kind))
        referee = _num(getattr(r, "referee", None))
        if referee:
            out.append(RefereeAssignment(**ref, source_key=f"{r.event_id}:referee:main",
                                         available_at=min(ko - REFEREE_LEAD, fetched_at),
                                         available_at_estimated=True, referee=str(referee).strip()))
    return out
