"""Wspolny schemat meczu. Kazdy adapter zwraca DataFrame w tym formacie.

Konwencja kursow:
  odds_{h,d,a}, odds_{o25,u25}   kurs w chwili typu ("wziety"), np. Bet365 sprzed meczu
  max_{h,d,a}, max_{o25,u25}     najlepszy kurs rynku w tej samej chwili (tylko analiza wrazliwosci)
  close_{h,d,a}, close_{o25,u25} kurs zamkniecia (Pinnacle), jesli zrodlo go ma
  bench_{h,d,a}                  kurs o nieznanym momencie: wolno go uzyc tylko jako benchmarku rynku
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ODDS_GROUPS = {
    "odds_1x2": ["odds_h", "odds_d", "odds_a"],
    "odds_ou": ["odds_o25", "odds_u25"],
    "max_1x2": ["max_h", "max_d", "max_a"],
    "max_ou": ["max_o25", "max_u25"],
    "close_1x2": ["close_h", "close_d", "close_a"],
    "close_ou": ["close_o25", "close_u25"],
    "bench_1x2": ["bench_h", "bench_d", "bench_a"],
}
ODDS_COLS = [c for cols in ODDS_GROUPS.values() for c in cols]
STAT_COLS = ["fthg", "ftag", "hthg", "htag", "hs", "as_", "hst", "ast", "hr", "ar"]
BASE_COLS = ["event_id", "sport", "league", "season", "kickoff_utc", "time_known",
             "date", "home", "away", "source"]
COLUMNS = BASE_COLS + STAT_COLS + ODDS_COLS + ["ah_line", "ah_h", "ah_a"]

# Granice sensownej marzy (suma 1/kurs). Poza nimi kursy uznajemy za bledne i zerujemy grupe.
OVERROUND_MIN = {"max": 0.90, "default": 1.0}
OVERROUND_MAX = 1.30


class ContractError(ValueError):
    """Dane nie spelniaja kontraktu schematu."""


def make_event_id(league: str, date, home: str, away: str) -> str:
    d = pd.Timestamp(date).strftime("%Y%m%d")
    slug = lambda s: "".join(ch for ch in s.lower().replace(" ", "-") if ch.isalnum() or ch == "-")
    return f"{league}-{d}-{slug(home)}-{slug(away)}"


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in COLUMNS})


def clean_odds(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Zeruje (NaN) cale grupy kursow, gdy ktorys kurs <= 1.01 albo marza jest nierealna.
    Zwraca liczbe wyzerowanych grup, zeby adapter mogl to zglosic, a nie ukryc."""
    report = {}
    for name, cols in ODDS_GROUPS.items():
        present = [c for c in cols if c in df.columns]
        if len(present) != len(cols):
            continue
        o = df[cols].apply(pd.to_numeric, errors="coerce")
        any_val = o.notna().any(axis=1)
        valid = o.notna().all(axis=1) & (o > 1.01).all(axis=1)
        over = (1.0 / o).sum(axis=1)
        lo = OVERROUND_MIN["max"] if name.startswith("max") else OVERROUND_MIN["default"]
        valid &= (over >= lo) & (over <= OVERROUND_MAX)
        bad = any_val & ~valid
        report[name] = int(bad.sum())
        o.loc[~valid, :] = np.nan
        df[cols] = o
    return df, report


def validate(df: pd.DataFrame, *, allow_unplayed: bool = False) -> pd.DataFrame:
    """Kontrakt schematu: kolumny, brak duplikatow, strefa czasu UTC, poprawne gole.
    Rzuca ContractError zamiast po cichu poprawiac."""
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ContractError(f"brak kolumn: {sorted(missing)}")
    if df.empty:
        return df
    k = pd.to_datetime(df["kickoff_utc"])
    if k.dt.tz is None or str(k.dt.tz) != "UTC":
        raise ContractError("kickoff_utc musi byc tz-aware w UTC")
    if df["event_id"].duplicated().any():
        dup = df.loc[df["event_id"].duplicated(), "event_id"].head(5).tolist()
        raise ContractError(f"zduplikowane event_id: {dup}")
    key = df[["league", "date", "home", "away"]].astype(str).agg("|".join, axis=1)
    if key.duplicated().any():
        raise ContractError("zduplikowany mecz (liga, data, gospodarz, gosc)")
    if (df["home"] == df["away"]).any():
        raise ContractError("gospodarz == gosc")
    for c in ("home", "away", "league"):
        if df[c].isna().any() or (df[c].astype(str).str.strip() == "").any():
            raise ContractError(f"puste wartosci w kolumnie {c}")
    # druzyna nie gra dwa razy w ciagu doby: lapie zamienione daty i duplikaty z dwoch zrodel
    long = pd.concat([df[["league", "home", "kickoff_utc"]].set_axis(["league", "team", "k"], axis=1),
                      df[["league", "away", "kickoff_utc"]].set_axis(["league", "team", "k"], axis=1)])
    long["k"] = pd.to_datetime(long["k"])
    gap = long.sort_values("k").groupby(["league", "team"])["k"].diff().dt.total_seconds() / 3600
    if (gap < 36).any():
        raise ContractError(f"{int((gap < 36).sum())} przypadkow gry tej samej druzyny w odstepie < 36 h "
                            f"(zamienione daty? duplikaty?)")
    goals = df[["fthg", "ftag"]].apply(pd.to_numeric, errors="coerce")
    if not allow_unplayed and goals.isna().any().any():
        raise ContractError("brak wyniku w meczu rozegranym")
    if (goals.dropna() < 0).any().any():
        raise ContractError("ujemna liczba goli")
    return df
