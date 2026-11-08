"""Adapter: oryginalne pliki football-data.co.uk (docelowe glowne zrodlo).

Przewaga nad kopia z GitHuba: kursy zamkniecia Pinnacle (PSCH/PSCD/PSCA, PC>2.5/PC<2.5),
wiec w backteście da sie liczyc CLV wzgledem zamkniecia bez marzy, oraz fixtures.csv
z terminarzem i kursami na najblizsze mecze.

UWAGA: w sesji, w ktorej powstal ten kod, host www.football-data.co.uk byl zablokowany przez
polityke sieci, wiec parser jest sprawdzony tylko testem kontraktu na probce w formacie
football-data (tests/fixtures/), nie na zywych plikach.
"""
from __future__ import annotations

import io
import logging

import numpy as np
import pandas as pd

from typer import config
from typer.ingest import schema
from typer.ingest.base import SourceUnavailable, fetch
from typer.ingest.seasons import assign_seasons

log = logging.getLogger("typer.ingest.fduk")
SOURCE = "football_data_uk"
LOCAL_TZ = "Europe/London"

# kolumna docelowa -> kandydaci w kolejnosci preferencji (nowsze sezony maja inne nazwy)
MAIN_MAP = {
    "home": ["HomeTeam", "Home"], "away": ["AwayTeam", "Away"],
    "fthg": ["FTHG", "HG"], "ftag": ["FTAG", "AG"], "hthg": ["HTHG"], "htag": ["HTAG"],
    "hs": ["HS"], "as_": ["AS"], "hst": ["HST"], "ast": ["AST"], "hr": ["HR"], "ar": ["AR"],
    # kurs "wziety": Bet365 sprzed zamkniecia
    "odds_h": ["B365H"], "odds_d": ["B365D"], "odds_a": ["B365A"],
    "odds_o25": ["B365>2.5"], "odds_u25": ["B365<2.5"],
    "max_h": ["MaxH", "BbMxH"], "max_d": ["MaxD", "BbMxD"], "max_a": ["MaxA", "BbMxA"],
    "max_o25": ["Max>2.5", "BbMx>2.5"], "max_u25": ["Max<2.5", "BbMx<2.5"],
    # zamkniecie: Pinnacle
    "close_h": ["PSCH"], "close_d": ["PSCD"], "close_a": ["PSCA"],
    "close_o25": ["PC>2.5"], "close_u25": ["PC<2.5"],
    "ah_line": ["AHh", "BbAHh"], "ah_h": ["B365AHH"], "ah_a": ["B365AHA"],
    # tryb extended
    "hc": ["HC"], "ac": ["AC"], "hf": ["HF"], "af": ["AF"], "hy": ["HY"], "ay": ["AY"], "referee": ["Referee"],
}
# nowe ligi (np. POL): tylko kursy zamkniecia
NEW_MAP = {
    "home": ["Home"], "away": ["Away"], "fthg": ["HG"], "ftag": ["AG"],
    "close_h": ["PSCH", "PH"], "close_d": ["PSCD", "PD"], "close_a": ["PSCA", "PA"],
}


def season_code(season: str) -> str:
    """'2024-25' -> '2425'"""
    a, b = season.split("-")
    return a[2:] + b


def _pick(df: pd.DataFrame, cands: list[str]) -> pd.Series:
    for c in cands:
        if c in df.columns:
            return df[c]
    return pd.Series(np.nan, index=df.index)


def _parse_dates(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    date = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce", format="mixed")
    has_time = "Time" in df.columns
    t = df["Time"].fillna("15:00") if has_time else pd.Series("15:00", index=df.index)
    local = pd.to_datetime(date.dt.strftime("%Y-%m-%d") + " " + t.astype(str), errors="coerce")
    utc = local.dt.tz_localize(LOCAL_TZ, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    utc = utc.fillna(local.dt.tz_localize("UTC"))
    known = df["Time"].notna() if has_time else pd.Series(False, index=df.index)
    return date, utc, known


def parse(raw: bytes, league: str, *, kind: str = "main", allow_unplayed: bool = False,
          extended: bool = False) -> pd.DataFrame:
    """extended=True: dodatkowo rozne, faule, zolte kartki i sedzia (schema.EXTRA_COLS)."""
    text = raw.decode("utf-8-sig", errors="replace")
    df = pd.read_csv(io.StringIO(text), on_bad_lines="skip")
    df = df.dropna(how="all")
    if df.empty:
        return schema.empty_frame()
    if kind == "new" and "League" in df.columns and league == "POL":
        df = df[df["League"].astype(str).str.contains("Ekstraklasa", case=False, na=False)]
    mp = MAIN_MAP if kind == "main" else NEW_MAP
    need = ["home", "away"] + ([] if allow_unplayed else ["fthg", "ftag"])
    missing = [c for c in need if not any(x in df.columns for x in mp[c])] + \
              (["Date"] if "Date" not in df.columns else [])
    if missing:  # zrodlo zmienilo format: test kontraktu czerwony, nie cicha pustka
        raise schema.ContractError(f"football-data.co.uk {league}: brak kolumn dla {missing}")
    out = pd.DataFrame(index=df.index)
    for col, cands in mp.items():
        out[col] = _pick(df, cands)
    date, utc, known = _parse_dates(df)
    out["date"], out["kickoff_utc"], out["time_known"] = date.dt.date, utc, known
    out["league"], out["sport"], out["source"] = league, "football", SOURCE
    for c in schema.COLUMNS + schema.EXTRA_COLS:
        if c not in out.columns:
            out[c] = np.nan
    out = out.dropna(subset=["home", "away", "kickoff_utc"])
    if not allow_unplayed:
        out = out.dropna(subset=["fthg", "ftag"])
    out["season"] = assign_seasons(pd.to_datetime(out["date"])) if len(out) else ""
    out["event_id"] = [schema.make_event_id(league, d, h, a)
                       for d, h, a in zip(out["date"], out["home"], out["away"])]
    out, bad = schema.clean_odds(out)
    if any(bad.values()):
        log.warning("%s: wyzerowane bledne grupy kursow %s", league, {k: v for k, v in bad.items() if v})
    cols = schema.COLUMNS + (schema.EXTRA_COLS if extended else [])
    out = out.drop_duplicates("event_id", keep="last")[cols]
    return schema.validate(out.reset_index(drop=True), allow_unplayed=allow_unplayed)


def download_season(code: str, season: str, max_age_hours: float | None = 24) -> bytes:
    url = config.sources()["football_data_uk"]["url_sezon"].format(season=season_code(season), code=code)
    return fetch(url, SOURCE, f"{season_code(season)}_{code}.csv", max_age_hours=max_age_hours)


def load(seasons: list[str], leagues: dict | None = None, max_age_hours: float | None = 24,
         extended: bool = False) -> pd.DataFrame:
    leagues = leagues or config.leagues()
    src = config.sources()["football_data_uk"]
    frames = []
    for lg, meta in leagues.items():
        f = meta.get("fduk", {})
        if f.get("kind") == "new":
            raw = fetch(src["url_nowe_ligi"].format(code=f["code"]), SOURCE, f"new_{f['code']}.csv",
                        max_age_hours=max_age_hours)
            frames.append(parse(raw, lg, kind="new", extended=extended))
        else:
            for s in seasons:
                frames.append(parse(download_season(f["code"], s, max_age_hours), lg, kind="main",
                                    extended=extended))
    if not frames:
        return schema.empty_frame()
    from typer.entities.history import harmonize
    out = harmonize(pd.concat(frames, ignore_index=True), config.load_yaml("aliases.yaml"))
    out["event_id"] = [schema.make_event_id(l, d, h, a)
                       for l, d, h, a in zip(out["league"], out["date"], out["home"], out["away"])]
    return schema.validate(out)


def load_fixtures(leagues: dict | None = None) -> pd.DataFrame:
    """Terminarz z kursami sprzed meczu (fixtures.csv). Mecze bez wyniku."""
    leagues = leagues or config.leagues()
    src = config.sources()["football_data_uk"]
    raw = fetch(src["url_terminarz"], SOURCE, "fixtures.csv", max_age_hours=3)
    df = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
    frames = []
    for lg, meta in leagues.items():
        f = meta.get("fduk", {})
        if f.get("kind") == "new":
            continue
        part = df[df.get("Div", pd.Series(dtype=str)) == f.get("code")]
        if len(part):
            buf = part.to_csv(index=False).encode()
            frames.append(parse(buf, lg, kind="main", allow_unplayed=True))
    # ligi "nowe" (Ekstraklasa) maja osobny terminarz; bez niego POL nigdy nie dostawala typow
    if any(m.get("fduk", {}).get("kind") == "new" for m in leagues.values()):
        try:
            raw_new = fetch(src["url_terminarz_nowe"], SOURCE, "new_league_fixtures.csv", max_age_hours=3)
            for lg, meta in leagues.items():
                if meta.get("fduk", {}).get("kind") == "new":
                    frames.append(parse(raw_new, lg, kind="new", allow_unplayed=True))
        except (SourceUnavailable, schema.ContractError) as e:
            log.warning("terminarz nowych lig niedostepny: %s", e)
    frames = [f for f in frames if len(f)]
    if not frames:
        return schema.empty_frame()
    from typer.entities.history import apply_aliases
    out = apply_aliases(pd.concat(frames, ignore_index=True), config.load_yaml("aliases.yaml"))
    out["event_id"] = [schema.make_event_id(l, d, h, a)
                       for l, d, h, a in zip(out["league"], out["date"], out["home"], out["away"])]
    return out
