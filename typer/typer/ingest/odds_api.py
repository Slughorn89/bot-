"""Adapter: The Odds API v4 (kursy na zywo). Sluzy do snapshotow kursow:
w chwili typu i tuz przed startem (zamkniecie). Historycznych zamkniec dla wielu rynkow nigdzie
nie ma, wiec trzeba je zbierac samemu od pierwszego dnia.

Wymaga ODDS_API_KEY w .env i dostepu do api.the-odds-api.com (w sesji budowy host byl zablokowany).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pandas as pd

from typer import config
from typer.ingest.base import SourceUnavailable, fetch

log = logging.getLogger("typer.ingest.odds_api")
SOURCE = "the_odds_api"
CLOSE_WINDOW_MIN = 10  # snapshot w ciagu 10 min przed startem traktujemy jako zamkniecie


def download(sport_key: str, *, regions: str = "eu", markets: str = "h2h,totals",
             now: datetime | None = None) -> bytes:
    key = config.env("ODDS_API_KEY")
    if not key:
        raise SourceUnavailable("brak ODDS_API_KEY w .env")
    now = now or datetime.now(timezone.utc)
    url = config.sources()["the_odds_api"]["url"].format(sport=sport_key)
    params = dict(apiKey=key, regions=regions, markets=markets, oddsFormat="decimal", dateFormat="iso")
    # kazdy snapshot to osobny plik w raw/: to jest nasza historia kursow
    return fetch(url, SOURCE, f"{sport_key}_{now:%Y%m%dT%H%M}.json", params=params, max_age_hours=0.2)


def parse(raw: bytes, league: str, snapshot_utc: datetime) -> pd.DataFrame:
    """Plaska tabela snapshotu: jeden wiersz = bukmacher x rynek x selekcja."""
    rows = []
    for ev in json.loads(raw):
        home, away = ev["home_team"], ev["away_team"]
        ko = pd.Timestamp(ev["commence_time"]).tz_convert("UTC")
        mins = (ko - pd.Timestamp(snapshot_utc)).total_seconds() / 60
        for bk in ev.get("bookmakers", []):
            for m in bk.get("markets", []):
                for o in m.get("outcomes", []):
                    if m["key"] == "h2h":
                        market = "1X2"
                        sel = "1" if o["name"] == home else "2" if o["name"] == away else "X"
                        line = None
                    elif m["key"] == "totals" and o.get("point") is not None:
                        line = float(o["point"])
                        market = f"OU{line:g}"
                        sel = f"{o['name'].lower()}{line:g}"
                    else:
                        continue
                    rows.append(dict(league=league, source_event_id=ev["id"], home_raw=home,
                                     away_raw=away, kickoff_utc=ko, bookmaker=bk["key"],
                                     market=market, selection=sel, line=line,
                                     price=float(o["price"]), snapshot_utc=pd.Timestamp(snapshot_utc),
                                     minutes_to_kickoff=mins,
                                     kind="close" if 0 <= mins <= CLOSE_WINDOW_MIN else
                                     ("taken" if mins > 0 else "inplay")))
    return pd.DataFrame(rows)


def best_price(snap: pd.DataFrame, bookmakers: list[str] | None = None) -> pd.DataFrame:
    """Najlepszy kurs per mecz x rynek x selekcja (opcjonalnie tylko u wskazanych bukmacherow)."""
    if snap.empty:
        return snap
    s = snap if not bookmakers else snap[snap["bookmaker"].isin(bookmakers)]
    idx = s.groupby(["source_event_id", "market", "selection"])["price"].idxmax()
    return s.loc[idx].reset_index(drop=True)
