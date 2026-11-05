"""Adapter: API-Football v3 (api-sports.io): terminarz z ID meczow, sklady, kontuzje.

Po co: sklady ok. 60 min przed meczem to najwieksza pojedyncza aktualizacja informacji (sekcja 6
skilla), a w danych historycznych ich nie ma. Zbieramy je sami od pierwszego dnia, tak jak kursy.

Wymaga API_FOOTBALL_KEY w .env i dostepu do v3.football.api-sports.io.
UWAGA: w sesji budowy (2026-11-05) host byl zablokowany polityka sieci, wiec parsery sa sprawdzone
testem kontraktu na probkach w formacie z dokumentacji (tests/fixtures/api_football_*.json),
nie na zywych odpowiedziach. Pierwsze uruchomienie: `python cli.py lineups --dry-run`.

Budzet darmowego planu: 100 zapytan dziennie (reset o polnocy UTC). Licznik w raw/api_football/
_budzet_<data>.json; ponizej rezerwy (sources.yaml: api_football.rezerwa) nie pytamy wiecej.
Koszt dnia meczowego: 1 (terminarz) + 1 (kontuzje) na lige i dzien + 1 na kazdy mecz (sklady).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from typer import config
from typer.config import RAW_DIR
from typer.ingest.base import SourceUnavailable, fetch

log = logging.getLogger("typer.ingest.api_football")
SOURCE = "api_football"


def _src() -> dict:
    return config.sources().get("api_football", {})


def season_year(day) -> int:
    """API-Football: sezon = rok startu (2026/27 -> 2026). Sezon europejski startuje w lipcu."""
    d = pd.Timestamp(day)
    return d.year if d.month >= 7 else d.year - 1


# --- budzet zapytan -------------------------------------------------------------------------
def _budget_path(day=None) -> Path:
    d = pd.Timestamp(day or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return RAW_DIR / SOURCE / f"_budzet_{d}.json"


def budget_used(day=None) -> int:
    p = _budget_path(day)
    return json.loads(p.read_text()).get("uzyte", 0) if p.exists() else 0


def _spend(n: int = 1, day=None) -> None:
    p = _budget_path(day)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"uzyte": budget_used(day) + n}))


def budget_left(day=None) -> int:
    s = _src()
    return int(s.get("limit_dzienny", 100)) - int(s.get("rezerwa", 10)) - budget_used(day)


# --- pobieranie -----------------------------------------------------------------------------
def _get(endpoint: str, params: dict, filename: str, max_age_hours: float | None) -> dict:
    key = config.env("API_FOOTBALL_KEY")
    if not key:
        raise SourceUnavailable("brak API_FOOTBALL_KEY w .env")
    path = RAW_DIR / SOURCE / filename
    fresh = path.exists() and (max_age_hours is None or
                               (datetime.now().timestamp() - path.stat().st_mtime) < max_age_hours * 3600)
    if not fresh:
        if budget_left() <= 0:
            raise SourceUnavailable(f"{SOURCE}: dzienny budzet zapytan wyczerpany ({budget_used()} uzytych)")
        _spend()
    raw = fetch(_src().get("url", "https://v3.football.api-sports.io") + endpoint, SOURCE, filename,
                params=params, headers={"x-apisports-key": key}, max_age_hours=max_age_hours)
    data = json.loads(raw)
    errs = data.get("errors")
    if errs:  # API-Football zwraca 200 z polem errors (zly klucz, limit, plan)
        (RAW_DIR / SOURCE / filename).unlink(missing_ok=True)
        raise SourceUnavailable(f"{SOURCE}: {errs}")
    return data


def download_fixtures(league_id: int, day) -> dict:
    d = pd.Timestamp(day).strftime("%Y-%m-%d")
    return _get("/fixtures", dict(league=league_id, season=season_year(day), date=d),
                f"fixtures_{league_id}_{d}.json", max_age_hours=6)


def download_lineups(fixture_id: int) -> dict:
    # sklady publikowane ok. 60 min przed meczem; pusta odpowiedz = jeszcze ich nie ma, nie cache'ujemy
    return _get("/fixtures/lineups", dict(fixture=fixture_id), f"lineups_{fixture_id}.json", max_age_hours=0.25)


def download_injuries(league_id: int, day) -> dict:
    d = pd.Timestamp(day).strftime("%Y-%m-%d")
    return _get("/injuries", dict(league=league_id, season=season_year(day), date=d),
                f"injuries_{league_id}_{d}.json", max_age_hours=3)


# --- parsowanie -----------------------------------------------------------------------------
def parse_fixtures(data: dict) -> pd.DataFrame:
    rows = []
    for r in data.get("response", []):
        rows.append(dict(fixture_id=int(r["fixture"]["id"]),
                         kickoff_utc=pd.Timestamp(r["fixture"]["date"]).tz_convert("UTC"),
                         home=r["teams"]["home"]["name"], away=r["teams"]["away"]["name"],
                         home_id=r["teams"]["home"]["id"], away_id=r["teams"]["away"]["id"]))
    return pd.DataFrame(rows, columns=["fixture_id", "kickoff_utc", "home", "away", "home_id", "away_id"])


def parse_lineups(data: dict, published_utc: datetime) -> pd.DataFrame:
    """Jeden wiersz = zawodnik: team, player, is_starter, position."""
    rows = []
    for t in data.get("response", []):
        team = t["team"]["name"]
        for key, starter in (("startXI", True), ("substitutes", False)):
            for p in t.get(key) or []:
                pl = p.get("player") or {}
                if pl.get("name"):
                    rows.append(dict(team=team, player=pl["name"], is_starter=starter,
                                     position=pl.get("pos"), published_utc=published_utc, source=SOURCE))
    df = pd.DataFrame(rows, columns=["team", "player", "is_starter", "position", "published_utc", "source"])
    # sklad jest uzyteczny tylko, gdy obie druzyny maja po 11 w wyjsciowym skladzie
    if len(df):
        starters = df[df["is_starter"]].groupby("team").size()
        if len(starters) != 2 or (starters != 11).any():
            log.warning("niekompletny sklad: %s", starters.to_dict())
            return df.iloc[0:0]
    return df


def parse_injuries(data: dict, published_utc: datetime) -> pd.DataFrame:
    rows = []
    for r in data.get("response", []):
        pl = r.get("player") or {}
        rows.append(dict(fixture_id=int((r.get("fixture") or {}).get("id") or 0), team=r["team"]["name"],
                         player=pl.get("name", ""), kind=pl.get("type"), reason=pl.get("reason"),
                         published_utc=published_utc, source=SOURCE))
    return pd.DataFrame(rows, columns=["fixture_id", "team", "player", "kind", "reason", "published_utc", "source"])
