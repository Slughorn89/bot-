"""Adapter: API-Football v3 (API-Sports): sklady i kontuzje/zawieszenia.

Budzet: 100 zapytan dziennie w planie darmowym (reset o polnocy UTC), pilnowany przez typer/ingest/budget.py.
Na razie tylko ZBIERAMY dane do tabeli lineups (slepa plamka nr 1 z dziennika bledow). Ceche do modelu
dodamy dopiero, gdy uzbiera sie historia i walidacja pokaze zysk (sekcja 9.2 skilla).
W sesji budowy host byl zablokowany: parser sprawdzony testem kontraktu na probce (tests/fixtures/).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from typer import config
from typer.ingest.base import SourceUnavailable, fetch

SOURCE = "api_football"
REQUIRED_LINEUP = {"team", "startXI", "substitutes"}


def download(path: str, params: dict, now: datetime | None = None, ledger=None,
             max_age_hours: float | None = 0.5, stamp: str | None = None, meta_out: dict | None = None) -> bytes:
    """stamp: czesc nazwy pliku cache (domyslnie minuta zapytania); terminarz dnia cache'ujemy per dzien."""
    from typer.ingest.budget import Ledger
    key = config.env("API_FOOTBALL_KEY")
    if not key:
        raise SourceUnavailable("brak API_FOOTBALL_KEY w .env")
    now = now or datetime.now(timezone.utc)
    ledger = ledger or Ledger()
    if not ledger.can_spend(SOURCE, 1, now):
        raise SourceUnavailable(f"dzienny budzet API-Football wyczerpany ({ledger.used(SOURCE, now)} zapytan)")
    url = config.sources()[SOURCE]["url"] + path
    name = path.strip("/").replace("/", "_") + "_" + "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
    meta: dict = {}
    raw = fetch(url, SOURCE, f"{name}_{stamp or f'{now:%Y%m%dT%H%M}'}.json", params=params,
                headers={"x-apisports-key": key}, max_age_hours=max_age_hours, meta=meta)
    if not meta.get("cache"):
        ledger.record(SOURCE, 1, now, meta.get("headers"), note=f"{path} {params}")
    body = json.loads(raw)
    if body.get("errors"):
        raise SourceUnavailable(f"API-Football: {body['errors']}")
    if meta_out is not None:
        meta_out.update(meta)
    return raw


def parse_fixtures(raw: bytes) -> pd.DataFrame:
    rows = []
    for f in json.loads(raw).get("response", []):
        rows.append(dict(fixture_id=f["fixture"]["id"], kickoff_utc=pd.Timestamp(f["fixture"]["date"]).tz_convert("UTC"),
                         home_raw=f["teams"]["home"]["name"], away_raw=f["teams"]["away"]["name"],
                         league_id=f["league"]["id"]))
    return pd.DataFrame(rows)


def parse_lineups(raw: bytes) -> pd.DataFrame:
    """Kontrakt: kazda druzyna ma team/startXI/substitutes; brak pola = blad (test czerwony), nie cisza."""
    rows = []
    for t in json.loads(raw).get("response", []):
        missing = REQUIRED_LINEUP - set(t)
        if missing:
            raise ValueError(f"API-Football lineups: brak pol {sorted(missing)}")
        for group, status in (("startXI", "start"), ("substitutes", "lawka")):
            for p in t[group]:
                pl = p["player"]
                rows.append(dict(team_raw=t["team"]["name"], player=pl["name"], is_starter=status == "start",
                                 position=pl.get("pos"), status=status, reason=None))
    return pd.DataFrame(rows)


def parse_injuries(raw: bytes) -> pd.DataFrame:
    rows = []
    for x in json.loads(raw).get("response", []):
        typ = (x["player"].get("type") or "").lower()
        rows.append(dict(fixture_id=x["fixture"]["id"], team_raw=x["team"]["name"], player=x["player"]["name"],
                         is_starter=False, position=None,
                         status="zawieszenie" if "suspen" in (x["player"].get("reason") or "").lower() else
                         ("watpliwy" if "question" in typ or "doubt" in typ else "nieobecny"),
                         reason=x["player"].get("reason")))
    return pd.DataFrame(rows)
