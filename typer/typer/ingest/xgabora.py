"""Adapter: xgabora/Club-Football-Match-Data (kopia football-data.co.uk na GitHubie, MIT).

Daje wyniki, strzaly, kartki i kursy Bet365 oraz maksymalne SPRZED meczu (zbierane przez
football-data.co.uk w piatek dla meczow weekendowych i we wtorek dla srodowych).
Nie daje kursow zamkniecia, wiec na tych danych nie policzysz CLV.
Kolumn klastrow C_* NIE wczytujemy: sa liczone ze statystyk meczu (wyciek).
"""
from __future__ import annotations

import io
import logging

import numpy as np
import pandas as pd

from typer import config
from typer.ingest import schema
from typer.ingest.base import fetch
from typer.ingest.seasons import assign_seasons

log = logging.getLogger("typer.ingest.xgabora")

SOURCE = "xgabora"
LOCAL_TZ = "Europe/London"   # football-data.co.uk podaje czas brytyjski
DEFAULT_KICKOFF = "15:00:00"  # gdy brak godziny (sezony sprzed 2019/20)

RENAME = {
    "Division": "league", "MatchDate": "date", "MatchTime": "time",
    "HomeTeam": "home", "AwayTeam": "away",
    "FTHome": "fthg", "FTAway": "ftag", "HTHome": "hthg", "HTAway": "htag",
    "HomeShots": "hs", "AwayShots": "as_", "HomeTarget": "hst", "AwayTarget": "ast",
    "HomeRed": "hr", "AwayRed": "ar",
    "OddHome": "odds_h", "OddDraw": "odds_d", "OddAway": "odds_a",
    "MaxHome": "max_h", "MaxDraw": "max_d", "MaxAway": "max_a",
    "Over25": "odds_o25", "Under25": "odds_u25",
    "MaxOver25": "max_o25", "MaxUnder25": "max_u25",
    "HandiSize": "ah_line", "HandiHome": "ah_h", "HandiAway": "ah_a",
}


def swap_day_month(dates: pd.Series) -> pd.Series:
    """Naprawa bledu zrodla: daty z dniem <= 12 maja zamieniony dzien z miesiacem
    (np. 2012-02-09 zamiast 2012-09-02). Wykryte w Ekstraklasie: 0 meczow w 'styczniu'
    i 159 przypadkow gry dwa razy w ciagu doby. Po naprawie kontrakt (gapy druzyn) przechodzi."""
    d = pd.to_datetime(dates)
    m = d.dt.day <= 12
    fixed = pd.to_datetime(dict(year=d[m].dt.year, month=d[m].dt.day, day=d[m].dt.month))
    out = d.copy()
    out[m] = fixed
    return out


def download(ref: str | None = None, max_age_hours: float | None = None) -> bytes:
    src = config.sources()["xgabora"]
    ref = ref or src["ref"]
    url = src["url"].format(ref=ref)
    # przypiety commit nie zmienia sie, wiec cache bezterminowy; "main" odswiezamy codziennie
    age = max_age_hours if max_age_hours is not None else (None if len(ref) == 40 else 24)
    return fetch(url, SOURCE, f"Matches_{ref[:12]}.csv", max_age_hours=age)


def parse(raw: bytes, leagues: dict, since: str | None = None, ref: str = "") -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), low_memory=False)
    df = df[df["Division"].isin(list(leagues))]
    df = df[[c for c in RENAME if c in df.columns]].rename(columns=RENAME)
    df["date"] = pd.to_datetime(df["date"])
    for lg, meta in leagues.items():
        if meta.get("fix_dates") == "swap_day_month":
            df.loc[df["league"] == lg, "date"] = swap_day_month(df.loc[df["league"] == lg, "date"])
    if since:
        df = df[df["date"] >= pd.Timestamp(since)]
    df["time_known"] = df["time"].notna()
    t = df["time"].fillna(DEFAULT_KICKOFF).astype(str)
    local = pd.to_datetime(df["date"].dt.strftime("%Y-%m-%d") + " " + t, errors="coerce")
    df["kickoff_utc"] = local.dt.tz_localize(LOCAL_TZ, ambiguous="NaT",
                                             nonexistent="shift_forward").dt.tz_convert("UTC")
    # godzina niejednoznaczna przy zmianie czasu: bierzemy UTC = czas lokalny (blad <= 1h)
    bad = df["kickoff_utc"].isna()
    df.loc[bad, "kickoff_utc"] = local[bad].dt.tz_localize("UTC")
    df["date"] = df["date"].dt.date
    for c in schema.ODDS_COLS:
        if c not in df.columns:
            df[c] = np.nan
    for c in ("ah_line", "ah_h", "ah_a"):
        if c not in df.columns:
            df[c] = np.nan
    # ligi z kursami o nieznanym momencie: przenosimy do bench_*, nie wolno ich "brac"
    for lg, meta in leagues.items():
        if meta.get("odds_timing", "prematch") != "prematch":
            m = df["league"] == lg
            for s in ("h", "d", "a"):
                df.loc[m, f"bench_{s}"] = df.loc[m, f"odds_{s}"]
            df.loc[m, ["odds_h", "odds_d", "odds_a", "odds_o25", "odds_u25", "max_h", "max_d",
                       "max_a", "max_o25", "max_u25", "ah_line", "ah_h", "ah_a"]] = np.nan
        if not meta.get("has_shots", True):
            df.loc[df["league"] == lg, ["hs", "as_", "hst", "ast"]] = np.nan
    df["sport"] = "football"
    df["source"] = f"{SOURCE}@{ref[:7]}" if ref else SOURCE
    df["season"] = ""
    for lg, idx in df.groupby("league").groups.items():
        df.loc[idx, "season"] = assign_seasons(df.loc[idx, "date"])
    df = df.dropna(subset=["fthg", "ftag"])  # tylko rozegrane
    df["event_id"] = [schema.make_event_id(l, d, h, a)
                      for l, d, h, a in zip(df["league"], df["date"], df["home"], df["away"])]
    df, bad_odds = schema.clean_odds(df)
    if any(bad_odds.values()):
        log.warning("wyzerowane bledne grupy kursow: %s", {k: v for k, v in bad_odds.items() if v})
    df = df.drop_duplicates("event_id", keep="last")
    df = df[schema.COLUMNS].sort_values(["kickoff_utc", "league", "home"], kind="stable")
    return schema.validate(df.reset_index(drop=True))


def load(since: str | None = None, ref: str | None = None) -> pd.DataFrame:
    ref = ref or config.sources()["xgabora"]["ref"]
    return parse(download(ref), config.leagues(), since=since, ref=ref)
