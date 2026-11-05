"""Cykl dzienny: sklady i kontuzje z API-Football do bazy (lineups, absences).

Wywolanie: `python cli.py lineups` co 15 minut w dni meczowe (crontab). Pobiera tylko mecze
startujace w ciagu `okno_min` minut (domyslnie 90), bo sklady pojawiaja sie ok. 60 min przed meczem.
Nazwy druzyn mapujemy na kanoniczne (entity_map, zrodlo api_football); niepewne = pending, mecz pomijamy.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import sqlalchemy as sa

from typer import config
from typer.entities.mapping import resolve_many
from typer.ingest import api_football as af
from typer.ingest.base import SourceUnavailable
from typer.store import db

log = logging.getLogger("typer.lineups")


def _map_names(engine, lg: str, raws: list[str], cands: list[str]) -> tuple[dict, int]:
    manual = db.read_df(engine, "SELECT raw_name, canonical FROM entity_map "
                                "WHERE source = :s AND league = :l AND status = 'manual'", s=af.SOURCE, l=lg)
    mapping, pending = resolve_many(raws, cands, dict(manual.to_numpy()) if len(manual) else None)
    db.upsert(engine, db.entity_map,
              [dict(source=af.SOURCE, league=lg, raw_name=k, canonical=v, score=1.0, status="auto")
               for k, v in mapping.items()] +
              [dict(source=af.SOURCE, league=lg, raw_name=m.raw, canonical=m.canonical, score=m.score,
                    status="pending") for m in pending],
              ["source", "league", "raw_name"], update=False)
    return mapping, len(pending)


def collect(engine: sa.Engine, now: datetime | None = None, window_min: int | None = None,
            dry_run: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    window_min = window_min or int(config.sources().get("api_football", {}).get("okno_min", 90))
    ev = db.read_df(engine, "SELECT event_id, league, home, away, kickoff_utc FROM events WHERE status = 'scheduled'")
    out = dict(mecze=0, sklady=0, kontuzje=0, pending=0, pominiete=[], budzet_uzyty=af.budget_used())
    if ev.empty:
        return out
    ev["kickoff_utc"] = pd.to_datetime(ev["kickoff_utc"], utc=True)
    now_ts = pd.Timestamp(now)
    soon = ev[(ev["kickoff_utc"] > now_ts) & (ev["kickoff_utc"] <= now_ts + pd.Timedelta(minutes=window_min))]
    have = db.read_df(engine, "SELECT DISTINCT event_id FROM lineups WHERE source = :s", s=af.SOURCE)
    soon = soon[~soon["event_id"].isin(set(have["event_id"]))]
    out["mecze"] = int(len(soon))
    for lg, grp in soon.groupby("league"):
        league_id = config.leagues().get(lg, {}).get("api_football")
        if not league_id:
            out["pominiete"].append(f"{lg}: brak api_football w sports.yaml")
            continue
        day = grp["kickoff_utc"].min().date()
        if dry_run:
            out["pominiete"].append(f"{lg}: dry-run, {len(grp)} meczow, koszt ok. {2 + len(grp)} zapytan")
            continue
        try:
            fx = af.parse_fixtures(af.download_fixtures(league_id, day))
            inj = af.parse_injuries(af.download_injuries(league_id, day), now)
        except SourceUnavailable as e:
            out["pominiete"].append(f"{lg}: {e}")
            continue
        cands = sorted(set(ev.loc[ev["league"] == lg, "home"]) | set(ev.loc[ev["league"] == lg, "away"]))
        mapping, n_pend = _map_names(engine, lg, list(fx["home"]) + list(fx["away"]) + list(inj["team"]), cands)
        out["pending"] += n_pend
        fx["home_c"], fx["away_c"] = fx["home"].map(mapping), fx["away"].map(mapping)
        j = fx.dropna(subset=["home_c", "away_c"]).merge(grp, left_on=["home_c", "away_c"],
                                                          right_on=["home", "away"], suffixes=("_af", ""))
        j = j[(j["kickoff_utc_af"] - j["kickoff_utc"]).abs() <= pd.Timedelta(hours=3)]
        for r in j.itertuples(index=False):
            a = inj[inj["fixture_id"] == r.fixture_id]
            rows = [dict(event_id=r.event_id, team=mapping.get(x.team, x.team), player=x.player, kind=x.kind,
                         reason=x.reason, published_utc=x.published_utc, source=af.SOURCE)
                    for x in a.itertuples(index=False) if x.team in mapping]
            out["kontuzje"] += db.upsert(engine, db.absences, rows, ["event_id", "team", "player", "source"],
                                         update=False)
            try:
                lu = af.parse_lineups(af.download_lineups(r.fixture_id), now)
            except SourceUnavailable as e:
                out["pominiete"].append(f"{r.event_id}: {e}")
                continue
            if lu.empty:
                continue   # skladow jeszcze nie ma: sprobujemy za 15 minut
            lu["team"] = lu["team"].map(lambda t: mapping.get(t))
            lu = lu.dropna(subset=["team"])
            db.append(engine, db.lineups, [dict(event_id=r.event_id, **x) for x in lu.to_dict("records")])
            out["sklady"] += 1
    out["budzet_uzyty"] = af.budget_used()
    return out
