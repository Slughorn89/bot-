"""Laczenie historii xgabora z plikami football-data.co.uk (oryginal albo lustro z GitHuba).

Po co: xgabora konczy sie 2026-09-03 i nie ma kursow zamkniecia. Pliki sezonowe football-data
maja zamkniecia (Bet365, Avg, do 2025/26 takze Pinnacle) i mecze do dzis.

Zasada zaufania: lustro to cudze repo bez licencji, wiec zanim cokolwiek z niego wezmiemy,
porownujemy wyniki i kursy Bet365 sprzed meczu z xgabora na wspolnych meczach. Ten sam mecz
w dwoch kopiach tego samego zrodla musi sie zgadzac; rozjazd powyzej progu = odmowa (ContractError),
nigdy cicha podmiana danych.

Kontrola idzie po kursie MAKSYMALNYM sprzed meczu (max_h), bo tylko on ma w xgabora stale znaczenie.
Wykryte 2026-11-05: kolumna OddHome w xgabora to do sezonu 2024/25 SREDNIA rynku (AvgH, zgodnosc
100%), a od 2025/26 Bet365 (B365H, zgodnosc 100%), pod ta sama nazwa. Dlatego przy laczeniu kurs
"wziety" (odds_*) nadpisujemy Bet365 z football-data wszedzie, gdzie go mamy: to cena, ktora dalo
sie realnie wziac u jednego bukmachera, i jest taka sama we wszystkich sezonach.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from typer import config
from typer.ingest import footballdata_uk as fduk
from typer.ingest import schema
from typer.ingest.base import SourceUnavailable

log = logging.getLogger("typer.ingest.merge")
CLOSE_COLS = schema.ODDS_GROUPS["close_1x2"] + schema.ODDS_GROUPS["close_ou"]
TAKEN_COLS = schema.ODDS_GROUPS["odds_1x2"] + schema.ODDS_GROUPS["odds_ou"]
MAX_MISMATCH = 0.005   # max odsetek rozbieznych meczow na wspolnym okresie
MIN_OVERLAP = 300      # tyle wspolnych meczow musi byc, zeby w ogole ocenic zgodnosc


def mirror_seasons() -> list[str]:
    spec = config.sources().get("fduk_lustro", {}).get("sezony", "2019-20 do 2026-27")
    a, b = [int(x.split("-")[0]) for x in spec.split(" do ")]
    return [f"{y}-{str(y + 1)[2:]}" for y in range(a, b + 1)]


def load_fduk(leagues: dict | None = None, seasons: list[str] | None = None) -> pd.DataFrame:
    """Wszystkie ligi 'main' z football-data (oryginal albo lustro). Brak pliku ligi = pomijamy z logiem."""
    leagues = leagues or config.leagues()
    seasons = seasons or mirror_seasons()
    frames, missing = [], []
    for lg, meta in leagues.items():
        f = meta.get("fduk", {})
        if f.get("kind", "main") != "main":
            continue
        for s in seasons:
            try:
                frames.append(fduk.parse(fduk.download_season(f["code"], s), lg, kind="main"))
            except SourceUnavailable as e:
                missing.append(f"{lg} {s}")
                log.info("brak pliku: %s", e)
    if missing:
        log.warning("football-data: brak %d plikow: %s", len(missing), ", ".join(missing[:10]))
    return pd.concat(frames, ignore_index=True) if frames else schema.empty_frame()


def agreement(base: pd.DataFrame, other: pd.DataFrame) -> dict:
    """Zgodnosc dwoch kopii na wspolnych meczach: wynik i kurs maksymalny sprzed meczu."""
    m = base.merge(other, on="event_id", suffixes=("_a", "_b"))
    out = {"wspolne": int(len(m))}
    if not len(m):
        return out
    out["wynik_rozne"] = float(((m["fthg_a"] != m["fthg_b"]) | (m["ftag_a"] != m["ftag_b"])).mean())
    both = m["max_h_a"].notna() & m["max_h_b"].notna()
    rel = (m.loc[both, "max_h_a"] - m.loc[both, "max_h_b"]).abs() / m.loc[both, "max_h_b"]
    out["kurs_rozne"] = float((rel > 0.01).mean()) if both.any() else np.nan
    out["kurs_porownane"] = int(both.sum())
    return out


def enrich(base: pd.DataFrame, other: pd.DataFrame, *, check: bool = True) -> tuple[pd.DataFrame, dict]:
    """Do historii dokleja kursy zamkniecia z `other` i dopisuje mecze rozegrane po koncu `base`."""
    rep = agreement(base, other)
    if check:
        if rep["wspolne"] < MIN_OVERLAP:
            raise schema.ContractError(f"lustro: za malo wspolnych meczow do kontroli zgodnosci ({rep})")
        bad = max(rep.get("wynik_rozne", 1.0), np.nan_to_num(rep.get("kurs_rozne", 0.0)))
        if bad > MAX_MISMATCH:
            raise schema.ContractError(f"lustro niezgodne z xgabora powyzej {MAX_MISMATCH:.1%}: {rep}")
    out = base.copy()
    src = other.set_index("event_id")
    idx = out["event_id"].isin(src.index)
    for c in CLOSE_COLS:
        out.loc[idx, c] = out.loc[idx, "event_id"].map(src[c]).to_numpy()
    # kurs "wziety": Bet365 z football-data (tylko gdy cala grupa jest w lustrze)
    for grp in ("odds_1x2", "odds_ou"):
        cols = schema.ODDS_GROUPS[grp]
        have = idx & out["event_id"].map(src[cols].notna().all(axis=1)).fillna(False).astype(bool)
        for c in cols:
            out.loc[have, c] = out.loc[have, "event_id"].map(src[c]).to_numpy()
        rep[f"{grp}_bet365"] = int(have.sum())
    out, _ = schema.clean_odds(out)
    # mecze po koncu historii base, liga po lidze (POL i inne ligi spoza lustra zostaja bez zmian)
    last = base.groupby("league")["kickoff_utc"].max()
    new = other[~other["event_id"].isin(set(base["event_id"]))]
    new = new[new["league"].map(last).notna() & (new["kickoff_utc"] > new["league"].map(last))]
    rep["zamkniecia_doklejone"] = int(out[CLOSE_COLS[0]].notna().sum())
    rep["nowe_mecze"] = int(len(new))
    rep["nowe_do"] = str(new["date"].max()) if len(new) else None
    out = pd.concat([out, new[schema.COLUMNS]], ignore_index=True)
    out = out.sort_values(["kickoff_utc", "league", "home"], kind="stable").reset_index(drop=True)
    return schema.validate(out), rep
